# tresorerie/serializers.py
from rest_framework import serializers
from django.db.models import Sum
from django.utils import timezone
from .models import *
from users.serializers import AgenceSimpleSerializer


# ============================================================
# CAISSE SERIALIZERS
# ============================================================

class CaisseSerializer(serializers.ModelSerializer):
    type_caisse_display = serializers.CharField(
        source='get_type_caisse_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    responsable_nom = serializers.CharField(
        source='responsable.get_full_name', read_only=True, default=None)
    est_sous_seuil_min = serializers.BooleanField(read_only=True)
    est_sur_seuil_max = serializers.BooleanField(read_only=True)
    mouvements_count = serializers.SerializerMethodField()

    class Meta:
        model = Caisse
        fields = (
            'id', 'code', 'nom', 'type_caisse', 'type_caisse_display',
            'agence', 'agence_nom', 'responsable', 'responsable_nom',
            'solde_initial', 'solde_actuel',
            'seuil_min', 'seuil_max',
            'est_sous_seuil_min', 'est_sur_seuil_max',
            'is_active', 'is_default', 'description',
            'mouvements_count', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def get_mouvements_count(self, obj):
        return obj.mouvements.filter(status='effectue').count()


class CaisseCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Caisse
        fields = (
            'code', 'nom', 'type_caisse', 'agence', 'responsable',
            'solde_initial', 'seuil_min', 'seuil_max',
            'is_active', 'is_default', 'description'
        )

    def validate_code(self, value):
        if Caisse.objects.filter(code=value).exists():
            raise serializers.ValidationError(f"La caisse {value} existe déjà")
        return value


# ============================================================
# COMPTE BANCAIRE SERIALIZERS
# ============================================================

class CompteBancaireSerializer(serializers.ModelSerializer):
    type_compte_display = serializers.CharField(
        source='get_type_compte_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)

    class Meta:
        model = CompteBancaire
        fields = (
            'id', 'banque', 'code', 'nom', 'type_compte', 'type_compte_display',
            'agence', 'agence_nom',
            'numero_compte', 'iban', 'bic',
            'devise', 'solde_initial', 'solde_actuel',
            'is_active', 'is_default',
            'date_ouverture', 'description',
            'created_by', 'created_by_email',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


# ✅ AJOUT: CompteBancaireCreateSerializer (manquant)
class CompteBancaireCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'un compte bancaire"""

    class Meta:
        model = CompteBancaire
        fields = (
            'banque', 'code', 'nom', 'type_compte', 'agence',
            'numero_compte', 'iban', 'bic',
            'devise', 'solde_initial',
            'is_active', 'is_default',
            'date_ouverture', 'description'
        )

    def validate(self, data):
        if CompteBancaire.objects.filter(
            agence=data['agence'],
            numero_compte=data['numero_compte']
        ).exists():
            raise serializers.ValidationError({
                'numero_compte': 'Ce numéro de compte existe déjà pour cette agence'
            })
        return data


# ============================================================
# MOUVEMENT DE TRÉSORERIE SERIALIZERS
# ============================================================

class MouvementTresorerieSerializer(serializers.ModelSerializer):
    type_mouvement_display = serializers.CharField(
        source='get_type_mouvement_display', read_only=True)
    source_type_display = serializers.CharField(
        source='get_source_type_display', read_only=True)
    mode_paiement_display = serializers.CharField(
        source='get_mode_paiement_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    caisse_nom = serializers.CharField(
        source='caisse.nom', read_only=True, default=None)
    compte_bancaire_nom = serializers.CharField(
        source='compte_bancaire.nom', read_only=True, default=None)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)

    class Meta:
        model = MouvementTresorerie
        fields = (
            'id', 'reference', 'type_mouvement', 'type_mouvement_display',
            'agence', 'agence_nom',
            'source_type', 'source_type_display', 'source_id', 'source_reference',
            'montant',
            'mode_paiement', 'mode_paiement_display',
            'caisse', 'caisse_nom',
            'compte_bancaire', 'compte_bancaire_nom',
            'date_mouvement', 'date_valeur', 'date_prevue',
            'status', 'status_display',
            'reference_externe', 'piece_justificative',
            'date_rapprochement', 'rapproche',
            'libelle', 'notes',
            'ecriture',
            'created_by', 'created_by_email',
            'valide_par', 'date_validation',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'reference', 'created_at', 'updated_at')


class MouvementTresorerieCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MouvementTresorerie
        fields = (
            'type_mouvement', 'agence',
            'source_type', 'source_id', 'source_reference',
            'montant', 'mode_paiement',
            'caisse', 'compte_bancaire',
            'date_mouvement', 'date_valeur', 'date_prevue',
            'reference_externe', 'piece_justificative',
            'libelle', 'notes'
        )

    def validate(self, data):
        if not data.get('caisse') and not data.get('compte_bancaire'):
            raise serializers.ValidationError(
                "Un mouvement doit avoir une caisse ou un compte bancaire"
            )

        if data.get('type_mouvement') == 'transfert':
            if not data.get('caisse') or not data.get('compte_bancaire'):
                raise serializers.ValidationError(
                    "Un transfert nécessite une caisse ET un compte bancaire"
                )

        return data


# ============================================================
# FRAIS SERIALIZERS
# ============================================================

# tresorerie/serializers.py

# ============================================================
# FRAIS SERIALIZERS (version complète)
# ============================================================

class FraisSerializer(serializers.ModelSerializer):
    categorie_display = serializers.CharField(
        source='get_categorie_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    mode_paiement_display = serializers.CharField(
        source='get_mode_paiement_display', read_only=True)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)

    # Nouveaux champs pour afficher les noms des destinations
    caisse_destination_nom = serializers.CharField(
        source='caisse_destination.nom', read_only=True
    )
    compte_destination_nom = serializers.CharField(
        source='compte_destination.nom', read_only=True
    )

    class Meta:
        model = Frais
        fields = (
            'id', 'reference', 'titre',
            'agence', 'agence_nom',
            'categorie', 'categorie_display',
            'montant',
            'date_frais', 'date_paiement',
            'beneficiaire',
            'piece_justificative',
            'mode_paiement', 'mode_paiement_display',
            'mouvement',
            'status', 'status_display',
            'notes',
            'created_by', 'created_by_email',
            'valide_par', 'date_validation',
            'created_at', 'updated_at',
            # Nouveaux champs
            'caisse_destination', 'caisse_destination_nom',
            'compte_destination', 'compte_destination_nom',
        )
        read_only_fields = ('id', 'reference', 'created_at', 'updated_at')


class FraisCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Frais
        fields = (
            'titre', 'agence', 'categorie', 'montant',
            'date_frais', 'date_paiement', 'beneficiaire',
            'piece_justificative', 'mode_paiement', 'status', 'notes',
            'caisse_destination', 'compte_destination'
        )

    def validate(self, data):
        # Validation du montant
        if data.get('montant', 0) <= 0:
            raise serializers.ValidationError({
                'montant': 'Le montant doit être supérieur à 0'
            })

        # Validation des destinations
        caisse = data.get('caisse_destination')
        compte = data.get('compte_destination')
        if caisse and compte:
            raise serializers.ValidationError(
                "Choisissez une seule destination (caisse ou compte)."
            )

        # Vérifier que la destination appartient à la même agence
        agence = data.get('agence')
        if agence:
            if caisse and caisse.agence != agence:
                raise serializers.ValidationError({
                    'caisse_destination': 'La caisse doit appartenir à la même agence.'
                })
            if compte and compte.agence != agence:
                raise serializers.ValidationError({
                    'compte_destination': 'Le compte bancaire doit appartenir à la même agence.'
                })

        return data

# ============================================================
# PRÉVISIONS SERIALIZERS
# ============================================================


class PrevisionTresorerieSerializer(serializers.ModelSerializer):
    type_prevision_display = serializers.CharField(
        source='get_type_prevision_display', read_only=True)
    periode_display = serializers.CharField(
        source='get_periode_display', read_only=True)
    statut_display = serializers.CharField(
        source='get_statut_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)

    class Meta:
        model = PrevisionTresorerie
        fields = (
            'id', 'reference', 'titre',
            'agence', 'agence_nom',
            'type_prevision', 'type_prevision_display',
            'periode', 'periode_display',
            'montant_prevu', 'montant_reel',
            'date_debut', 'date_fin',
            'source_type', 'source_id',
            'categorie', 'sous_categorie',
            'statut', 'statut_display',
            'probabilite',
            'ecart', 'pourcentage_ecart',
            'notes',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'reference', 'created_at', 'updated_at')


# ✅ AJOUT: PrevisionTresorerieCreateSerializer (manquant)
class PrevisionTresorerieCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrevisionTresorerie
        fields = (
            'titre', 'agence', 'type_prevision', 'periode',
            'montant_prevu', 'date_debut', 'date_fin',
            'source_type', 'source_id', 'categorie', 'sous_categorie',
            'statut', 'probabilite', 'notes'
        )

    def validate(self, data):
        if data.get('date_debut') and data.get('date_fin'):
            if data['date_debut'] > data['date_fin']:
                raise serializers.ValidationError({
                    'date_debut': 'La date début doit être antérieure à la date fin'
                })
        return data


# ============================================================
# RAPPROCHEMENT SERIALIZERS
# ============================================================

class RapprochementBancaireSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    compte_bancaire_nom = serializers.CharField(
        source='compte_bancaire.nom', read_only=True)
    est_rapproche = serializers.BooleanField(read_only=True)

    class Meta:
        model = RapprochementBancaire
        fields = (
            'id', 'reference',
            'agence', 'agence_nom',
            'compte_bancaire', 'compte_bancaire_nom',
            'date_debut', 'date_fin',
            'solde_comptable', 'solde_bancaire',
            'solde_rapproche', 'ecart', 'est_rapproche',
            'status', 'status_display',
            'encours_emission', 'encours_encaissement',
            'commissions', 'autres_ecarts',
            'notes',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'reference', 'created_at', 'updated_at')


# ✅ AJOUT: RapprochementBancaireCreateSerializer (manquant)
class RapprochementBancaireCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RapprochementBancaire
        fields = (
            'agence', 'compte_bancaire',
            'date_debut', 'date_fin',
            'solde_comptable', 'solde_bancaire',
            'status',
            'encours_emission', 'encours_encaissement',
            'commissions', 'autres_ecarts',
            'notes'
        )

    def validate(self, data):
        if data.get('date_debut') and data.get('date_fin'):
            if data['date_debut'] > data['date_fin']:
                raise serializers.ValidationError({
                    'date_debut': 'La date début doit être antérieure à la date fin'
                })
        return data


# ============================================================
# TRÉSORERIE JOURNALIÈRE SERIALIZER
# ============================================================

class TresorerieJournaliereSerializer(serializers.ModelSerializer):
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    variation = serializers.DecimalField(
        read_only=True, max_digits=15, decimal_places=2)

    class Meta:
        model = TresorerieJournaliere
        fields = (
            'id', 'date',
            'agence', 'agence_nom',
            'solde_ouverture', 'solde_fermeture', 'variation',
            'total_entrees', 'total_sorties',
            'entrees_ventes', 'entrees_reglements', 'entrees_autres',
            'sorties_achats', 'sorties_frais', 'sorties_salaires', 'sorties_autres',
            'nb_operations', 'nb_entrees', 'nb_sorties',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


# ============================================================
# TRÉSORERIE GLOBAL SERIALIZER
# ============================================================

class TresorerieGlobalSerializer(serializers.Serializer):
    """Serializer pour le solde global de trésorerie"""
    solde_global = serializers.DecimalField(max_digits=15, decimal_places=2)
    solde_caisses = serializers.DecimalField(max_digits=15, decimal_places=2)
    solde_banques = serializers.DecimalField(max_digits=15, decimal_places=2)
    nb_caisses = serializers.IntegerField()
    nb_comptes = serializers.IntegerField()
