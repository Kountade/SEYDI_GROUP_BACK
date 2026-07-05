"""
Serializers pour l'application Comptabilité / Finance
"""

from rest_framework import serializers
from django.db.models import Sum
from django.utils import timezone
from .models import *
from users.serializers import AgenceSimpleSerializer, UserSerializer
from sales.serializers import ClientSimpleSerializer
from purchases.serializers import SupplierSimpleSerializer


# ============================================================
# PLAN COMPTABLE SERIALIZERS
# ============================================================

class PlanComptableSerializer(serializers.ModelSerializer):
    """Serializer pour le plan comptable"""
    type_compte_display = serializers.CharField(
        source='get_type_compte_display', read_only=True)
    solde_normal_display = serializers.CharField(
        source='get_solde_normal_display', read_only=True)
    parent_code = serializers.CharField(
        source='parent.code', read_only=True, default=None)
    parent_nom = serializers.CharField(
        source='parent.nom', read_only=True, default=None)
    sous_comptes_count = serializers.SerializerMethodField()
    niveau_display = serializers.SerializerMethodField()

    class Meta:
        model = PlanComptable
        fields = (
            'id', 'code', 'nom', 'type_compte', 'type_compte_display',
            'parent', 'parent_code', 'parent_nom', 'niveau', 'niveau_display',
            'classe', 'sous_classe', 'solde_normal', 'solde_normal_display',
            'is_active', 'is_analytique', 'description',
            'sous_comptes_count', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def get_sous_comptes_count(self, obj):
        return obj.sous_comptes.filter(is_active=True).count()

    def get_niveau_display(self, obj):
        niveaux = {1: 'Classe', 2: 'Compte',
                   3: 'Sous-compte', 4: 'Sous-sous-compte'}
        return niveaux.get(obj.niveau, f'Niveau {obj.niveau}')

    def validate(self, data):
        # Vérifier que le parent est d'un niveau inférieur
        if data.get('parent'):
            if data.get('niveau', 1) <= data['parent'].niveau:
                raise serializers.ValidationError(
                    f"Le niveau du compte doit être supérieur à celui du parent ({data['parent'].niveau})"
                )
        return data


class PlanComptableCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'un compte"""

    class Meta:
        model = PlanComptable
        fields = (
            'code', 'nom', 'type_compte', 'parent', 'niveau',
            'classe', 'sous_classe', 'solde_normal',
            'is_active', 'is_analytique', 'description'
        )

    def validate_code(self, value):
        if PlanComptable.objects.filter(code=value).exists():
            raise serializers.ValidationError(f"Le code {value} existe déjà")
        return value


# ============================================================
# JOURNAL SERIALIZERS
# ============================================================

class JournalSerializer(serializers.ModelSerializer):
    """Serializer pour les journaux"""
    type_journal_display = serializers.CharField(
        source='get_type_journal_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    ecritures_count = serializers.SerializerMethodField()

    class Meta:
        model = Journal
        fields = (
            'id', 'code', 'nom', 'type_journal', 'type_journal_display',
            'agence', 'agence_nom', 'is_active', 'is_default',
            'description', 'ecritures_count', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def get_ecritures_count(self, obj):
        return obj.ecritures.filter(status='valide').count()


class JournalCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'un journal"""

    class Meta:
        model = Journal
        fields = ('code', 'nom', 'type_journal', 'agence',
                  'is_active', 'is_default', 'description')

    def validate(self, data):
        if Journal.objects.filter(agence=data['agence'], code=data['code']).exists():
            raise serializers.ValidationError(
                f"Un journal avec le code {data['code']} existe déjà pour cette agence"
            )
        return data


# ============================================================
# ÉCRITURES SERIALIZERS
# ============================================================

class LigneEcritureSerializer(serializers.ModelSerializer):
    """Serializer pour les lignes d'écriture"""
    compte_code = serializers.CharField(source='compte.code', read_only=True)
    compte_nom = serializers.CharField(source='compte.nom', read_only=True)
    sens = serializers.CharField(read_only=True)

    class Meta:
        model = LigneEcriture
        fields = (
            'id', 'compte', 'compte_code', 'compte_nom',
            'debit', 'credit', 'montant', 'sens',
            'libelle', 'lettrage', 'date_lettrage', 'centre_analytique'
        )
        read_only_fields = ('id',)

    def validate(self, data):
        debit = data.get('debit', 0)
        credit = data.get('credit', 0)

        if debit > 0 and credit > 0:
            raise serializers.ValidationError(
                "Une ligne ne peut pas avoir à la fois débit et crédit")
        if debit == 0 and credit == 0:
            raise serializers.ValidationError(
                "Une ligne doit avoir un débit ou un crédit")

        return data


class EcritureSerializer(serializers.ModelSerializer):
    """Serializer pour les écritures comptables"""
    journal_code = serializers.CharField(source='journal.code', read_only=True)
    journal_nom = serializers.CharField(source='journal.nom', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    lignes = LigneEcritureSerializer(many=True, read_only=True)
    est_equilibree = serializers.BooleanField(read_only=True)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)
    validated_by_email = serializers.EmailField(
        source='validated_by.email', read_only=True, default=None)

    class Meta:
        model = Ecriture
        fields = (
            'id', 'reference', 'journal', 'journal_code', 'journal_nom',
            'agence', 'agence_nom', 'date_ecriture', 'date_comptable',
            'libelle', 'piece_justificative',
            'source_type', 'source_id',
            'total_debit', 'total_credit', 'montant', 'est_equilibree',
            'status', 'status_display',
            'created_by', 'created_by_email',
            'validated_by', 'validated_by_email', 'validated_at',
            'lignes', 'notes', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'reference', 'created_at',
                            'updated_at', 'total_debit', 'total_credit')

    def validate(self, data):
        # Vérifier que la date comptable n'est pas dans le futur
        if data.get('date_comptable') and data['date_comptable'] > timezone.now().date():
            raise serializers.ValidationError({
                'date_comptable': 'La date comptable ne peut pas être dans le futur'
            })
        return data


class EcritureCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'une écriture"""
    lignes = LigneEcritureSerializer(many=True)

    class Meta:
        model = Ecriture
        fields = (
            'journal', 'agence', 'date_ecriture', 'date_comptable',
            'libelle', 'piece_justificative',
            'source_type', 'source_id',
            'lignes', 'notes'
        )

    def validate(self, data):
        lignes = data.get('lignes', [])
        if not lignes:
            raise serializers.ValidationError({
                'lignes': 'Au moins une ligne d\'écriture est requise'
            })

        # Vérifier l'équilibre
        total_debit = sum(l.get('debit', 0) for l in lignes)
        total_credit = sum(l.get('credit', 0) for l in lignes)

        if total_debit != total_credit:
            raise serializers.ValidationError({
                'lignes': f'Total débit ({total_debit}) ≠ Total crédit ({total_credit})'
            })

        return data

    def create(self, validated_data):
        lignes_data = validated_data.pop('lignes')

        # Calculer les totaux
        total_debit = sum(l.get('debit', 0) for l in lignes_data)
        total_credit = sum(l.get('credit', 0) for l in lignes_data)

        # Créer l'écriture
        ecriture = Ecriture.objects.create(
            **validated_data,
            total_debit=total_debit,
            total_credit=total_credit,
            created_by=self.context['request'].user
        )

        # Créer les lignes
        for ligne_data in lignes_data:
            LigneEcriture.objects.create(ecriture=ecriture, **ligne_data)

        return ecriture


class EcritureValidationSerializer(serializers.Serializer):
    """Serializer pour la validation d'une écriture"""
    valider = serializers.BooleanField(default=True)
    notes = serializers.CharField(required=False, allow_blank=True)


# ============================================================
# SOLDES SERIALIZERS
# ============================================================

class SoldeCompteSerializer(serializers.ModelSerializer):
    """Serializer pour les soldes de comptes"""
    compte_code = serializers.CharField(source='compte.code', read_only=True)
    compte_nom = serializers.CharField(source='compte.nom', read_only=True)
    type_compte = serializers.CharField(
        source='compte.type_compte', read_only=True)
    solde_debiteur = serializers.BooleanField(read_only=True)
    solde_crediteur = serializers.BooleanField(read_only=True)

    class Meta:
        model = SoldeCompte
        fields = (
            'id', 'compte', 'compte_code', 'compte_nom', 'type_compte',
            'agence', 'date_solde',
            'debit', 'credit', 'solde',
            'debit_periode', 'credit_periode',
            'solde_debiteur', 'solde_crediteur',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


# ============================================================
# BALANCES SERIALIZERS
# ============================================================

class LigneBalanceSerializer(serializers.ModelSerializer):
    """Serializer pour les lignes de balance"""
    compte_code = serializers.CharField(source='compte.code', read_only=True)
    compte_nom = serializers.CharField(source='compte.nom', read_only=True)
    type_compte = serializers.CharField(
        source='compte.type_compte', read_only=True)

    class Meta:
        model = LigneBalance
        fields = (
            'id', 'compte', 'compte_code', 'compte_nom', 'type_compte',
            'solde_initial_debit', 'solde_initial_credit',
            'mouvement_debit', 'mouvement_credit',
            'solde_final_debit', 'solde_final_credit'
        )


class BalanceSerializer(serializers.ModelSerializer):
    """Serializer pour les balances"""
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    type_balance_display = serializers.CharField(
        source='get_type_balance_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    lignes = LigneBalanceSerializer(many=True, read_only=True)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)
    total_debit = serializers.SerializerMethodField()
    total_credit = serializers.SerializerMethodField()
    est_equilibree = serializers.SerializerMethodField()

    class Meta:
        model = Balance
        fields = (
            'id', 'reference', 'type_balance', 'type_balance_display',
            'agence', 'agence_nom',
            'date_debut', 'date_fin',
            'status', 'status_display',
            'lignes', 'total_debit', 'total_credit', 'est_equilibree',
            'created_by', 'created_by_email',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'reference', 'created_at', 'updated_at')

    def get_total_debit(self, obj):
        return obj.lignes.aggregate(
            total=Sum('solde_final_debit')
        )['total'] or 0

    def get_total_credit(self, obj):
        return obj.lignes.aggregate(
            total=Sum('solde_final_credit')
        )['total'] or 0

    def get_est_equilibree(self, obj):
        return self.get_total_debit(obj) == self.get_total_credit(obj)


class BalanceCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'une balance"""

    class Meta:
        model = Balance
        fields = ('type_balance', 'agence', 'date_debut', 'date_fin')

    def validate(self, data):
        if data['date_debut'] > data['date_fin']:
            raise serializers.ValidationError({
                'date_debut': 'La date début doit être antérieure à la date fin'
            })

        # Vérifier qu'il n'y a pas déjà une balance pour cette période
        if Balance.objects.filter(
            agence=data['agence'],
            date_debut=data['date_debut'],
            date_fin=data['date_fin']
        ).exists():
            raise serializers.ValidationError(
                'Une balance existe déjà pour cette période'
            )

        return data


# ============================================================
# FACTURES COMPTABLES SERIALIZERS
# ============================================================

class FactureComptableSerializer(serializers.ModelSerializer):
    """Serializer pour les factures comptables"""
    type_facture_display = serializers.CharField(
        source='get_type_facture_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    client_nom = serializers.CharField(
        source='client.nom', read_only=True, default=None)
    fournisseur_nom = serializers.CharField(
        source='fournisseur.company_name', read_only=True, default=None)
    pourcentage_paye = serializers.SerializerMethodField()
    jours_retard = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)

    class Meta:
        model = FactureComptable
        fields = (
            'id', 'reference', 'type_facture', 'type_facture_display',
            'agence', 'agence_nom',
            'client', 'client_nom',
            'fournisseur', 'fournisseur_nom',
            'vente', 'achat',
            'date_facture', 'date_echeance',
            'montant_ht', 'montant_tva', 'montant_ttc',
            'montant_paye', 'montant_restant', 'pourcentage_paye',
            'status', 'status_display', 'jours_retard',
            'date_rapprochement', 'rapproche',
            'notes', 'created_by', 'created_by_email',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'reference', 'created_at', 'updated_at')

    def get_pourcentage_paye(self, obj):
        if obj.montant_ttc > 0:
            return (obj.montant_paye / obj.montant_ttc) * 100
        return 0

    def get_jours_retard(self, obj):
        if obj.status in ['impayee', 'partielle'] and obj.date_echeance < timezone.now().date():
            return (timezone.now().date() - obj.date_echeance).days
        return 0


class FactureComptableCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'une facture comptable"""

    class Meta:
        model = FactureComptable
        fields = (
            'type_facture', 'agence', 'client', 'fournisseur',
            'vente', 'achat', 'date_facture', 'date_echeance',
            'montant_ht', 'montant_tva', 'notes'
        )

    def validate(self, data):
        # Vérifier que la date d'échéance est postérieure à la date de facture
        if data['date_echeance'] < data['date_facture']:
            raise serializers.ValidationError({
                'date_echeance': 'La date d\'échéance doit être postérieure à la date de facture'
            })

        # Vérifier que client ou fournisseur est présent selon le type
        if data['type_facture'] == 'client' and not data.get('client'):
            raise serializers.ValidationError({
                'client': 'Un client est requis pour une facture client'
            })

        if data['type_facture'] == 'fournisseur' and not data.get('fournisseur'):
            raise serializers.ValidationError({
                'fournisseur': 'Un fournisseur est requis pour une facture fournisseur'
            })

        return data


# ============================================================
# RÈGLEMENTS SERIALIZERS
# ============================================================

class ReglementSerializer(serializers.ModelSerializer):
    """Serializer pour les règlements"""
    type_reglement_display = serializers.CharField(
        source='get_type_reglement_display', read_only=True)
    mode_reglement_display = serializers.CharField(
        source='get_mode_reglement_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    client_nom = serializers.CharField(
        source='client.nom', read_only=True, default=None)
    fournisseur_nom = serializers.CharField(
        source='fournisseur.company_name', read_only=True, default=None)
    facture_reference = serializers.CharField(
        source='facture.reference', read_only=True, default=None)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)

    class Meta:
        model = Reglement
        fields = (
            'id', 'reference', 'type_reglement', 'type_reglement_display',
            'agence', 'agence_nom',
            'client', 'client_nom',
            'fournisseur', 'fournisseur_nom',
            'facture', 'facture_reference',
            'montant', 'mode_reglement', 'mode_reglement_display',
            'date_reglement', 'reference_externe',
            'date_rapprochement', 'rapproche',
            'notes', 'created_by', 'created_by_email',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'reference', 'created_at', 'updated_at')


class ReglementCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'un règlement"""

    class Meta:
        model = Reglement
        fields = (
            'type_reglement', 'agence', 'client', 'fournisseur',
            'facture', 'montant', 'mode_reglement',
            'date_reglement', 'reference_externe', 'notes'
        )

    def validate(self, data):
        # Vérifier que client ou fournisseur est présent selon le type
        if data['type_reglement'] == 'client' and not data.get('client'):
            raise serializers.ValidationError({
                'client': 'Un client est requis pour un règlement client'
            })

        if data['type_reglement'] == 'fournisseur' and not data.get('fournisseur'):
            raise serializers.ValidationError({
                'fournisseur': 'Un fournisseur est requis pour un règlement fournisseur'
            })

        # Vérifier que le montant ne dépasse pas le montant restant
        facture = data.get('facture')
        if facture:
            if data['montant'] > facture.montant_restant:
                raise serializers.ValidationError({
                    'montant': f'Le montant ({data["montant"]}) dépasse le reste à payer ({facture.montant_restant})'
                })

        return data


# ============================================================
# INDICATEURS FINANCIERS SERIALIZERS
# ============================================================

class IndicateurFinancierSerializer(serializers.ModelSerializer):
    """Serializer pour les indicateurs financiers"""
    type_indicateur_display = serializers.CharField(
        source='get_type_indicateur_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    variation = serializers.SerializerMethodField()
    variation_pourcentage = serializers.SerializerMethodField()

    class Meta:
        model = IndicateurFinancier
        fields = (
            'id', 'nom', 'code', 'type_indicateur', 'type_indicateur_display',
            'agence', 'agence_nom',
            'valeur', 'valeur_previous',
            'variation', 'variation_pourcentage',
            'date_calcul', 'periode_debut', 'periode_fin',
            'formule', 'interpretation',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def get_variation(self, obj):
        return obj.valeur - obj.valeur_previous

    def get_variation_pourcentage(self, obj):
        if obj.valeur_previous != 0:
            return ((obj.valeur - obj.valeur_previous) / abs(obj.valeur_previous)) * 100
        return 0


class IndicateurCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'un indicateur"""

    class Meta:
        model = IndicateurFinancier
        fields = (
            'nom', 'code', 'type_indicateur', 'agence',
            'valeur', 'valeur_previous',
            'periode_debut', 'periode_fin',
            'formule', 'interpretation'
        )

    def validate_code(self, value):
        if IndicateurFinancier.objects.filter(code=value).exists():
            raise serializers.ValidationError(
                f"L'indicateur {value} existe déjà")
        return value


# ============================================================
# CLÔTURE COMPTABLE SERIALIZERS
# ============================================================

class ClotureComptableSerializer(serializers.ModelSerializer):
    """Serializer pour les clôtures comptables"""
    type_cloture_display = serializers.CharField(
        source='get_type_cloture_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    closed_by_email = serializers.EmailField(
        source='closed_by.email', read_only=True, default=None)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)
    duree_jours = serializers.SerializerMethodField()

    class Meta:
        model = ClotureComptable
        fields = (
            'id', 'reference', 'type_cloture', 'type_cloture_display',
            'agence', 'agence_nom',
            'date_debut', 'date_fin', 'duree_jours',
            'status', 'status_display',
            'total_debit', 'total_credit', 'resultat_exercice',
            'closed_by', 'closed_by_email', 'closed_at',
            'notes', 'created_by', 'created_by_email',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'reference', 'created_at', 'updated_at')

    def get_duree_jours(self, obj):
        return (obj.date_fin - obj.date_debut).days


class ClotureCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'une clôture"""

    class Meta:
        model = ClotureComptable
        fields = ('type_cloture', 'agence', 'date_debut', 'date_fin', 'notes')

    def validate(self, data):
        if data['date_debut'] > data['date_fin']:
            raise serializers.ValidationError({
                'date_debut': 'La date début doit être antérieure à la date fin'
            })

        # Vérifier qu'il n'y a pas déjà une clôture pour cette période
        if ClotureComptable.objects.filter(
            agence=data['agence'],
            date_debut=data['date_debut'],
            date_fin=data['date_fin']
        ).exclude(status='cloturee').exists():
            raise serializers.ValidationError(
                'Une clôture est déjà en cours pour cette période'
            )

        return data


# ============================================================
# ANALYSE FINANCIÈRE SERIALIZERS
# ============================================================

class AnalyseFinanciereSerializer(serializers.ModelSerializer):
    """Serializer pour les analyses financières"""
    type_analyse_display = serializers.CharField(
        source='get_type_analyse_display', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)

    class Meta:
        model = AnalyseFinanciere
        fields = (
            'id', 'reference', 'type_analyse', 'type_analyse_display',
            'agence', 'agence_nom',
            'titre', 'description',
            'donnees', 'resultat',
            'date_debut', 'date_fin', 'date_analyse',
            'created_by', 'created_by_email',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'reference', 'created_at', 'updated_at')


class AnalyseCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'une analyse"""

    class Meta:
        model = AnalyseFinanciere
        fields = (
            'type_analyse', 'agence', 'titre', 'description',
            'donnees', 'date_debut', 'date_fin'
        )

    def validate(self, data):
        if data['date_debut'] > data['date_fin']:
            raise serializers.ValidationError({
                'date_debut': 'La date début doit être antérieure à la date fin'
            })
        return data


# ============================================================
# TABLEAUX DE BORD ET RAPPORTS SERIALIZERS
# ============================================================

class DashboardSerializer(serializers.Serializer):
    """Serializer pour le tableau de bord financier"""
    periode = serializers.CharField()
    agence_id = serializers.IntegerField()

    # Indicateurs clés
    ca_total = serializers.DecimalField(max_digits=15, decimal_places=2)
    ca_evolution = serializers.DecimalField(max_digits=10, decimal_places=2)
    marge_brute = serializers.DecimalField(max_digits=15, decimal_places=2)
    marge_pourcentage = serializers.DecimalField(
        max_digits=10, decimal_places=2)
    tresorerie = serializers.DecimalField(max_digits=15, decimal_places=2)

    # Détails
    ventes_mois = serializers.DecimalField(max_digits=15, decimal_places=2)
    achats_mois = serializers.DecimalField(max_digits=15, decimal_places=2)
    charges_mois = serializers.DecimalField(max_digits=15, decimal_places=2)

    # Alertes
    alertes = serializers.ListField(child=serializers.DictField())


class CompteResultatSerializer(serializers.Serializer):
    """Serializer pour le compte de résultat"""
    periode = serializers.CharField()
    agence_id = serializers.IntegerField()

    # Produits
    produits = serializers.DictField()
    total_produits = serializers.DecimalField(max_digits=15, decimal_places=2)

    # Charges
    charges = serializers.DictField()
    total_charges = serializers.DecimalField(max_digits=15, decimal_places=2)

    # Résultat
    resultat = serializers.DecimalField(max_digits=15, decimal_places=2)
    type_resultat = serializers.CharField()


class BilanSerializer(serializers.Serializer):
    """Serializer pour le bilan comptable"""
    date = serializers.DateField()
    agence_id = serializers.IntegerField()

    # Actif
    actif = serializers.DictField()
    total_actif = serializers.DecimalField(max_digits=15, decimal_places=2)

    # Passif
    passif = serializers.DictField()
    total_passif = serializers.DecimalField(max_digits=15, decimal_places=2)

    # Équilibre
    est_equilibre = serializers.BooleanField()


class TresorerieSerializer(serializers.Serializer):
    """Serializer pour la trésorerie"""
    agence_id = serializers.IntegerField()
    date = serializers.DateField()

    solde_initial = serializers.DecimalField(max_digits=15, decimal_places=2)
    encaissements = serializers.DecimalField(max_digits=15, decimal_places=2)
    decaissements = serializers.DecimalField(max_digits=15, decimal_places=2)
    solde_final = serializers.DecimalField(max_digits=15, decimal_places=2)

    details_encaissements = serializers.ListField(
        child=serializers.DictField())
    details_decaissements = serializers.ListField(
        child=serializers.DictField())
