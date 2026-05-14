# products/serializers.py

from rest_framework import serializers
from .models import *
from users.serializers import UserSerializer


class CategorySerializer(serializers.ModelSerializer):
    products_count = serializers.IntegerField(source='products.count', read_only=True)
    subcategories_count = serializers.IntegerField(source='subcategories.count', read_only=True)

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
        return ProductListSerializer(obj.products.filter(is_active=True)[:10], many=True, context=self.context).data

    def get_subcategories(self, obj):
        return CategorySerializer(obj.subcategories.filter(is_active=True), many=True).data


class BrandSerializer(serializers.ModelSerializer):
    products_count = serializers.IntegerField(source='products.count', read_only=True)

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
        fields = ('id', 'reference', 'barcode', 'name', 'category_name', 'brand_name',
                  'purchase_price', 'sale_price', 'wholesale_price', 
                  'stock_quantity', 'minimum_stock', 'is_low_stock', 
                  'is_active', 'is_featured', 'main_image', 'unit_abbrev')

    def get_main_image(self, obj):
        request = self.context.get('request')
        if obj.main_image and request:
            return request.build_absolute_uri(obj.main_image.url)
        return None

    def _get_warehouse(self):
        warehouse_id = self.context.get('warehouse_id')
        if warehouse_id:
            try:
                from inventaire.models import Warehouse
                return Warehouse.objects.get(id=warehouse_id)
            except:
                pass
        
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            user = request.user
            if hasattr(user, 'get_agence_principale'):
                agence = user.get_agence_principale()
                if agence:
                    from inventaire.models import Warehouse
                    return agence.warehouses.filter(is_default=True).first()
        return None

    def get_purchase_price(self, obj):
        warehouse = self._get_warehouse()
        if warehouse:
            pricing = obj.prices.filter(warehouse=warehouse, is_current=True).first()
            return pricing.purchase_price if pricing else None
        return None

    def get_sale_price(self, obj):
        warehouse = self._get_warehouse()
        if warehouse:
            pricing = obj.prices.filter(warehouse=warehouse, is_current=True).first()
            return pricing.sale_price if pricing else None
        return None

    def get_wholesale_price(self, obj):
        warehouse = self._get_warehouse()
        if warehouse:
            pricing = obj.prices.filter(warehouse=warehouse, is_current=True).first()
            return pricing.wholesale_price if pricing else None
        return None


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
        from inventaire.models import Warehouse
        
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            user = request.user
            if user.est_pdg():
                prices = obj.prices.filter(is_current=True)
            else:
                agences_ids = user.get_agences().values_list('id', flat=True)
                warehouses = Warehouse.objects.filter(agence_id__in=agences_ids)
                prices = obj.prices.filter(warehouse__in=warehouses, is_current=True)
            return ProductPricingSerializer(prices, many=True, context=self.context).data
        return []


class ProductCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ('reference', 'barcode', 'name', 'description', 'product_type',
                  'category', 'brand', 'unit', 'main_image', 'minimum_stock',
                  'maximum_stock', 'location', 'is_active', 'is_featured',
                  'is_digital', 'has_variants', 'weight', 'volume')
        read_only_fields = ('id', 'created_at', 'updated_at', 'created_by', 'stock_quantity')

    def validate(self, data):
        minimum_stock = data.get('minimum_stock', 0)
        maximum_stock = data.get('maximum_stock')
        
        if maximum_stock is not None and minimum_stock > maximum_stock:
            raise serializers.ValidationError({
                'minimum_stock': 'Le stock minimum ne peut pas être supérieur au stock maximum'
            })
        
        return data


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
        sale_price = data.get('sale_price', 0)
        purchase_price = data.get('purchase_price', 0)
        
        if sale_price < purchase_price:
            raise serializers.ValidationError({
                'sale_price': 'Le prix de vente ne peut pas être inférieur au prix d\'achat'
            })
        
        tax_rate = data.get('tax_rate', 20)
        if tax_rate < 0 or tax_rate > 100:
            raise serializers.ValidationError({
                'tax_rate': 'La TVA doit être comprise entre 0 et 100%'
            })
        
        return data


class ProductStockAlertSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Product
        fields = ('id', 'reference', 'name', 'stock_quantity', 'minimum_stock',
                  'category_name', 'location')