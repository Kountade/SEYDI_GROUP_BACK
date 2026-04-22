# products/serializers.py

from rest_framework import serializers
from .models import *
from users.serializers import UserSerializer


class CategorySerializer(serializers.ModelSerializer):
    products_count = serializers.IntegerField(
        source='products.count', read_only=True)
    subcategories_count = serializers.IntegerField(
        source='subcategories.count', read_only=True)

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
        return ProductListSerializer(obj.products.filter(is_active=True)[:10], many=True).data

    def get_subcategories(self, obj):
        return CategorySerializer(obj.subcategories.filter(is_active=True), many=True).data


class BrandSerializer(serializers.ModelSerializer):
    products_count = serializers.IntegerField(
        source='products.count', read_only=True)

    class Meta:
        model = Brand
        fields = '__all__'


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = '__all__'


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


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = '__all__'


# products/serializers.py (seulement les parties concernant les images)

class ProductListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source='category.name', read_only=True)
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    unit_abbrev = serializers.CharField(
        source='unit.abbreviation', read_only=True)
    # Changé de main_image_url à main_image
    main_image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ('id', 'reference', 'barcode', 'name', 'category_name', 'brand_name',
                  'purchase_price', 'sale_price', 'wholesale_price', 'stock_quantity',
                  'minimum_stock', 'is_low_stock', 'is_active', 'is_featured',
                  'main_image', 'unit_abbrev', 'margin_percentage')  # Changé ici aussi

    def get_main_image(self, obj):
        """Retourne l'URL complète de l'image principale"""
        request = self.context.get('request')
        if obj.main_image and request:
            # Construire l'URL absolue
            return request.build_absolute_uri(obj.main_image.url)
        elif obj.main_image:
            # Si pas de request dans le contexte, retourner l'URL relative
            return obj.main_image.url
        return None


class ProductDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    brand = BrandSerializer(read_only=True)
    unit = UnitSerializer(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    main_image = serializers.SerializerMethodField()  # Ajouté

    class Meta:
        model = Product
        fields = '__all__'

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name()
        return None

    def get_main_image(self, obj):
        """Retourne l'URL complète de l'image principale"""
        request = self.context.get('request')
        if obj.main_image and request:
            return request.build_absolute_uri(obj.main_image.url)
        elif obj.main_image:
            return obj.main_image.url
        return None


class ProductCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at', 'created_by')

    def validate(self, data):
        # Validation personnalisée
        if data.get('sale_price', 0) < data.get('purchase_price', 0):
            raise serializers.ValidationError({
                'sale_price': 'Le prix de vente doit être supérieur au prix d\'achat'
            })

        # CORRECTION ICI : Gérer le cas où maximum_stock est None
        minimum_stock = data.get('minimum_stock', 0)
        maximum_stock = data.get('maximum_stock')

        if maximum_stock is not None and minimum_stock > maximum_stock:
            raise serializers.ValidationError({
                'minimum_stock': 'Le stock minimum ne peut pas être supérieur au stock maximum'
            })

        # Validation de la TVA
        tax_rate = data.get('tax_rate')
        if tax_rate is not None and (tax_rate < 0 or tax_rate > 100):
            raise serializers.ValidationError({
                'tax_rate': 'La TVA doit être comprise entre 0 et 100%'
            })

        return data


class ProductStockAlertSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source='category.name', read_only=True)

    class Meta:
        model = Product
        fields = ('id', 'reference', 'name', 'stock_quantity', 'minimum_stock',
                  'category_name', 'location')


class ProductBulkUpdateSerializer(serializers.Serializer):
    """Pour mise à jour en masse"""
    product_ids = serializers.ListField(child=serializers.IntegerField())
    action = serializers.ChoiceField(
        choices=['activate', 'deactivate', 'update_price'])
    price_increase = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False)
    price_decrease = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False)


class ProductImportSerializer(serializers.Serializer):
    """Pour import de produits"""
    file = serializers.FileField()


class ProductExportSerializer(serializers.Serializer):
    """Pour export de produits"""
    format = serializers.ChoiceField(choices=['csv', 'excel', 'pdf'])
    category_id = serializers.IntegerField(required=False)
    brand_id = serializers.IntegerField(required=False)
    is_active = serializers.BooleanField(required=False)
