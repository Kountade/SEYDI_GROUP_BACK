# products/models.py

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from users.models import CustomUser


class Category(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE,
                               null=True, blank=True, related_name='subcategories')
    image = models.ImageField(upload_to='categories/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    logo = models.ImageField(upload_to='brands/', null=True, blank=True)
    website = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Unit(models.Model):
    name = models.CharField(max_length=50)  # Kilogramme, Litre, Pièce, etc.
    abbreviation = models.CharField(max_length=10)  # kg, L, pcs, etc.

    def __str__(self):
        return f"{self.name} ({self.abbreviation})"


class Product(models.Model):
    PRODUCT_TYPES = (
        ('simple', 'Simple'),
        ('variable', 'Variable'),
        ('service', 'Service'),
        ('digital', 'Numérique'),
    )

    # Informations de base
    reference = models.CharField(max_length=100, unique=True)
    barcode = models.CharField(
        max_length=100, unique=True, null=True, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    product_type = models.CharField(
        max_length=20, choices=PRODUCT_TYPES, default='simple')

    # Relations
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name='products')
    brand = models.ForeignKey(
        Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_products')

    # Images
    main_image = models.ImageField(
        upload_to='products/', null=True, blank=True)

    # Prix et taxes
    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    sale_price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[
                                          MinValueValidator(0)], null=True, blank=True)
    tax_rate = models.IntegerField(
        default=20,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Taux de TVA en % (ex: 20 pour 20%)"
    )

    # Stock
    stock_quantity = models.IntegerField(
        default=0, validators=[MinValueValidator(0)])
    minimum_stock = models.IntegerField(
        default=5, validators=[MinValueValidator(0)])
    maximum_stock = models.IntegerField(null=True, blank=True)
    # Emplacement dans l'entrepôt
    location = models.CharField(max_length=100, blank=True, null=True)

    # Options
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_digital = models.BooleanField(default=False)
    has_variants = models.BooleanField(default=False)

    # Métadonnées
    weight = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True, help_text="Poids en kg")
    volume = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True, help_text="Volume en m³")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['barcode']),
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"{self.reference} - {self.name}"

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.minimum_stock

    @property
    def margin(self):
        return self.sale_price - self.purchase_price

    @property
    def margin_percentage(self):
        if self.purchase_price > 0:
            return (self.margin / self.purchase_price) * 100
        return 0


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/gallery/')
    alt_text = models.CharField(max_length=200, blank=True)
    is_main = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_main', 'created_at']


class ProductVariant(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='variants')
    sku = models.CharField(max_length=100, unique=True)
    # { "size": "M", "color": "Red", "material": "Cotton" }
    attributes = models.JSONField()
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_quantity = models.IntegerField(default=0)
    image = models.ImageField(
        upload_to='products/variants/', null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.product.name} - {self.sku}"
