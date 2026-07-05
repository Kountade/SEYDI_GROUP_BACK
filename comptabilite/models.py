

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from users.models import CustomUser, Agence
from produits.models import Product
from sales.models import Vente, Facture, Paiement
from purchases.models import PurchaseOrder, PurchaseReceipt
from inventaire.models import Warehouse

# ============================================================
# PLAN COMPTABLE
# ============================================================

class PlanComptable(models.Model):
    """
    Plan comptable général
    """
    TYPE_COMPTES = (
        ('actif', 'Actif'),
        ('passif', 'Passif'),
        ('capitaux', 'Capitaux propres'),
        ('charges', 'Charges'),
        ('produits', 'Produits'),
    )

    code = models.CharField(max_length=20, unique=True, verbose_name="Code compte")
    nom = models.CharField(max_length=200, verbose_name="Nom du compte")
    type_compte = models.CharField(max_length=20, choices=TYPE_COMPTES, verbose_name="Type de compte")
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, 
                               related_name='sous_comptes', verbose_name="Compte parent")
    niveau = models.IntegerField(default=1, verbose_name="Niveau")
    
    # Pour la classification
    classe = models.CharField(max_length=10, blank=True, null=True, verbose_name="Classe")
    sous_classe = models.CharField(max_length=10, blank=True, null=True, verbose_name="Sous-classe")
    
    # Solde
    solde_normal = models.CharField(max_length=10, choices=(
        ('debiteur', 'Débiteur'),
        ('crediteur', 'Créditeur'),
    ), default='debiteur', verbose_name="Solde normal")
    
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    is_analytique = models.BooleanField(default=False, verbose_name="Compte analytique")
    
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, 
                                   related_name='comptes_crees')

    class Meta:
        verbose_name = "Plan comptable"
        verbose_name_plural = "Plan comptable"
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.nom}"

    def get_full_code(self):
        """Retourne le code complet avec les parents"""
        if self.parent:
            return f"{self.parent.get_full_code()}.{self.code}"
        return self.code

    @property
    def is_debit(self):
        return self.solde_normal == 'debiteur'

    @property
    def is_credit(self):
        return self.solde_normal == 'crediteur'


# ============================================================
# JOURNAUX
# ============================================================

class Journal(models.Model):
    """
    Journal comptable
    """
    TYPE_JOURNAUX = (
        ('achats', 'Achats'),
        ('ventes', 'Ventes'),
        ('banque', 'Banque'),
        ('caisse', 'Caisse'),
        ('od', 'Opérations diverses'),
        ('inventaire', 'Inventaire'),
        ('paie', 'Paie'),
        ('immobilisations', 'Immobilisations'),
    )

    code = models.CharField(max_length=10, unique=True, verbose_name="Code journal")
    nom = models.CharField(max_length=100, verbose_name="Nom du journal")
    type_journal = models.CharField(max_length=20, choices=TYPE_JOURNAUX, verbose_name="Type de journal")
    
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='journaux', 
                               verbose_name="Agence")
    
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    is_default = models.BooleanField(default=False, verbose_name="Journal par défaut")
    
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Journal"
        verbose_name_plural = "Journaux"
        unique_together = ['agence', 'code']
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.nom} ({self.agence.nom})"

    def save(self, *args, **kwargs):
        if self.is_default:
            Journal.objects.filter(agence=self.agence, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)


# ============================================================
# ÉCRITURES COMPTABLES
# ============================================================

class Ecriture(models.Model):
    """
    Écriture comptable principale
    """
    STATUS_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('valide', 'Validée'),
        ('annulee', 'Annulée'),
        ('cloturee', 'Clôturée'),
    )

    reference = models.CharField(max_length=50, unique=True, verbose_name="Référence")
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name='ecritures', 
                               verbose_name="Journal")
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='ecritures', 
                              verbose_name="Agence")
    
    date_ecriture = models.DateField(default=timezone.now, verbose_name="Date d'écriture")
    date_comptable = models.DateField(default=timezone.now, verbose_name="Date comptable")
    
    libelle = models.CharField(max_length=200, verbose_name="Libellé")
    piece_justificative = models.CharField(max_length=50, blank=True, null=True, 
                                          verbose_name="Pièce justificative")
    
    # Lien vers les opérations source
    source_type = models.CharField(max_length=50, blank=True, null=True, 
                                  verbose_name="Type de source")
    source_id = models.IntegerField(null=True, blank=True, verbose_name="ID source")
    
    # Totaux
    total_debit = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                     verbose_name="Total débit")
    total_credit = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                      verbose_name="Total crédit")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='brouillon', 
                             verbose_name="Statut")
    
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, 
                                   related_name='ecritures_crees', verbose_name="Créé par")
    validated_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, 
                                     blank=True, related_name='ecritures_validees', 
                                     verbose_name="Validé par")
    validated_at = models.DateTimeField(null=True, blank=True, verbose_name="Date validation")
    
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Écriture"
        verbose_name_plural = "Écritures"
        ordering = ['-date_ecriture', '-created_at']
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['date_ecriture']),
            models.Index(fields=['journal', 'status']),
            models.Index(fields=['agence', 'date_ecriture']),
        ]

    def __str__(self):
        return f"{self.reference} - {self.libelle} ({self.date_ecriture})"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"ECR{datetime.now().strftime('%Y%m')}"
            last = Ecriture.objects.filter(reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"
        super().save(*args, **kwargs)

    @property
    def est_equilibree(self):
        return self.total_debit == self.total_credit

    @property
    def montant(self):
        return self.total_debit or self.total_credit

    def valider(self, user):
        self.status = 'valide'
        self.validated_by = user
        self.validated_at = timezone.now()
        self.save()


class LigneEcriture(models.Model):
    """
    Ligne d'écriture comptable
    """
    ecriture = models.ForeignKey(Ecriture, on_delete=models.CASCADE, related_name='lignes', 
                                verbose_name="Écriture")
    compte = models.ForeignKey(PlanComptable, on_delete=models.PROTECT, related_name='lignes', 
                              verbose_name="Compte")
    
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                               verbose_name="Débit")
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                verbose_name="Crédit")
    
    libelle = models.CharField(max_length=200, blank=True, null=True, verbose_name="Libellé ligne")
    
    # Pour le lettrage
    lettrage = models.CharField(max_length=50, blank=True, null=True, verbose_name="Lettrage")
    date_lettrage = models.DateField(null=True, blank=True, verbose_name="Date lettrage")
    
    # Pour la comptabilité analytique
    centre_analytique = models.CharField(max_length=50, blank=True, null=True, 
                                        verbose_name="Centre analytique")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ligne d'écriture"
        verbose_name_plural = "Lignes d'écriture"
        ordering = ['id']

    def __str__(self):
        return f"{self.compte.code} - {self.compte.nom}: {self.montant}"

    @property
    def montant(self):
        return self.debit or self.credit

    @property
    def sens(self):
        if self.debit > 0:
            return 'D'
        if self.credit > 0:
            return 'C'
        return ''

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.debit > 0 and self.credit > 0:
            raise ValidationError("Une ligne ne peut pas avoir à la fois débit et crédit")
        if self.debit == 0 and self.credit == 0:
            raise ValidationError("Une ligne doit avoir un débit ou un crédit")


# ============================================================
# SOLDES
# ============================================================

class SoldeCompte(models.Model):
    """
    Solde d'un compte à une date donnée
    """
    compte = models.ForeignKey(PlanComptable, on_delete=models.PROTECT, related_name='soldes', 
                              verbose_name="Compte")
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='soldes_comptes', 
                              verbose_name="Agence")
    
    date_solde = models.DateField(verbose_name="Date du solde")
    
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Débit")
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Crédit")
    solde = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Solde")
    
    # Mouvements de la période
    debit_periode = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                       verbose_name="Débit période")
    credit_periode = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                        verbose_name="Crédit période")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Solde de compte"
        verbose_name_plural = "Soldes de comptes"
        unique_together = ['compte', 'agence', 'date_solde']
        ordering = ['compte__code', '-date_solde']

    def __str__(self):
        return f"{self.compte.code} - {self.date_solde}: {self.solde}"

    @property
    def solde_debiteur(self):
        return self.solde > 0 and self.compte.solde_normal == 'debiteur'

    @property
    def solde_crediteur(self):
        return self.solde > 0 and self.compte.solde_normal == 'crediteur'


# ============================================================
# BALANCES ET ÉTATS
# ============================================================

class Balance(models.Model):
    """
    Balance comptable (générale, des comptes, etc.)
    """
    TYPE_BALANCE = (
        ('generale', 'Balance générale'),
        ('comptes', 'Balance des comptes'),
        ('agee', 'Balance âgée'),
    )

    reference = models.CharField(max_length=50, unique=True, verbose_name="Référence")
    type_balance = models.CharField(max_length=20, choices=TYPE_BALANCE, default='generale',
                                   verbose_name="Type de balance")
    
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='balances', 
                              verbose_name="Agence")
    
    date_debut = models.DateField(verbose_name="Date début")
    date_fin = models.DateField(verbose_name="Date fin")
    
    status = models.CharField(max_length=20, choices=(
        ('brouillon', 'Brouillon'),
        ('valide', 'Validée'),
        ('archive', 'Archivée'),
    ), default='brouillon', verbose_name="Statut")
    
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, 
                                   related_name='balances_crees', verbose_name="Créé par")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Balance"
        verbose_name_plural = "Balances"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reference} - {self.type_balance} ({self.date_debut} au {self.date_fin})"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"BAL{datetime.now().strftime('%Y%m')}"
            last = Balance.objects.filter(reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"
        super().save(*args, **kwargs)


class LigneBalance(models.Model):
    """
    Ligne de balance
    """
    balance = models.ForeignKey(Balance, on_delete=models.CASCADE, related_name='lignes', 
                               verbose_name="Balance")
    compte = models.ForeignKey(PlanComptable, on_delete=models.PROTECT, related_name='lignes_balance', 
                              verbose_name="Compte")
    
    solde_initial_debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    solde_initial_credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    mouvement_debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    mouvement_credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    solde_final_debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    solde_final_credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Ligne de balance"
        verbose_name_plural = "Lignes de balance"
        ordering = ['compte__code']

    def __str__(self):
        return f"{self.compte.code} - {self.compte.nom}"


# ============================================================
# FACTURES CLIENT/FOURNISSEUR (Comptabilité)
# ============================================================

class FactureComptable(models.Model):
    """
    Facture comptable (client ou fournisseur)
    """
    TYPE_FACTURE = (
        ('client', 'Client'),
        ('fournisseur', 'Fournisseur'),
    )
    STATUS_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('envoyee', 'Envoyée'),
        ('recue', 'Reçue'),
        ('payee', 'Payée'),
        ('partielle', 'Partiellement payée'),
        ('impayee', 'Impayée'),
        ('annulee', 'Annulée'),
    )

    reference = models.CharField(max_length=50, unique=True, verbose_name="Référence")
    type_facture = models.CharField(max_length=20, choices=TYPE_FACTURE, verbose_name="Type")
    
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='factures_comptables', 
                              verbose_name="Agence")
    
    # Pour les clients
    client = models.ForeignKey('sales.Client', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='factures_comptables', verbose_name="Client")
    
    # Pour les fournisseurs
    fournisseur = models.ForeignKey('purchases.Supplier', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='factures_comptables', verbose_name="Fournisseur")
    
    # Lien vers les opérations
    vente = models.ForeignKey('sales.Vente', on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='factures_comptables', verbose_name="Vente")
    achat = models.ForeignKey('purchases.PurchaseOrder', on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='factures_comptables', verbose_name="Achat")
    
    date_facture = models.DateField(default=timezone.now, verbose_name="Date facture")
    date_echeance = models.DateField(verbose_name="Date échéance")
    
    montant_ht = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                    verbose_name="Montant HT")
    montant_tva = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                     verbose_name="Montant TVA")
    montant_ttc = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                     verbose_name="Montant TTC")
    
    montant_paye = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                      verbose_name="Montant payé")
    montant_restant = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                         verbose_name="Montant restant")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='brouillon',
                             verbose_name="Statut")
    
    # Rapprochement bancaire
    date_rapprochement = models.DateField(null=True, blank=True, verbose_name="Date rapprochement")
    rapproche = models.BooleanField(default=False, verbose_name="Rapproché")
    
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                  related_name='factures_comptables_crees', verbose_name="Créé par")

    class Meta:
        verbose_name = "Facture comptable"
        verbose_name_plural = "Factures comptables"
        ordering = ['-date_facture']
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['type_facture', 'status']),
            models.Index(fields=['date_facture', 'date_echeance']),
        ]

    def __str__(self):
        return f"{self.reference} - {self.type_facture} - {self.montant_ttc} FCFA"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"FC{datetime.now().strftime('%Y%m')}"
            if self.type_facture == 'client':
                prefix = f"FCL{datetime.now().strftime('%Y%m')}"
            else:
                prefix = f"FOU{datetime.now().strftime('%Y%m')}"
            last = FactureComptable.objects.filter(reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"
        
        self.montant_restant = self.montant_ttc - self.montant_paye
        
        if self.montant_paye >= self.montant_ttc:
            self.status = 'payee'
        elif self.montant_paye > 0:
            self.status = 'partielle'
        elif self.date_echeance < timezone.now().date():
            self.status = 'impayee'
        
        super().save(*args, **kwargs)


# ============================================================
# RÈGLEMENTS
# ============================================================

class Reglement(models.Model):
    """
    Règlement (paiement client ou fournisseur)
    """
    TYPE_REGLEMENT = (
        ('client', 'Client'),
        ('fournisseur', 'Fournisseur'),
    )
    MODE_REGLEMENT = (
        ('especes', 'Espèces'),
        ('carte', 'Carte bancaire'),
        ('cheque', 'Chèque'),
        ('virement', 'Virement'),
        ('mobile_money', 'Mobile Money'),
        ('autre', 'Autre'),
    )

    reference = models.CharField(max_length=50, unique=True, verbose_name="Référence")
    type_reglement = models.CharField(max_length=20, choices=TYPE_REGLEMENT, verbose_name="Type")
    
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='reglements', 
                              verbose_name="Agence")
    
    # Client ou fournisseur
    client = models.ForeignKey('sales.Client', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='reglements', verbose_name="Client")
    fournisseur = models.ForeignKey('purchases.Supplier', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='reglements', verbose_name="Fournisseur")
    
    # Facture associée
    facture = models.ForeignKey(FactureComptable, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='reglements', verbose_name="Facture")
    
    montant = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(0)],
                                 verbose_name="Montant")
    mode_reglement = models.CharField(max_length=20, choices=MODE_REGLEMENT, verbose_name="Mode")
    
    date_reglement = models.DateField(default=timezone.now, verbose_name="Date règlement")
    reference_externe = models.CharField(max_length=100, blank=True, null=True,
                                        verbose_name="Référence externe")
    
    # Rapprochement bancaire
    date_rapprochement = models.DateField(null=True, blank=True, verbose_name="Date rapprochement")
    rapproche = models.BooleanField(default=False, verbose_name="Rapproché")
    
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                  related_name='reglements_crees', verbose_name="Créé par")

    class Meta:
        verbose_name = "Règlement"
        verbose_name_plural = "Règlements"
        ordering = ['-date_reglement']
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['type_reglement', 'date_reglement']),
        ]

    def __str__(self):
        return f"{self.reference} - {self.type_reglement} - {self.montant} FCFA"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"REG{datetime.now().strftime('%Y%m')}"
            if self.type_reglement == 'client':
                prefix = f"RCL{datetime.now().strftime('%Y%m')}"
            else:
                prefix = f"RFOU{datetime.now().strftime('%Y%m')}"
            last = Reglement.objects.filter(reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"
        super().save(*args, **kwargs)


# ============================================================
# TABLEAUX DE BORD FINANCIERS
# ============================================================

class IndicateurFinancier(models.Model):
    """
    Indicateurs financiers (KPI)
    """
    INDICATEUR_TYPES = (
        ('tresorerie', 'Trésorerie'),
        ('profitabilite', 'Profitabilité'),
        ('liquidite', 'Liquidité'),
        ('endettement', 'Endettement'),
        ('rotation', 'Rotation'),
        ('marge', 'Marge'),
    )

    nom = models.CharField(max_length=100, verbose_name="Nom")
    type_indicateur = models.CharField(max_length=20, choices=INDICATEUR_TYPES, verbose_name="Type")
    code = models.CharField(max_length=20, unique=True, verbose_name="Code")
    
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='indicateurs', 
                              verbose_name="Agence")
    
    valeur = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Valeur")
    valeur_previous = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                         verbose_name="Valeur précédente")
    
    date_calcul = models.DateField(default=timezone.now, verbose_name="Date calcul")
    periode_debut = models.DateField(verbose_name="Période début")
    periode_fin = models.DateField(verbose_name="Période fin")
    
    formule = models.TextField(blank=True, null=True, verbose_name="Formule de calcul")
    interpretation = models.TextField(blank=True, null=True, verbose_name="Interprétation")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Indicateur financier"
        verbose_name_plural = "Indicateurs financiers"
        ordering = ['type_indicateur', 'code']

    def __str__(self):
        return f"{self.code} - {self.nom}: {self.valeur}"


# ============================================================
# CLÔTURE COMPTABLE
# ============================================================

class ClotureComptable(models.Model):
    """
    Clôture comptable (mensuelle, annuelle)
    """
    TYPE_CLOTURE = (
        ('mensuelle', 'Mensuelle'),
        ('trimestrielle', 'Trimestrielle'),
        ('annuelle', 'Annuelle'),
    )
    STATUS_CHOICES = (
        ('ouverte', 'Ouverte'),
        ('en_cours', 'En cours'),
        ('cloturee', 'Clôturée'),
        ('verrouillee', 'Verrouillée'),
    )

    reference = models.CharField(max_length=50, unique=True, verbose_name="Référence")
    type_cloture = models.CharField(max_length=20, choices=TYPE_CLOTURE, verbose_name="Type")
    
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='clotures', 
                              verbose_name="Agence")
    
    date_debut = models.DateField(verbose_name="Date début")
    date_fin = models.DateField(verbose_name="Date fin")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ouverte',
                             verbose_name="Statut")
    
    # Opérations de clôture
    total_debit = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                     verbose_name="Total débit")
    total_credit = models.DecimalField(max_digits=15, decimal_places=2, default=0, 
                                      verbose_name="Total crédit")
    
    resultat_exercice = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                           verbose_name="Résultat exercice")
    
    closed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='clotures_fermees', verbose_name="Fermé par")
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="Date fermeture")
    
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                  related_name='clotures_crees', verbose_name="Créé par")

    class Meta:
        verbose_name = "Clôture comptable"
        verbose_name_plural = "Clôtures comptables"
        ordering = ['-date_fin']
        unique_together = ['agence', 'date_debut', 'date_fin']

    def __str__(self):
        return f"{self.reference} - {self.type_cloture} ({self.date_debut} au {self.date_fin})"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"CLOT{datetime.now().strftime('%Y%m')}"
            last = ClotureComptable.objects.filter(reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"
        super().save(*args, **kwargs)


# ============================================================
# ANALYSE FINANCIÈRE
# ============================================================

class AnalyseFinanciere(models.Model):
    """
    Analyse financière (ratio, tendances, etc.)
    """
    ANALYSE_TYPES = (
        ('ratio', 'Ratio'),
        ('tendance', 'Tendance'),
        ('comparaison', 'Comparaison'),
        ('prevision', 'Prévision'),
    )

    reference = models.CharField(max_length=50, unique=True, verbose_name="Référence")
    type_analyse = models.CharField(max_length=20, choices=ANALYSE_TYPES, verbose_name="Type")
    
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='analyses', 
                              verbose_name="Agence")
    
    titre = models.CharField(max_length=200, verbose_name="Titre")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    
    donnees = models.JSONField(default=dict, verbose_name="Données de l'analyse")
    resultat = models.JSONField(default=dict, verbose_name="Résultat de l'analyse")
    
    date_debut = models.DateField(verbose_name="Date début")
    date_fin = models.DateField(verbose_name="Date fin")
    date_analyse = models.DateField(default=timezone.now, verbose_name="Date analyse")
    
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                  related_name='analyses_crees', verbose_name="Créé par")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Analyse financière"
        verbose_name_plural = "Analyses financières"
        ordering = ['-date_analyse']

    def __str__(self):
        return f"{self.reference} - {self.titre}"