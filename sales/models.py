# sales/models.py
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from users.models import CustomUser, Agence
from produits.models import Product, ProductVariant


class Client(models.Model):
    """Client (optionnel pour la vente)"""
    CLIENT_TYPES = (
        ('particulier', 'Particulier'),
        ('entreprise', 'Entreprise'),
        ('revendeur', 'Revendeur'),
    )

    client_type = models.CharField(
        max_length=20, choices=CLIENT_TYPES, default='particulier')
    nom = models.CharField(max_length=200)
    prenom = models.CharField(max_length=200, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    telephone = models.CharField(max_length=20)
    adresse = models.TextField(blank=True, null=True)
    raison_sociale = models.CharField(max_length=200, blank=True, null=True)
    numero_tva = models.CharField(max_length=50, blank=True, null=True)
    est_revendeur = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_clients')

    class Meta:
        ordering = ['nom']

    def __str__(self):
        if self.raison_sociale:
            return f"{self.raison_sociale} - {self.nom}"
        return self.nom

    @property
    def full_name(self):
        return f"{self.nom} {self.prenom}" if self.prenom else self.nom


class Vente(models.Model):
    """Vente principale"""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('pending_approval', 'En attente d\'approbation'),
        ('approved', 'Approuvée'),
        ('rejected', 'Rejetée'),
        ('completed', 'Complétée'),
        ('cancelled', 'Annulée'),
    )
    TYPE_VENTE = (
        ('comptoir', 'Comptoir'),
        ('livraison', 'Livraison'),
        ('en_ligne', 'En ligne'),
    )

    reference = models.CharField(max_length=100, unique=True)
    type_vente = models.CharField(
        max_length=20, choices=TYPE_VENTE, default='comptoir')
    agence = models.ForeignKey(
        Agence, on_delete=models.PROTECT, related_name='ventes')
    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='ventes')
    vendeur = models.ForeignKey(
        CustomUser, on_delete=models.PROTECT, related_name='ventes')
    approved_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_ventes')

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')
    date_vente = models.DateTimeField(default=timezone.now)
    date_approbation = models.DateTimeField(null=True, blank=True)

    sous_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    remise = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remise_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0)
    tva = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    montant_paye = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    montant_du = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    est_paye = models.BooleanField(default=False)

    notes = models.TextField(blank=True, null=True)
    motif_rejet = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_vente']
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['status']),
            models.Index(fields=['agence', 'status']),
        ]

    def __str__(self):
        return f"{self.reference} - {self.agence.nom} - {self.total} FCFA"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"VENTE{datetime.now().strftime('%Y%m%d')}"
            last = Vente.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                last_num = int(last.reference.replace(prefix, ''))
                self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
            else:
                self.reference = f"{prefix}0001"
        super().save(*args, **kwargs)

    @property
    def reste_a_payer(self):
        return self.total - self.montant_paye


class VenteItem(models.Model):
    vente = models.ForeignKey(
        Vente, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)

    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    prix_unitaire = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    remise = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tva = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    stock_preleve = models.BooleanField(default=False)
    warehouse_source = models.ForeignKey(
        'inventaire.Warehouse', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    def save(self, *args, **kwargs):
        self.total = (self.prix_unitaire * self.quantity) - \
            self.remise + self.tva
        super().save(*args, **kwargs)


class Devis(models.Model):
    """Devis (proforma / estimation) avant transformation en vente"""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('sent', 'Envoyé'),
        ('accepted', 'Accepté'),
        ('refused', 'Refusé'),
        ('converted', 'Converti en vente'),
        ('expired', 'Expiré'),
        ('cancelled', 'Annulé'),
    )

    reference = models.CharField(max_length=100, unique=True)
    agence = models.ForeignKey(
        Agence, on_delete=models.PROTECT, related_name='devis')
    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='devis')
    vendeur = models.ForeignKey(
        CustomUser, on_delete=models.PROTECT, related_name='devis')

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')
    date_creation = models.DateTimeField(default=timezone.now)
    date_expiration = models.DateField()  # Date de validité du devis

    sous_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    remise = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remise_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0)
    tva = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    notes = models.TextField(blank=True, null=True)
    conditions = models.TextField(
        blank=True, null=True, help_text="Conditions générales du devis")
    pied_de_page = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_creation']
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['status']),
            models.Index(fields=['agence', 'status']),
        ]

    def __str__(self):
        return f"{self.reference} - {self.client} - {self.total} FCFA"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"DEV{datetime.now().strftime('%Y%m%d')}"
            last = Devis.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                last_num = int(last.reference.replace(prefix, ''))
                self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
            else:
                self.reference = f"{prefix}0001"
        super().save(*args, **kwargs)

    @property
    def est_valide(self):
        return self.status in ('draft', 'sent', 'accepted') and self.date_expiration >= timezone.now().date()

    @property
    def jours_restants(self):
        if self.est_valide:
            return (self.date_expiration - timezone.now().date()).days
        return 0


class DevisItem(models.Model):
    """Ligne d'un devis"""
    devis = models.ForeignKey(
        Devis, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)

    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    prix_unitaire = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    remise = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tva = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    def save(self, *args, **kwargs):
        self.total = (self.prix_unitaire * self.quantity) - \
            self.remise + self.tva
        super().save(*args, **kwargs)


class Facture(models.Model):
    """Facture générée à partir d'une vente"""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('sent', 'Envoyée'),
        ('paid', 'Payée'),
        ('partially_paid', 'Partiellement payée'),
        ('overdue', 'En retard'),
        ('cancelled', 'Annulée'),
    )
    TYPE_FACTURE = (
        ('proforma', 'Proforma'),
        ('finale', 'Finale'),
        ('avoir', 'Avoir'),
    )

    reference = models.CharField(max_length=100, unique=True)
    type_facture = models.CharField(
        max_length=20, choices=TYPE_FACTURE, default='finale')

    vente = models.ForeignKey(
        Vente, on_delete=models.CASCADE, related_name='factures')
    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True)
    agence = models.ForeignKey(
        Agence, on_delete=models.PROTECT, related_name='factures')
    cree_par = models.ForeignKey(
        CustomUser, on_delete=models.PROTECT, related_name='factures_creees')

    date_facture = models.DateField(default=timezone.now)
    date_echeance = models.DateField()

    sous_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    remise = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tva = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_ttc = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    montant_paye = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    montant_restant = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)

    currency = models.CharField(max_length=10, default='XOF')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')
    conditions_paiement = models.TextField(default="Paiement à 30 jours")
    notes = models.TextField(blank=True, null=True)
    pied_de_page = models.TextField(blank=True, null=True)
    pdf_file = models.FileField(upload_to='factures/', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_facture']
        verbose_name = "Facture"
        verbose_name_plural = "Factures"

    def __str__(self):
        return f"{self.reference} - {self.total_ttc} FCFA"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"FACT{datetime.now().strftime('%Y%m')}"
            last = Facture.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                last_num = int(last.reference.replace(prefix, ''))
                self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
            else:
                self.reference = f"{prefix}0001"

        self.montant_restant = self.total_ttc - self.montant_paye

        if self.montant_paye >= self.total_ttc:
            self.status = 'paid'
        elif self.montant_paye > 0:
            self.status = 'partially_paid'
        elif self.date_echeance < timezone.now().date():
            self.status = 'overdue'

        super().save(*args, **kwargs)

    @property
    def is_paid(self):
        return self.montant_paye >= self.total_ttc

    @property
    def is_overdue(self):
        return self.date_echeance < timezone.now().date() and not self.is_paid

    @property
    def payment_percentage(self):
        return (self.montant_paye / self.total_ttc) * 100 if self.total_ttc > 0 else 0

    @property
    def days_overdue(self):
        if self.is_overdue:
            return (timezone.now().date() - self.date_echeance).days
        return 0


class Paiement(models.Model):
    """Paiement d'une facture"""
    METHODES_PAIEMENT = (
        ('especes', 'Espèces'),
        ('carte', 'Carte bancaire'),
        ('cheque', 'Chèque'),
        ('virement', 'Virement'),
        ('mobile_money', 'Mobile Money'),
        ('autre', 'Autre'),
    )
    STATUT_PAIEMENT = (
        ('pending', 'En attente'),
        ('completed', 'Complété'),
        ('failed', 'Échoué'),
        ('refunded', 'Remboursé'),
    )

    reference = models.CharField(max_length=50, unique=True)

    facture = models.ForeignKey(
        Facture, on_delete=models.CASCADE, related_name='paiements')
    client = models.ForeignKey(
        Client, on_delete=models.PROTECT, null=True, blank=True, related_name='paiements')
    vente = models.ForeignKey(
        Vente, on_delete=models.PROTECT, null=True, blank=True, related_name='paiements')

    montant = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    methode = models.CharField(max_length=20, choices=METHODES_PAIEMENT)
    date_paiement = models.DateField(auto_now_add=True)

    reference_externe = models.CharField(max_length=100, blank=True, null=True,
                                         help_text="Référence du paiement (numéro de chèque, de virement, etc.)")

    statut = models.CharField(
        max_length=20, choices=STATUT_PAIEMENT, default='completed')
    notes = models.TextField(blank=True, null=True)

    encaisse_par = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                     related_name='paiements_encaisses')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_paiement']
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['facture', 'statut']),
            models.Index(fields=['date_paiement']),
        ]

    def __str__(self):
        return f"PAI-{self.reference} - {self.montant} FCFA"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"PAI{datetime.now().strftime('%Y%m%d')}"
            last = Paiement.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                last_num = int(last.reference.replace(prefix, ''))
                self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
            else:
                self.reference = f"{prefix}0001"

        super().save(*args, **kwargs)

        # Mise à jour de la facture (prend en compte ce paiement)
        self.mettre_a_jour_facture()

        # Mise à jour de la vente si elle existe
        if self.vente:
            self.mettre_a_jour_vente()

    def mettre_a_jour_facture(self):
        """Recompte le total payé de la facture à partir de tous ses paiements."""
        total_paye = self.facture.paiements.filter(statut='completed').aggregate(
            total=models.Sum('montant')
        )['total'] or 0

        self.facture.montant_paye = total_paye
        self.facture.montant_restant = self.facture.total_ttc - total_paye

        if total_paye >= self.facture.total_ttc:
            self.facture.status = 'paid'
        elif total_paye > 0:
            self.facture.status = 'partially_paid'
        elif self.facture.date_echeance < timezone.now().date():
            self.facture.status = 'overdue'

        self.facture.save(
            update_fields=['montant_paye', 'montant_restant', 'status'])

    def mettre_a_jour_vente(self):
        total_paye_vente = self.vente.paiements.filter(statut='completed').aggregate(
            total=models.Sum('montant')
        )['total'] or 0

        self.vente.montant_paye = total_paye_vente
        self.vente.montant_du = self.vente.total - total_paye_vente
        self.vente.est_paye = total_paye_vente >= self.vente.total
        self.vente.save(
            update_fields=['montant_paye', 'montant_du', 'est_paye'])

    @property
    def methode_display(self):
        return dict(self.METHODES_PAIEMENT).get(self.methode, self.methode)

    @property
    def statut_display(self):
        return dict(self.STATUT_PAIEMENT).get(self.statut, self.statut)
