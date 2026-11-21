from django.db import models

"""
Models pour l'application users
Gestion des utilisateurs, agences et rôles
"""

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.base_user import BaseUserManager
from django.db import models
from django.core.exceptions import ValidationError
from django.conf import settings  # ✅ AJOUTÉ : Nécessaire pour lire FRONTEND_URL
from django_rest_passwordreset.signals import reset_password_token_created
from django.dispatch import receiver
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.template.loader import render_to_string


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('L\'email est requis')

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role_global', 'pdg')
        extra_fields.setdefault('is_active', True)
        return self.create_user(email, password, **extra_fields)


class Agence(models.Model):
    TYPE_AGENCE_CHOICES = (
        ('principale', 'Agence Principale'),
        ('secondaire', 'Agence Secondaire'),
    )

    nom = models.CharField(max_length=200, verbose_name="Nom de l'agence")
    code = models.CharField(max_length=20, unique=True,
                            verbose_name="Code agence", blank=True)
    type_agence = models.CharField(
        max_length=20, choices=TYPE_AGENCE_CHOICES, default='principale', verbose_name="Type d'agence")
    adresse = models.TextField(verbose_name="Adresse")
    telephone = models.CharField(max_length=20, verbose_name="Téléphone")
    email = models.EmailField(verbose_name="Email")
    ville = models.CharField(max_length=100, verbose_name="Ville")
    code_postal = models.CharField(max_length=20, verbose_name="Code postal")
    pays = models.CharField(
        max_length=100, default='France', verbose_name="Pays")

    est_active = models.BooleanField(
        default=True, verbose_name="Agence active")
    date_creation = models.DateTimeField(
        auto_now_add=True, verbose_name="Date de création")
    date_modification = models.DateTimeField(
        auto_now=True, verbose_name="Date de modification")
    created_by = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='agences_crees', verbose_name="Créée par")

    class Meta:
        verbose_name = "Agence"
        verbose_name_plural = "Agences"
        ordering = ['-type_agence', 'nom']
        permissions = [
            ("can_create_agence", "Peut créer une agence"),
            ("can_edit_agence", "Peut modifier une agence"),
            ("can_delete_agence", "Peut supprimer une agence"),
            ("can_view_all_agences", "Peut voir toutes les agences"),
        ]

    def __str__(self):
        return f"{self.nom} ({self.get_type_agence_display()})"

    def get_roles_disponibles(self):
        return [
            ('chef_agence', 'Chef d\'agence'),
            ('gestionnaire_stock', 'Gestionnaire de stock'),
            ('commercial', 'Commercial'),
            ('comptable', 'Comptable'),
        ]

    def get_nombre_roles(self):
        return len(self.get_roles_disponibles())

    def save(self, *args, **kwargs):
        if not self.code:
            prefix = 'P' if self.type_agence == 'principale' else 'S'
            count = Agence.objects.filter(
                type_agence=self.type_agence).count() + 1
            self.code = f"{prefix}{self.nom[:3].upper()}{str(count).zfill(3)}"
        super().save(*args, **kwargs)


class RoleAgence(models.Model):
    ROLE_CHOICES = (
        ('chef_agence', 'Chef d\'agence'),
        ('gestionnaire_stock', 'Gestionnaire de stock'),
        ('commercial', 'Commercial'),
        ('comptable', 'Comptable'),
    )

    user = models.ForeignKey('CustomUser', on_delete=models.CASCADE,
                             related_name='roles_agence', verbose_name="Utilisateur")
    agence = models.ForeignKey(
        Agence, on_delete=models.CASCADE, related_name='roles', verbose_name="Agence")
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, verbose_name="Rôle")
    date_attribution = models.DateTimeField(
        auto_now_add=True, verbose_name="Date d'attribution")
    est_actif = models.BooleanField(default=True, verbose_name="Rôle actif")

    class Meta:
        verbose_name = "Rôle par agence"
        verbose_name_plural = "Rôles par agence"
        unique_together = ['user', 'agence', 'role']
        ordering = ['agence', 'user']

    def clean(self):
        roles_disponibles = [r[0] for r in self.agence.get_roles_disponibles()]
        if self.role not in roles_disponibles:
            raise ValidationError(
                f"Le rôle '{self.get_role_display()}' n'est pas disponible pour cette agence."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email} - {self.agence.nom} : {self.get_role_display()}"


class CustomUser(AbstractUser):
    ROLE_GLOBAL_CHOICES = (
        ('pdg', 'PDG - Accès total'),
        ('drh', 'DRH - Gestion RH toutes agences'),
        ('autre', 'Autre'),
    )

    email = models.EmailField(
        max_length=200, unique=True, verbose_name="Email")
    birthday = models.DateField(
        null=True, blank=True, verbose_name="Date de naissance")
    username = models.CharField(
        max_length=200, null=True, blank=True, verbose_name="Nom d'utilisateur")
    role_global = models.CharField(
        max_length=20, choices=ROLE_GLOBAL_CHOICES, default='autre', verbose_name="Rôle global")
    department = models.CharField(
        max_length=20, null=True, blank=True, verbose_name="Département")
    phone = models.CharField(max_length=20, null=True,
                             blank=True, verbose_name="Téléphone")
    address = models.TextField(null=True, blank=True, verbose_name="Adresse")
    city = models.CharField(max_length=100, null=True,
                            blank=True, verbose_name="Ville")
    country = models.CharField(
        max_length=100, null=True, blank=True, default='Sénégal', verbose_name="Pays")
    postal_code = models.CharField(
        max_length=20, null=True, blank=True, verbose_name="Code postal")
    employee_id = models.CharField(
        max_length=50, unique=True, null=True, blank=True, verbose_name="Matricule")
    hire_date = models.DateField(
        null=True, blank=True, verbose_name="Date d'embauche")
    contract_type = models.CharField(
        max_length=50, null=True, blank=True, verbose_name="Type de contrat")
    salary = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Salaire")
    agence_principale = models.ForeignKey(Agence, on_delete=models.SET_NULL, null=True,
                                          blank=True, related_name='utilisateurs_principaux', verbose_name="Agence principale")
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    last_login_ip = models.GenericIPAddressField(
        null=True, blank=True, verbose_name="Dernière IP")
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Date de création")
    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Date de modification")
    created_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='created_users', verbose_name="Créé par")
    profile_picture = models.ImageField(
        upload_to='profile_pictures/', null=True, blank=True, verbose_name="Photo de profil")

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        permissions = [
            ("can_view_reports", "Peut voir les rapports"),
            ("can_manage_users", "Peut gérer les utilisateurs"),
            ("can_validate_orders", "Peut valider les commandes"),
            ("can_manage_inventory", "Peut gérer l'inventaire"),
            ("can_manage_rh", "Peut gérer les ressources humaines"),
            ("can_view_all_agences", "Peut voir toutes les agences"),
            ("can_manage_accounting", "Peut gérer la comptabilité"),
        ]

    def __str__(self):
        return f"{self.email} ({self.get_role_global_display()})"

    def get_full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.email

    def get_full_name_display(self):
        return self.get_full_name()

    def est_pdg(self):
        return self.role_global == 'pdg'

    def est_drh(self):
        return self.role_global == 'drh'

    def est_chef_agence(self, agence_id=None):
        if agence_id:
            return self.a_role_dans_agence(agence_id, 'chef_agence')
        return self.roles_agence.filter(role='chef_agence', est_actif=True).exists()

    def est_commercial(self, agence_id=None):
        if agence_id:
            return self.a_role_dans_agence(agence_id, 'commercial')
        return self.roles_agence.filter(role='commercial', est_actif=True).exists()

    def est_gestionnaire_stock(self, agence_id=None):
        if agence_id:
            return self.a_role_dans_agence(agence_id, 'gestionnaire_stock')
        return self.roles_agence.filter(role='gestionnaire_stock', est_actif=True).exists()

    def est_comptable(self, agence_id=None):
        if agence_id:
            return self.a_role_dans_agence(agence_id, 'comptable')
        return self.roles_agence.filter(role='comptable', est_actif=True).exists()

    def est_vendeur(self, agence_id=None):
        return self.est_commercial(agence_id)

    def a_role_dans_agence(self, agence_id, role):
        if not agence_id:
            return self.roles_agence.filter(role=role, est_actif=True).exists()
        return self.roles_agence.filter(agence_id=agence_id, role=role, est_actif=True).exists()

    def get_role_dans_agence(self, agence_id):
        try:
            role_agence = self.roles_agence.get(
                agence_id=agence_id, est_actif=True)
            return role_agence.role
        except RoleAgence.DoesNotExist:
            return None

    def get_role_display_dans_agence(self, agence_id):
        role = self.get_role_dans_agence(agence_id)
        if role:
            return dict(RoleAgence.ROLE_CHOICES).get(role, role)
        return "Aucun rôle"

    def get_agences(self):
        if self.est_pdg() or self.est_drh():
            return Agence.objects.filter(est_active=True)
        agences_ids = self.roles_agence.filter(
            est_actif=True).values_list('agence_id', flat=True)
        return Agence.objects.filter(id__in=agences_ids, est_active=True)

    def get_agences_par_type(self):
        agences = self.get_agences()
        return {
            'principales': agences.filter(type_agence='principale'),
            'secondaires': agences.filter(type_agence='secondaire'),
        }

    def get_agence_principale(self):
        if self.agence_principale:
            return self.agence_principale
        premiere_agence = self.roles_agence.filter(est_actif=True).first()
        if premiere_agence:
            return premiere_agence.agence
        return None

    def peut_acceder_agence(self, agence_id):
        if self.est_pdg() or self.est_drh():
            return True
        if not agence_id:
            return False
        return self.roles_agence.filter(agence_id=agence_id, est_actif=True).exists()

    def get_roles_disponibles_agence(self, agence_id):
        try:
            agence = Agence.objects.get(id=agence_id)
            return agence.get_roles_disponibles()
        except Agence.DoesNotExist:
            return []

    def peut_assigner_role(self, agence_id, role):
        try:
            agence = Agence.objects.get(id=agence_id)
            roles_disponibles = [r[0] for r in agence.get_roles_disponibles()]
            return role in roles_disponibles
        except Agence.DoesNotExist:
            return False

    def get_all_roles(self):
        roles = self.roles_agence.filter(
            est_actif=True).select_related('agence')
        return [
            {
                'agence_id': role.agence.id,
                'agence_nom': role.agence.nom,
                'agence_type': role.agence.type_agence,
                'role': role.role,
                'role_display': role.get_role_display()
            }
            for role in roles
        ]

    def has_perm(self, perm, obj=None):
        if self.est_pdg():
            return True
        return super().has_perm(perm, obj)


@receiver(reset_password_token_created)
def password_reset_token_created(reset_password_token, *args, **kwargs):
    """
    ✅ CORRIGÉ : Utilise le bon lien (Render) et le bon expéditeur Gmail
    """
    sitelink = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173/')
    if not sitelink.endswith('/'):
        sitelink += '/'

    token = str(reset_password_token.key)
    full_link = f"{sitelink}password-reset/{token}"

    context = {
        'full_link': full_link,
        'email_address': reset_password_token.user.email
    }

    html_message = render_to_string("backend/email.html", context=context)
    plain_message = strip_tags(html_message)

    try:
        msg = EmailMultiAlternatives(
            subject=f"Réinitialisation de mot de passe pour {reset_password_token.user.email}",
            body=plain_message,
            from_email=settings.EMAIL_HOST_USER,  # ✅ Utilise ton email Gmail
            to=[reset_password_token.user.email]
        )
        msg.attach_alternative(html_message, "text/html")
        msg.send(fail_silently=False)
    except Exception as e:
        print(f"❌ Erreur envoi email : {e}")
