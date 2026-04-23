from django.contrib import admin
from .models import (
    Category, Brand, Unit,
    Product, ProductImage, ProductVariant
)

# ==========================
# CATEGORY
# ==========================
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name',)
    prepopulated_fields = {'name': ('name',)}
    list_per_page = 20


# ==========================
# BRAND
# ==========================
@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'website', 'is_active', 'created_at')
    search_fields = ('name',)
    list_filter = ('is_active',)
    list_per_page = 20


# ==========================
# UNIT
# ==========================
@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation')
    search_fields = ('name', 'abbreviation')


# ==========================
# PRODUCT IMAGE INLINE
# ==========================
class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


# ==========================
# PRODUCT VARIANT INLINE
# ==========================
class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


# ==========================
# PRODUCT
# ==========================
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'reference', 'name', 'category',
        'sale_price', 'stock_quantity',
        'is_active', 'is_low_stock'
    )
    list_filter = ('is_active', 'category', 'brand', 'product_type')
    search_fields = ('reference', 'name', 'barcode')
    readonly_fields = ('created_at', 'updated_at', 'margin', 'margin_percentage')
    list_per_page = 25

    fieldsets = (
        ("Informations générales", {
            'fields': ('reference', 'barcode', 'name', 'description', 'product_type')
        }),
        ("Relations", {
            'fields': ('category', 'brand', 'unit', 'created_by')
        }),
        ("Images", {
            'fields': ('main_image',)
        }),
        ("Prix", {
            'fields': ('purchase_price', 'sale_price', 'wholesale_price', 'tax_rate')
        }),
        ("Stock", {
            'fields': ('stock_quantity', 'minimum_stock', 'maximum_stock', 'location')
        }),
        ("Options", {
            'fields': ('is_active', 'is_featured')
        }),
        ("Métadonnées", {
            'fields': ('weight', 'volume', 'created_at', 'updated_at')
        }),
    )

    inlines = [ProductImageInline, ProductVariantInline]

    def is_low_stock(self, obj):
        return obj.is_low_stock
    is_low_stock.boolean = True
    is_low_stock.short_description = "Stock faible"


# ==========================
# PRODUCT IMAGE
# ==========================
@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ('product', 'is_main', 'created_at')
    list_filter = ('is_main',)
    search_fields = ('product__name',)


# ==========================
# PRODUCT VARIANT
# ==========================
@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('product', 'sku', 'sale_price', 'stock_quantity', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('sku', 'product__name')