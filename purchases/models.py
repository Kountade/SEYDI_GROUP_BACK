from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from users.models import CustomUser, Agence
from produits.models import Product, ProductVariant
from decimal import Decimal
# purchases/models.py

# ... autres imports ...
from django.core.exceptions import ValidationError
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from decimal import Decimal
from users.models import CustomUser, Agence
from produits.models import Product, ProductVariant

# ...
# models.py
from django.db import models
from django.conf import settings


class Supplier(models.Model):
    """Fournisseur - version simplifiée (9 champs)"""
    # Identité
    code = models.CharField(max_length=20, unique=True, verbose_name="Code")
    company_name = models.CharField(
        max_length=150, verbose_name="Raison sociale")

    # Contact
    email = models.EmailField(verbose_name="Email")
    phone = models.CharField(max_length=20, verbose_name="Téléphone")
    address = models.TextField(verbose_name="Adresse")
    city = models.CharField(max_length=100, verbose_name="Ville")
    country = models.CharField(
        max_length=50, default="Sénégal", verbose_name="Pays")

    # Statut
    is_active = models.BooleanField(default=True, verbose_name="Actif")

    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        ordering = ['company_name']

    def __str__(self):
        return f"{self.code} - {self.company_name}"


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


# purchases/models.py

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from users.models import CustomUser, Agence
from produits.models import Product, ProductVariant
from decimal import Decimal
from django.utils import timezone

class PurchaseOrderItem(models.Model):
    """Lignes de commande d'achat"""
    purchase_order = models.ForeignKey(
        'PurchaseOrder', on_delete=models.CASCADE, related_name='items')

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
        """Quantité restante à recevoir"""
        return max(0, self.quantity_ordered - self.quantity_received)

    @property
    def is_fully_received(self):
        """Vérifie si l'article est entièrement reçu"""
        return self.quantity_received >= self.quantity_ordered

    @property
    def is_partially_received(self):
        """Vérifie si l'article est partiellement reçu"""
        return 0 < self.quantity_received < self.quantity_ordered

    @property
    def is_not_received(self):
        """Vérifie si aucun article n'a été reçu"""
        return self.quantity_received == 0

    @property
    def reception_progress(self):
        """Pourcentage de réception (0-100)"""
        if self.quantity_ordered == 0:
            return 0
        return round((self.quantity_received / self.quantity_ordered) * 100, 2)

    @property
    def remaining_value(self):
        """Valeur restante à recevoir"""
        return self.remaining_quantity * self.unit_price

    @property
    def received_value(self):
        """Valeur déjà reçue"""
        return self.quantity_received * self.unit_price

    @property
    def total_value(self):
        """Valeur totale de la ligne de commande"""
        return self.quantity_ordered * self.unit_price

    def can_receive(self, quantity):
        """
        Vérifie si on peut recevoir une quantité donnée
        """
        if quantity is None:
            return False
        if not isinstance(quantity, (int, float)):
            return False
        if quantity <= 0:
            return False
        if self.is_fully_received:
            return False
        if quantity > self.remaining_quantity:
            return False
        return True

    def receive_quantity(self, quantity):
        """
        Ajoute une quantité reçue (avec validation)
        """
        if not self.can_receive(quantity):
            raise ValueError(
                f"Impossible de recevoir {quantity} unités. "
                f"Quantité restante: {self.remaining_quantity}"
            )
        
        self.quantity_received += quantity
        self.save()
        return True


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

    order_number = models.CharField(max_length=50, unique=True)
    supplier_reference = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Réf. fournisseur")

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
        'Supplier', on_delete=models.PROTECT, related_name='purchase_orders')
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_purchase_orders')
    validated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='validated_purchase_orders')

    order_date = models.DateField(auto_now_add=True)
    expected_date = models.DateField(verbose_name="Date de livraison prévue")
    confirmed_date = models.DateField(null=True, blank=True)
    shipped_date = models.DateField(null=True, blank=True, verbose_name="Date d'expédition")
    received_date = models.DateField(null=True, blank=True, verbose_name="Date de réception")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')
    urgency = models.CharField(
        max_length=20, choices=URGENCY_CHOICES, default='normal')

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    currency = models.CharField(max_length=10, default='XOF')
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, default=1.0)

    shipping_address = models.TextField(blank=True, default='')
    shipping_method = models.CharField(max_length=100, blank=True, null=True)
    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    carrier = models.CharField(max_length=100, blank=True, null=True)

    order_file = models.FileField(upload_to='purchase_orders/', null=True, blank=True)

    notes = models.TextField(blank=True, null=True)
    internal_notes = models.TextField(blank=True, null=True)
    terms_conditions = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-order_date', '-order_number']
        indexes = [
            models.Index(fields=['order_number']),
            models.Index(fields=['supplier', 'status']),
            models.Index(fields=['expected_date']),
            models.Index(fields=['agence']),
        ]

    def __str__(self):
        return f"PO-{self.order_number} - {self.supplier.company_name} - {self.agence.nom}"

    def save(self, *args, **kwargs):
        if self.warehouse and self.agence and self.warehouse.agence != self.agence:
            raise ValidationError(
                "L'entrepôt doit appartenir à l'agence de la commande")

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


# purchases/models.py - Modèle PurchaseOrderItem COMPLET
# purchases/models.py - Modèle PurchaseOrderItem COMPLET
#

# purchases/models.py - PurchaseReceipt COMPLET

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

    # ============================================================
    # ✅ CHAMPS POUR LA FACTURE AUTO (COMME SODEPCI)
    # ============================================================
    auto_invoice = models.BooleanField(
        default=True,
        verbose_name="Créer facture automatiquement"
    )
    is_invoiced = models.BooleanField(
        default=False,
        verbose_name="Facturée"
    )
    auto_invoice_number = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="N° Facture auto"
    )

    # ============================================================
    # DESTINATION DU DÉCAISSEMENT
    # ============================================================
    caisse_destination = models.ForeignKey(
        'tresorerie.Caisse',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='receptions_achats',
        verbose_name="Caisse de décaissement"
    )
    compte_destination = models.ForeignKey(
        'tresorerie.CompteBancaire',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='receptions_achats',
        verbose_name="Compte bancaire de décaissement"
    )
    mouvement_tresorerie = models.ForeignKey(
        'tresorerie.MouvementTresorerie',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reception_achat',
        verbose_name="Mouvement de trésorerie associé"
    )

    class Meta:
        ordering = ['-receipt_date']

    def __str__(self):
        return f"REC-{self.receipt_number}"

    # ============================================================
    # ✅ PROPRIÉTÉ total_received_amount (COMME SODEPCI)
    # ============================================================

    @property
    def total_received_amount(self):
        """Calcule le montant total reçu à partir des items"""
        from decimal import Decimal
        total = Decimal('0')
        for item in self.items.all():
            if item.order_item:
                total += item.order_item.unit_price * item.quantity
        return total

    @property
    def total_received_quantity(self):
        """Quantité totale reçue"""
        return sum(item.quantity or 0 for item in self.items.all())

    @property
    def items_count(self):
        """Nombre d'articles"""
        return self.items.count()

    def creer_mouvement_decaissement(self, user):
        """Crée un mouvement de trésorerie pour le décaissement"""
        if self.mouvement_tresorerie:
            return self.mouvement_tresorerie

        montant = self.total_received_amount
        if montant <= 0:
            return None

        caisse = self.caisse_destination
        compte = self.compte_destination

        if not caisse and not compte:
            agence = self.purchase_order.agence
            if agence:
                from tresorerie.models import Caisse
                caisse = Caisse.objects.filter(
                    agence=agence, is_default=True).first()
            if not caisse:
                return None

        from tresorerie.models import MouvementTresorerie
        mouvement = MouvementTresorerie.objects.create(
            type_mouvement='decaissement',
            agence=self.purchase_order.agence,
            source_type='achat',
            source_id=self.purchase_order.id,
            source_reference=self.purchase_order.order_number,
            montant=montant,
            mode_paiement='virement',
            caisse=caisse,
            compte_bancaire=compte,
            date_mouvement=timezone.now(),
            date_valeur=self.receipt_date,
            status='effectue',
            libelle=f"Décaissement pour réception {self.receipt_number}",
            created_by=user
        )
        self.mouvement_tresorerie = mouvement
        self.save(update_fields=['mouvement_tresorerie'])
        return mouvement

class PurchaseReceiptItem(models.Model):
    """Lignes de réception"""
    receipt = models.ForeignKey(
        PurchaseReceipt, on_delete=models.CASCADE, related_name='items')
    order_item = models.ForeignKey('PurchaseOrderItem', on_delete=models.CASCADE)

    quantity = models.IntegerField(validators=[MinValueValidator(1)])

    quality_checked = models.BooleanField(default=False)
    quality_ok = models.BooleanField(default=True)
    quality_notes = models.TextField(blank=True, null=True)

    lot_number = models.CharField(max_length=100, blank=True, null=True)
    serial_numbers = models.JSONField(default=list, blank=True)

    expiry_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.quantity > self.order_item.remaining_quantity:
            raise ValidationError(
                f"La quantité reçue ({self.quantity}) dépasse la quantité restante ({self.order_item.remaining_quantity})"
            )
        super().save(*args, **kwargs)
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
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True)
    volume_m3 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True)

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')

    waybill_file = models.FileField(
        upload_to='waybills/', null=True, blank=True)

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
    exchange_rate = models.DecimalField(
        max_digits=10, decimal_places=4, default=1.0)
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
    document = models.FileField(
        upload_to='receipt_costs/', null=True, blank=True)

    is_billable = models.BooleanField(
        default=True, verbose_name="Facturable au client")

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
# purchases/models.py - Ajoutez ces modèles

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from users.models import CustomUser, Agence
from produits.models import Product, ProductVariant

# purchases/models.py - Modèle Invoice COMPLET

class Invoice(models.Model):
    """Facture fournisseur"""
    
    INVOICE_STATUS = (
        ('draft', 'Brouillon'),
        ('pending', 'En attente de paiement'),
        ('partial', 'Partiellement payée'),
        ('paid', 'Payée'),
        ('overdue', 'En retard'),
        ('cancelled', 'Annulée'),
    )
    
    INVOICE_TYPE = (
        ('purchase', "Facture d'achat"),
        ('service', 'Facture de service'),
        ('expense', 'Facture de dépense'),
    )
    
    # Références
    invoice_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="N° Facture"
    )
    supplier_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Réf. fournisseur"
    )
    
    # Relations
    agence = models.ForeignKey(
        Agence,
        on_delete=models.PROTECT,
        related_name='invoices',
        verbose_name="Agence"
    )
    
    supplier = models.ForeignKey(
        'Supplier',
        on_delete=models.PROTECT,
        related_name='invoices',
        verbose_name="Fournisseur"
    )
    
    purchase_receipt = models.ForeignKey(
        'PurchaseReceipt',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices',
        verbose_name="Réception associée"
    )
    
    purchase_order = models.ForeignKey(
        'PurchaseOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices',
        verbose_name="Commande associée"
    )
    
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_invoices'
    )
    
    validated_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='validated_invoices'
    )
    
    # Dates
    invoice_date = models.DateField(
        verbose_name="Date de facture",
        default=timezone.now
    )
    due_date = models.DateField(
        verbose_name="Date d'échéance"
    )
    payment_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Date de paiement"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Montants
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Sous-total"
    )
    tax_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Total TVA"
    )
    discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Remise"
    )
    shipping_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Frais de livraison"
    )
    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Total"
    )
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Montant payé"
    )
    amount_remaining = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Montant restant"
    )
    
    currency = models.CharField(
        max_length=10,
        default='XOF',
        verbose_name="Devise"
    )
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=1.0,
        verbose_name="Taux de change"
    )
    
    # Statuts
    status = models.CharField(
        max_length=20,
        choices=INVOICE_STATUS,
        default='pending',
        verbose_name="Statut"
    )
    invoice_type = models.CharField(
        max_length=20,
        choices=INVOICE_TYPE,
        default='purchase',
        verbose_name="Type de facture"
    )
    
    # Documents
    invoice_file = models.FileField(
        upload_to='invoices/',
        null=True,
        blank=True,
        verbose_name="Fichier facture"
    )
    
    # Notes
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Notes"
    )
    internal_notes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Notes internes"
    )
    
    # Métadonnées
    is_auto_generated = models.BooleanField(
        default=True,
        verbose_name="Générée automatiquement"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Active"
    )
    
    class Meta:
        ordering = ['-invoice_date', '-invoice_number']
        indexes = [
            models.Index(fields=['invoice_number']),
            models.Index(fields=['supplier', 'status']),
            models.Index(fields=['due_date']),
            models.Index(fields=['agence']),
        ]
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
    
    def __str__(self):
        return f"{self.invoice_number} - {self.supplier.company_name} - {self.status}"
    
    def save(self, *args, **kwargs):
        # Générer le numéro de facture si non défini
        if not self.invoice_number:
            last_invoice = Invoice.objects.order_by('-id').first()
            if last_invoice:
                try:
                    last_num = int(last_invoice.invoice_number.replace('INV', ''))
                    self.invoice_number = f"INV{str(last_num + 1).zfill(6)}"
                except (ValueError, AttributeError):
                    self.invoice_number = "INV000001"
            else:
                self.invoice_number = "INV000001"
        
        # Mettre à jour le montant restant
        self.amount_remaining = self.total - self.amount_paid
        
        # Mettre à jour le statut automatiquement
        if self.amount_paid >= self.total and self.total > 0:
            self.status = 'paid'
            if not self.payment_date:
                self.payment_date = timezone.now().date()
        elif self.amount_paid > 0:
            self.status = 'partial'
        elif self.due_date and self.due_date < timezone.now().date() and self.amount_paid < self.total:
            self.status = 'overdue'
        elif self.status not in ['draft', 'cancelled']:
            self.status = 'pending'
        
        super().save(*args, **kwargs)
    
    @property
    def is_fully_paid(self):
        """Vérifie si la facture est entièrement payée"""
        return self.amount_paid >= self.total
    
    @property
    def payment_progress(self):
        """Pourcentage de paiement"""
        if self.total == 0:
            return 0
        return round((self.amount_paid / self.total) * 100, 2)
    
    @property
    def is_overdue(self):
        """Vérifie si la facture est en retard"""
        return self.due_date < timezone.now().date() and not self.is_fully_paid
    
    def create_payment(self, amount, payment_method, **kwargs):
        """
        Crée un paiement pour cette facture
        """
        if amount <= 0:
            raise ValidationError("Le montant du paiement doit être supérieur à 0")
        
        if amount > self.amount_remaining:
            raise ValidationError(
                f"Le montant ({amount}) dépasse le montant restant ({self.amount_remaining})"
            )
        
        payment = Payment.objects.create(
            invoice=self,
            amount=amount,
            payment_method=payment_method,
            **kwargs
        )
        
        self.amount_paid += amount
        self.save()
        
        return payment
    
    def get_items_total(self):
        """Calcule le total des lignes de facture"""
        return self.items.aggregate(total=models.Sum('total'))['total'] or 0


# purchases/models.py

class Payment(models.Model):
    """Paiement d'une facture"""
    
    PAYMENT_METHOD = (
        ('cash', 'Espèces'),
        ('bank_transfer', 'Virement bancaire'),
        ('check', 'Chèque'),
        ('card', 'Carte bancaire'),
        ('mobile_money', 'Mobile Money'),
        ('other', 'Autre'),
    )
    
    PAYMENT_STATUS = (
        ('pending', 'En attente'),
        ('processing', 'En cours'),
        ('completed', 'Terminé'),
        ('failed', 'Échoué'),
        ('cancelled', 'Annulé'),
    )
    
    # Références
    payment_number = models.CharField(max_length=50, unique=True, verbose_name="N° Paiement")
    reference_number = models.CharField(
        max_length=100, 
        blank=True, 
        null=True,
        verbose_name="N° de référence"
    )
    
    # Relations
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name="Facture"
    )
    
    agence = models.ForeignKey(
        Agence,
        on_delete=models.PROTECT,
        related_name='payments'
    )
    
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_payments'
    )
    
    validated_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='validated_payments'
    )
    
    # Lien vers la trésorerie
    caisse = models.ForeignKey(
        'tresorerie.Caisse',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments',
        verbose_name="Caisse utilisée"
    )
    
    compte_bancaire = models.ForeignKey(
        'tresorerie.CompteBancaire',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments',
        verbose_name="Compte bancaire utilisé"
    )
    
    mouvement_tresorerie = models.ForeignKey(
        'tresorerie.MouvementTresorerie',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment',
        verbose_name="Mouvement de trésorerie"
    )
    
    # Montants
    amount = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )
    
    currency = models.CharField(max_length=10, default='XOF')
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, default=1.0)
    
    # Dates
    payment_date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Méthode et statut
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='completed')
    
    # Notes
    notes = models.TextField(blank=True, null=True)
    
    # Documents
    receipt_file = models.FileField(
        upload_to='payments/',
        null=True,
        blank=True,
        verbose_name="Reçu"
    )
    
    class Meta:
        ordering = ['-payment_date', '-payment_number']
        indexes = [
            models.Index(fields=['payment_number']),
            models.Index(fields=['invoice', 'status']),
            models.Index(fields=['payment_date']),
        ]
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
    
    def __str__(self):
        return f"{self.payment_number} - {self.invoice.invoice_number} - {self.amount}"
    
    def save(self, *args, **kwargs):
        # Générer le numéro de paiement
        if not self.payment_number:
            last_payment = Payment.objects.order_by('-id').first()
            if last_payment:
                try:
                    last_num = int(last_payment.payment_number.replace('PAY', ''))
                    self.payment_number = f"PAY{str(last_num + 1).zfill(6)}"
                except (ValueError, AttributeError):
                    self.payment_number = "PAY000001"
            else:
                self.payment_number = "PAY000001"
        
        super().save(*args, **kwargs)
        
        # Mettre à jour le montant payé de la facture
        if self.status == 'completed':
            self.invoice.amount_paid = Payment.objects.filter(
                invoice=self.invoice,
                status='completed'
            ).aggregate(total=models.Sum('amount'))['total'] or 0
            self.invoice.save()
            
            # ✅ CRÉER AUTOMATIQUEMENT LE MOUVEMENT DE TRÉSORERIE
            try:
                if not self.mouvement_tresorerie:
                    self.create_treasury_movement()
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Erreur création mouvement trésorerie: {str(e)}")
    
    def create_treasury_movement(self):
        """
        Crée un mouvement de trésorerie pour ce paiement
        """
        from tresorerie.models import MouvementTresorerie, Caisse
        
        # ✅ Vérifier si le mouvement existe déjà
        if self.mouvement_tresorerie:
            return self.mouvement_tresorerie
        
        # ✅ Récupérer la caisse ou le compte
        caisse = self.caisse
        compte = self.compte_bancaire
        
        # ✅ Fallback : prendre la caisse par défaut de l'agence
        if not caisse and not compte:
            caisse = Caisse.objects.filter(
                agence=self.agence,
                is_default=True,
                is_active=True
            ).first()
            
            # Si pas de caisse par défaut, prendre la première caisse active
            if not caisse:
                caisse = Caisse.objects.filter(
                    agence=self.agence,
                    is_active=True
                ).first()
        
        # ✅ Vérifier qu'on a bien une destination
        if not caisse and not compte:
            raise ValueError(
                f"Aucune caisse ou compte bancaire trouvé pour l'agence {self.agence.nom}. "
                "Veuillez configurer une caisse par défaut."
            )
        
        # ✅ Mapping du mode de paiement
        mode_mapping = {
            'cash': 'especes',
            'bank_transfer': 'virement',
            'check': 'cheque',
            'card': 'carte',
            'mobile_money': 'mobile_money',
            'other': 'autre',
        }
        mode_paiement = mode_mapping.get(self.payment_method, 'virement')
        
        # ✅ CRÉER LE MOUVEMENT DE TRÉSORERIE
        mouvement = MouvementTresorerie.objects.create(
            type_mouvement='decaissement',
            agence=self.agence,
            source_type='payment',
            source_id=self.id,
            source_reference=self.payment_number,
            montant=self.amount,
            mode_paiement=mode_paiement,
            caisse=caisse,
            compte_bancaire=compte,
            date_mouvement=timezone.now(),
            date_valeur=self.payment_date or timezone.now().date(),
            status='effectue',  # ✅ Statut effectué pour mettre à jour le solde
            libelle=f"Paiement facture {self.invoice.invoice_number} - {self.payment_number}",
            notes=f"{self.notes or ''} - Paiement fournisseur {self.invoice.supplier.company_name}",
            created_by=self.created_by
        )
        
        # ✅ Sauvegarder la référence
        self.mouvement_tresorerie = mouvement
        self.save(update_fields=['mouvement_tresorerie'])
        
        return mouvement

# purchases/models.py - Modèle InvoiceItem COMPLET
# purchases/models.py - InvoiceItem

class InvoiceItem(models.Model):
    """Lignes de facture"""
    
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Facture"
    )
    
    receipt_item = models.ForeignKey(
        'PurchaseReceiptItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice_items',
        verbose_name="Ligne de réception"
    )
    
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Produit"
    )
    
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Variante"
    )
    
    description = models.CharField(
        max_length=255,
        verbose_name="Description"
    )
    
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1,
        validators=[MinValueValidator(0.01)],
        verbose_name="Quantité"
    )
    
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Prix unitaire"
    )
    
    discount_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="Taux de remise (%)"
    )
    
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,  # ✅ Mettre 0 par défaut pour correspondre au total de la réception
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="Taux de TVA (%)"
    )
    
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        editable=False,
        default=0,
        verbose_name="Sous-total"
    )
    
    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        editable=False,
        default=0,
        verbose_name="Montant TVA"
    )
    
    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        editable=False,
        default=0,
        verbose_name="Total"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Créé le"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Modifié le"
    )
    
    class Meta:
        ordering = ['id']
        verbose_name = "Ligne de facture"
        verbose_name_plural = "Lignes de facture"
        indexes = [
            models.Index(fields=['invoice']),
            models.Index(fields=['product']),
        ]
    
    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.description} - {self.total} FCFA"
    
    def save(self, *args, **kwargs):
        """
        Calcule automatiquement les montants avant la sauvegarde
        """
        from decimal import Decimal
        
        qty = Decimal(str(self.quantity))
        unit_price = Decimal(str(self.unit_price))
        disc_rate = Decimal(str(self.discount_rate))
        tax_rate = Decimal(str(self.tax_rate))
        
        # Calcul du sous-total avec remise
        discount_factor = (Decimal('100') - disc_rate) / Decimal('100')
        self.subtotal = qty * unit_price * discount_factor
        
        # Calcul de la TVA
        tax_factor = tax_rate / Decimal('100')
        self.tax_amount = self.subtotal * tax_factor
        
        # Calcul du total
        self.total = self.subtotal + self.tax_amount
        
        super().save(*args, **kwargs)