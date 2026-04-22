from django.db import models

# Create your models here.
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from datetime import date, timedelta, datetime
from decimal import Decimal

User = get_user_model()

# Import Agence
try:
    from users.models import Agence
except ImportError:
    import sys
    import os
    sys.path.append(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    from users.models import Agence


# ============================================================
# MODÈLES DE BASE
# ============================================================

class Departement(models.Model):
    """Département de l'entreprise"""
    nom = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    agence = models.ForeignKey(
        Agence, on_delete=models.CASCADE, related_name='departements_drh')
    est_actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Département"
        verbose_name_plural = "Départements"
        ordering = ['agence', 'nom']

    def __str__(self):
        return f"{self.nom} ({self.agence.nom})"


class Poste(models.Model):
    """Poste de travail"""
    NIVEAU_CHOICES = [
        ('junior', 'Junior'),
        ('confirme', 'Confirmé'),
        ('senior', 'Senior'),
        ('expert', 'Expert'),
        ('manager', 'Manager'),
        ('directeur', 'Directeur'),
    ]

    nom = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    departement = models.ForeignKey(
        Departement, on_delete=models.CASCADE, related_name='postes')
    description = models.TextField(blank=True)
    niveau = models.CharField(
        max_length=20, choices=NIVEAU_CHOICES, default='junior')
    salaire_min = models.DecimalField(max_digits=10, decimal_places=2)
    salaire_max = models.DecimalField(max_digits=10, decimal_places=2)
    competences_requises = models.TextField(blank=True)
    est_actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Poste"
        verbose_name_plural = "Postes"
        ordering = ['departement', 'niveau', 'nom']

    def __str__(self):
        return f"{self.nom} - {self.get_niveau_display()}"


# ============================================================
# MODÈLE EMPLOYÉ
# ============================================================

class Employe(models.Model):
    """Employé de l'entreprise"""
    SEXE_CHOICES = [
        ('M', 'Masculin'),
        ('F', 'Féminin'),
    ]

    SITUATION_FAMILIALE_CHOICES = [
        ('celibataire', 'Célibataire'),
        ('marie', 'Marié(e)'),
        ('divorce', 'Divorcé(e)'),
        ('veuf', 'Veuf/Veuve'),
    ]

    # Liaison avec l'utilisateur (optionnelle)
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employe_drh'
    )

    # Informations personnelles
    matricule = models.CharField(max_length=50, unique=True)
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    telephone = models.CharField(max_length=20, blank=True)
    sexe = models.CharField(max_length=1, choices=SEXE_CHOICES)
    date_naissance = models.DateField()
    lieu_naissance = models.CharField(max_length=100)
    nationalite = models.CharField(max_length=50, default='Sénégalaise')
    numero_cni = models.CharField(max_length=50, blank=True)

    # Situation familiale
    situation_familiale = models.CharField(
        max_length=20,
        choices=SITUATION_FAMILIALE_CHOICES,
        default='celibataire'
    )
    nombre_enfants = models.PositiveIntegerField(default=0)
    telephone_urgence = models.CharField(max_length=20, blank=True)
    contact_urgence = models.CharField(max_length=100, blank=True)

    # Adresse
    adresse = models.TextField(blank=True)
    ville = models.CharField(max_length=100, blank=True)
    code_postal = models.CharField(max_length=20, blank=True)
    pays = models.CharField(max_length=50, default='Sénégal')

    # Informations professionnelles
    poste = models.ForeignKey(
        Poste, on_delete=models.SET_NULL, null=True, blank=True, related_name='employes')
    departement = models.ForeignKey(
        Departement, on_delete=models.SET_NULL, null=True, blank=True, related_name='employes')
    agence = models.ForeignKey(Agence, on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='employes_drh')

    # Coordonnées bancaires
    banque = models.CharField(max_length=100, blank=True)
    rib = models.CharField(max_length=50, blank=True)

    # Statut
    est_actif = models.BooleanField(default=True)
    date_embauche = models.DateField()
    date_depart = models.DateField(null=True, blank=True)
    motif_depart = models.TextField(blank=True)

    # Photo
    photo = models.ImageField(
        upload_to='employes/photos/', null=True, blank=True)

    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employes_crees_drh'
    )

    class Meta:
        verbose_name = "Employé"
        verbose_name_plural = "Employés"
        ordering = ['nom', 'prenom']

    def __str__(self):
        return f"{self.nom} {self.prenom} - {self.matricule}"

    @property
    def nom_complet(self):
        return f"{self.nom} {self.prenom}"

    @property
    def age(self):
        today = date.today()
        return today.year - self.date_naissance.year - (
            (today.month, today.day) < (
                self.date_naissance.month, self.date_naissance.day)
        )

    @property
    def anciennete(self):
        today = date.today()
        years = today.year - self.date_embauche.year
        months = today.month - self.date_embauche.month
        if months < 0:
            years -= 1
            months += 12
        return {'annees': years, 'mois': months}

    def save(self, *args, **kwargs):
        # Génération automatique du matricule si non fourni
        if not self.matricule:
            year = datetime.now().year
            count = Employe.objects.filter(created_at__year=year).count() + 1
            self.matricule = f"EMP{year}{str(count).zfill(4)}"
        super().save(*args, **kwargs)


# ============================================================
# MODÈLES DE CONTRAT
# ============================================================

class Contrat(models.Model):
    """Contrat de travail"""
    TYPE_CONTRAT_CHOICES = [
        ('cdi', 'CDI'),
        ('cdd', 'CDD'),
        ('stage', 'Stage'),
        ('interim', 'Intérim'),
        ('prestation', 'Prestation'),
    ]

    STATUT_CHOICES = [
        ('brouillon', 'Brouillon'),
        ('en_attente', 'En attente de signature'),
        ('signe', 'Signé'),
        ('en_cours', 'En cours'),
        ('termine', 'Terminé'),
        ('resilie', 'Résilié'),
    ]

    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name='contrats')
    type_contrat = models.CharField(
        max_length=20, choices=TYPE_CONTRAT_CHOICES)
    statut = models.CharField(
        max_length=20, choices=STATUT_CHOICES, default='brouillon')
    reference = models.CharField(max_length=50, unique=True)
    date_debut = models.DateField()
    date_fin = models.DateField(null=True, blank=True)
    date_signature = models.DateField(null=True, blank=True)
    salaire_brut = models.DecimalField(max_digits=10, decimal_places=2)
    lieu_travail = models.CharField(max_length=200, blank=True)
    document = models.FileField(upload_to='contrats/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Contrat"
        verbose_name_plural = "Contrats"
        ordering = ['-date_debut']

    def __str__(self):
        return f"{self.reference} - {self.employe.nom_complet}"

    def save(self, *args, **kwargs):
        if not self.reference:
            year = datetime.now().year
            count = Contrat.objects.filter(created_at__year=year).count() + 1
            self.reference = f"CTR-{year}-{str(count).zfill(4)}"
        super().save(*args, **kwargs)


# ============================================================
# MODÈLES DE CONGÉS
# ============================================================

class TypeConge(models.Model):
    """Type de congé"""
    nom = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    nombre_jours_par_an = models.PositiveIntegerField(default=25)
    est_paye = models.BooleanField(default=True)
    est_actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Type de congé"
        verbose_name_plural = "Types de congés"
        ordering = ['nom']

    def __str__(self):
        return self.nom


class DemandeConge(models.Model):
    """Demande de congé"""
    STATUT_CHOICES = [
        ('brouillon', 'Brouillon'),
        ('en_attente', 'En attente'),
        ('validee', 'Validée'),
        ('refusee', 'Refusée'),
        ('annulee', 'Annulée'),
    ]

    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name='demandes_conges')
    type_conge = models.ForeignKey(
        TypeConge, on_delete=models.CASCADE, related_name='demandes')
    date_debut = models.DateField()
    date_fin = models.DateField()
    nombre_jours = models.DecimalField(max_digits=5, decimal_places=1)
    motif = models.TextField()
    statut = models.CharField(
        max_length=20, choices=STATUT_CHOICES, default='brouillon')
    date_demande = models.DateTimeField(auto_now_add=True)
    date_validation = models.DateTimeField(null=True, blank=True)
    valide_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True)
    motif_refus = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Demande de congé"
        verbose_name_plural = "Demandes de congés"
        ordering = ['-date_demande']

    def __str__(self):
        return f"{self.employe.nom_complet} - {self.type_conge.nom} - {self.date_debut}"

    def clean(self):
        if self.date_fin < self.date_debut:
            raise ValidationError(
                "La date de fin doit être postérieure à la date de début")

    def save(self, *args, **kwargs):
        delta = self.date_fin - self.date_debut
        self.nombre_jours = delta.days + 1
        super().save(*args, **kwargs)


# ============================================================
# MODÈLES DE PRÉSENCE
# ============================================================

class Pointage(models.Model):
    """Pointage des employés"""
    TYPE_POINTAGE_CHOICES = [
        ('entree', 'Entrée'),
        ('sortie', 'Sortie'),
    ]

    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name='pointages')
    type_pointage = models.CharField(
        max_length=20, choices=TYPE_POINTAGE_CHOICES)
    date_heure = models.DateTimeField(auto_now_add=True)
    commentaire = models.TextField(blank=True)
    est_valide = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Pointage"
        verbose_name_plural = "Pointages"
        ordering = ['-date_heure']

    def __str__(self):
        return f"{self.employe.nom_complet} - {self.get_type_pointage_display()} - {self.date_heure}"


class Absence(models.Model):
    """Absence d'un employé"""
    TYPE_ABSENCE_CHOICES = [
        ('maladie', 'Maladie'),
        ('accident_travail', 'Accident de travail'),
        ('maternite', 'Congé maternité'),
        ('non_justifiee', 'Absence non justifiée'),
        ('formation', 'Formation'),
        ('mission', 'Mission'),
        ('autre', 'Autre'),
    ]

    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name='absences')
    type_absence = models.CharField(
        max_length=20, choices=TYPE_ABSENCE_CHOICES)
    date_debut = models.DateField()
    date_fin = models.DateField()
    justifiee = models.BooleanField(default=False)
    justificatif = models.FileField(
        upload_to='absences/', null=True, blank=True)
    commentaire = models.TextField(blank=True)
    est_validee = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Absence"
        verbose_name_plural = "Absences"
        ordering = ['-date_debut']

    def __str__(self):
        return f"{self.employe.nom_complet} - {self.get_type_absence_display()} - {self.date_debut}"

    @property
    def duree_jours(self):
        delta = self.date_fin - self.date_debut
        return delta.days + 1


# ============================================================
# MODÈLES DE FORMATION
# ============================================================

class Formation(models.Model):
    """Formation"""
    STATUT_CHOICES = [
        ('planifiee', 'Planifiée'),
        ('en_cours', 'En cours'),
        ('terminee', 'Terminée'),
        ('annulee', 'Annulée'),
    ]

    titre = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    date_debut = models.DateField()
    date_fin = models.DateField()
    duree_heures = models.PositiveIntegerField(default=0)
    formateur = models.CharField(max_length=100, blank=True)
    organisme = models.CharField(max_length=100, blank=True)
    lieu = models.CharField(max_length=200, blank=True)
    cout = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    statut = models.CharField(
        max_length=20, choices=STATUT_CHOICES, default='planifiee')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Formation"
        verbose_name_plural = "Formations"
        ordering = ['-date_debut']

    def __str__(self):
        return f"{self.titre} - {self.date_debut}"


class ParticipationFormation(models.Model):
    """Participation à une formation"""
    RESULTAT_CHOICES = [
        ('inscrit', 'Inscrit'),
        ('present', 'Présent'),
        ('absent', 'Absent'),
        ('reussi', 'Réussi'),
        ('echoue', 'Échoué'),
    ]

    employe = models.ForeignKey(Employe, on_delete=models.CASCADE)
    formation = models.ForeignKey(Formation, on_delete=models.CASCADE)
    date_inscription = models.DateTimeField(auto_now_add=True)
    resultat = models.CharField(
        max_length=20, choices=RESULTAT_CHOICES, default='inscrit')
    note = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True)
    certificat = models.FileField(
        upload_to='formations/certificats/', null=True, blank=True)
    commentaire = models.TextField(blank=True)

    class Meta:
        verbose_name = "Participation à une formation"
        verbose_name_plural = "Participations aux formations"
        unique_together = ['employe', 'formation']

    def __str__(self):
        return f"{self.employe.nom_complet} - {self.formation.titre}"
