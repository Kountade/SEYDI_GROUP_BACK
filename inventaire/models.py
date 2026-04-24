from django.db import models

# Create your models here.
from django.db import models
from django.core.validators import MinValueValidator
from users.models import CustomUser, Agence
from produits.models import Product, ProductVariant


class Warehouse(models.Model):
    """Entrepôt / Magasin"""
    WAREHOUSE_TYPES = (
        ('main', 'Entrepôt principal'),
        ('secondary', 'Entrepôt secondaire'),
        ('store', 'Magasin'),
        ('transit', 'Zone de transit'),
        ('returns', 'Zone de retour'),
        ('quarantine', 'Zone de quarantaine'),
    )

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    warehouse_type = models.CharField(
        max_length=20, choices=WAREHOUSE_TYPES, default='main')
    
    # Lien avec l'agence
    agence = models.ForeignKey(
        Agence, 
        on_delete=models.PROTECT, 
        related_name='warehouses',
        verbose_name="Agence associée"
    )

    # Adresse
    address = models.TextField()
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='Sénégal')

    # Contact
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    manager = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        blank=True, related_name='managed_warehouses'
    )

    # Options
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        related_name='created_warehouses'
    )

    class Meta:
        ordering = ['name']
        unique_together = ['agence', 'is_default']

    def __str__(self):
        return f"{self.code} - {self.name} ({self.agence.nom})"

    def save(self, *args, **kwargs):
        if self.is_default:
            Warehouse.objects.filter(agence=self.agence, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)


class Location(models.Model):
    """Emplacement dans un entrepôt"""
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name='locations')

    code = models.CharField(max_length=50)
    aisle = models.CharField(max_length=50, blank=True, null=True)
    rack = models.CharField(max_length=50, blank=True, null=True)
    shelf = models.CharField(max_length=50, blank=True, null=True)
    bin = models.CharField(max_length=50, blank=True, null=True)

    description = models.CharField(max_length=200, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    max_weight = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Poids maximum en kg"
    )
    max_volume = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Volume maximum en m³"
    )

    class Meta:
        unique_together = ['warehouse', 'code']
        ordering = ['warehouse', 'code']

    def __str__(self):
        return f"{self.warehouse.code} - {self.code}"


class StockMovement(models.Model):
    """Mouvement de stock"""
    MOVEMENT_TYPES = (
        ('in', 'Entrée'),
        ('out', 'Sortie'),
        ('transfer', 'Transfert'),
        ('adjustment', 'Ajustement'),
        ('return', 'Retour fournisseur'),
        ('return_customer', 'Retour client'),
        ('scrap', 'Mise au rebut'),
        ('quarantine', 'Mise en quarantaine'),
    )

    REFERENCE_TYPES = (
        ('purchase', 'Achat'),
        ('sale', 'Vente'),
        ('transfer', 'Transfert'),
        ('inventory', 'Inventaire'),
        ('production', 'Production'),
        ('manual', 'Manuel'),
    )

    reference = models.CharField(max_length=100, unique=True)
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    reference_type = models.CharField(
        max_length=20, choices=REFERENCE_TYPES, default='manual')
    reference_id = models.IntegerField(null=True, blank=True)

    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='stock_movements')
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stock_movements'
    )

    quantity = models.IntegerField(validators=[MinValueValidator(1)])

    from_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT,
        null=True, blank=True, related_name='movements_out'
    )
    to_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT,
        null=True, blank=True, related_name='movements_in'
    )

    from_location = models.ForeignKey(
        Location, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='movements_from'
    )
    to_location = models.ForeignKey(
        Location, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='movements_to'
    )

    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    total_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)]
    )

    movement_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        related_name='created_movements'
    )

    class Meta:
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['product', 'movement_date']),
            models.Index(fields=['from_warehouse', 'to_warehouse']),
        ]
        ordering = ['-movement_date']

    def __str__(self):
        return f"{self.reference} - {self.get_movement_type_display()} - {self.product.name}"

    def save(self, *args, **kwargs):
        if not self.reference:
            last = StockMovement.objects.order_by('-id').first()
            if last:
                last_num = int(last.reference.replace('MOV', ''))
                self.reference = f"MOV{str(last_num + 1).zfill(6)}"
            else:
                self.reference = "MOV000001"

        self.total_price = self.quantity * self.unit_price
        super().save(*args, **kwargs)


class Transfer(models.Model):
    """Transfert entre entrepôts"""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('pending', 'En attente'),
        ('in_transit', 'En transit'),
        ('partial', 'Partiellement reçu'),
        ('completed', 'Terminé'),
        ('cancelled', 'Annulé'),
    )

    reference = models.CharField(max_length=100, unique=True)
    from_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='transfers_out')
    to_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='transfers_in')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')
    transfer_date = models.DateField(auto_now_add=True)
    expected_date = models.DateField(null=True, blank=True)
    completed_date = models.DateField(null=True, blank=True)
    waybill = models.CharField(
        max_length=100, blank=True, null=True,
        help_text="Numéro de bon de livraison"
    )
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        related_name='created_transfers'
    )
    validated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        blank=True, related_name='validated_transfers'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['status']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"Transfer {self.reference}: {self.from_warehouse.code} → {self.to_warehouse.code}"


class TransferItem(models.Model):
    """Article dans un transfert"""
    transfer = models.ForeignKey(
        Transfer, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL,
        null=True, blank=True
    )
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    quantity_received = models.IntegerField(default=0)
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    notes = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        unique_together = ['transfer', 'product', 'variant']

    def __str__(self):
        return f"{self.product.name} - {self.quantity}"

    @property
    def remaining_quantity(self):
        return self.quantity - self.quantity_received


class InventoryCount(models.Model):
    """Comptage d'inventaire"""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('in_progress', 'En cours'),
        ('completed', 'Terminé'),
        ('validated', 'Validé'),
        ('cancelled', 'Annulé'),
    )

    reference = models.CharField(max_length=100, unique=True)
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='inventory_counts')
    count_date = models.DateField(auto_now_add=True)
    scheduled_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')
    counted_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL,
        null=True, related_name='inventory_counts'
    )
    validated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='validated_counts'
    )
    total_items = models.IntegerField(default=0)
    total_differences = models.IntegerField(default=0)
    total_difference_value = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-count_date']

    def __str__(self):
        return f"Inventaire {self.reference} - {self.warehouse.name}"


class InventoryCountItem(models.Model):
    """Ligne de comptage d'inventaire"""
    inventory = models.ForeignKey(
        InventoryCount, on_delete=models.CASCADE, related_name='items')

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL,
        null=True, blank=True
    )

    theoretical_quantity = models.IntegerField(default=0)
    counted_quantity = models.IntegerField(default=0)
    difference = models.IntegerField(default=0)

    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)
    difference_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)

    is_counted = models.BooleanField(default=False)
    is_valid = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ['inventory', 'product', 'variant']

    def __str__(self):
        return f"{self.product.name} - Théorique: {self.theoretical_quantity} - Compté: {self.counted_quantity}"

    def save(self, *args, **kwargs):
        self.difference = self.counted_quantity - self.theoretical_quantity
        self.difference_value = self.difference * self.unit_price
        super().save(*args, **kwargs)


class StockAlert(models.Model):
    """Alertes de stock"""
    ALERT_TYPES = (
        ('low_stock', 'Stock faible'),
        ('out_of_stock', 'Rupture'),
        ('overstock', 'Surstock'),
        ('expiry', 'Expiration proche'),
    )

    STATUS_CHOICES = (
        ('active', 'Active'),
        ('acknowledged', 'Reconnue'),
        ('resolved', 'Résolue'),
        ('ignored', 'Ignorée'),
    )

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='stock_alerts')
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL,
        null=True, blank=True
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name='stock_alerts')

    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='active')

    current_quantity = models.IntegerField()
    threshold = models.IntegerField()
    message = models.TextField()

    acknowledged_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='acknowledged_alerts'
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_alert_type_display()} - {self.product.name}"


class Lot(models.Model):
    """Gestion des lots"""
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='lots')

    lot_number = models.CharField(max_length=100, unique=True)
    serial_number = models.CharField(
        max_length=100, unique=True, null=True, blank=True)

    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    best_before_date = models.DateField(null=True, blank=True)

    quantity = models.IntegerField(
        default=0, validators=[MinValueValidator(0)])
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='lots')
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True)

    QUALITY_STATUS = (
        ('good', 'Bon'),
        ('damaged', 'Endommagé'),
        ('expired', 'Expiré'),
        ('quarantine', 'En quarantaine'),
    )
    quality_status = models.CharField(
        max_length=20, choices=QUALITY_STATUS, default='good')

    supplier = models.CharField(max_length=200, blank=True, null=True)
    purchase_order = models.CharField(max_length=100, blank=True, null=True)

    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['lot_number']),
            models.Index(fields=['serial_number']),
            models.Index(fields=['expiry_date']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        if self.serial_number:
            return f"{self.product.name} - SN: {self.serial_number}"
        return f"{self.product.name} - Lot: {self.lot_number}"

    @property
    def is_expired(self):
        from django.utils import timezone
        if self.expiry_date and self.expiry_date < timezone.now().date():
            return True
        return False


class QualityControl(models.Model):
    """Contrôle qualité"""
    lot = models.ForeignKey(
        Lot, on_delete=models.CASCADE, related_name='quality_controls')

    inspector = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)

    control_date = models.DateTimeField(auto_now_add=True)

    RESULT_CHOICES = (
        ('passed', 'Conforme'),
        ('failed', 'Non conforme'),
        ('pending', 'En attente'),
    )
    result = models.CharField(
        max_length=20, choices=RESULT_CHOICES, default='pending')

    notes = models.TextField(blank=True, null=True)

    certificate = models.FileField(
        upload_to='quality/', null=True, blank=True)

    def __str__(self):
        return f"Contrôle {self.lot.lot_number} - {self.get_result_display()}"