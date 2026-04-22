from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    Departement, Poste, Employe, Contrat,
    TypeConge, DemandeConge, Pointage
)
from users.models import Agence

User = get_user_model()


# ============================================================
# SERIALIZERS DE BASE
# ============================================================

class AgenceSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agence
        fields = ['id', 'nom', 'code', 'type_agence', 'ville']


class DepartementSerializer(serializers.ModelSerializer):
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)

    class Meta:
        model = Departement
        fields = ['id', 'nom', 'code', 'agence',
                  'agence_nom', 'est_actif', 'date_creation']
        read_only_fields = ['id', 'date_creation']


class PosteSerializer(serializers.ModelSerializer):
    departement_nom = serializers.CharField(
        source='departement.nom', read_only=True)

    class Meta:
        model = Poste
        fields = ['id', 'nom', 'code', 'departement', 'departement_nom',
                  'niveau', 'salaire_min', 'salaire_max', 'est_actif']
        read_only_fields = ['id']


# ============================================================
# SERIALIZERS EMPLOYÉ
# ============================================================

class EmployeListSerializer(serializers.ModelSerializer):
    """Serializer simplifié pour la liste"""
    nom_complet = serializers.SerializerMethodField()
    poste_nom = serializers.CharField(
        source='poste.nom', read_only=True, default='')
    departement_nom = serializers.CharField(
        source='departement.nom', read_only=True, default='')
    agence_nom = serializers.CharField(
        source='agence.nom', read_only=True, default='')
    age = serializers.IntegerField(read_only=True)

    class Meta:
        model = Employe
        fields = [
            'id', 'matricule', 'nom', 'prenom', 'nom_complet',
            'email', 'telephone', 'sexe', 'date_naissance',
            'poste', 'poste_nom', 'departement', 'departement_nom',
            'agence', 'agence_nom', 'date_embauche', 'est_actif', 'photo', 'age'
        ]

    def get_nom_complet(self, obj):
        return f"{obj.nom} {obj.prenom}".strip()


class EmployeSerializer(serializers.ModelSerializer):
    """Serializer complet pour Employe"""
    user_email = serializers.CharField(
        source='user.email', read_only=True, default='')
    poste_nom = serializers.CharField(
        source='poste.nom', read_only=True, default='')
    departement_nom = serializers.CharField(
        source='departement.nom', read_only=True, default='')
    agence_nom = serializers.CharField(
        source='agence.nom', read_only=True, default='')
    nom_complet = serializers.SerializerMethodField()
    age = serializers.IntegerField(read_only=True)

    class Meta:
        model = Employe
        fields = [
            'id', 'user', 'user_email', 'matricule', 'nom', 'prenom',
            'email', 'telephone', 'sexe', 'date_naissance', 'lieu_naissance',
            'nationalite', 'numero_cni', 'situation_familiale', 'nombre_enfants',
            'telephone_urgence', 'contact_urgence', 'adresse', 'ville',
            'code_postal', 'pays', 'poste', 'poste_nom', 'departement',
            'departement_nom', 'agence', 'agence_nom', 'banque', 'rib',
            'est_actif', 'date_embauche', 'date_depart', 'photo',
            'nom_complet', 'age', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'matricule', 'created_at', 'updated_at']

    def get_nom_complet(self, obj):
        return f"{obj.nom} {obj.prenom}".strip()


class EmployeCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'un employé"""

    class Meta:
        model = Employe
        fields = [
            'user', 'nom', 'prenom', 'email', 'telephone', 'sexe',
            'date_naissance', 'lieu_naissance', 'nationalite', 'numero_cni',
            'situation_familiale', 'nombre_enfants', 'telephone_urgence',
            'contact_urgence', 'adresse', 'ville', 'code_postal', 'pays',
            'poste', 'departement', 'agence', 'banque', 'rib',
            'date_embauche', 'photo', 'est_actif'
        ]


# ============================================================
# SERIALIZERS CONTRAT
# ============================================================

class ContratSerializer(serializers.ModelSerializer):
    employe_nom = serializers.SerializerMethodField()

    class Meta:
        model = Contrat
        fields = [
            'id', 'employe', 'employe_nom', 'type_contrat', 'statut',
            'reference', 'date_debut', 'date_fin', 'salaire_brut', 'created_at'
        ]
        read_only_fields = ['id', 'reference', 'created_at']

    def get_employe_nom(self, obj):
        return f"{obj.employe.nom} {obj.employe.prenom}".strip()


# ============================================================
# SERIALIZERS CONGÉS
# ============================================================

class TypeCongeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypeConge
        fields = ['id', 'nom', 'code', 'nombre_jours_par_an', 'est_actif']


class DemandeCongeSerializer(serializers.ModelSerializer):
    employe_nom = serializers.SerializerMethodField()
    type_conge_nom = serializers.CharField(
        source='type_conge.nom', read_only=True)

    class Meta:
        model = DemandeConge
        fields = [
            'id', 'employe', 'employe_nom', 'type_conge', 'type_conge_nom',
            'date_debut', 'date_fin', 'nombre_jours', 'motif', 'statut',
            'date_demande'
        ]
        read_only_fields = ['id', 'date_demande', 'nombre_jours']

    def get_employe_nom(self, obj):
        return f"{obj.employe.nom} {obj.employe.prenom}".strip()


# ============================================================
# SERIALIZERS POINTAGE
# ============================================================

class PointageSerializer(serializers.ModelSerializer):
    employe_nom = serializers.SerializerMethodField()

    class Meta:
        model = Pointage
        fields = ['id', 'employe', 'employe_nom',
                  'type_pointage', 'date_heure']
        read_only_fields = ['id', 'date_heure']

    def get_employe_nom(self, obj):
        return f"{obj.employe.nom} {obj.employe.prenom}".strip()