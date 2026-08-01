from django.db import models

# Create your models here.
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from users.models import CustomUser, Agence
from comptabilite.models import PlanComptable, Ecriture, LigneEcriture


# ============================================================
# 1. CAISSES
# ============================================================

class Caisse(models.Model):
    """
    Caisse physique ou virtuelle
    """
    TYPE_CAISSE = (
        ('principale', 'Caisse principale'),
        ('secondaire', 'Caisse secondaire'),
        ('mobile', 'Caisse mobile'),
        ('virtuelle', 'Caisse virtuelle'),
    )

    code = models.CharField(max_length=20, unique=True,
                            verbose_name="Code caisse")
    nom = models.CharField(max_length=100, verbose_name="Nom de la caisse")
    type_caisse = models.CharField(max_length=20, choices=TYPE_CAISSE, default='principale',
                                   verbose_name="Type de caisse")

    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='caisses',
                               verbose_name="Agence")
    responsable = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='caisses_gerrees', verbose_name="Responsable")

    solde_initial = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                        verbose_name="Solde initial")
    solde_actuel = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                       verbose_name="Solde actuel")

    seuil_min = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                    verbose_name="Seuil minimum")
    seuil_max = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                    verbose_name="Seuil maximum")

    devise = models.CharField(
        max_length=3, default='GNF', verbose_name="Devise")

    is_active = models.BooleanField(default=True, verbose_name="Active")
    is_default = models.BooleanField(
        default=False, verbose_name="Caisse par défaut")

    description = models.TextField(
        blank=True, null=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   related_name='caisses_crees', verbose_name="Créé par")

    class Meta:
        verbose_name = "Caisse"
        verbose_name_plural = "Caisses"
        ordering = ['code']
        unique_together = ['agence', 'code']

    def __str__(self):
        return f"{self.code} - {self.nom} ({self.agence.nom})"

    def save(self, *args, **kwargs):
        if self.is_default:
            Caisse.objects.filter(agence=self.agence,
                                  is_default=True).update(is_default=False)
        super().save(*args, **kwargs)

    @property
    def est_sous_seuil_min(self):
        return self.solde_actuel < self.seuil_min

    @property
    def est_sur_seuil_max(self):
        return self.seuil_max > 0 and self.solde_actuel > self.seuil_max


# ============================================================
# 2. COMPTES BANCAIRES
# ============================================================

class CompteBancaire(models.Model):
    """
    Compte bancaire de l'entreprise
    """
    TYPE_COMPTE = (
        ('courant', 'Compte courant'),
        ('epargne', 'Compte épargne'),
        ('bloque', 'Compte bloqué'),
    )

    banque = models.CharField(max_length=100, verbose_name="Banque")
    code = models.CharField(max_length=20, unique=True,
                            verbose_name="Code compte")
    nom = models.CharField(max_length=100, verbose_name="Nom du compte")
    type_compte = models.CharField(max_length=20, choices=TYPE_COMPTE, default='courant',
                                   verbose_name="Type de compte")

    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='comptes_bancaires',
                               verbose_name="Agence")

    numero_compte = models.CharField(
        max_length=50, verbose_name="Numéro de compte")
    iban = models.CharField(max_length=34, blank=True,
                            null=True, verbose_name="IBAN")
    bic = models.CharField(max_length=11, blank=True,
                           null=True, verbose_name="BIC/SWIFT")

    devise = models.CharField(
        max_length=3, default='GNF', verbose_name="Devise")
    solde_initial = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                        verbose_name="Solde initial")
    solde_actuel = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                       verbose_name="Solde actuel")

    is_active = models.BooleanField(default=True, verbose_name="Actif")
    is_default = models.BooleanField(
        default=False, verbose_name="Compte par défaut")

    date_ouverture = models.DateField(
        default=timezone.now, verbose_name="Date d'ouverture")
    description = models.TextField(
        blank=True, null=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   related_name='comptes_bancaires_crees', verbose_name="Créé par")

    class Meta:
        verbose_name = "Compte bancaire"
        verbose_name_plural = "Comptes bancaires"
        ordering = ['banque', 'code']
        unique_together = ['agence', 'code', 'numero_compte']

    def __str__(self):
        return f"{self.banque} - {self.nom} ({self.numero_compte})"


# ============================================================
# 3. MOUVEMENTS DE TRÉSORERIE
# ============================================================

class MouvementTresorerie(models.Model):
    """
    Mouvement de trésorerie (entrée ou sortie d'argent)
    """
    TYPE_MOUVEMENT = (
        ('encaissement', 'Encaissement'),
        ('decaissement', 'Décaissement'),
        ('transfert', 'Transfert'),
    )

    SOURCE_TYPE = (
        ('vente', 'Vente'),
        ('achat', 'Achat'),
        ('facture_client', 'Facture client'),
        ('facture_fournisseur', 'Facture fournisseur'),
        ('reglement', 'Règlement'),
        ('ecriture', 'Écriture comptable'),
        ('salaire', 'Salaire'),
        ('frais', 'Frais'),
        ('caisse', 'Caisse'),
        ('compte_bancaire', 'Compte bancaire'),
        ('autre', 'Autre'),
    )

    MODE_PAIEMENT = (
        ('especes', 'Espèces'),
        ('carte', 'Carte bancaire'),
        ('cheque', 'Chèque'),
        ('virement', 'Virement'),
        ('mobile_money', 'Mobile Money'),
        ('prelevement', 'Prélèvement'),
        ('autre', 'Autre'),
    )

    STATUS_CHOICES = (
        ('planifie', 'Planifié'),
        ('en_attente', 'En attente'),
        ('effectue', 'Effectué'),
        ('annule', 'Annulé'),
        ('rejete', 'Rejeté'),
    )

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Référence")
    type_mouvement = models.CharField(
        max_length=20, choices=TYPE_MOUVEMENT, verbose_name="Type de mouvement")

    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='mouvements_tresorerie',
                               verbose_name="Agence")

    # Source du mouvement
    source_type = models.CharField(
        max_length=20, choices=SOURCE_TYPE, verbose_name="Type source")
    source_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID source")
    source_reference = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Référence source")

    # Montant
    montant = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(0)],
                                  verbose_name="Montant")

    # Mode de paiement
    mode_paiement = models.CharField(
        max_length=20, choices=MODE_PAIEMENT, verbose_name="Mode de paiement")

    # Caisse ou compte bancaire
    caisse = models.ForeignKey(Caisse, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='mouvements', verbose_name="Caisse")
    compte_bancaire = models.ForeignKey(CompteBancaire, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='mouvements', verbose_name="Compte bancaire")

    # Dates
    date_mouvement = models.DateTimeField(
        default=timezone.now, verbose_name="Date du mouvement")
    date_valeur = models.DateField(verbose_name="Date de valeur")
    date_prevue = models.DateField(
        null=True, blank=True, verbose_name="Date prévue")

    # Statut
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planifie',
                              verbose_name="Statut")

    # Références externes
    reference_externe = models.CharField(max_length=100, blank=True, null=True,
                                         verbose_name="Référence externe")
    piece_justificative = models.CharField(max_length=50, blank=True, null=True,
                                           verbose_name="Pièce justificative")

    # Rapprochement
    date_rapprochement = models.DateField(
        null=True, blank=True, verbose_name="Date rapprochement")
    rapproche = models.BooleanField(default=False, verbose_name="Rapproché")

    # Libellé et notes
    libelle = models.CharField(max_length=200, verbose_name="Libellé")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")

    # Lien vers l'écriture comptable (EXISTANT)
    ecriture = models.ForeignKey(Ecriture, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='mouvements_tresorerie', verbose_name="Écriture comptable")

    # Création et validation
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   related_name='mouvements_tresorerie_crees', verbose_name="Créé par")
    valide_par = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='mouvements_tresorerie_valides', verbose_name="Validé par")
    date_validation = models.DateTimeField(
        null=True, blank=True, verbose_name="Date validation")

    class Meta:
        verbose_name = "Mouvement de trésorerie"
        verbose_name_plural = "Mouvements de trésorerie"
        ordering = ['-date_mouvement']
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['type_mouvement', 'date_mouvement']),
            models.Index(fields=['agence', 'status']),
            models.Index(fields=['caisse', 'date_mouvement']),
            models.Index(fields=['compte_bancaire', 'date_mouvement']),
        ]

    def __str__(self):
        return f"{self.reference} - {self.type_mouvement} - {self.montant:,.0f} GNF"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"TRES{datetime.now().strftime('%Y%m')}"
            if self.type_mouvement == 'encaissement':
                prefix = f"ENC{datetime.now().strftime('%Y%m')}"
            elif self.type_mouvement == 'decaissement':
                prefix = f"DEC{datetime.now().strftime('%Y%m')}"
            else:
                prefix = f"TRF{datetime.now().strftime('%Y%m')}"

            last = MouvementTresorerie.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"

        # Mettre à jour les soldes si mouvement effectué
        if self.status == 'effectue' and not self.pk:
            self._mettre_a_jour_soldes()

        super().save(*args, **kwargs)

    def _mettre_a_jour_soldes(self):
        """Met à jour les soldes des caisses/comptes bancaires"""
        if self.caisse:
            if self.type_mouvement == 'encaissement':
                self.caisse.solde_actuel += self.montant
            elif self.type_mouvement == 'decaissement':
                self.caisse.solde_actuel -= self.montant
            self.caisse.save()

        if self.compte_bancaire:
            if self.type_mouvement == 'encaissement':
                self.compte_bancaire.solde_actuel += self.montant
            elif self.type_mouvement == 'decaissement':
                self.compte_bancaire.solde_actuel -= self.montant
            self.compte_bancaire.save()

    @property
    def est_encaissement(self):
        return self.type_mouvement == 'encaissement'

    @property
    def est_decaissement(self):
        return self.type_mouvement == 'decaissement'

    @property
    def est_transfert(self):
        return self.type_mouvement == 'transfert'


# ============================================================
# 4. FRAIS ET DÉPENSES
# ============================================================

class Frais(models.Model):
    """
    Frais et dépenses diverses
    """
    CATEGORIE_FRAIS = (
        ('transport', 'Transport'),
        ('restauration', 'Restauration'),
        ('fournitures', 'Fournitures de bureau'),
        ('communication', 'Communication'),
        ('entretien', 'Entretien'),
        ('formation', 'Formation'),
        ('mission', 'Mission'),
        ('representations', 'Représentation'),
        ('assurances', 'Assurances'),
        ('impots', 'Impôts et taxes'),
        ('loyer', 'Loyer'),
        ('services', 'Services'),
        ('autre', 'Autre'),
    )

    STATUS_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('en_attente', 'En attente de validation'),
        ('valide', 'Validé'),
        ('paye', 'Payé'),
        ('refuse', 'Refusé'),
        ('annule', 'Annulé'),
    )

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Référence")
    titre = models.CharField(max_length=200, verbose_name="Titre")

    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='frais',
                               verbose_name="Agence")

    categorie = models.CharField(
        max_length=20, choices=CATEGORIE_FRAIS, verbose_name="Catégorie")
    montant = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(0)],
                                  verbose_name="Montant")

    date_frais = models.DateField(
        default=timezone.now, verbose_name="Date du frais")
    date_paiement = models.DateField(
        null=True, blank=True, verbose_name="Date de paiement")

    beneficiaire = models.CharField(
        max_length=200, verbose_name="Bénéficiaire")

    piece_justificative = models.CharField(max_length=50, blank=True, null=True,
                                           verbose_name="Pièce justificative")

    mode_paiement = models.CharField(max_length=20, choices=MouvementTresorerie.MODE_PAIEMENT,
                                     default='especes', verbose_name="Mode de paiement")

    # ============================================================
    # DESTINATION DU DÉCAISSEMENT (NOUVEAU)
    # ============================================================
    caisse_destination = models.ForeignKey(
        'Caisse',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='frais_sortants',
        verbose_name="Caisse de décaissement"
    )
    compte_destination = models.ForeignKey(
        'CompteBancaire',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='frais_sortants',
        verbose_name="Compte bancaire de décaissement"
    )

    mouvement = models.ForeignKey(
        MouvementTresorerie,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='frais_associes',
        verbose_name="Mouvement associé"
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='brouillon',
                              verbose_name="Statut")

    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   related_name='frais_crees', verbose_name="Créé par")
    valide_par = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='frais_valides', verbose_name="Validé par")
    date_validation = models.DateTimeField(
        null=True, blank=True, verbose_name="Date validation")

    class Meta:
        verbose_name = "Frais"
        verbose_name_plural = "Frais"
        ordering = ['-date_frais']

    def __str__(self):
        return f"{self.reference} - {self.titre} ({self.montant:,.0f} GNF)"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"FRAIS{datetime.now().strftime('%Y%m')}"
            last = Frais.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"

        # ✅ Création du mouvement si le frais est payé et qu'il n'y en a pas encore
        if self.status == 'paye' and not self.mouvement:
            # Déterminer la destination
            caisse = self.caisse_destination
            compte = self.compte_destination

            # Fallback : caisse par défaut si aucune destination choisie
            if not caisse and not compte:
                caisse = Caisse.objects.filter(
                    agence=self.agence,
                    is_default=True
                ).first()
                if not caisse:
                    raise ValidationError(
                        f"Aucune caisse par défaut pour l'agence '{self.agence.nom}'. "
                        "Veuillez choisir une destination."
                    )

            # Créer le mouvement de décaissement
            # La méthode save() de MouvementTresorerie gère automatiquement
            # la mise à jour des soldes (puisque status='effectue' et pk is None).
            # On n'appelle PAS _mettre_a_jour_soldes() ni save() manuellement.
            mouvement = MouvementTresorerie.objects.create(
                type_mouvement='decaissement',
                agence=self.agence,
                source_type='frais',
                source_id=self.id,
                source_reference=self.reference,
                montant=self.montant,
                mode_paiement=self.mode_paiement,
                caisse=caisse,
                compte_bancaire=compte,
                date_mouvement=timezone.now(),
                date_valeur=self.date_paiement or timezone.now().date(),
                status='effectue',
                libelle=f"Frais: {self.titre}",
                created_by=self.created_by
            )
            # Le mouvement est déjà sauvegardé et a mis à jour le solde.
            self.mouvement = mouvement

        super().save(*args, **kwargs)

# ============================================================
# 5. PRÉVISIONS DE TRÉSORERIE
# ============================================================


class PrevisionTresorerie(models.Model):
    """
    Prévision de trésorerie
    """
    PERIODE_CHOICES = (
        ('journalier', 'Journalier'),
        ('hebdomadaire', 'Hebdomadaire'),
        ('mensuel', 'Mensuel'),
        ('trimestriel', 'Trimestriel'),
        ('annuel', 'Annuel'),
    )

    TYPE_PREVISION = (
        ('entree', 'Entrée prévue'),
        ('sortie', 'Sortie prévue'),
    )

    STATUT_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('en_cours', 'En cours'),
        ('valide', 'Validée'),
        ('realise', 'Réalisé'),
        ('annule', 'Annulé'),
        ('ecart', 'Écart constaté'),
    )

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Référence")
    titre = models.CharField(max_length=200, verbose_name="Titre")

    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='previsions_tresorerie',
                               verbose_name="Agence")

    type_prevision = models.CharField(
        max_length=20, choices=TYPE_PREVISION, verbose_name="Type de prévision")
    periode = models.CharField(max_length=20, choices=PERIODE_CHOICES, default='mensuel',
                               verbose_name="Période")

    montant_prevu = models.DecimalField(max_digits=15, decimal_places=2,
                                        validators=[MinValueValidator(0)],
                                        verbose_name="Montant prévu")
    montant_reel = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                       verbose_name="Montant réel")

    date_debut = models.DateField(verbose_name="Date début")
    date_fin = models.DateField(verbose_name="Date fin")

    # Source
    source_type = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="Type source")
    source_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID source")

    # Catégorie
    categorie = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="Catégorie")
    sous_categorie = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="Sous-catégorie")

    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='brouillon',
                              verbose_name="Statut")

    probabilite = models.IntegerField(default=50, validators=[MinValueValidator(0), MaxValueValidator(100)],
                                      verbose_name="Probabilité (%)")

    # Écart
    ecart = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Écart")
    pourcentage_ecart = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                            verbose_name="Pourcentage d'écart")

    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   related_name='previsions_crees', verbose_name="Créé par")

    class Meta:
        verbose_name = "Prévision de trésorerie"
        verbose_name_plural = "Prévisions de trésorerie"
        ordering = ['-date_debut']

    def __str__(self):
        return f"{self.reference} - {self.titre} ({self.montant_prevu:,.0f} GNF)"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"PREV{datetime.now().strftime('%Y%m')}"
            last = PrevisionTresorerie.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"

        # Calculer l'écart
        self.ecart = self.montant_reel - self.montant_prevu
        if self.montant_prevu > 0:
            self.pourcentage_ecart = (self.ecart / self.montant_prevu) * 100

        super().save(*args, **kwargs)


# ============================================================
# 6. RAPPROCHEMENT BANCAIRE
# ============================================================

class RapprochementBancaire(models.Model):
    """
    Rapprochement bancaire
    """
    STATUS_CHOICES = (
        ('brouillon', 'Brouillon'),
        ('en_cours', 'En cours'),
        ('partiel', 'Partiellement rapproché'),
        ('complete', 'Complètement rapproché'),
        ('ecart', 'Écart constaté'),
    )

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Référence")

    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='rapprochements',
                               verbose_name="Agence")
    compte_bancaire = models.ForeignKey(CompteBancaire, on_delete=models.PROTECT,
                                        related_name='rapprochements', verbose_name="Compte bancaire")

    date_debut = models.DateField(verbose_name="Date début")
    date_fin = models.DateField(verbose_name="Date fin")

    solde_comptable = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                          verbose_name="Solde comptable")
    solde_bancaire = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                         verbose_name="Solde bancaire")
    solde_rapproche = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                          verbose_name="Solde rapproché")
    ecart = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                verbose_name="Écart")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='brouillon',
                              verbose_name="Statut")

    # Éléments de rapprochement
    encours_emission = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                           verbose_name="En-cours d'émission")
    encours_encaissement = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                               verbose_name="En-cours d'encaissement")
    commissions = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                      verbose_name="Commissions bancaires")
    autres_ecarts = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                        verbose_name="Autres écarts")

    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   related_name='rapprochements_crees', verbose_name="Créé par")
    valide_par = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='rapprochements_valides', verbose_name="Validé par")
    date_validation = models.DateTimeField(
        null=True, blank=True, verbose_name="Date validation")

    class Meta:
        verbose_name = "Rapprochement bancaire"
        verbose_name_plural = "Rapprochements bancaires"
        ordering = ['-date_fin']
        unique_together = ['compte_bancaire', 'date_debut', 'date_fin']

    def __str__(self):
        return f"{self.reference} - {self.compte_bancaire.banque} ({self.date_debut} au {self.date_fin})"

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import datetime
            prefix = f"RAP{datetime.now().strftime('%Y%m')}"
            last = RapprochementBancaire.objects.filter(
                reference__startswith=prefix).order_by('-id').first()
            if last:
                try:
                    last_num = int(last.reference.replace(prefix, ''))
                    self.reference = f"{prefix}{str(last_num + 1).zfill(4)}"
                except (ValueError, AttributeError):
                    self.reference = f"{prefix}0001"
            else:
                self.reference = f"{prefix}0001"

        # Calculer l'écart
        self.ecart = self.solde_comptable - self.solde_bancaire
        self.solde_rapproche = self.solde_comptable - self.encours_emission + \
            self.encours_encaissement - self.commissions - self.autres_ecarts

        super().save(*args, **kwargs)

    @property
    def est_rapproche(self):
        return abs(self.ecart) < 1


# ============================================================
# 7. TRÉSORERIE JOURNALIÈRE
# ============================================================

class TresorerieJournaliere(models.Model):
    """
    Suivi journalier de la trésorerie
    """
    date = models.DateField(unique=True, verbose_name="Date")
    agence = models.ForeignKey(Agence, on_delete=models.PROTECT, related_name='tresorerie_journaliere',
                               verbose_name="Agence")

    # Soldes
    solde_ouverture = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                          verbose_name="Solde d'ouverture")
    solde_fermeture = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                          verbose_name="Solde de fermeture")

    # Entrées/Sorties
    total_entrees = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                        verbose_name="Total entrées")
    total_sorties = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                        verbose_name="Total sorties")

    # Détails par source
    entrees_ventes = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                         verbose_name="Entrées ventes")
    entrees_reglements = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                             verbose_name="Entrées règlements")
    entrees_autres = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                         verbose_name="Entrées autres")

    sorties_achats = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                         verbose_name="Sorties achats")
    sorties_frais = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                        verbose_name="Sorties frais")
    sorties_salaires = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                           verbose_name="Sorties salaires")
    sorties_autres = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                         verbose_name="Sorties autres")

    # Métriques
    nb_operations = models.IntegerField(
        default=0, verbose_name="Nombre d'opérations")
    nb_entrees = models.IntegerField(
        default=0, verbose_name="Nombre d'entrées")
    nb_sorties = models.IntegerField(
        default=0, verbose_name="Nombre de sorties")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Trésorerie journalière"
        verbose_name_plural = "Trésoreries journalières"
        ordering = ['-date']
        unique_together = ['date', 'agence']

    def __str__(self):
        return f"{self.date} - {self.agence.nom}"

    @property
    def variation(self):
        return self.solde_fermeture - self.solde_ouverture
