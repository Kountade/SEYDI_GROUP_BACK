"""
Serializers pour l'application users
Gestion des utilisateurs, agences et rôles
"""

from rest_framework import serializers
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from .models import Agence, RoleAgence, CustomUser

User = get_user_model()


# ============================================================
# LOGIN SERIALIZER
# ============================================================

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret.pop('password', None)
        return ret

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if email and password:
            user = authenticate(request=self.context.get(
                'request'), email=email, password=password)

            if not user:
                raise serializers.ValidationError(
                    "Impossible de se connecter avec ces identifiants", code='authorization')

            if not user.is_active:
                raise serializers.ValidationError(
                    "Ce compte utilisateur est désactivé", code='authorization')

            attrs['user'] = user
        else:
            raise serializers.ValidationError(
                "Email et mot de passe sont requis", code='authorization')

        return attrs


# ============================================================
# REGISTER SERIALIZER
# ============================================================

class RegisterSerializer(serializers.ModelSerializer):
    role_global = serializers.ChoiceField(
        choices=CustomUser.ROLE_GLOBAL_CHOICES, required=False)
    agence_id = serializers.IntegerField(
        write_only=True, required=False, allow_null=True)
    role_agence = serializers.ChoiceField(
        choices=RoleAgence.ROLE_CHOICES, required=False, allow_null=True)

    class Meta:
        model = User
        fields = ('id', 'email', 'password', 'first_name', 'last_name',
                  'role_global', 'agence_id', 'role_agence', 'phone',
                  'address', 'city', 'employee_id')
        extra_kwargs = {
            'password': {'write_only': True},
            'role_global': {'required': False, 'default': 'autre'},
            'agence_id': {'required': False, 'allow_null': True},
            'role_agence': {'required': False, 'allow_null': True},
        }

    def validate(self, data):
        role_global = data.get('role_global', 'autre')

        if role_global in ['pdg', 'drh']:
            data.pop('agence_id', None)
            data.pop('role_agence', None)
            return data

        if role_global == 'autre':
            agence_id = data.get('agence_id')
            role_agence = data.get('role_agence')

            if not agence_id:
                raise serializers.ValidationError(
                    {'agence_id': 'L\'agence est obligatoire pour cet utilisateur'})

            if not role_agence:
                raise serializers.ValidationError(
                    {'role_agence': 'Le rôle dans l\'agence est obligatoire'})

            try:
                agence = Agence.objects.get(id=agence_id, est_active=True)
            except Agence.DoesNotExist:
                raise serializers.ValidationError(
                    {'agence_id': 'Agence non trouvée ou inactive'})

            # ✅ Utilisation de la méthode get_roles_disponibles() qui inclut maintenant gestionnaire_stock et comptable
            roles_disponibles = [r[0] for r in agence.get_roles_disponibles()]
            if role_agence not in roles_disponibles:
                raise serializers.ValidationError({
                    'role_agence': f'Ce rôle n\'est pas disponible. Rôles disponibles: {", ".join(roles_disponibles)}'
                })

        return data

    def create(self, validated_data):
        agence_id = validated_data.pop('agence_id', None)
        role_agence = validated_data.pop('role_agence', None)

        if 'role_global' not in validated_data:
            validated_data['role_global'] = 'autre'

        user = User.objects.create_user(**validated_data)

        if agence_id and role_agence and user.role_global == 'autre':
            try:
                agence = Agence.objects.get(id=agence_id)
                RoleAgence.objects.create(
                    user=user, agence=agence, role=role_agence, est_actif=True)
                user.agence_principale = agence
                user.save(update_fields=['agence_principale'])
            except Agence.DoesNotExist:
                pass

        return user


# ============================================================
# AGENCE SIMPLE SERIALIZER (pour éviter import circulaire)
# ============================================================

class AgenceSimpleSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(
        source='get_type_agence_display', read_only=True)
    roles_disponibles = serializers.SerializerMethodField()  # ✅ AJOUTÉ

    class Meta:
        model = Agence
        fields = ('id', 'nom', 'code', 'type_agence',
                  'type_display', 'ville', 'est_active', 'roles_disponibles')

    def get_roles_disponibles(self, obj):
        """Retourne les rôles disponibles pour cette agence"""
        return [{'value': r[0], 'label': r[1]} for r in obj.get_roles_disponibles()]


# ============================================================
# USER SERIALIZER (AVEC roles_agence)
# ============================================================

class UserSerializer(serializers.ModelSerializer):
    role_global_display = serializers.CharField(
        source='get_role_global_display', read_only=True)
    agences = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    roles_agence = serializers.SerializerMethodField()

    # ✅ NOUVEAUX CHAMPS pour les rôles spécifiques
    est_chef_agence = serializers.SerializerMethodField()
    est_commercial = serializers.SerializerMethodField()
    est_gestionnaire_stock = serializers.SerializerMethodField()
    est_comptable = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'full_name',
                  'role_global', 'role_global_display', 'agences', 'roles_agence',
                  'is_active', 'est_chef_agence', 'est_commercial',
                  'est_gestionnaire_stock', 'est_comptable')
        read_only_fields = ('id', 'email')

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_agences(self, obj):
        if obj.est_pdg() or obj.est_drh():
            agences = Agence.objects.filter(est_active=True)
            return AgenceSimpleSerializer(agences, many=True).data
        else:
            roles = obj.roles_agence.filter(
                est_actif=True).select_related('agence')
            return AgenceSimpleSerializer([role.agence for role in roles], many=True).data

    def get_roles_agence(self, obj):
        """Retourne les rôles de l'utilisateur dans les agences"""
        roles = obj.roles_agence.filter(
            est_actif=True).select_related('agence')
        return [
            {
                'id': role.id,
                'agence_id': role.agence.id,
                'agence_nom': role.agence.nom,
                'agence_type': role.agence.type_agence,
                'role': role.role,
                'role_display': role.get_role_display(),
                'est_actif': role.est_actif
            }
            for role in roles
        ]

    # ✅ NOUVELLES MÉTHODES pour vérifier les rôles
    def get_est_chef_agence(self, obj):
        """Vérifie si l'utilisateur est chef d'agence"""
        return obj.est_chef_agence()

    def get_est_commercial(self, obj):
        """Vérifie si l'utilisateur est commercial"""
        return obj.est_commercial()

    def get_est_gestionnaire_stock(self, obj):
        """Vérifie si l'utilisateur est gestionnaire de stock"""
        return obj.est_gestionnaire_stock()

    def get_est_comptable(self, obj):
        """Vérifie si l'utilisateur est comptable"""
        return obj.est_comptable()


# ============================================================
# USER DETAIL SERIALIZER
# ============================================================

class UserDetailSerializer(serializers.ModelSerializer):
    role_global_display = serializers.CharField(
        source='get_role_global_display', read_only=True)
    agences = serializers.SerializerMethodField()
    roles_agence = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)
    full_name = serializers.SerializerMethodField()

    # ✅ NOUVEAUX CHAMPS pour les rôles spécifiques
    est_chef_agence = serializers.SerializerMethodField()
    est_commercial = serializers.SerializerMethodField()
    est_gestionnaire_stock = serializers.SerializerMethodField()
    est_comptable = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'full_name', 'username',
                  'role_global', 'role_global_display', 'agences', 'roles_agence',
                  'birthday', 'phone', 'address', 'city', 'country', 'postal_code',
                  'employee_id', 'hire_date', 'contract_type', 'department', 'is_active',
                  'is_staff', 'is_superuser', 'created_at', 'updated_at', 'created_by_email',
                  'agence_principale', 'last_login', 'date_joined',
                  'est_chef_agence', 'est_commercial', 'est_gestionnaire_stock', 'est_comptable')
        read_only_fields = ('id', 'is_staff', 'is_superuser',
                            'created_at', 'updated_at', 'last_login', 'date_joined')

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_agences(self, obj):
        if obj.est_pdg() or obj.est_drh():
            agences = Agence.objects.filter(est_active=True)
            return AgenceSerializer(agences, many=True, context=self.context).data
        else:
            agences = obj.get_agences()
            return AgenceSerializer(agences, many=True, context=self.context).data

    def get_roles_agence(self, obj):
        """Retourne les rôles détaillés par agence"""
        if obj.est_pdg() or obj.est_drh():
            return []
        roles = obj.roles_agence.filter(
            est_actif=True).select_related('agence')
        return [
            {
                'id': role.id,
                'agence_id': role.agence.id,
                'agence_nom': role.agence.nom,
                'agence_type': role.agence.type_agence,
                'role': role.role,
                'role_display': role.get_role_display(),
                'est_actif': role.est_actif,
                'date_attribution': role.date_attribution
            }
            for role in roles
        ]

    # ✅ NOUVELLES MÉTHODES pour vérifier les rôles
    def get_est_chef_agence(self, obj):
        """Vérifie si l'utilisateur est chef d'agence"""
        return obj.est_chef_agence()

    def get_est_commercial(self, obj):
        """Vérifie si l'utilisateur est commercial"""
        return obj.est_commercial()

    def get_est_gestionnaire_stock(self, obj):
        """Vérifie si l'utilisateur est gestionnaire de stock"""
        return obj.est_gestionnaire_stock()

    def get_est_comptable(self, obj):
        """Vérifie si l'utilisateur est comptable"""
        return obj.est_comptable()


# ============================================================
# AGENCE SERIALIZER
# ============================================================

class AgenceSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(
        source='get_type_agence_display', read_only=True)
    roles_disponibles = serializers.SerializerMethodField()
    nombre_utilisateurs = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)

    # ✅ NOUVEAU champ pour les statistiques par rôle
    nombre_chefs_agence = serializers.SerializerMethodField()
    nombre_commerciaux = serializers.SerializerMethodField()
    nombre_gestionnaires_stock = serializers.SerializerMethodField()
    nombre_comptables = serializers.SerializerMethodField()

    class Meta:
        model = Agence
        fields = ('id', 'nom', 'code', 'type_agence', 'type_display', 'adresse',
                  'telephone', 'email', 'ville', 'code_postal', 'pays', 'est_active',
                  'roles_disponibles', 'nombre_utilisateurs', 'date_creation',
                  'date_modification', 'created_by_email',
                  'nombre_chefs_agence', 'nombre_commerciaux',
                  'nombre_gestionnaires_stock', 'nombre_comptables')
        read_only_fields = ('id', 'code', 'date_creation', 'date_modification')

    def get_roles_disponibles(self, obj):
        """Retourne les rôles disponibles pour cette agence"""
        return [{'value': r[0], 'label': r[1]} for r in obj.get_roles_disponibles()]

    def get_nombre_utilisateurs(self, obj):
        return obj.roles.filter(est_actif=True).count()

    # ✅ NOUVELLES MÉTHODES pour les statistiques par rôle
    def get_nombre_chefs_agence(self, obj):
        return obj.roles.filter(role='chef_agence', est_actif=True).count()

    def get_nombre_commerciaux(self, obj):
        return obj.roles.filter(role='commercial', est_actif=True).count()

    def get_nombre_gestionnaires_stock(self, obj):
        return obj.roles.filter(role='gestionnaire_stock', est_actif=True).count()

    def get_nombre_comptables(self, obj):
        return obj.roles.filter(role='comptable', est_actif=True).count()


class AgenceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agence
        fields = ('id', 'nom', 'type_agence', 'adresse', 'telephone',
                  'email', 'ville', 'code_postal', 'pays')

    def validate_nom(self, value):
        if Agence.objects.filter(nom__iexact=value).exists():
            raise serializers.ValidationError(
                "Une agence avec ce nom existe déjà")
        return value


# ============================================================
# ROLE AGENCE SERIALIZER
# ============================================================

class RoleAgenceSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    agence_type = serializers.CharField(
        source='agence.type_agence', read_only=True)
    role_display = serializers.CharField(
        source='get_role_display', read_only=True)

    # ✅ NOUVEAU champ pour vérifier si le rôle est disponible
    role_disponible = serializers.SerializerMethodField()

    class Meta:
        model = RoleAgence
        fields = ('id', 'user', 'user_email', 'user_name', 'agence', 'agence_nom',
                  'agence_type', 'role', 'role_display', 'est_actif',
                  'date_attribution', 'role_disponible')
        read_only_fields = ('id', 'date_attribution')

    def get_user_name(self, obj):
        return obj.user.get_full_name()

    def get_role_disponible(self, obj):
        """Vérifie si le rôle est toujours disponible pour cette agence"""
        roles_disponibles = [r[0] for r in obj.agence.get_roles_disponibles()]
        return obj.role in roles_disponibles

    def validate(self, data):
        user = data.get('user')
        agence = data.get('agence')
        role = data.get('role')

        if user and agence and role:
            # Vérifier si l'utilisateur a déjà ce rôle dans cette agence
            if RoleAgence.objects.filter(user=user, agence=agence, role=role, est_actif=True).exists():
                raise serializers.ValidationError(
                    f"L'utilisateur a déjà le rôle {role} dans cette agence")

            # ✅ Vérifier que le rôle est disponible (inclut maintenant gestionnaire_stock et comptable)
            roles_disponibles = [r[0] for r in agence.get_roles_disponibles()]
            if role not in roles_disponibles:
                raise serializers.ValidationError(
                    f"Le rôle '{role}' n'est pas disponible pour cette agence. "
                    f"Rôles disponibles: {', '.join(roles_disponibles)}"
                )

            # Vérifier que l'utilisateur n'est pas PDG ou DRH
            if user.est_pdg() or user.est_drh():
                raise serializers.ValidationError(
                    "Le PDG et le DRH n'ont pas de rôles spécifiques par agence")

        return data


class AssignRoleSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    agence_id = serializers.IntegerField()
    role = serializers.ChoiceField(choices=RoleAgence.ROLE_CHOICES)

    def validate(self, data):
        try:
            user = User.objects.get(id=data['user_id'], is_active=True)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {'user_id': 'Utilisateur non trouvé'})

        try:
            agence = Agence.objects.get(id=data['agence_id'], est_active=True)
        except Agence.DoesNotExist:
            raise serializers.ValidationError(
                {'agence_id': 'Agence non trouvée ou inactive'})

        # ✅ Vérification des rôles disponibles (inclut maintenant gestionnaire_stock et comptable)
        roles_disponibles = [r[0] for r in agence.get_roles_disponibles()]
        if data['role'] not in roles_disponibles:
            raise serializers.ValidationError(
                {'role': f'Rôle non disponible. Rôles disponibles: {", ".join(roles_disponibles)}'})

        # Vérification que l'utilisateur n'est pas PDG ou DRH
        if user.est_pdg() or user.est_drh():
            raise serializers.ValidationError(
                "Le PDG et le DRH n'ont pas de rôles d'agence")

        # Vérification des doublons
        if RoleAgence.objects.filter(user=user, agence=agence, role=data['role'], est_actif=True).exists():
            raise serializers.ValidationError(
                {'role': f'L\'utilisateur a déjà ce rôle dans cette agence'})

        data['user'] = user
        data['agence'] = agence
        return data

    def create(self, validated_data):
        return RoleAgence.objects.create(
            user=validated_data['user'],
            agence=validated_data['agence'],
            role=validated_data['role'],
            est_actif=True
        )


# ============================================================
# ✅ NOUVEAU SERIALIZER : STATISTIQUES DES RÔLES
# ============================================================

class RoleStatisticsSerializer(serializers.Serializer):
    """
    Serializer pour les statistiques des rôles par agence
    """
    agence_id = serializers.IntegerField()
    agence_nom = serializers.CharField()
    total_utilisateurs = serializers.IntegerField()
    chefs_agence = serializers.IntegerField()
    commerciaux = serializers.IntegerField()
    gestionnaires_stock = serializers.IntegerField()
    comptables = serializers.IntegerField()
    roles_disponibles = serializers.ListField(child=serializers.DictField())


# ============================================================
# ✅ NOUVEAU SERIALIZER : RÔLES DÉTAILLÉS D'UN UTILISATEUR
# ============================================================

class UserRolesDetailSerializer(serializers.Serializer):
    """
    Serializer pour afficher tous les rôles d'un utilisateur avec détails
    """
    user_id = serializers.IntegerField()
    user_email = serializers.EmailField()
    user_full_name = serializers.CharField()
    role_global = serializers.CharField()
    role_global_display = serializers.CharField()
    roles_par_agence = serializers.ListField(child=serializers.DictField())
    est_pdg = serializers.BooleanField()
    est_drh = serializers.BooleanField()
    est_chef_agence = serializers.BooleanField()
    est_commercial = serializers.BooleanField()
    est_gestionnaire_stock = serializers.BooleanField()
    est_comptable = serializers.BooleanField()


# ============================================================
# ✅ NOUVEAU SERIALIZER : MISE À JOUR DES RÔLES
# ============================================================

class UpdateUserRolesSerializer(serializers.Serializer):
    """
    Serializer pour mettre à jour les rôles d'un utilisateur
    """
    user_id = serializers.IntegerField()
    roles = serializers.ListField(
        child=serializers.DictField(
            child=serializers.CharField()
        ),
        required=False,
        help_text="Liste des rôles à assigner: [{'agence_id': 1, 'role': 'chef_agence'}]"
    )

    def validate_roles(self, value):
        for item in value:
            if 'agence_id' not in item or 'role' not in item:
                raise serializers.ValidationError(
                    "Chaque rôle doit avoir 'agence_id' et 'role'"
                )

            try:
                agence = Agence.objects.get(
                    id=item['agence_id'], est_active=True)
            except Agence.DoesNotExist:
                raise serializers.ValidationError(
                    f"Agence {item['agence_id']} non trouvée ou inactive"
                )

            roles_disponibles = [r[0] for r in agence.get_roles_disponibles()]
            if item['role'] not in roles_disponibles:
                raise serializers.ValidationError(
                    f"Rôle '{item['role']}' non disponible pour l'agence {agence.nom}. "
                    f"Rôles disponibles: {', '.join(roles_disponibles)}"
                )

        return value
