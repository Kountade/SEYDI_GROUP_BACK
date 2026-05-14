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
    name = models.CharField(max_length=50)
    abbreviation = models.CharField(max_length=10)

    def __str__(self):
        return f"{self.name} ({self.abbreviation})"


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
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_products')

    # Images
    main_image = models.ImageField(upload_to='products/', null=True, blank=True)

    # Stock global (pour information, le vrai stock est dans WarehouseStock)
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
    weight = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, help_text="Poids en kg")
    volume = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, help_text="Volume en m³")
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


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/gallery/')
    alt_text = models.CharField(max_length=200, blank=True)
    is_main = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_main', 'created_at']


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    sku = models.CharField(max_length=100, unique=True)
    attributes = models.JSONField()
    stock_quantity = models.IntegerField(default=0)
    image = models.ImageField(upload_to='products/variants/', null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.product.name} - {self.sku}"


class ProductPricing(models.Model):
    """
    Prix d'un produit dans un entrepôt spécifique
    Permet d'avoir des prix différents selon l'agence/entrepôt
    """
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='prices'
    )
    warehouse = models.ForeignKey(
        'inventaire.Warehouse',
        on_delete=models.CASCADE,
        related_name='product_prices'
    )
    
    # Prix spécifiques à cet entrepôt
    purchase_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        validators=[MinValueValidator(0)],
        default=0,
        verbose_name="Prix d'achat"
    )
    sale_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        validators=[MinValueValidator(0)],
        default=0,
        verbose_name="Prix de vente"
    )
    wholesale_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        validators=[MinValueValidator(0)],
        null=True, 
        blank=True,
        verbose_name="Prix de gros"
    )
    
    # Devise (car prix peuvent différer selon le pays)
    currency = models.CharField(max_length=10, default='XOF')
    
    # Taux de TVA spécifique à l'entrepôt
    tax_rate = models.IntegerField(
        default=20,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Taux de TVA en %"
    )
    
    # Date de validité du prix
    valid_from = models.DateField(auto_now_add=True)
    valid_to = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=True)
    
    # Historique
    updated_by = models.ForeignKey(
        CustomUser, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='updated_prices'
    )
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['product', 'warehouse']
        ordering = ['product__name', 'warehouse__name']
        verbose_name = "Prix par entrepôt"
        verbose_name_plural = "Prix par entrepôt"
    
    def __str__(self):
        return f"{self.product.name} @ {self.warehouse.name}: Achat={self.purchase_price}, Vente={self.sale_price}"
    
    @property
    def margin(self):
        return self.sale_price - self.purchase_price
    
    @property
    def margin_percentage(self):
        if self.purchase_price > 0:
            return (self.margin / self.purchase_price) * 100
        return 0