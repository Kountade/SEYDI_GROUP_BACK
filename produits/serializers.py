# products/serializers.py

import os
from django.core.files import File
from rest_framework import serializers
from .models import (
    Category, Brand, Unit, Product, ProductImage,
    ProductVariant, ProductPricing
)
from users.serializers import UserSerializer


# ============================================================
# CATEGORY
# ============================================================
class CategorySerializer(serializers.ModelSerializer):
    # ✅ Compteurs fournis par annotate() dans le ViewSet
    products_count = serializers.IntegerField(read_only=True, default=0)
    subcategories_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = '__all__'


class CategoryDetailSerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()
    subcategories = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = '__all__'

    def get_products(self, obj):
        qs = obj.products.filter(is_active=True).select_related(
            'category', 'brand', 'unit'
        )[:10]
        return ProductListSerializer(qs, many=True, context=self.context).data

    def get_subcategories(self, obj):
        return CategorySerializer(
            obj.subcategories.filter(is_active=True), many=True
        ).data


# ============================================================
# BRAND
# ============================================================
class BrandSerializer(serializers.ModelSerializer):
    products_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Brand
        fields = '__all__'


# ============================================================
# UNIT
# ============================================================
class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = '__all__'


# ============================================================
# PRODUCT IMAGE
# ============================================================
class ProductImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = '__all__'

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None


# ============================================================
# PRODUCT VARIANT
# ============================================================
class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = '__all__'


# ============================================================
# PRODUCT LIST  (✅ OPTIMISÉ - N+1 éliminé)
# ============================================================
class ProductListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    unit_abbrev = serializers.CharField(source='unit.abbreviation', read_only=True)
    main_image = serializers.SerializerMethodField()

    purchase_price = serializers.SerializerMethodField()
    sale_price = serializers.SerializerMethodField()
    wholesale_price = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            'id', 'reference', 'barcode', 'name',
            'category_name', 'brand_name',
            'purchase_price', 'sale_price', 'wholesale_price',
            'stock_quantity', 'minimum_stock', 'is_low_stock',
            'is_active', 'is_featured', 'main_image', 'unit_abbrev',
        )

    def get_main_image(self, obj):
        request = self.context.get('request')
        if obj.main_image and request:
            return request.build_absolute_uri(obj.main_image.url)
        return None

    def _pricing(self, obj):
        # ✅ Utilise l'annotation posée par le ViewSet (0 requête SQL ici)
        return getattr(obj, '_pricing', None)

    def get_purchase_price(self, obj):
        p = self._pricing(obj)
        return p.purchase_price if p else None

    def get_sale_price(self, obj):
        p = self._pricing(obj)
        return p.sale_price if p else None

    def get_wholesale_price(self, obj):
        p = self._pricing(obj)
        return p.wholesale_price if p else None


# ============================================================
# PRODUCT DETAIL
# ============================================================
class ProductDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    brand = BrandSerializer(read_only=True)
    unit = UnitSerializer(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    main_image = serializers.SerializerMethodField()
    prices = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = '__all__'

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name()
        return None

    def get_main_image(self, obj):
        request = self.context.get('request')
        if obj.main_image and request:
            return request.build_absolute_uri(obj.main_image.url)
        elif obj.main_image:
            return obj.main_image.url
        return None

    def get_prices(self, obj):
        """
        ✅ Utilise le prefetch `_prices_detail` du ViewSet si disponible.
        Sinon, requête filtrée SQL (jamais Python-filter).
        """
        request = self.context.get('request')
        if not (request and hasattr(request, 'user')):
            return []
        user = request.user

        # Prefetch déjà chargé côté ViewSet
        prefetched = getattr(obj, '_prices_detail', None)
        if prefetched is not None:
            return ProductPricingSerializer(
                prefetched, many=True, context=self.context
            ).data

        # Fallback (si retrieve sans le bon queryset)
        from inventaire.models import Warehouse
        qs = obj.prices.filter(is_current=True).select_related('warehouse')
        if not user.est_pdg():
            agences_ids = user.get_agences().values_list('id', flat=True)
            qs = qs.filter(warehouse__agence_id__in=agences_ids)
        return ProductPricingSerializer(qs, many=True, context=self.context).data


# ============================================================
# PRODUCT CREATE / UPDATE
# ============================================================
class ProductCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = (
            'reference', 'barcode', 'name', 'description', 'product_type',
            'category', 'brand', 'unit', 'main_image', 'minimum_stock',
            'maximum_stock', 'location', 'is_active', 'is_featured',
            'is_digital', 'has_variants', 'weight', 'volume',
        )
        read_only_fields = ('id', 'created_at', 'updated_at', 'created_by', 'stock_quantity')

    def validate(self, data):
        minimum_stock = data.get('minimum_stock', 0)
        maximum_stock = data.get('maximum_stock')
        if maximum_stock is not None and minimum_stock > maximum_stock:
            raise serializers.ValidationError({
                'minimum_stock': 'Le stock minimum ne peut pas être supérieur au stock maximum'
            })
        return data


# ============================================================
# PRODUCT PRICING
# ============================================================
class ProductPricingSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(source='product.reference', read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)
    warehouse_code = serializers.CharField(source='warehouse.code', read_only=True)
    margin = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    margin_percentage = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = ProductPricing
        fields = '__all__'
        read_only_fields = ('id', 'valid_from', 'updated_at')

    def validate(self, data):
        # Sur update partiel, récupérer les valeurs existantes
        instance = getattr(self, 'instance', None)
        sale_price = data.get('sale_price', instance.sale_price if instance else 0)
        purchase_price = data.get('purchase_price', instance.purchase_price if instance else 0)

        if sale_price is not None and purchase_price is not None and sale_price < purchase_price:
            raise serializers.ValidationError({
                'sale_price': 'Le prix de vente ne peut pas être inférieur au prix d\'achat'
            })
        return data


# ============================================================
# PRODUCT STOCK ALERT
# ============================================================
class ProductStockAlertSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Product
        fields = (
            'id', 'reference', 'name', 'stock_quantity', 'minimum_stock',
            'category_name', 'location',
        )