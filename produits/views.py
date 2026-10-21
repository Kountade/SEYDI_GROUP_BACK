# products/views.py

import os
from django.db.models import (
    Q, F, Sum, Count, Prefetch, OuterRef, Subquery, DecimalField
)
from django.core.cache import cache
from django.utils import timezone
from rest_framework import viewsets, permissions, status, filters
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.core.files import File

from .serializers import (
    CategorySerializer, CategoryDetailSerializer,
    BrandSerializer, UnitSerializer,
    ProductListSerializer, ProductDetailSerializer,
    ProductCreateUpdateSerializer, ProductImageSerializer,
    ProductVariantSerializer, ProductPricingSerializer,
    ProductStockAlertSerializer,
)
from .models import (
    Category, Brand, Unit, Product, ProductImage,
    ProductVariant, ProductPricing,
)
from .pagination import ProductPagination, OptimizedPagination, SmallPagination
from users.permissions import IsPDG, IsChefAgence, IsPDGOrChefAgence
from inventaire.models import Warehouse


# ============================================================
# HELPERS DE CACHE
# ============================================================
def _purge_products_cache():
    """Purge le cache des listes produits (appelé après toute mutation)."""
    try:
        cache.delete_pattern('products_*')
    except Exception:
        # Fallback si django-redis n'est pas installé
        cache.clear()


# ============================================================
# CATEGORY VIEWSET
# ============================================================
class CategoryViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = SmallPagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'parent']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at',
                       'products_count', 'subcategories_count']

    def get_queryset(self):
        # ✅ annotate au lieu de source='products.count' (N+1)
        return Category.objects.annotate(
            products_count=Count('products', distinct=True),
            subcategories_count=Count('subcategories', distinct=True),
        )

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return CategoryDetailSerializer
        return CategorySerializer

    def perform_create(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_destroy(self, instance):
        instance.delete()
        _purge_products_cache()

    @action(detail=False, methods=['get'])
    def tree(self, request):
        categories = self.get_queryset().filter(parent__isnull=True)
        serializer = self.get_serializer(categories, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        category = self.get_object()
        qs = (
            category.products.filter(is_active=True)
            .select_related('category', 'brand', 'unit')
            .order_by('name')
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = ProductListSerializer(
                page, many=True, context={'request': request}
            )
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(
            qs, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================
# BRAND VIEWSET
# ============================================================
class BrandViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = SmallPagination
    serializer_class = BrandSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at', 'products_count']

    def get_queryset(self):
        return Brand.objects.annotate(
            products_count=Count('products', distinct=True)
        )

    def perform_create(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_destroy(self, instance):
        instance.delete()
        _purge_products_cache()

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        brand = self.get_object()
        qs = (
            brand.products.filter(is_active=True)
            .select_related('category', 'brand', 'unit')
            .order_by('name')
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = ProductListSerializer(
                page, many=True, context={'request': request}
            )
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(
            qs, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================
# UNIT VIEWSET
# ============================================================
class UnitViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    pagination_class = SmallPagination


# ============================================================
# PRODUCT VIEWSET  (✅ VITESSE OPTIMISÉE)
# ============================================================
class ProductViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProductPagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'brand', 'is_active', 'product_type']
    search_fields = ['reference', 'barcode', 'name', 'description']
    ordering_fields = ['created_at', 'name', 'stock_quantity']

    # ---------- helpers ----------
    def _resolve_warehouse_id(self):
        """
        Priorité :
        1. ?warehouse_id=... (ou ?warehouse=...)
        2. agence principale de l'utilisateur -> entrepôt par défaut
        """
        wid = (
            self.request.query_params.get('warehouse_id')
            or self.request.query_params.get('warehouse')
        )
        if wid:
            return wid

        user = self.request.user
        if hasattr(user, 'get_agence_principale'):
            agence = user.get_agence_principale()
            if agence:
                wh = agence.warehouses.filter(is_default=True).first()
                if wh:
                    return wh.id
        return None

    def _apply_pricing_prefetch(self, queryset):
        """
        ✅ Prefetch (1 seule requête SQL) au lieu de 3 Subquery.
        Plus rapide : le prix est indexé par produit côté Python.
        """
        warehouse_id = self._resolve_warehouse_id()
        pricing_qs = (
            ProductPricing.objects
            .filter(is_current=True)
            .select_related('warehouse')
            .order_by('id')
        )
        if warehouse_id:
            pricing_qs = pricing_qs.filter(warehouse_id=warehouse_id)

        return queryset.prefetch_related(
            Prefetch('prices', queryset=pricing_qs,
                     to_attr='_prefetched_prices')
        )

    def _attach_pricing_object(self, products):
        """
        ✅ Hydrate `_pricing` depuis le prefetch (0 requête SQL supplémentaire).
        Compatible avec Subquery (fallback si présent).
        """
        for p in products:
            prefetched = getattr(p, '_prefetched_prices', None)
            if prefetched:
                p._pricing = prefetched[0]
            elif getattr(p, '_purchase_price', None) is not None \
                    or getattr(p, '_sale_price', None) is not None:
                # Fallback si Subquery a été utilisé (rétrocompat)
                p._pricing = type('P', (), {
                    'purchase_price': getattr(p, '_purchase_price', None),
                    'sale_price': getattr(p, '_sale_price', None),
                    'wholesale_price': getattr(p, '_wholesale_price', None),
                })()
            else:
                p._pricing = None

    # ---------- queryset ----------
    def get_queryset(self):
        if self.action in ('list', 'low_stock', 'out_of_stock', 'featured',
                           'by_category', 'by_brand'):
            # ✅ Pas de created_by en liste : JOIN inutile
            base = Product.objects.select_related('category', 'brand', 'unit')
            return self._apply_pricing_prefetch(base)

        if self.action == 'retrieve':
            # ✅ Détail : created_by + prefetch prices/images/variants
            base = Product.objects.select_related(
                'category', 'brand', 'unit', 'created_by'
            )
            user = self.request.user
            prices_qs = (
                ProductPricing.objects.filter(is_current=True)
                .select_related('warehouse')
            )
            if not user.est_pdg():
                agences_ids = user.get_agences().values_list('id', flat=True)
                prices_qs = prices_qs.filter(
                    warehouse__agence_id__in=agences_ids)

            return base.prefetch_related(
                Prefetch('prices', queryset=prices_qs,
                         to_attr='_prices_detail'),
                Prefetch(
                    'images',
                    queryset=ProductImage.objects.order_by(
                        '-is_main', 'created_at'),
                ),
                Prefetch(
                    'variants',
                    queryset=ProductVariant.objects.filter(is_active=True),
                ),
            )

        # Actions d'écriture : simple select_related
        return Product.objects.select_related('category', 'brand', 'unit')

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        if self.action == 'retrieve':
            return ProductDetailSerializer
        return ProductCreateUpdateSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        ctx['warehouse_id'] = self._resolve_warehouse_id()
        return ctx

    # ---------- list avec cache 60s ----------
    def list(self, request, *args, **kwargs):
        # ✅ Cache 60s par combinaison user + URL complète
        cache_key = f'products_list_{request.user.id}_{request.get_full_path()}'
        bypass = request.query_params.get('nocache') == '1'
        if not bypass:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            self._attach_pricing_object(page)
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            if not bypass:
                cache.set(cache_key, response.data, 60)
            return response

        products = list(queryset)
        self._attach_pricing_object(products)
        serializer = self.get_serializer(products, many=True)
        data = serializer.data
        if not bypass:
            cache.set(cache_key, data, 60)
        return Response(data)

    # ---------- CRUD : purge cache ----------
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_products_cache()

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        remove_main_image = request.data.get('remove_main_image', 'false')
        if str(remove_main_image).lower() == 'true' and instance.main_image:
            if os.path.isfile(instance.main_image.path):
                try:
                    os.remove(instance.main_image.path)
                except Exception as e:
                    print(f"Erreur suppression image: {e}")
            instance.main_image = None

        if 'main_image' in request.FILES and instance.main_image:
            if os.path.isfile(instance.main_image.path):
                try:
                    os.remove(instance.main_image.path)
                except Exception as e:
                    print(f"Erreur suppression image: {e}")

        serializer = self.get_serializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        _purge_products_cache()
        return Response(serializer.data)

    def perform_destroy(self, instance):
        instance.delete()
        _purge_products_cache()

    # ---------- actions ----------
    @action(detail=False, methods=['get'], url_path='low-stock')
    def low_stock(self, request):
        qs = self.get_queryset().filter(stock_quantity__lte=F('minimum_stock'))
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(
                ProductStockAlertSerializer(page, many=True).data
            )
        return Response(ProductStockAlertSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'], url_path='out-of-stock')
    def out_of_stock(self, request):
        qs = self.get_queryset().filter(stock_quantity=0)
        page = self.paginate_queryset(qs)
        if page is not None:
            self._attach_pricing_object(page)
            return self.get_paginated_response(
                ProductListSerializer(
                    page, many=True, context={'request': request}
                ).data
            )
        products = list(qs)
        self._attach_pricing_object(products)
        return Response(
            ProductListSerializer(
                products, many=True, context={'request': request}
            ).data
        )

    @action(detail=True, methods=['get'])
    def prices(self, request, pk=None):
        product = self.get_object()
        user = request.user

        if user.est_pdg() or user.est_drh():
            warehouses = Warehouse.objects.filter(is_active=True)
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            warehouses = Warehouse.objects.filter(
                agence_id__in=agences_ids, is_active=True
            )

        prices = (
            product.prices
            .filter(warehouse__in=warehouses, is_current=True)
            .select_related('warehouse', 'product')
        )
        serializer = ProductPricingSerializer(
            prices, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def images(self, request, pk=None):
        product = self.get_object()
        images = product.images.all()
        serializer = ProductImageSerializer(
            images, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def variants(self, request, pk=None):
        product = self.get_object()
        variants = product.variants.filter(is_active=True)
        serializer = ProductVariantSerializer(variants, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='add-image')
    def add_image(self, request, pk=None):
        product = self.get_object()
        image_file = request.FILES.get('image')

        if not image_file:
            return Response({'error': 'Aucune image fournie'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not image_file.content_type.startswith('image/'):
            return Response({'error': 'Le fichier doit être une image'},
                            status=status.HTTP_400_BAD_REQUEST)
        if image_file.size > 5 * 1024 * 1024:
            return Response({'error': 'L\'image ne doit pas dépasser 5MB'},
                            status=status.HTTP_400_BAD_REQUEST)

        is_main = str(request.data.get('is_main', 'false')).lower() == 'true'

        if is_main:
            product.images.filter(is_main=True).update(is_main=False)
            product.main_image = image_file
            product.save()

        image = ProductImage.objects.create(
            product=product,
            image=image_file,
            alt_text=request.data.get('alt_text', ''),
            is_main=is_main,
        )
        _purge_products_cache()
        serializer = ProductImageSerializer(
            image, context={'request': request}
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path='remove-image')
    def remove_image(self, request, pk=None):
        product = self.get_object()
        image_id = request.query_params.get('image_id')

        if not image_id:
            return Response({'error': 'image_id est requis'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            image = product.images.get(id=image_id)
            was_main = image.is_main
            image.delete()

            if was_main:
                next_image = product.images.first()
                if next_image:
                    next_image.is_main = True
                    next_image.save()
                    product.main_image = next_image.image
                else:
                    product.main_image = None
                product.save()

            _purge_products_cache()
            return Response({'message': 'Image supprimée avec succès'},
                            status=status.HTTP_200_OK)
        except ProductImage.DoesNotExist:
            return Response({'error': 'Image non trouvée'},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': f'Erreur: {str(e)}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['delete'], url_path='remove-main-image')
    def remove_main_image(self, request, pk=None):
        product = self.get_object()
        if not product.main_image:
            return Response({'error': 'Aucune image principale'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            if os.path.isfile(product.main_image.path):
                os.remove(product.main_image.path)
            product.main_image = None
            product.save()
            product.images.filter(is_main=True).update(is_main=False)
            _purge_products_cache()
            return Response({'message': 'Image principale supprimée'},
                            status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': f'Erreur: {str(e)}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='set-main-image')
    def set_main_image(self, request, pk=None):
        product = self.get_object()
        image_id = (
            request.data.get('image_id')
            or request.query_params.get('image_id')
        )
        if not image_id:
            return Response({'error': 'image_id est requis'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            product.images.filter(is_main=True).update(is_main=False)
            image = product.images.get(id=image_id)
            image.is_main = True
            image.save()
            product.main_image = image.image
            product.save()
            _purge_products_cache()
            return Response({'message': 'Image principale mise à jour'},
                            status=status.HTTP_200_OK)
        except ProductImage.DoesNotExist:
            return Response({'error': 'Image non trouvée'},
                            status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'], url_path='replace-main-image')
    def replace_main_image(self, request, pk=None):
        product = self.get_object()
        image_file = request.FILES.get('image')
        if not image_file:
            return Response({'error': 'Aucune image fournie'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            if product.main_image and os.path.isfile(product.main_image.path):
                os.remove(product.main_image.path)
            product.main_image = image_file
            product.save()
            product.images.filter(is_main=True).update(is_main=False)
            ProductImage.objects.create(
                product=product,
                image=image_file,
                alt_text=request.data.get('alt_text', product.name),
                is_main=True,
            )
            _purge_products_cache()
            return Response({
                'message': 'Image principale remplacée',
                'main_image': request.build_absolute_uri(product.main_image.url),
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': f'Erreur: {str(e)}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='stock-by-warehouse')
    def stock_by_warehouse(self, request, pk=None):
        product = self.get_object()
        user = request.user

        if user.est_pdg() or user.est_drh():
            warehouses = Warehouse.objects.filter(is_active=True)
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            warehouses = Warehouse.objects.filter(
                agence_id__in=agences_ids, is_active=True
            )

        from inventaire.models import WarehouseStock
        from inventaire.serializers import WarehouseStockSerializer

        stocks = (
            WarehouseStock.objects
            .filter(product=product, warehouse__in=warehouses)
            .select_related('warehouse', 'product')
        )
        return Response(WarehouseStockSerializer(stocks, many=True).data)

    @action(detail=False, methods=['get'], url_path='by-category')
    def by_category(self, request):
        category_id = request.query_params.get('category_id')
        if not category_id:
            return Response({'error': 'category_id est requis'},
                            status=status.HTTP_400_BAD_REQUEST)

        qs = self.get_queryset().filter(category_id=category_id, is_active=True)
        page = self.paginate_queryset(qs)
        if page is not None:
            self._attach_pricing_object(page)
            return self.get_paginated_response(
                ProductListSerializer(
                    page, many=True, context={'request': request}
                ).data
            )
        products = list(qs)
        self._attach_pricing_object(products)
        return Response(
            ProductListSerializer(
                products, many=True, context={'request': request}
            ).data
        )

    @action(detail=False, methods=['get'], url_path='by-brand')
    def by_brand(self, request):
        brand_id = request.query_params.get('brand_id')
        if not brand_id:
            return Response({'error': 'brand_id est requis'},
                            status=status.HTTP_400_BAD_REQUEST)

        qs = self.get_queryset().filter(brand_id=brand_id, is_active=True)
        page = self.paginate_queryset(qs)
        if page is not None:
            self._attach_pricing_object(page)
            return self.get_paginated_response(
                ProductListSerializer(
                    page, many=True, context={'request': request}
                ).data
            )
        products = list(qs)
        self._attach_pricing_object(products)
        return Response(
            ProductListSerializer(
                products, many=True, context={'request': request}
            ).data
        )

    @action(detail=False, methods=['get'])
    def featured(self, request):
        qs = self.get_queryset().filter(is_featured=True, is_active=True)
        page = self.paginate_queryset(qs)
        if page is not None:
            self._attach_pricing_object(page)
            return self.get_paginated_response(
                ProductListSerializer(
                    page, many=True, context={'request': request}
                ).data
            )
        products = list(qs)
        self._attach_pricing_object(products)
        return Response(
            ProductListSerializer(
                products, many=True, context={'request': request}
            ).data
        )

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """✅ Copie PHYSIQUE des fichiers images (pas de partage)"""
        original = self.get_object()

        duplicate = Product.objects.create(
            reference=f"{original.reference}_COPY_{timezone.now().strftime('%Y%m%d%H%M%S')}",
            name=f"{original.name} (copie)",
            description=original.description,
            product_type=original.product_type,
            category=original.category,
            brand=original.brand,
            unit=original.unit,
            created_by=request.user,
            minimum_stock=original.minimum_stock,
            maximum_stock=original.maximum_stock,
            location=original.location,
            is_active=False,
            is_featured=False,
            has_variants=original.has_variants,
            weight=original.weight,
            volume=original.volume,
        )

        for image in original.images.all():
            new_img = ProductImage(
                product=duplicate,
                alt_text=image.alt_text,
                is_main=image.is_main,
            )
            if image.image:
                with image.image.open('rb') as f:
                    new_img.image.save(
                        os.path.basename(image.image.name),
                        File(f),
                        save=False,
                    )
            new_img.save()

        for variant in original.variants.all():
            ProductVariant.objects.create(
                product=duplicate,
                sku=f"{variant.sku}_COPY_{timezone.now().strftime('%Y%m%d%H%M%S')}",
                attributes=variant.attributes,
                stock_quantity=0,
                is_active=False,
            )

        _purge_products_cache()
        serializer = ProductDetailSerializer(
            duplicate, context={'request': request}
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='toggle-active')
    def toggle_active(self, request, pk=None):
        product = self.get_object()
        product.is_active = not product.is_active
        product.save(update_fields=['is_active', 'updated_at'])
        _purge_products_cache()
        return Response({
            'message': f'Produit {"activé" if product.is_active else "désactivé"}',
            'is_active': product.is_active,
        })

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        product = self.get_object()
        from inventaire.models import StockMovement, TransferItem

        entries = StockMovement.objects.filter(
            product=product, movement_type='in'
        ).aggregate(total=Sum('quantity'))['total'] or 0

        exits = StockMovement.objects.filter(
            product=product, movement_type='out'
        ).aggregate(total=Sum('quantity'))['total'] or 0

        trans_out = StockMovement.objects.filter(
            product=product, movement_type='transfer',
            from_warehouse__isnull=False
        ).aggregate(total=Sum('quantity'))['total'] or 0

        trans_in = StockMovement.objects.filter(
            product=product, movement_type='transfer',
            to_warehouse__isnull=False
        ).aggregate(total=Sum('quantity'))['total'] or 0

        pending = TransferItem.objects.filter(
            product=product,
            transfer__status__in=[
                'pending_approval', 'approved', 'in_transit'
            ],
            quantity__gt=F('quantity_received'),
        ).count()

        return Response({
            'product_id': product.id,
            'product_name': product.name,
            'total_stock': product.stock_quantity,
            'statistics': {
                'total_entries': entries,
                'total_exits': exits,
                'total_transferred_out': trans_out,
                'total_transferred_in': trans_in,
                'net_movement': entries + trans_in - exits - trans_out,
            },
            'pending_transfers': pending,
            'has_variants': product.has_variants,
            'variants_count': product.variants.count(),
            'images_count': product.images.count(),
            'warehouses_count': product.warehouse_stocks.count(),
        })


# ============================================================
# PRODUCT VARIANT VIEWSET
# ============================================================
class ProductVariantViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = ProductVariant.objects.select_related('product')
    serializer_class = ProductVariantSerializer
    pagination_class = OptimizedPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'is_active']
    search_fields = ['sku']

    def perform_create(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_destroy(self, instance):
        instance.delete()
        _purge_products_cache()


# ============================================================
# PRODUCT PRICING VIEWSET  (✅ OPTIMISÉ)
# ============================================================
class ProductPricingViewSet(viewsets.ModelViewSet):
    serializer_class = ProductPricingSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = OptimizedPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'warehouse', 'is_current']
    search_fields = ['product__name', 'product__reference', 'warehouse__name']

    def get_permissions(self):
        if self.action in (
            'create', 'update', 'partial_update', 'destroy', 'set_price'
        ):
            return [IsAuthenticated(), IsPDGOrChefAgence()]
        return [IsAuthenticated()]

    def get_queryset(self):
        # ✅ Cache des permissions par requête
        if hasattr(self, '_base_qs'):
            return self._base_qs

        user = self.request.user
        base = ProductPricing.objects.select_related('warehouse', 'product')

        if user.est_pdg() or user.est_drh():
            self._base_qs = base
        elif user.est_chef_agence():
            agences_ids = list(user.get_agences().values_list('id', flat=True))
            self._base_qs = base.filter(warehouse__agence_id__in=agences_ids)
        else:
            self._base_qs = base.none()

        return self._base_qs

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        product_id = request.query_params.get('product_id')
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        warehouse_id = request.query_params.get('warehouse_id')
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)

        is_current = request.query_params.get('is_current')
        if is_current is not None:
            queryset = queryset.filter(
                is_current=str(is_current).lower() == 'true'
            )

        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(
                self.get_serializer(page, many=True).data
            )
        return Response(self.get_serializer(queryset, many=True).data)

    def create(self, request, *args, **kwargs):
        try:
            product_id = request.data.get('product')
            warehouse_id = request.data.get('warehouse')

            ProductPricing.objects.filter(
                product_id=product_id,
                warehouse_id=warehouse_id,
                is_current=True,
            ).update(is_current=False, valid_to=timezone.now().date())

            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(updated_by=request.user, is_current=True)
            _purge_products_cache()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': f'Erreur: {str(e)}'},
                            status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        """✅ Historisation : ancien désactivé, NOUVEL enregistrement créé."""
        try:
            partial = kwargs.pop('partial', False)
            instance = self.get_object()

            serializer = self.get_serializer(
                instance, data=request.data, partial=partial
            )
            serializer.is_valid(raise_exception=True)

            instance.is_current = False
            instance.valid_to = timezone.now().date()
            instance.save(update_fields=['is_current', 'valid_to'])

            new_pricing = ProductPricing.objects.create(
                product=instance.product,
                warehouse=instance.warehouse,
                purchase_price=serializer.validated_data.get(
                    'purchase_price', instance.purchase_price
                ),
                sale_price=serializer.validated_data.get(
                    'sale_price', instance.sale_price
                ),
                wholesale_price=serializer.validated_data.get(
                    'wholesale_price', instance.wholesale_price
                ),
                currency=serializer.validated_data.get(
                    'currency', instance.currency
                ),
                updated_by=request.user,
                is_current=True,
                valid_from=timezone.now().date(),
            )
            _purge_products_cache()
            return Response(self.get_serializer(new_pricing).data)
        except Exception as e:
            return Response({'error': f'Erreur: {str(e)}'},
                            status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            instance.is_current = False
            instance.valid_to = timezone.now().date()
            instance.save(update_fields=['is_current', 'valid_to'])
            _purge_products_cache()
            return Response({'message': 'Prix désactivé'},
                            status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)},
                            status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='set-price')
    def set_price(self, request):
        product_id = request.data.get('product_id')
        warehouse_id = request.data.get('warehouse_id')
        purchase_price = request.data.get('purchase_price')
        sale_price = request.data.get('sale_price')

        if not product_id:
            return Response({'error': 'product_id requis'}, status=400)
        if not warehouse_id:
            return Response({'error': 'warehouse_id requis'}, status=400)
        if purchase_price is None:
            return Response({'error': 'purchase_price requis'}, status=400)
        if sale_price is None:
            return Response({'error': 'sale_price requis'}, status=400)

        try:
            product = Product.objects.get(id=product_id)
            warehouse = Warehouse.objects.get(id=warehouse_id)

            try:
                purchase_price = float(purchase_price)
                sale_price = float(sale_price)
            except ValueError:
                return Response({'error': 'Prix invalides'}, status=400)

            if sale_price < purchase_price:
                return Response(
                    {'error': 'Le prix de vente ne peut pas être inférieur au prix d\'achat'},
                    status=400,
                )

            wholesale_price = request.data.get('wholesale_price')
            if wholesale_price not in (None, ''):
                try:
                    wholesale_price = float(wholesale_price)
                except ValueError:
                    return Response({'error': 'Prix de gros invalide'}, status=400)
            else:
                wholesale_price = None

            ProductPricing.objects.filter(
                product=product, warehouse=warehouse, is_current=True
            ).update(is_current=False, valid_to=timezone.now().date())

            pricing = ProductPricing.objects.create(
                product=product,
                warehouse=warehouse,
                purchase_price=purchase_price,
                sale_price=sale_price,
                wholesale_price=wholesale_price,
                currency=request.data.get('currency', 'XOF'),
                updated_by=request.user,
                is_current=True,
                valid_from=timezone.now().date(),
            )
            _purge_products_cache()

            serializer = self.get_serializer(pricing)
            return Response({
                'success': True,
                'message': 'Prix enregistré',
                'data': serializer.data,
            }, status=200)

        except Product.DoesNotExist:
            return Response({'error': 'Produit non trouvé'}, status=404)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Entrepôt non trouvé'}, status=404)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['get'], url_path='by-warehouse')
    def by_warehouse(self, request):
        warehouse_id = request.query_params.get('warehouse_id')
        if not warehouse_id:
            return Response({'error': 'warehouse_id requis'}, status=400)
        try:
            prices = self.get_queryset().filter(
                warehouse_id=warehouse_id, is_current=True
            ).select_related('product', 'warehouse')
            return Response(self.get_serializer(prices, many=True).data)
        except Exception as e:
            return Response({'error': str(e)}, status=400)

    @action(detail=False, methods=['get'], url_path='by-product')
    def by_product(self, request):
        product_id = request.query_params.get('product_id')
        if not product_id:
            return Response({'error': 'product_id requis'}, status=400)
        prices = self.get_queryset().filter(
            product_id=product_id, is_current=True
        )
        return Response(self.get_serializer(prices, many=True).data)

    @action(detail=False, methods=['get'], url_path='by-product-and-warehouse')
    def by_product_and_warehouse(self, request):
        product_id = request.query_params.get('product_id')
        warehouse_id = request.query_params.get('warehouse_id')
        if not product_id or not warehouse_id:
            return Response(
                {'error': 'product_id et warehouse_id requis'},
                status=400,
            )
        try:
            pricing = ProductPricing.objects.select_related(
                'product', 'warehouse'
            ).get(
                product_id=product_id,
                warehouse_id=warehouse_id,
                is_current=True,
            )
            return Response(self.get_serializer(pricing).data)
        except ProductPricing.DoesNotExist:
            return Response(
                {'message': 'Aucun prix défini pour ce produit dans cet entrepôt'},
                status=404,
            )  # products/views.py


# ============================================================
# HELPERS DE CACHE
# ============================================================
def _purge_products_cache():
    """Purge le cache des listes produits (appelé après toute mutation)."""
    try:
        cache.delete_pattern('products_*')
    except Exception:
        # Fallback si django-redis n'est pas installé
        cache.clear()


# ============================================================
# CATEGORY VIEWSET
# ============================================================
class CategoryViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = SmallPagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'parent']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at',
                       'products_count', 'subcategories_count']

    def get_queryset(self):
        # ✅ annotate au lieu de source='products.count' (N+1)
        return Category.objects.annotate(
            products_count=Count('products', distinct=True),
            subcategories_count=Count('subcategories', distinct=True),
        )

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return CategoryDetailSerializer
        return CategorySerializer

    def perform_create(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_destroy(self, instance):
        instance.delete()
        _purge_products_cache()

    @action(detail=False, methods=['get'])
    def tree(self, request):
        categories = self.get_queryset().filter(parent__isnull=True)
        serializer = self.get_serializer(categories, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        category = self.get_object()
        qs = (
            category.products.filter(is_active=True)
            .select_related('category', 'brand', 'unit')
            .order_by('name')
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = ProductListSerializer(
                page, many=True, context={'request': request}
            )
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(
            qs, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================
# BRAND VIEWSET
# ============================================================
class BrandViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = SmallPagination
    serializer_class = BrandSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at', 'products_count']

    def get_queryset(self):
        return Brand.objects.annotate(
            products_count=Count('products', distinct=True)
        )

    def perform_create(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_destroy(self, instance):
        instance.delete()
        _purge_products_cache()

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        brand = self.get_object()
        qs = (
            brand.products.filter(is_active=True)
            .select_related('category', 'brand', 'unit')
            .order_by('name')
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = ProductListSerializer(
                page, many=True, context={'request': request}
            )
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(
            qs, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================
# UNIT VIEWSET
# ============================================================
class UnitViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    pagination_class = SmallPagination


# ============================================================
# PRODUCT VIEWSET  (✅ VITESSE OPTIMISÉE)
# ============================================================
class ProductViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProductPagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'brand', 'is_active', 'product_type']
    search_fields = ['reference', 'barcode', 'name', 'description']
    ordering_fields = ['created_at', 'name', 'stock_quantity']

    # ---------- helpers ----------
    def _resolve_warehouse_id(self):
        """
        Priorité :
        1. ?warehouse_id=... (ou ?warehouse=...)
        2. agence principale de l'utilisateur -> entrepôt par défaut
        """
        wid = (
            self.request.query_params.get('warehouse_id')
            or self.request.query_params.get('warehouse')
        )
        if wid:
            return wid

        user = self.request.user
        if hasattr(user, 'get_agence_principale'):
            agence = user.get_agence_principale()
            if agence:
                wh = agence.warehouses.filter(is_default=True).first()
                if wh:
                    return wh.id
        return None

    def _apply_pricing_prefetch(self, queryset):
        """
        ✅ Prefetch (1 seule requête SQL) au lieu de 3 Subquery.
        Plus rapide : le prix est indexé par produit côté Python.
        """
        warehouse_id = self._resolve_warehouse_id()
        pricing_qs = (
            ProductPricing.objects
            .filter(is_current=True)
            .select_related('warehouse')
            .order_by('id')
        )
        if warehouse_id:
            pricing_qs = pricing_qs.filter(warehouse_id=warehouse_id)

        return queryset.prefetch_related(
            Prefetch('prices', queryset=pricing_qs,
                     to_attr='_prefetched_prices')
        )

    def _attach_pricing_object(self, products):
        """
        ✅ Hydrate `_pricing` depuis le prefetch (0 requête SQL supplémentaire).
        Compatible avec Subquery (fallback si présent).
        """
        for p in products:
            prefetched = getattr(p, '_prefetched_prices', None)
            if prefetched:
                p._pricing = prefetched[0]
            elif getattr(p, '_purchase_price', None) is not None \
                    or getattr(p, '_sale_price', None) is not None:
                # Fallback si Subquery a été utilisé (rétrocompat)
                p._pricing = type('P', (), {
                    'purchase_price': getattr(p, '_purchase_price', None),
                    'sale_price': getattr(p, '_sale_price', None),
                    'wholesale_price': getattr(p, '_wholesale_price', None),
                })()
            else:
                p._pricing = None

    # ---------- queryset ----------
    def get_queryset(self):
        if self.action in ('list', 'low_stock', 'out_of_stock', 'featured',
                           'by_category', 'by_brand'):
            # ✅ Pas de created_by en liste : JOIN inutile
            base = Product.objects.select_related('category', 'brand', 'unit')
            return self._apply_pricing_prefetch(base)

        if self.action == 'retrieve':
            # ✅ Détail : created_by + prefetch prices/images/variants
            base = Product.objects.select_related(
                'category', 'brand', 'unit', 'created_by'
            )
            user = self.request.user
            prices_qs = (
                ProductPricing.objects.filter(is_current=True)
                .select_related('warehouse')
            )
            if not user.est_pdg():
                agences_ids = user.get_agences().values_list('id', flat=True)
                prices_qs = prices_qs.filter(
                    warehouse__agence_id__in=agences_ids)

            return base.prefetch_related(
                Prefetch('prices', queryset=prices_qs,
                         to_attr='_prices_detail'),
                Prefetch(
                    'images',
                    queryset=ProductImage.objects.order_by(
                        '-is_main', 'created_at'),
                ),
                Prefetch(
                    'variants',
                    queryset=ProductVariant.objects.filter(is_active=True),
                ),
            )

        # Actions d'écriture : simple select_related
        return Product.objects.select_related('category', 'brand', 'unit')

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        if self.action == 'retrieve':
            return ProductDetailSerializer
        return ProductCreateUpdateSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        ctx['warehouse_id'] = self._resolve_warehouse_id()
        return ctx

    # ---------- list avec cache 60s ----------
    def list(self, request, *args, **kwargs):
        # ✅ Cache 60s par combinaison user + URL complète
        cache_key = f'products_list_{request.user.id}_{request.get_full_path()}'
        bypass = request.query_params.get('nocache') == '1'
        if not bypass:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            self._attach_pricing_object(page)
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            if not bypass:
                cache.set(cache_key, response.data, 60)
            return response

        products = list(queryset)
        self._attach_pricing_object(products)
        serializer = self.get_serializer(products, many=True)
        data = serializer.data
        if not bypass:
            cache.set(cache_key, data, 60)
        return Response(data)

    # ---------- CRUD : purge cache ----------
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_products_cache()

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        remove_main_image = request.data.get('remove_main_image', 'false')
        if str(remove_main_image).lower() == 'true' and instance.main_image:
            if os.path.isfile(instance.main_image.path):
                try:
                    os.remove(instance.main_image.path)
                except Exception as e:
                    print(f"Erreur suppression image: {e}")
            instance.main_image = None

        if 'main_image' in request.FILES and instance.main_image:
            if os.path.isfile(instance.main_image.path):
                try:
                    os.remove(instance.main_image.path)
                except Exception as e:
                    print(f"Erreur suppression image: {e}")

        serializer = self.get_serializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        _purge_products_cache()
        return Response(serializer.data)

    def perform_destroy(self, instance):
        instance.delete()
        _purge_products_cache()

    # ---------- actions ----------
    @action(detail=False, methods=['get'], url_path='low-stock')
    def low_stock(self, request):
        qs = self.get_queryset().filter(stock_quantity__lte=F('minimum_stock'))
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(
                ProductStockAlertSerializer(page, many=True).data
            )
        return Response(ProductStockAlertSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'], url_path='out-of-stock')
    def out_of_stock(self, request):
        qs = self.get_queryset().filter(stock_quantity=0)
        page = self.paginate_queryset(qs)
        if page is not None:
            self._attach_pricing_object(page)
            return self.get_paginated_response(
                ProductListSerializer(
                    page, many=True, context={'request': request}
                ).data
            )
        products = list(qs)
        self._attach_pricing_object(products)
        return Response(
            ProductListSerializer(
                products, many=True, context={'request': request}
            ).data
        )

    @action(detail=True, methods=['get'])
    def prices(self, request, pk=None):
        product = self.get_object()
        user = request.user

        if user.est_pdg() or user.est_drh():
            warehouses = Warehouse.objects.filter(is_active=True)
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            warehouses = Warehouse.objects.filter(
                agence_id__in=agences_ids, is_active=True
            )

        prices = (
            product.prices
            .filter(warehouse__in=warehouses, is_current=True)
            .select_related('warehouse', 'product')
        )
        serializer = ProductPricingSerializer(
            prices, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def images(self, request, pk=None):
        product = self.get_object()
        images = product.images.all()
        serializer = ProductImageSerializer(
            images, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def variants(self, request, pk=None):
        product = self.get_object()
        variants = product.variants.filter(is_active=True)
        serializer = ProductVariantSerializer(variants, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='add-image')
    def add_image(self, request, pk=None):
        product = self.get_object()
        image_file = request.FILES.get('image')

        if not image_file:
            return Response({'error': 'Aucune image fournie'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not image_file.content_type.startswith('image/'):
            return Response({'error': 'Le fichier doit être une image'},
                            status=status.HTTP_400_BAD_REQUEST)
        if image_file.size > 5 * 1024 * 1024:
            return Response({'error': 'L\'image ne doit pas dépasser 5MB'},
                            status=status.HTTP_400_BAD_REQUEST)

        is_main = str(request.data.get('is_main', 'false')).lower() == 'true'

        if is_main:
            product.images.filter(is_main=True).update(is_main=False)
            product.main_image = image_file
            product.save()

        image = ProductImage.objects.create(
            product=product,
            image=image_file,
            alt_text=request.data.get('alt_text', ''),
            is_main=is_main,
        )
        _purge_products_cache()
        serializer = ProductImageSerializer(
            image, context={'request': request}
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path='remove-image')
    def remove_image(self, request, pk=None):
        product = self.get_object()
        image_id = request.query_params.get('image_id')

        if not image_id:
            return Response({'error': 'image_id est requis'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            image = product.images.get(id=image_id)
            was_main = image.is_main
            image.delete()

            if was_main:
                next_image = product.images.first()
                if next_image:
                    next_image.is_main = True
                    next_image.save()
                    product.main_image = next_image.image
                else:
                    product.main_image = None
                product.save()

            _purge_products_cache()
            return Response({'message': 'Image supprimée avec succès'},
                            status=status.HTTP_200_OK)
        except ProductImage.DoesNotExist:
            return Response({'error': 'Image non trouvée'},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': f'Erreur: {str(e)}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['delete'], url_path='remove-main-image')
    def remove_main_image(self, request, pk=None):
        product = self.get_object()
        if not product.main_image:
            return Response({'error': 'Aucune image principale'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            if os.path.isfile(product.main_image.path):
                os.remove(product.main_image.path)
            product.main_image = None
            product.save()
            product.images.filter(is_main=True).update(is_main=False)
            _purge_products_cache()
            return Response({'message': 'Image principale supprimée'},
                            status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': f'Erreur: {str(e)}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='set-main-image')
    def set_main_image(self, request, pk=None):
        product = self.get_object()
        image_id = (
            request.data.get('image_id')
            or request.query_params.get('image_id')
        )
        if not image_id:
            return Response({'error': 'image_id est requis'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            product.images.filter(is_main=True).update(is_main=False)
            image = product.images.get(id=image_id)
            image.is_main = True
            image.save()
            product.main_image = image.image
            product.save()
            _purge_products_cache()
            return Response({'message': 'Image principale mise à jour'},
                            status=status.HTTP_200_OK)
        except ProductImage.DoesNotExist:
            return Response({'error': 'Image non trouvée'},
                            status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'], url_path='replace-main-image')
    def replace_main_image(self, request, pk=None):
        product = self.get_object()
        image_file = request.FILES.get('image')
        if not image_file:
            return Response({'error': 'Aucune image fournie'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            if product.main_image and os.path.isfile(product.main_image.path):
                os.remove(product.main_image.path)
            product.main_image = image_file
            product.save()
            product.images.filter(is_main=True).update(is_main=False)
            ProductImage.objects.create(
                product=product,
                image=image_file,
                alt_text=request.data.get('alt_text', product.name),
                is_main=True,
            )
            _purge_products_cache()
            return Response({
                'message': 'Image principale remplacée',
                'main_image': request.build_absolute_uri(product.main_image.url),
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': f'Erreur: {str(e)}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='stock-by-warehouse')
    def stock_by_warehouse(self, request, pk=None):
        product = self.get_object()
        user = request.user

        if user.est_pdg() or user.est_drh():
            warehouses = Warehouse.objects.filter(is_active=True)
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            warehouses = Warehouse.objects.filter(
                agence_id__in=agences_ids, is_active=True
            )

        from inventaire.models import WarehouseStock
        from inventaire.serializers import WarehouseStockSerializer

        stocks = (
            WarehouseStock.objects
            .filter(product=product, warehouse__in=warehouses)
            .select_related('warehouse', 'product')
        )
        return Response(WarehouseStockSerializer(stocks, many=True).data)

    @action(detail=False, methods=['get'], url_path='by-category')
    def by_category(self, request):
        category_id = request.query_params.get('category_id')
        if not category_id:
            return Response({'error': 'category_id est requis'},
                            status=status.HTTP_400_BAD_REQUEST)

        qs = self.get_queryset().filter(category_id=category_id, is_active=True)
        page = self.paginate_queryset(qs)
        if page is not None:
            self._attach_pricing_object(page)
            return self.get_paginated_response(
                ProductListSerializer(
                    page, many=True, context={'request': request}
                ).data
            )
        products = list(qs)
        self._attach_pricing_object(products)
        return Response(
            ProductListSerializer(
                products, many=True, context={'request': request}
            ).data
        )

    @action(detail=False, methods=['get'], url_path='by-brand')
    def by_brand(self, request):
        brand_id = request.query_params.get('brand_id')
        if not brand_id:
            return Response({'error': 'brand_id est requis'},
                            status=status.HTTP_400_BAD_REQUEST)

        qs = self.get_queryset().filter(brand_id=brand_id, is_active=True)
        page = self.paginate_queryset(qs)
        if page is not None:
            self._attach_pricing_object(page)
            return self.get_paginated_response(
                ProductListSerializer(
                    page, many=True, context={'request': request}
                ).data
            )
        products = list(qs)
        self._attach_pricing_object(products)
        return Response(
            ProductListSerializer(
                products, many=True, context={'request': request}
            ).data
        )

    @action(detail=False, methods=['get'])
    def featured(self, request):
        qs = self.get_queryset().filter(is_featured=True, is_active=True)
        page = self.paginate_queryset(qs)
        if page is not None:
            self._attach_pricing_object(page)
            return self.get_paginated_response(
                ProductListSerializer(
                    page, many=True, context={'request': request}
                ).data
            )
        products = list(qs)
        self._attach_pricing_object(products)
        return Response(
            ProductListSerializer(
                products, many=True, context={'request': request}
            ).data
        )

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """✅ Copie PHYSIQUE des fichiers images (pas de partage)"""
        original = self.get_object()

        duplicate = Product.objects.create(
            reference=f"{original.reference}_COPY_{timezone.now().strftime('%Y%m%d%H%M%S')}",
            name=f"{original.name} (copie)",
            description=original.description,
            product_type=original.product_type,
            category=original.category,
            brand=original.brand,
            unit=original.unit,
            created_by=request.user,
            minimum_stock=original.minimum_stock,
            maximum_stock=original.maximum_stock,
            location=original.location,
            is_active=False,
            is_featured=False,
            has_variants=original.has_variants,
            weight=original.weight,
            volume=original.volume,
        )

        for image in original.images.all():
            new_img = ProductImage(
                product=duplicate,
                alt_text=image.alt_text,
                is_main=image.is_main,
            )
            if image.image:
                with image.image.open('rb') as f:
                    new_img.image.save(
                        os.path.basename(image.image.name),
                        File(f),
                        save=False,
                    )
            new_img.save()

        for variant in original.variants.all():
            ProductVariant.objects.create(
                product=duplicate,
                sku=f"{variant.sku}_COPY_{timezone.now().strftime('%Y%m%d%H%M%S')}",
                attributes=variant.attributes,
                stock_quantity=0,
                is_active=False,
            )

        _purge_products_cache()
        serializer = ProductDetailSerializer(
            duplicate, context={'request': request}
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='toggle-active')
    def toggle_active(self, request, pk=None):
        product = self.get_object()
        product.is_active = not product.is_active
        product.save(update_fields=['is_active', 'updated_at'])
        _purge_products_cache()
        return Response({
            'message': f'Produit {"activé" if product.is_active else "désactivé"}',
            'is_active': product.is_active,
        })

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        product = self.get_object()
        from inventaire.models import StockMovement, TransferItem

        entries = StockMovement.objects.filter(
            product=product, movement_type='in'
        ).aggregate(total=Sum('quantity'))['total'] or 0

        exits = StockMovement.objects.filter(
            product=product, movement_type='out'
        ).aggregate(total=Sum('quantity'))['total'] or 0

        trans_out = StockMovement.objects.filter(
            product=product, movement_type='transfer',
            from_warehouse__isnull=False
        ).aggregate(total=Sum('quantity'))['total'] or 0

        trans_in = StockMovement.objects.filter(
            product=product, movement_type='transfer',
            to_warehouse__isnull=False
        ).aggregate(total=Sum('quantity'))['total'] or 0

        pending = TransferItem.objects.filter(
            product=product,
            transfer__status__in=[
                'pending_approval', 'approved', 'in_transit'
            ],
            quantity__gt=F('quantity_received'),
        ).count()

        return Response({
            'product_id': product.id,
            'product_name': product.name,
            'total_stock': product.stock_quantity,
            'statistics': {
                'total_entries': entries,
                'total_exits': exits,
                'total_transferred_out': trans_out,
                'total_transferred_in': trans_in,
                'net_movement': entries + trans_in - exits - trans_out,
            },
            'pending_transfers': pending,
            'has_variants': product.has_variants,
            'variants_count': product.variants.count(),
            'images_count': product.images.count(),
            'warehouses_count': product.warehouse_stocks.count(),
        })


# ============================================================
# PRODUCT VARIANT VIEWSET
# ============================================================
class ProductVariantViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = ProductVariant.objects.select_related('product')
    serializer_class = ProductVariantSerializer
    pagination_class = OptimizedPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'is_active']
    search_fields = ['sku']

    def perform_create(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_products_cache()

    def perform_destroy(self, instance):
        instance.delete()
        _purge_products_cache()


# ============================================================
# PRODUCT PRICING VIEWSET  (✅ OPTIMISÉ)
# ============================================================
class ProductPricingViewSet(viewsets.ModelViewSet):
    serializer_class = ProductPricingSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = OptimizedPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'warehouse', 'is_current']
    search_fields = ['product__name', 'product__reference', 'warehouse__name']

    def get_permissions(self):
        if self.action in (
            'create', 'update', 'partial_update', 'destroy', 'set_price'
        ):
            return [IsAuthenticated(), IsPDGOrChefAgence()]
        return [IsAuthenticated()]

    def get_queryset(self):
        # ✅ Cache des permissions par requête
        if hasattr(self, '_base_qs'):
            return self._base_qs

        user = self.request.user
        base = ProductPricing.objects.select_related('warehouse', 'product')

        if user.est_pdg() or user.est_drh():
            self._base_qs = base
        elif user.est_chef_agence():
            agences_ids = list(user.get_agences().values_list('id', flat=True))
            self._base_qs = base.filter(warehouse__agence_id__in=agences_ids)
        else:
            self._base_qs = base.none()

        return self._base_qs

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        product_id = request.query_params.get('product_id')
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        warehouse_id = request.query_params.get('warehouse_id')
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)

        is_current = request.query_params.get('is_current')
        if is_current is not None:
            queryset = queryset.filter(
                is_current=str(is_current).lower() == 'true'
            )

        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(
                self.get_serializer(page, many=True).data
            )
        return Response(self.get_serializer(queryset, many=True).data)

    def create(self, request, *args, **kwargs):
        try:
            product_id = request.data.get('product')
            warehouse_id = request.data.get('warehouse')

            ProductPricing.objects.filter(
                product_id=product_id,
                warehouse_id=warehouse_id,
                is_current=True,
            ).update(is_current=False, valid_to=timezone.now().date())

            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(updated_by=request.user, is_current=True)
            _purge_products_cache()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': f'Erreur: {str(e)}'},
                            status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        """✅ Historisation : ancien désactivé, NOUVEL enregistrement créé."""
        try:
            partial = kwargs.pop('partial', False)
            instance = self.get_object()

            serializer = self.get_serializer(
                instance, data=request.data, partial=partial
            )
            serializer.is_valid(raise_exception=True)

            instance.is_current = False
            instance.valid_to = timezone.now().date()
            instance.save(update_fields=['is_current', 'valid_to'])

            new_pricing = ProductPricing.objects.create(
                product=instance.product,
                warehouse=instance.warehouse,
                purchase_price=serializer.validated_data.get(
                    'purchase_price', instance.purchase_price
                ),
                sale_price=serializer.validated_data.get(
                    'sale_price', instance.sale_price
                ),
                wholesale_price=serializer.validated_data.get(
                    'wholesale_price', instance.wholesale_price
                ),
                currency=serializer.validated_data.get(
                    'currency', instance.currency
                ),
                updated_by=request.user,
                is_current=True,
                valid_from=timezone.now().date(),
            )
            _purge_products_cache()
            return Response(self.get_serializer(new_pricing).data)
        except Exception as e:
            return Response({'error': f'Erreur: {str(e)}'},
                            status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            instance.is_current = False
            instance.valid_to = timezone.now().date()
            instance.save(update_fields=['is_current', 'valid_to'])
            _purge_products_cache()
            return Response({'message': 'Prix désactivé'},
                            status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)},
                            status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='set-price')
    def set_price(self, request):
        product_id = request.data.get('product_id')
        warehouse_id = request.data.get('warehouse_id')
        purchase_price = request.data.get('purchase_price')
        sale_price = request.data.get('sale_price')

        if not product_id:
            return Response({'error': 'product_id requis'}, status=400)
        if not warehouse_id:
            return Response({'error': 'warehouse_id requis'}, status=400)
        if purchase_price is None:
            return Response({'error': 'purchase_price requis'}, status=400)
        if sale_price is None:
            return Response({'error': 'sale_price requis'}, status=400)

        try:
            product = Product.objects.get(id=product_id)
            warehouse = Warehouse.objects.get(id=warehouse_id)

            try:
                purchase_price = float(purchase_price)
                sale_price = float(sale_price)
            except ValueError:
                return Response({'error': 'Prix invalides'}, status=400)

            if sale_price < purchase_price:
                return Response(
                    {'error': 'Le prix de vente ne peut pas être inférieur au prix d\'achat'},
                    status=400,
                )

            wholesale_price = request.data.get('wholesale_price')
            if wholesale_price not in (None, ''):
                try:
                    wholesale_price = float(wholesale_price)
                except ValueError:
                    return Response({'error': 'Prix de gros invalide'}, status=400)
            else:
                wholesale_price = None

            ProductPricing.objects.filter(
                product=product, warehouse=warehouse, is_current=True
            ).update(is_current=False, valid_to=timezone.now().date())

            pricing = ProductPricing.objects.create(
                product=product,
                warehouse=warehouse,
                purchase_price=purchase_price,
                sale_price=sale_price,
                wholesale_price=wholesale_price,
                currency=request.data.get('currency', 'XOF'),
                updated_by=request.user,
                is_current=True,
                valid_from=timezone.now().date(),
            )
            _purge_products_cache()

            serializer = self.get_serializer(pricing)
            return Response({
                'success': True,
                'message': 'Prix enregistré',
                'data': serializer.data,
            }, status=200)

        except Product.DoesNotExist:
            return Response({'error': 'Produit non trouvé'}, status=404)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Entrepôt non trouvé'}, status=404)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['get'], url_path='by-warehouse')
    def by_warehouse(self, request):
        warehouse_id = request.query_params.get('warehouse_id')
        if not warehouse_id:
            return Response({'error': 'warehouse_id requis'}, status=400)
        try:
            prices = self.get_queryset().filter(
                warehouse_id=warehouse_id, is_current=True
            ).select_related('product', 'warehouse')
            return Response(self.get_serializer(prices, many=True).data)
        except Exception as e:
            return Response({'error': str(e)}, status=400)

    @action(detail=False, methods=['get'], url_path='by-product')
    def by_product(self, request):
        product_id = request.query_params.get('product_id')
        if not product_id:
            return Response({'error': 'product_id requis'}, status=400)
        prices = self.get_queryset().filter(
            product_id=product_id, is_current=True
        )
        return Response(self.get_serializer(prices, many=True).data)

    @action(detail=False, methods=['get'], url_path='by-product-and-warehouse')
    def by_product_and_warehouse(self, request):
        product_id = request.query_params.get('product_id')
        warehouse_id = request.query_params.get('warehouse_id')
        if not product_id or not warehouse_id:
            return Response(
                {'error': 'product_id et warehouse_id requis'},
                status=400,
            )
        try:
            pricing = ProductPricing.objects.select_related(
                'product', 'warehouse'
            ).get(
                product_id=product_id,
                warehouse_id=warehouse_id,
                is_current=True,
            )
            return Response(self.get_serializer(pricing).data)
        except ProductPricing.DoesNotExist:
            return Response(
                {'message': 'Aucun prix défini pour ce produit dans cet entrepôt'},
                status=404,
            )
