# products/models.py

import os
from django.db import models
from django.core.validators import MinValueValidator
from django.dispatch import receiver
from django.db.models.signals import pre_delete, post_delete
from users.models import CustomUser


# ============================================================
# CATEGORY
# ============================================================
class Category(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE,
        null=True, blank=True, related_name='subcategories'
    )
    image = models.ImageField(upload_to='categories/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"
        indexes = [
            models.Index(fields=['is_active'], name='cat_active_idx'),
            models.Index(fields=['parent', 'is_active'], name='cat_parent_active_idx'),
        ]

    def __str__(self):
        return self.name


# ============================================================
# BRAND
# ============================================================
class Brand(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    logo = models.ImageField(upload_to='brands/', null=True, blank=True)
    website = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['is_active'], name='brand_active_idx'),
        ]

    def __str__(self):
        return self.name


# ============================================================
# UNIT
# ============================================================
class Unit(models.Model):
    name = models.CharField(max_length=50)
    abbreviation = models.CharField(max_length=10)

    def __str__(self):
        return f"{self.name} ({self.abbreviation})"


# ============================================================
# PRODUCT
# ============================================================
class Product(models.Model):
    PRODUCT_TYPES = (
        ('simple', 'Simple'),
        ('variable', 'Variable'),
        ('service', 'Service'),
        ('digital', 'Numérique'),
    )

    # Informations de base (SANS PRIX)
    reference = models.CharField(max_length=100, unique=True)
    barcode = models.CharField(max_length=100, unique=True, null=True, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    product_type = models.CharField(max_length=20, choices=PRODUCT_TYPES, default='simple')

    # Relations
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    brand = models.ForeignKey(
        Brand, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='products'
    )
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL,
        null=True, related_name='created_products'
    )

    # Images
    main_image = models.ImageField(upload_to='products/', null=True, blank=True)

    # Stock global
    stock_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    minimum_stock = models.IntegerField(default=5, validators=[MinValueValidator(0)])
    maximum_stock = models.IntegerField(null=True, blank=True)
    location = models.CharField(max_length=100, blank=True, null=True)

    # Options
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_digital = models.BooleanField(default=False)
    has_variants = models.BooleanField(default=False)

    # Métadonnées
    weight = models.DecimalField(
        max_digits=10, decimal_places=3,
        null=True, blank=True, help_text="Poids en kg"
    )
    volume = models.DecimalField(
        max_digits=10, decimal_places=3,
        null=True, blank=True, help_text="Volume en m³"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['reference'], name='prod_reference_idx'),
            models.Index(fields=['barcode'], name='prod_barcode_idx'),
            models.Index(fields=['name'], name='prod_name_idx'),
            # ✅ Nouveaux index composites
            models.Index(fields=['category', 'is_active'], name='prod_cat_active_idx'),
            models.Index(fields=['brand', 'is_active'], name='prod_brand_active_idx'),
            models.Index(fields=['is_active', 'is_featured'], name='prod_active_featured_idx'),
            models.Index(fields=['is_active', '-created_at'], name='prod_active_created_idx'),
            models.Index(fields=['stock_quantity'], name='prod_stock_idx'),
            models.Index(fields=['product_type', 'is_active'], name='prod_type_active_idx'),
        ]

    def __str__(self):
        return f"{self.reference} - {self.name}"

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.minimum_stock


# ============================================================
# PRODUCT IMAGE
# ============================================================
class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/gallery/')
    alt_text = models.CharField(max_length=200, blank=True)
    is_main = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_main', 'created_at']
        indexes = [
            models.Index(fields=['product', 'is_main'], name='pimg_prod_main_idx'),
        ]

    def delete(self, *args, **kwargs):
        if self.image and os.path.isfile(self.image.path):
            os.remove(self.image.path)
        super().delete(*args, **kwargs)


@receiver(post_delete, sender=ProductImage)
def delete_product_image_file(sender, instance, **kwargs):
    if instance.image and os.path.isfile(instance.image.path):
        try:
            os.remove(instance.image.path)
        except Exception as e:
            print(f"Erreur lors de la suppression du fichier image: {e}")


@receiver(pre_delete, sender=Product)
def delete_product_files(sender, instance, **kwargs):
    if instance.main_image and os.path.isfile(instance.main_image.path):
        try:
            os.remove(instance.main_image.path)
        except Exception as e:
            print(f"Erreur lors de la suppression de l'image principale: {e}")

    for image in instance.images.all():
        if image.image and os.path.isfile(image.image.path):
            try:
                os.remove(image.image.path)
            except Exception as e:
                print(f"Erreur lors de la suppression de l'image: {e}")


# ============================================================
# PRODUCT VARIANT
# ============================================================
class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    sku = models.CharField(max_length=100, unique=True)
    attributes = models.JSONField()
    stock_quantity = models.IntegerField(default=0)
    image = models.ImageField(upload_to='products/variants/', null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=['product', 'is_active'], name='variant_prod_active_idx'),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.sku}"


# ============================================================
# PRODUCT PRICING
# ============================================================
class ProductPricing(models.Model):
    """
    Prix d'un produit dans un entrepôt spécifique.
    (SANS TVA - supprimée complètement)
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='prices'
    )
    warehouse = models.ForeignKey(
        'inventaire.Warehouse', on_delete=models.CASCADE,
        related_name='product_prices'
    )

    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)], default=0,
        verbose_name="Prix d'achat"
    )
    sale_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)], default=0,
        verbose_name="Prix de vente"
    )
    wholesale_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)],
        null=True, blank=True,
        verbose_name="Prix de gros"
    )

    currency = models.CharField(max_length=10, default='XOF')

    valid_from = models.DateField(auto_now_add=True)
    valid_to = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=True)

    updated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL,
        null=True, related_name='updated_prices'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product__name', 'warehouse__name']
        verbose_name = "Prix par entrepôt"
        verbose_name_plural = "Prix par entrepôt"
        indexes = [
            # ✅ CRUCIAL : requête la plus fréquente
            models.Index(
                fields=['product', 'warehouse', 'is_current'],
                name='pricing_prod_wh_current_idx'
            ),
            models.Index(
                fields=['warehouse', 'is_current'],
                name='pricing_wh_current_idx'
            ),
            models.Index(
                fields=['product', 'is_current'],
                name='pricing_prod_current_idx'
            ),
            models.Index(
                fields=['-updated_at'],
                name='pricing_updated_idx'
            ),
        ]

    def __str__(self):
        return (
            f"{self.product.name} @ {self.warehouse.name}: "
            f"Achat={self.purchase_price}, Vente={self.sale_price}"
        )

    @property
    def margin(self):
        return self.sale_price - self.purchase_price

    @property
    def margin_percentage(self):
        if self.purchase_price > 0:
            return (self.margin / self.purchase_price) * 100
        return 0