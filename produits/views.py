# products/views.py - Supprimez les imports en double et corrigez

from django.shortcuts import render
from rest_framework import viewsets, permissions, status, filters
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, F, Sum, Count
from django.utils import timezone  # Important: ajoutez cette ligne
from .serializers import *
from .models import *
from users.permissions import IsPDG, IsChefAgence
from inventaire.models import Warehouse

# Supprimez les imports en double plus bas dans le fichier

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
    """
    ViewSet pour la gestion des produits
    """
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
        """
        Récupère les produits en stock faible
        """
        products = self.get_queryset().filter(stock_quantity__lte=F('minimum_stock'))
        serializer = ProductStockAlertSerializer(products, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def out_of_stock(self, request):
        """
        Récupère les produits en rupture de stock
        """
        products = self.get_queryset().filter(stock_quantity=0)
        serializer = ProductListSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def prices(self, request, pk=None):
        """
        Récupère les prix d'un produit par entrepôt
        URL: /products/{id}/prices/
        """
        product = self.get_object()
        user = request.user
        
        # Récupérer les entrepôts accessibles selon les droits de l'utilisateur
        if user.est_pdg() or user.est_drh():
            warehouses = Warehouse.objects.filter(is_active=True)
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            warehouses = Warehouse.objects.filter(agence_id__in=agences_ids, is_active=True)
        
        # Récupérer les prix pour les entrepôts accessibles
        prices = product.prices.filter(
            warehouse__in=warehouses, 
            is_current=True
        ).select_related('warehouse', 'product')
        
        serializer = ProductPricingSerializer(prices, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def images(self, request, pk=None):
        """
        Récupère toutes les images d'un produit
        URL: /products/{id}/images/
        """
        product = self.get_object()
        images = product.images.all()
        serializer = ProductImageSerializer(images, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def variants(self, request, pk=None):
        """
        Récupère toutes les variantes d'un produit
        URL: /products/{id}/variants/
        """
        product = self.get_object()
        variants = product.variants.filter(is_active=True)
        serializer = ProductVariantSerializer(variants, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def add_image(self, request, pk=None):
        """
        Ajoute une image à un produit
        URL: /products/{id}/add_image/
        """
        product = self.get_object()
        image_file = request.FILES.get('image')
        
        if not image_file:
            return Response(
                {'error': 'Aucune image fournie'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Vérifier le type et la taille de l'image
        if not image_file.content_type.startswith('image/'):
            return Response(
                {'error': 'Le fichier doit être une image'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if image_file.size > 5 * 1024 * 1024:  # 5MB max
            return Response(
                {'error': 'L\'image ne doit pas dépasser 5MB'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        is_main = request.data.get('is_main', 'false').lower() == 'true'
        
        # Si c'est l'image principale, retirer le statut des autres
        if is_main:
            product.images.filter(is_main=True).update(is_main=False)
        
        image = ProductImage.objects.create(
            product=product,
            image=image_file,
            alt_text=request.data.get('alt_text', ''),
            is_main=is_main
        )
        
        serializer = ProductImageSerializer(image, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'])
    def remove_image(self, request, pk=None):
        """
        Supprime une image d'un produit
        URL: /products/{id}/remove_image/?image_id=xxx
        """
        product = self.get_object()
        image_id = request.query_params.get('image_id')
        
        if not image_id:
            return Response(
                {'error': 'image_id est requis'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            image = product.images.get(id=image_id)
            image.delete()
            return Response(
                {'message': 'Image supprimée avec succès'}, 
                status=status.HTTP_200_OK
            )
        except ProductImage.DoesNotExist:
            return Response(
                {'error': 'Image non trouvée'}, 
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['post'])
    def set_main_image(self, request, pk=None):
        """
        Définit l'image principale d'un produit
        URL: /products/{id}/set_main_image/?image_id=xxx
        """
        product = self.get_object()
        image_id = request.data.get('image_id') or request.query_params.get('image_id')
        
        if not image_id:
            return Response(
                {'error': 'image_id est requis'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Retirer le statut principal de toutes les images
            product.images.filter(is_main=True).update(is_main=False)
            
            # Définir la nouvelle image principale
            image = product.images.get(id=image_id)
            image.is_main = True
            image.save()
            
            # Mettre à jour main_image du produit
            product.main_image = image.image
            product.save()
            
            return Response(
                {'message': 'Image principale mise à jour avec succès'}, 
                status=status.HTTP_200_OK
            )
        except ProductImage.DoesNotExist:
            return Response(
                {'error': 'Image non trouvée'}, 
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['get'])
    def stock_by_warehouse(self, request, pk=None):
        """
        Récupère le stock d'un produit par entrepôt
        URL: /products/{id}/stock_by_warehouse/
        """
        product = self.get_object()
        user = request.user
        
        # Récupérer les entrepôts accessibles
        if user.est_pdg() or user.est_drh():
            warehouses = Warehouse.objects.filter(is_active=True)
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            warehouses = Warehouse.objects.filter(agence_id__in=agences_ids, is_active=True)
        
        # Récupérer les stocks
        from inventaire.models import WarehouseStock
        from inventaire.serializers import WarehouseStockSerializer
        
        stocks = WarehouseStock.objects.filter(
            product=product,
            warehouse__in=warehouses
        ).select_related('warehouse')
        
        serializer = WarehouseStockSerializer(stocks, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_category(self, request):
        """
        Récupère les produits par catégorie
        URL: /products/by_category/?category_id=xxx
        """
        category_id = request.query_params.get('category_id')
        if not category_id:
            return Response(
                {'error': 'category_id est requis'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        products = self.get_queryset().filter(category_id=category_id, is_active=True)
        page = self.paginate_queryset(products)
        if page is not None:
            serializer = ProductListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_brand(self, request):
        """
        Récupère les produits par marque
        URL: /products/by_brand/?brand_id=xxx
        """
        brand_id = request.query_params.get('brand_id')
        if not brand_id:
            return Response(
                {'error': 'brand_id est requis'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        products = self.get_queryset().filter(brand_id=brand_id, is_active=True)
        page = self.paginate_queryset(products)
        if page is not None:
            serializer = ProductListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def featured(self, request):
        """
        Récupère les produits en vedette
        URL: /products/featured/
        """
        products = self.get_queryset().filter(is_featured=True, is_active=True)
        page = self.paginate_queryset(products)
        if page is not None:
            serializer = ProductListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """
        Duplique un produit
        URL: /products/{id}/duplicate/
        """
        original_product = self.get_object()
        
        # Créer une copie du produit
        duplicate_product = Product.objects.create(
            reference=f"{original_product.reference}_COPY",
            name=f"{original_product.name} (copie)",
            description=original_product.description,
            product_type=original_product.product_type,
            category=original_product.category,
            brand=original_product.brand,
            unit=original_product.unit,
            created_by=request.user,
            minimum_stock=original_product.minimum_stock,
            maximum_stock=original_product.maximum_stock,
            location=original_product.location,
            is_active=False,  # Par défaut inactif
            is_featured=False,
            has_variants=original_product.has_variants,
            weight=original_product.weight,
            volume=original_product.volume
        )
        
        # Copier les images
        for image in original_product.images.all():
            ProductImage.objects.create(
                product=duplicate_product,
                image=image.image,
                alt_text=image.alt_text,
                is_main=image.is_main
            )
        
        # Copier les variantes
        for variant in original_product.variants.all():
            ProductVariant.objects.create(
                product=duplicate_product,
                sku=f"{variant.sku}_COPY",
                attributes=variant.attributes,
                stock_quantity=0,
                is_active=False
            )
        
        serializer = ProductDetailSerializer(duplicate_product, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """
        Active/désactive un produit
        URL: /products/{id}/toggle_active/
        """
        product = self.get_object()
        product.is_active = not product.is_active
        product.save()
        
        return Response({
            'message': f'Produit {"activé" if product.is_active else "désactivé"} avec succès',
            'is_active': product.is_active
        })

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """
        Récupère les statistiques d'un produit
        URL: /products/{id}/statistics/
        """
        product = self.get_object()
        
        from inventaire.models import StockMovement, TransferItem
        
        # Statistiques des mouvements de stock
        total_entries = StockMovement.objects.filter(
            product=product, 
            movement_type='in'
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        total_exits = StockMovement.objects.filter(
            product=product, 
            movement_type='out'
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        total_transferred_out = StockMovement.objects.filter(
            product=product, 
            movement_type='transfer',
            from_warehouse__isnull=False
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        total_transferred_in = StockMovement.objects.filter(
            product=product, 
            movement_type='transfer',
            to_warehouse__isnull=False
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        # Transferts en cours
        pending_transfers = TransferItem.objects.filter(
            product=product,
            transfer__status__in=['pending_approval', 'approved', 'in_transit'],
            quantity__gt=F('quantity_received')
        ).count()
        
        return Response({
            'product_id': product.id,
            'product_name': product.name,
            'total_stock': product.stock_quantity,
            'statistics': {
                'total_entries': total_entries,
                'total_exits': total_exits,
                'total_transferred_out': total_transferred_out,
                'total_transferred_in': total_transferred_in,
                'net_movement': total_entries + total_transferred_in - total_exits - total_transferred_out
            },
            'pending_transfers': pending_transfers,
            'has_variants': product.has_variants,
            'variants_count': product.variants.count(),
            'images_count': product.images.count(),
            'warehouses_count': product.warehouse_stocks.count()
        })


class ProductVariantViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = ProductVariant.objects.all()
    serializer_class = ProductVariantSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'is_active']
    search_fields = ['sku']


# products/views.py - ProductPricingViewSet complet


# products/views.py - Version complète et corrigée de ProductPricingViewSet

from django.shortcuts import render
from rest_framework import viewsets, permissions, status, filters
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, F, Sum, Count
from django.utils import timezone
from .serializers import *
from .models import *
from users.permissions import IsPDG, IsChefAgence, IsPDGOrChefAgence
from inventaire.models import Warehouse


class ProductPricingViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des prix par entrepôt
    """
    serializer_class = ProductPricingSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'warehouse', 'is_current']
    search_fields = ['product__name', 'product__reference', 'warehouse__name']

    def get_permissions(self):
        """
        Permissions selon l'action
        """
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'set_price', 'bulk_set_prices']:
            # Utiliser la permission combinée
            return [IsAuthenticated(), IsPDGOrChefAgence()]
        return [IsAuthenticated()]

    def get_queryset(self):
        """
        Filtre les prix selon les droits de l'utilisateur
        """
        user = self.request.user
        
        # Les PDG et DRH voient tous les prix
        if user.est_pdg() or user.est_drh():
            return ProductPricing.objects.all()
        
        # Les chefs d'agence voient les prix de leurs agences
        if user.est_chef_agence():
            agences_ids = user.get_agences().values_list('id', flat=True)
            warehouses = Warehouse.objects.filter(agence_id__in=agences_ids)
            return ProductPricing.objects.filter(warehouse__in=warehouses)
        
        # Les autres utilisateurs ne voient rien par défaut
        return ProductPricing.objects.none()

    def list(self, request, *args, **kwargs):
        """
        Liste des prix avec filtres
        """
        queryset = self.filter_queryset(self.get_queryset())
        
        # Filtrer par produit
        product_id = request.query_params.get('product_id')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        
        # Filtrer par entrepôt
        warehouse_id = request.query_params.get('warehouse_id')
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        
        # Filtrer par statut
        is_current = request.query_params.get('is_current')
        if is_current is not None:
            queryset = queryset.filter(is_current=is_current.lower() == 'true')
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        """
        Crée un nouveau prix (désactive les anciens)
        """
        try:
            product_id = request.data.get('product')
            warehouse_id = request.data.get('warehouse')
            
            # Désactiver les anciens prix
            ProductPricing.objects.filter(
                product_id=product_id,
                warehouse_id=warehouse_id,
                is_current=True
            ).update(is_current=False, valid_to=timezone.now().date())
            
            # Créer le nouveau prix
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(updated_by=request.user, is_current=True)
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response(
                {'error': f'Erreur lors de la création: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

    def update(self, request, *args, **kwargs):
        """
        Met à jour un prix existant
        """
        try:
            partial = kwargs.pop('partial', False)
            instance = self.get_object()
            
            # Désactiver l'ancienne version
            instance.is_current = False
            instance.valid_to = timezone.now().date()
            instance.save()
            
            # Créer une nouvelle version avec les modifications
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            serializer.save(
                updated_by=request.user,
                is_current=True,
                valid_from=timezone.now().date(),
                valid_to=None
            )
            
            return Response(serializer.data)
            
        except Exception as e:
            return Response(
                {'error': f'Erreur lors de la mise à jour: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

    def destroy(self, request, *args, **kwargs):
        """
        Supprime (désactive) un prix
        """
        try:
            instance = self.get_object()
            instance.is_current = False
            instance.valid_to = timezone.now().date()
            instance.save()
            
            return Response(
                {'message': 'Prix désactivé avec succès'},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {'error': f'Erreur lors de la suppression: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'])
    def set_price(self, request):
        """
        Crée ou met à jour un prix pour un produit dans un entrepôt
        URL: /product-prices/set_price/
        """
        # Récupérer les données
        product_id = request.data.get('product_id')
        warehouse_id = request.data.get('warehouse_id')
        purchase_price = request.data.get('purchase_price')
        sale_price = request.data.get('sale_price')
        
        # Validation des champs requis
        if not product_id:
            return Response({'error': 'product_id est requis'}, status=400)
        if not warehouse_id:
            return Response({'error': 'warehouse_id est requis'}, status=400)
        if purchase_price is None:
            return Response({'error': 'purchase_price est requis'}, status=400)
        if sale_price is None:
            return Response({'error': 'sale_price est requis'}, status=400)
        
        try:
            # Récupérer les objets
            product = Product.objects.get(id=product_id)
            warehouse = Warehouse.objects.get(id=warehouse_id)
            
            # Convertir les prix en float
            try:
                purchase_price = float(purchase_price)
                sale_price = float(sale_price)
            except ValueError:
                return Response({'error': 'Les prix doivent être des nombres valides'}, status=400)
            
            # Valider les prix
            if sale_price < purchase_price:
                return Response({
                    'error': 'Le prix de vente ne peut pas être inférieur au prix d\'achat'
                }, status=400)
            
            # Désactiver les anciens prix
            ProductPricing.objects.filter(
                product=product,
                warehouse=warehouse,
                is_current=True
            ).update(is_current=False, valid_to=timezone.now().date())
            
            # Créer le nouveau prix
            pricing = ProductPricing.objects.create(
                product=product,
                warehouse=warehouse,
                purchase_price=purchase_price,
                sale_price=sale_price,
                wholesale_price=request.data.get('wholesale_price'),
                currency=request.data.get('currency', 'XOF'),
                tax_rate=int(request.data.get('tax_rate', 20)),
                updated_by=request.user,
                is_current=True,
                valid_from=timezone.now().date()
            )
            
            serializer = self.get_serializer(pricing)
            return Response({
                'success': True,
                'message': 'Prix enregistré avec succès',
                'data': serializer.data
            }, status=200)
            
        except Product.DoesNotExist:
            return Response({'error': 'Produit non trouvé'}, status=404)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Entrepôt non trouvé'}, status=404)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['get'])
    def by_warehouse(self, request):
        """
        Récupère tous les prix d'un entrepôt spécifique
        """
        warehouse_id = request.query_params.get('warehouse_id')
        
        if not warehouse_id:
            return Response({'error': 'warehouse_id est requis'}, status=400)
        
        try:
            warehouse = Warehouse.objects.get(id=warehouse_id)
            prices = ProductPricing.objects.filter(
                warehouse=warehouse,
                is_current=True
            ).select_related('product', 'warehouse')
            
            serializer = self.get_serializer(prices, many=True)
            return Response(serializer.data)
            
        except Warehouse.DoesNotExist:
            return Response({'error': 'Entrepôt non trouvé'}, status=404)

    @action(detail=False, methods=['get'])
    def by_product(self, request):
        """
        Récupère tous les prix d'un produit spécifique
        """
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

    @action(detail=False, methods=['get'])
    def by_product_and_warehouse(self, request):
        """
        Récupère le prix pour un produit et un entrepôt spécifiques
        """
        product_id = request.query_params.get('product_id')
        warehouse_id = request.query_params.get('warehouse_id')
        
        if not product_id:
            return Response({'error': 'product_id est requis'}, status=400)
        if not warehouse_id:
            return Response({'error': 'warehouse_id est requis'}, status=400)
        
        try:
            pricing = ProductPricing.objects.get(
                product_id=product_id,
                warehouse_id=warehouse_id,
                is_current=True
            )
            serializer = self.get_serializer(pricing)
            return Response(serializer.data)
            
        except ProductPricing.DoesNotExist:
            return Response(
                {'message': 'Aucun prix défini pour ce produit dans cet entrepôt'},
                status=404
            )