# products/views.py

from django.shortcuts import render
from rest_framework import viewsets, permissions, status, filters
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, F, Sum, Count
from .serializers import *
from .models import *
from users.permissions import IsPDG, IsChefAgence
from inventaire.models import Warehouse


class CategoryViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = Category.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'parent']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return CategoryDetailSerializer
        return CategorySerializer

    @action(detail=False, methods=['get'])
    def tree(self, request):
        categories = Category.objects.filter(parent__isnull=True)
        serializer = self.get_serializer(categories, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        category = self.get_object()
        products = category.products.filter(is_active=True)
        page = self.paginate_queryset(products)
        if page is not None:
            serializer = ProductListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)


class BrandViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'description']

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        brand = self.get_object()
        products = brand.products.filter(is_active=True)
        page = self.paginate_queryset(products)
        if page is not None:
            serializer = ProductListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)


class UnitViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer


class ProductViewset(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'brand', 'is_active', 'product_type']
    search_fields = ['reference', 'barcode', 'name', 'description']
    ordering_fields = ['created_at', 'name', 'stock_quantity']

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        elif self.action == 'retrieve':
            return ProductDetailSerializer
        return ProductCreateUpdateSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        products = self.get_queryset().filter(stock_quantity__lte=F('minimum_stock'))
        serializer = ProductStockAlertSerializer(products, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def out_of_stock(self, request):
        products = self.get_queryset().filter(stock_quantity=0)
        serializer = ProductListSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)


class ProductVariantViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = ProductVariant.objects.all()
    serializer_class = ProductVariantSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'is_active']
    search_fields = ['sku']


class ProductPricingViewSet(viewsets.ModelViewSet):
    serializer_class = ProductPricingSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'warehouse', 'is_current']
    search_fields = ['product__name', 'product__reference', 'warehouse__name']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsPDG() | IsChefAgence()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg():
            return ProductPricing.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        warehouses = Warehouse.objects.filter(agence_id__in=agences_ids)
        return ProductPricing.objects.filter(warehouse__in=warehouses)

    @action(detail=False, methods=['get'])
    def by_warehouse(self, request):
        warehouse_id = request.query_params.get('warehouse_id')
        if not warehouse_id:
            return Response({'error': 'warehouse_id est requis'}, status=400)
        
        try:
            warehouse = Warehouse.objects.get(id=warehouse_id)
            if not request.user.est_pdg() and not request.user.peut_acceder_agence(warehouse.agence.id):
                return Response({'error': 'Accès non autorisé'}, status=403)
            
            prices = ProductPricing.objects.filter(warehouse=warehouse, is_current=True)
            serializer = self.get_serializer(prices, many=True)
            return Response(serializer.data)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Entrepôt non trouvé'}, status=404)

    @action(detail=False, methods=['get'])
    def by_product(self, request):
        product_id = request.query_params.get('product_id')
        if not product_id:
            return Response({'error': 'product_id est requis'}, status=400)
        
        try:
            product = Product.objects.get(id=product_id)
            prices = self.get_queryset().filter(product=product, is_current=True)
            serializer = self.get_serializer(prices, many=True)
            return Response(serializer.data)
        except Product.DoesNotExist:
            return Response({'error': 'Produit non trouvé'}, status=404)

    @action(detail=False, methods=['post'])
    def set_price(self, request):
        product_id = request.data.get('product_id')
        warehouse_id = request.data.get('warehouse_id')
        purchase_price = request.data.get('purchase_price')
        sale_price = request.data.get('sale_price')
        
        if not all([product_id, warehouse_id, purchase_price, sale_price]):
            return Response({
                'error': 'product_id, warehouse_id, purchase_price, sale_price sont requis'
            }, status=400)
        
        try:
            product = Product.objects.get(id=product_id)
            warehouse = Warehouse.objects.get(id=warehouse_id)
            
            if not request.user.est_pdg() and not request.user.peut_acceder_agence(warehouse.agence.id):
                return Response({'error': 'Accès non autorisé'}, status=403)
            
            ProductPricing.objects.filter(product=product, warehouse=warehouse, is_current=True).update(is_current=False)
            
            pricing = ProductPricing.objects.create(
                product=product,
                warehouse=warehouse,
                purchase_price=purchase_price,
                sale_price=sale_price,
                wholesale_price=request.data.get('wholesale_price'),
                currency=request.data.get('currency', 'XOF'),
                tax_rate=request.data.get('tax_rate', 20),
                updated_by=request.user,
                is_current=True
            )
            
            serializer = self.get_serializer(pricing)
            return Response(serializer.data, status=201)
            
        except Product.DoesNotExist:
            return Response({'error': 'Produit non trouvé'}, status=404)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Entrepôt non trouvé'}, status=404)

    @action(detail=False, methods=['post'])
    def bulk_set_prices(self, request):
        warehouse_id = request.data.get('warehouse_id')
        prices_data = request.data.get('prices', [])
        
        if not warehouse_id:
            return Response({'error': 'warehouse_id est requis'}, status=400)
        
        if not prices_data:
            return Response({'error': 'prices est requis'}, status=400)
        
        try:
            warehouse = Warehouse.objects.get(id=warehouse_id)
            
            if not request.user.est_pdg() and not request.user.peut_acceder_agence(warehouse.agence.id):
                return Response({'error': 'Accès non autorisé'}, status=403)
            
            results = []
            errors = []
            
            for price_data in prices_data:
                product_id = price_data.get('product_id')
                purchase_price = price_data.get('purchase_price')
                sale_price = price_data.get('sale_price')
                
                if not all([product_id, purchase_price, sale_price]):
                    errors.append({'product_id': product_id, 'error': 'Données incomplètes'})
                    continue
                
                try:
                    product = Product.objects.get(id=product_id)
                    
                    ProductPricing.objects.filter(product=product, warehouse=warehouse, is_current=True).update(is_current=False)
                    
                    ProductPricing.objects.create(
                        product=product,
                        warehouse=warehouse,
                        purchase_price=purchase_price,
                        sale_price=sale_price,
                        wholesale_price=price_data.get('wholesale_price'),
                        currency=price_data.get('currency', 'XOF'),
                        tax_rate=price_data.get('tax_rate', 20),
                        updated_by=request.user,
                        is_current=True
                    )
                    
                    results.append({
                        'product_id': product_id,
                        'product_name': product.name,
                        'purchase_price': str(purchase_price),
                        'sale_price': str(sale_price)
                    })
                    
                except Product.DoesNotExist:
                    errors.append({'product_id': product_id, 'error': 'Produit non trouvé'})
            
            return Response({
                'success': results,
                'errors': errors,
                'total_processed': len(results),
                'total_errors': len(errors)
            }, status=201 if results else 400)
            
        except Warehouse.DoesNotExist:
            return Response({'error': 'Entrepôt non trouvé'}, status=404)