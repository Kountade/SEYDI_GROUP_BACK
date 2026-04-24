from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from users.models import CustomUser, Agence
from produits.models import Product, ProductVariant
from decimal import Decimal


class Supplier(models.Model):
    """Fournisseurs"""
    # ... (garder tout votre code existant inchangé)
    SUPPLIER_TYPES = (
        ('manufacturer', 'Fabricant'),
        ('distributor', 'Distributeur'),
        ('wholesaler', 'Grossiste'),
        ('importer', 'Importateur'),
        ('service', 'Prestataire de services'),
    )

    PAYMENT_TERMS = (
        ('immediate', 'Paiement immédiat'),
        ('15_days', '15 jours'),
        ('30_days', '30 jours'),
        ('45_days', '45 jours'),
        ('60_days', '60 jours'),
        ('end_of_month', 'Fin de mois'),
    )

    DELIVERY_TERMS = (
        ('exw', 'EXW - Départ usine'),
        ('fca', 'FCA - Franco transporteur'),
        ('fas', 'FAS - Franco le long du navire'),
        ('fob', 'FOB - Franco à bord'),
        ('cfr', 'CFR - Coût et fret'),
        ('cif', 'CIF - Coût, assurance et fret'),
        ('dap', 'DAP - Rendu au lieu de destination'),
        ('ddu', 'DDU - Droits non acquittés'),
        ('ddd', 'DDD - Droits acquittés'),
    )

    # Informations de base
    code = models.CharField(max_length=50, unique=True,
                            verbose_name="Code fournisseur")
    company_name = models.CharField(
        max_length=200, verbose_name="Raison sociale")
    supplier_type = models.CharField(
        max_length=20, choices=SUPPLIER_TYPES, default='distributor')
    registration_number = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="N° RC/RCCM")
    tax_id = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="N° TVA/IFU")

    # Contact principal
    contact_name = models.CharField(
        max_length=200, verbose_name="Personne de contact")
    contact_title = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Fonction")
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    mobile = models.CharField(max_length=20, blank=True, null=True)
    fax = models.CharField(max_length=20, blank=True, null=True)
    website = models.URLField(blank=True, null=True)

    # Adresse
    address = models.TextField()
    address_line2 = models.CharField(max_length=200, blank=True, null=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='Sénégal')

    # Informations bancaires
    bank_name = models.CharField(max_length=200, blank=True, null=True)
    bank_account = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="N° compte")
    bank_swift = models.CharField(
        max_length=20, blank=True, null=True, verbose_name="Code SWIFT/BIC")
    bank_iban = models.CharField(
        max_length=34, blank=True, null=True, verbose_name="IBAN")

    # Conditions commerciales
    payment_terms = models.CharField(
        max_length=20, choices=PAYMENT_TERMS, default='30_days')
    delivery_terms = models.CharField(
        max_length=20, choices=DELIVERY_TERMS, default='exw')
    currency = models.CharField(
        max_length=10, default='XOF', verbose_name="Devise")
    lead_time_days = models.IntegerField(
        default=7, verbose_name="Délai de livraison (jours)")
    minimum_order_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Montant minimum de commande")
    discount_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name="Remise (%)")

    # Évaluation et notation
    RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]
    rating = models.IntegerField(
        choices=RATING_CHOICES, null=True, blank=True, verbose_name="Note (1-5)")
    is_preferred = models.BooleanField(
        default=False, verbose_name="Fournisseur préféré")
    performance_score = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Score de performance")

    # Statistiques
    total_orders = models.IntegerField(
        default=0, verbose_name="Total commandes")
    total_spent = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Total dépensé")
    average_delivery_delay = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Retard moyen (jours)")
    on_time_delivery_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Taux de livraison à temps (%)")

    # Options
    is_active = models.BooleanField(default=True)
    is_blocked = models.BooleanField(default=False)
    blocking_reason = models.TextField(blank=True, null=True)

    # Métadonnées
    notes = models.TextField(blank=True, null=True)
    internal_notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_suppliers')
    updated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='updated_suppliers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company_name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['company_name']),
            models.Index(fields=['is_preferred']),
            models.Index(fields=['rating']),
        ]

    def __str__(self):
        return f"{self.code} - {self.company_name}"

    def update_statistics(self):
        """Met à jour les statistiques du fournisseur"""
        from django.db.models import Sum, Avg, Count

        orders = self.purchase_orders.all()
        self.total_orders = orders.count()
        self.total_spent = orders.filter(status='received').aggregate(
            total=Sum('total'))['total'] or 0

        # Calcul du retard moyen
        delayed_orders = orders.filter(
            status='received',
            received_date__gt=models.F('expected_date')
        )
        if delayed_orders.exists():
            total_delay = sum(
                (order.received_date - order.expected_date).days
                for order in delayed_orders
            )
            self.average_delivery_delay = total_delay / delayed_orders.count()

        # Calcul du taux de livraison à temps
        received_orders = orders.filter(status='received')
        if received_orders.exists():
            on_time = received_orders.filter(
                received_date__lte=models.F('expected_date')).count()
            self.on_time_delivery_rate = (
                on_time / received_orders.count()) * 100

        self.save()


class SupplierContact(models.Model):
    """Contacts multiples pour un fournisseur"""
    supplier = models.ForeignKey(
        Supplier, on_delete=models.CASCADE, related_name='contacts')

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    title = models.CharField(max_length=100, blank=True,
                             null=True, verbose_name="Fonction")
    department = models.CharField(max_length=100, blank=True, null=True)

    email = models.EmailField()
    phone = models.CharField(max_length=20)
    mobile = models.CharField(max_length=20, blank=True, null=True)

    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', 'last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.supplier.company_name}"


class SupplierEvaluation(models.Model):
    """Évaluation périodique des fournisseurs"""
    supplier = models.ForeignKey(
        Supplier, on_delete=models.CASCADE, related_name='evaluations')
    evaluator = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)

    evaluation_date = models.DateField(auto_now_add=True)

    # Critères d'évaluation (1-5)
    quality_score = models.IntegerField(
        choices=[(i, i) for i in range(1, 6)], verbose_name="Qualité des produits")
    price_score = models.IntegerField(
        choices=[(i, i) for i in range(1, 6)], verbose_name="Prix")
    delivery_score = models.IntegerField(
        choices=[(i, i) for i in range(1, 6)], verbose_name="Respect des délais")
    communication_score = models.IntegerField(
        choices=[(i, i) for i in range(1, 6)], verbose_name="Communication")
    responsiveness_score = models.IntegerField(
        choices=[(i, i) for i in range(1, 6)], verbose_name="Réactivité")

    total_score = models.DecimalField(
        max_digits=5, decimal_places=2, editable=False)

    comments = models.TextField(blank=True, null=True)
    improvement_suggestions = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-evaluation_date']

    def save(self, *args, **kwargs):
        scores = [
            self.quality_score,
            self.price_score,
            self.delivery_score,
            self.communication_score,
            self.responsiveness_score
        ]
        self.total_score = sum(scores) / len(scores)
        super().save(*args, **kwargs)


class PurchaseOrder(models.Model):
    """Commandes d'achat"""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('sent', 'Envoyée au fournisseur'),
        ('confirmed', 'Confirmée'),
        ('in_transit', 'En transit'),
        ('partially_received', 'Partiellement reçue'),
        ('received', 'Reçue complètement'),
        ('cancelled', 'Annulée'),
        ('rejected', 'Rejetée'),
    )

    URGENCY_CHOICES = (
        ('normal', 'Normal'),
        ('urgent', 'Urgent'),
        ('very_urgent', 'Très urgent'),
    )

    # Références
    order_number = models.CharField(max_length=50, unique=True)
    supplier_reference = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Réf. fournisseur")

    # Relations - MODIFIÉ avec agence
    agence = models.ForeignKey(
        Agence,
        on_delete=models.PROTECT,
        related_name='purchase_orders',
        verbose_name="Agence destinataire"
    )
    
    warehouse = models.ForeignKey(
        'inventaire.Warehouse',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchase_orders',
        verbose_name="Entrepôt de réception"
    )
    
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name='purchase_orders')
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_purchase_orders')
    validated_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='validated_purchase_orders')

    # Dates
    order_date = models.DateField(auto_now_add=True)
    expected_date = models.DateField(verbose_name="Date de livraison prévue")
    confirmed_date = models.DateField(null=True, blank=True)
    shipped_date = models.DateField(
        null=True, blank=True, verbose_name="Date d'expédition")
    received_date = models.DateField(
        null=True, blank=True, verbose_name="Date de réception")

    # Statuts
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')
    urgency = models.CharField(
        max_length=20, choices=URGENCY_CHOICES, default='normal')

    # Montants
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    currency = models.CharField(max_length=10, default='XOF')
    exchange_rate = models.DecimalField(
        max_digits=10, decimal_places=4, default=1.0)

    # Livraison
    shipping_address = models.TextField(blank=True, default='')
    shipping_method = models.CharField(max_length=100, blank=True, null=True)
    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    carrier = models.CharField(max_length=100, blank=True, null=True)

    # Documents
    order_file = models.FileField(
        upload_to='purchase_orders/', null=True, blank=True)

    # Notes
    notes = models.TextField(blank=True, null=True)
    internal_notes = models.TextField(blank=True, null=True)
    terms_conditions = models.TextField(blank=True, null=True)

    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-order_date', '-order_number']
        indexes = [
            models.Index(fields=['order_number']),
            models.Index(fields=['supplier', 'status']),
            models.Index(fields=['expected_date']),
            models.Index(fields=['agence']),  # NOUVEAU
        ]

    def __str__(self):
        return f"PO-{self.order_number} - {self.supplier.company_name} - {self.agence.nom}"

    def save(self, *args, **kwargs):
        # NOUVEAU : Validation : warehouse doit appartenir à l'agence
        if self.warehouse and self.agence and self.warehouse.agence != self.agence:
            raise ValidationError("L'entrepôt doit appartenir à l'agence de la commande")
        
        if not self.order_number:
            last_order = PurchaseOrder.objects.order_by('-id').first()
            if last_order:
                last_num = int(last_order.order_number.replace('PO', ''))
                self.order_number = f"PO{str(last_num + 1).zfill(6)}"
            else:
                self.order_number = "PO000001"
        super().save(*args, **kwargs)

    def calculate_totals(self):
        """Calcule les totaux de la commande"""
        self.subtotal = sum(item.subtotal for item in self.items.all())
        self.tax_total = sum(item.tax_amount for item in self.items.all())
        self.total = self.subtotal - self.discount + self.shipping_cost + self.tax_total
        self.save()


class PurchaseOrderItem(models.Model):
    """Lignes de commande d'achat"""
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='items')

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)

    supplier_reference = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Réf. fournisseur")

    quantity_ordered = models.IntegerField(validators=[MinValueValidator(1)])
    quantity_received = models.IntegerField(default=0)
    quantity_invoiced = models.IntegerField(default=0)

    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=20)

    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False)
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False)
    total = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False)

    notes = models.CharField(max_length=200, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.purchase_order.order_number} - {self.product.name}"

    def save(self, *args, **kwargs):
        qty = Decimal(self.quantity_ordered)
        unit_price = self.unit_price
        disc_rate = self.discount_rate
        tax_rate = self.tax_rate

        discount_factor = (Decimal('100') - disc_rate) / Decimal('100')
        tax_factor = tax_rate / Decimal('100')

        self.subtotal = qty * unit_price * discount_factor
        self.tax_amount = self.subtotal * tax_factor
        self.total = self.subtotal + self.tax_amount

        super().save(*args, **kwargs)

    @property
    def remaining_quantity(self):
        return self.quantity_ordered - self.quantity_received


class PurchaseReceipt(models.Model):
    """Réceptions de commandes"""
    receipt_number = models.CharField(max_length=50, unique=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='receipts')

    receipt_date = models.DateField(auto_now_add=True)
    received_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)

    notes = models.TextField(blank=True, null=True)
    document = models.FileField(
        upload_to='purchase_receipts/', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-receipt_date']

    def __str__(self):
        return f"REC-{self.receipt_number}"


class PurchaseReceiptItem(models.Model):
    """Lignes de réception"""
    receipt = models.ForeignKey(
        PurchaseReceipt, on_delete=models.CASCADE, related_name='items')
    order_item = models.ForeignKey(PurchaseOrderItem, on_delete=models.CASCADE)

    quantity = models.IntegerField(validators=[MinValueValidator(1)])

    quality_checked = models.BooleanField(default=False)
    quality_ok = models.BooleanField(default=True)
    quality_notes = models.TextField(blank=True, null=True)

    lot_number = models.CharField(max_length=100, blank=True, null=True)
    serial_numbers = models.JSONField(default=list, blank=True)

    expiry_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        order_item = self.order_item
        order_item.quantity_received += self.quantity
        order_item.save()


# ============= NOUVEAUX MODÈLES POUR LES FRAIS RÉELS =============

class Transporter(models.Model):
    """Transporteur / Logisticien"""
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    
    contact_person = models.CharField(max_length=200, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    
    is_active = models.BooleanField(default=True)
    is_preferred = models.BooleanField(default=False)
    
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['name']
        verbose_name = "Transporteur"
        verbose_name_plural = "Transporteurs"
    
    def __str__(self):
        return self.name


class Waybill(models.Model):
    """Bon de transport / LTA / Connaissement"""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('sent', 'Envoyé'),
        ('in_transit', 'En transit'),
        ('arrived', 'Arrivé'),
        ('cleared', 'Dédouané'),
        ('delivered', 'Livré'),
        ('cancelled', 'Annulé'),
    )
    
    waybill_number = models.CharField(max_length=100, unique=True)
    
    purchase_order = models.ForeignKey(
        PurchaseOrder, 
        on_delete=models.CASCADE, 
        related_name='waybills'
    )
    transporter = models.ForeignKey(
        Transporter, 
        on_delete=models.PROTECT, 
        related_name='waybills'
    )
    
    issue_date = models.DateField()
    estimated_arrival = models.DateField(null=True, blank=True)
    actual_arrival = models.DateField(null=True, blank=True)
    customs_clearance_date = models.DateField(null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    
    origin = models.CharField(max_length=200)
    destination = models.CharField(max_length=200)
    port_of_loading = models.CharField(max_length=200, blank=True, null=True)
    port_of_discharge = models.CharField(max_length=200, blank=True, null=True)
    
    container_number = models.CharField(max_length=50, blank=True, null=True)
    seal_number = models.CharField(max_length=50, blank=True, null=True)
    number_of_packages = models.IntegerField(default=1)
    weight_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    volume_m3 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    waybill_file = models.FileField(upload_to='waybills/', null=True, blank=True)
    
    notes = models.TextField(blank=True, null=True)
    
    created_by = models.ForeignKey(
        CustomUser, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='created_waybills'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-issue_date']
        verbose_name = "Bon de transport"
        verbose_name_plural = "Bons de transport"
    
    def __str__(self):
        return f"{self.waybill_number} - {self.transporter.name}"


class ReceiptCost(models.Model):
    """Frais liés à une réception (transport, douane, etc.)"""
    COST_TYPES = (
        ('transport', 'Transport'),
        ('customs_duty', 'Droits de douane'),
        ('customs_clearance', 'Frais de dédouanement'),
        ('insurance', 'Assurance'),
        ('handling', 'Frais de manutention'),
        ('storage', 'Frais de stockage'),
        ('port_fees', 'Frais portuaires'),
        ('transit_fees', 'Frais de transit'),
        ('other', 'Autres frais'),
    )
    
    receipt = models.ForeignKey(
        PurchaseReceipt, 
        on_delete=models.CASCADE, 
        related_name='costs'
    )
    
    cost_type = models.CharField(max_length=20, choices=COST_TYPES)
    description = models.CharField(max_length=200, blank=True, null=True)
    
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='XOF')
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, default=1.0)
    amount_in_local_currency = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        editable=False
    )
    
    reference_number = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        verbose_name="N° de référence"
    )
    document = models.FileField(upload_to='receipt_costs/', null=True, blank=True)
    
    is_billable = models.BooleanField(default=True, verbose_name="Facturable au client")
    
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['cost_type']
        verbose_name = "Frais de réception"
        verbose_name_plural = "Frais de réception"
    
    def save(self, *args, **kwargs):
        self.amount_in_local_currency = self.amount * self.exchange_rate
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.get_cost_type_display()} - {self.amount} {self.currency}"


class ReceiptCostAllocation(models.Model):
    """Allocation des frais aux produits d'une réception"""
    METHOD_CHOICES = (
        ('quantity', 'Par quantité'),
        ('weight', 'Par poids'),
        ('volume', 'Par volume'),
        ('value', 'Par valeur'),
        ('equal', 'De manière égale'),
    )
    
    receipt_cost = models.ForeignKey(
        ReceiptCost,
        on_delete=models.CASCADE,
        related_name='allocations'
    )
    
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    allocated_amount = models.DecimalField(max_digits=12, decimal_places=2)
    allocation_method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    
    class Meta:
        unique_together = ['receipt_cost', 'product', 'variant']
        verbose_name = "Allocation de frais"
        verbose_name_plural = "Allocations de frais"
    
    def __str__(self):
        return f"{self.product.name} - {self.allocated_amount}"


class PurchasePriceHistory(models.Model):
    """Historique des prix d'achat"""
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='price_history')
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE)
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)

    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.SET_NULL, null=True)

    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='XOF')
    quantity = models.IntegerField()

    date = models.DateField(auto_now_add=True)

    notes = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        ordering = ['-date']
        verbose_name_plural = "Historiques de prix"

    def __str__(self):
        return f"{self.product.name} - {self.price} ({self.date})"


class SupplierCatalog(models.Model):
    """Catalogues fournisseurs importés"""
    supplier = models.ForeignKey(
        Supplier, on_delete=models.CASCADE, related_name='catalogs')

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)

    file = models.FileField(upload_to='supplier_catalogs/')
    file_format = models.CharField(max_length=20, choices=[(
        'csv', 'CSV'), ('excel', 'Excel'), ('pdf', 'PDF')])

    import_date = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)

    products_imported = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'En attente'),
        ('processing', 'En cours'),
        ('completed', 'Terminé'),
        ('failed', 'Échec'),
    ], default='pending')

    error_log = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-import_date']

    def __str__(self):
        return f"{self.supplier.company_name} - {self.name}"


class PurchaseAlert(models.Model):
    """Alertes d'achat"""
    ALERT_TYPES = (
        ('reorder', 'Réapprovisionnement nécessaire'),
        ('supplier_outage', 'Rupture fournisseur'),
        ('price_increase', 'Augmentation de prix'),
        ('delivery_delay', 'Retard de livraison'),
        ('minimum_order', 'Seuil minimum atteint'),
    )

    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.CASCADE, null=True, blank=True)

    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    message = models.TextField()

    current_stock = models.IntegerField(default=0)
    reorder_point = models.IntegerField(default=0)
    suggested_quantity = models.IntegerField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_alert_type_display()} - {self.product.name}"