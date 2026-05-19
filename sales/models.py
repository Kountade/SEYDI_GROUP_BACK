# sales/models.py

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
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
    
    client_type = models.CharField(max_length=20, choices=CLIENT_TYPES, default='particulier')
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
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_clients')
    
    class Meta:
        ordering = ['nom']
    
    def __str__(self):
        if self.raison_sociale:
            return f"{self.raison_sociale} - {self.nom}"
        return self.nom
    
    @property
    def full_name(self):
        if self.prenom:
            return f"{self.nom} {self.prenom}"
        return self.nom


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
    type_vente = models.CharField(max_length=20, choices=TYPE_VENTE, default='comptoir')
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='ventes')
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='ventes')
    vendeur = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='ventes')
    approved_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_ventes')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    date_vente = models.DateTimeField(default=timezone.now)
    date_approbation = models.DateTimeField(null=True, blank=True)
    
    sous_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remise = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remise_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tva = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    montant_paye = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    montant_du = models.DecimalField(max_digits=12, decimal_places=2, default=0)
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
            last = Vente.objects.filter(reference__startswith=prefix).order_by('-id').first()
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
    """Ligne de vente"""
    vente = models.ForeignKey(Vente, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    remise = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tva = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    stock_preleve = models.BooleanField(default=False)
    warehouse_source = models.ForeignKey('inventaire.Warehouse', on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        ordering = ['id']
    
    def __str__(self):
        return f"{self.product.name} x {self.quantity}"
    
    def save(self, *args, **kwargs):
        self.total = (self.prix_unitaire * self.quantity) - self.remise + self.tva
        super().save(*args, **kwargs)


class Paiement(models.Model):
    """Paiement d'une vente"""
    METHODES = (
        ('especes', 'Espèces'),
        ('carte', 'Carte bancaire'),
        ('cheque', 'Chèque'),
        ('virement', 'Virement'),
        ('mobile_money', 'Mobile Money'),
    )
    
    STATUTS = (
        ('pending', 'En attente'),
        ('completed', 'Complété'),
        ('failed', 'Échoué'),
        ('refunded', 'Remboursé'),
    )
    
    vente = models.ForeignKey(Vente, on_delete=models.CASCADE, related_name='paiements')
    montant = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    methode = models.CharField(max_length=20, choices=METHODES)
    reference = models.CharField(max_length=100, blank=True, null=True)
    statut = models.CharField(max_length=20, choices=STATUTS, default='completed')
    date_paiement = models.DateTimeField(default=timezone.now)
    encaisse_par = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='encaissements')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-date_paiement']
    
    def __str__(self):
        return f"{self.vente.reference} - {self.montant} FCFA"


class Facture(models.Model):
    """Facture générée à partir d'une vente"""
    TYPE_FACTURE = (
        ('proforma', 'Proforma'),
        ('finale', 'Finale'),
        ('avoir', 'Avoir'),
    )
    
    STATUT_FACTURE = (
        ('brouillon', 'Brouillon'),
        ('envoyee', 'Envoyée'),
        ('payee', 'Payée'),
        ('partiellement_payee', 'Partiellement payée'),
        ('en_retard', 'En retard'),
        ('annulee', 'Annulée'),
    )
    
    reference = models.CharField(max_length=100, unique=True)
    type_facture = models.CharField(max_length=20, choices=TYPE_FACTURE, default='finale')
    statut = models.CharField(max_length=20, choices=STATUT_FACTURE, default='brouillon')
    
    vente = models.ForeignKey(Vente, on_delete=models.CASCADE, related_name='factures')
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True)
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='factures')
    cree_par = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='factures_creees')
    
    date_facture = models.DateField(default=timezone.now)
    date_echeance = models.DateField()
    
    sous_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remise = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tva = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_ttc = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    montant_paye = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    montant_restant = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    conditions_paiement = models.TextField(default="Paiement à 30 jours")
    notes = models.TextField(blank=True, null=True)
    pied_de_page = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date_facture']
    
    def __str__(self):
        return f"{self.reference} - {self.total_ttc} FCFA"
    
    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"FACT{datetime.now().strftime('%Y%m')}"
            last = Facture.objects.filter(reference__startswith=prefix).order_by('-id').first()
            if last:
                last_num = int(last.reference.replace(prefix, ''))
                self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
            else:
                self.reference = f"{prefix}0001"
        
        self.montant_restant = self.total_ttc - self.montant_paye
        
        if self.montant_paye >= self.total_ttc:
            self.statut = 'payee'
        elif self.montant_paye > 0:
            self.statut = 'partiellement_payee'
        elif self.date_echeance < timezone.now().date():
            self.statut = 'en_retard'
        
        super().save(*args, **kwargs)


class FactureItem(models.Model):
    """Ligne de facture"""
    facture = models.ForeignKey(Facture, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    
    description = models.CharField(max_length=500)
    quantite = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    prix_unitaire_ht = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    tva = models.DecimalField(max_digits=5, decimal_places=2, default=18)
    montant_ht = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    montant_tva = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    montant_ttc = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    def save(self, *args, **kwargs):
        self.montant_ht = self.quantite * self.prix_unitaire_ht
        self.montant_tva = self.montant_ht * (self.tva / 100)
        self.montant_ttc = self.montant_ht + self.montant_tva
        super().save(*args, **kwargs)