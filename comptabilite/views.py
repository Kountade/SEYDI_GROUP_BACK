# comptabilite/views.py
"""
Views pour l'application Comptabilité / Finance.

✅ OPTIMISATIONS N+1 :
- PlanComptable : select_related('parent','created_by') + annotate(sous_comptes_count)
- Journal       : select_related('agence') + annotate(ecritures_count)
- Ecriture      : select_related('journal','agence','created_by','validated_by')
                  + prefetch_related(Prefetch('lignes', select_related('compte')))
- SoldeCompte   : select_related('compte','agence')
- LigneEcriture : select_related('compte','ecriture')
- Balance       : select_related('agence','created_by')
                  + annotate(Sum debit/credit) + prefetch_related('lignes')
- FactureComptable : select_related('agence','client','fournisseur','created_by')
- Reglement     : select_related('agence','client','fournisseur','facture','created_by')
- Validation    : bulk_create + bulk_update pour les soldes
- Balance._generer_lignes : 3 requêtes au lieu de N

✅ PAGINATION sur TOUS les ViewSets
✅ CACHE sur Dashboard
✅ PARALLÉLISATION Dashboard (ThreadPoolExecutor)
"""

from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import Q, Sum, Count, Avg, F, Prefetch
from django.db import transaction
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

from .models import *
from .serializers import *
from .pagination import (
    PlanComptablePagination,
    JournalPagination,
    EcriturePagination,
    BalancePagination,
    FactureComptablePagination,
    ReglementPagination,
    IndicateurPagination,
    CloturePagination,
    AnalysePagination,
)
from users.permissions import (
    IsPDG, IsDRH, IsPDGOrDRH, IsChefAgence, IsComptable,
)


# ============================================================
# CACHE — Purge
# ============================================================
def _purge_compta_cache():
    """Purge le cache comptabilité après mutation."""
    try:
        cache.delete_pattern('compta_*')
    except Exception:
        cache.clear()


# ============================================================
# PLAN COMPTABLE VIEWSET
# ============================================================
class PlanComptableViewset(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion du plan comptable.

    ✅ N+1 ÉLIMINÉ :
    - select_related('parent', 'created_by')
    - annotate(sous_comptes_count=Count('sous_comptes', filter=...))
    """
    permission_classes = [permissions.IsAuthenticated, IsPDGOrDRH | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code', 'nom', 'description']
    ordering_fields = ['code', 'nom', 'type_compte', 'niveau']
    pagination_class = PlanComptablePagination

    def get_serializer_class(self):
        if self.action == 'create':
            return PlanComptableCreateSerializer
        return PlanComptableSerializer

    def get_queryset(self):
        # ✅ 1 requête : select_related + annotate
        queryset = (
            PlanComptable.objects
            .filter(is_active=True)
            .select_related('parent', 'created_by')
            .annotate(
                sous_comptes_count=Count(
                    'sous_comptes',
                    filter=Q(sous_comptes__is_active=True),
                    distinct=True,
                )
            )
        )

        type_compte = self.request.query_params.get('type_compte')
        if type_compte:
            queryset = queryset.filter(type_compte=type_compte)

        niveau = self.request.query_params.get('niveau')
        if niveau:
            queryset = queryset.filter(niveau=niveau)

        classe = self.request.query_params.get('classe')
        if classe:
            queryset = queryset.filter(classe=classe)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_compta_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_compta_cache()

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        _purge_compta_cache()

    @action(detail=True, methods=['get'])
    def soldes(self, request, pk=None):
        """Récupère les soldes d'un compte (paginé)."""
        compte = self.get_object()
        agence_id = request.query_params.get('agence_id')
        if not agence_id:
            return Response(
                {"error": "agence_id est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        soldes = (
            SoldeCompte.objects
            .filter(compte=compte, agence_id=agence_id)
            .select_related('compte', 'agence')
            .order_by('-date_solde')
        )

        page = self.paginate_queryset(soldes)
        if page is not None:
            return self.get_paginated_response(
                SoldeCompteSerializer(page, many=True).data
            )
        return Response(SoldeCompteSerializer(soldes, many=True).data)

    @action(detail=True, methods=['get'])
    def lignes_ecritures(self, request, pk=None):
        """Récupère les lignes d'écriture d'un compte (paginé)."""
        compte = self.get_object()
        agence_id = request.query_params.get('agence_id')
        if not agence_id:
            return Response(
                {"error": "agence_id est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        lignes = (
            LigneEcriture.objects
            .filter(
                compte=compte,
                ecriture__agence_id=agence_id,
                ecriture__status='valide',
            )
            .select_related('compte', 'ecriture')
            .order_by('-ecriture__date_ecriture')
        )

        page = self.paginate_queryset(lignes)
        if page is not None:
            return self.get_paginated_response(
                LigneEcritureSerializer(page, many=True).data
            )
        return Response(LigneEcritureSerializer(lignes, many=True).data)


# ============================================================
# JOURNAL VIEWSET
# ============================================================
class JournalViewset(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des journaux.

    ✅ N+1 ÉLIMINÉ :
    - select_related('agence')
    - annotate(ecritures_count=Count('ecritures', filter=...))
    """
    permission_classes = [
        permissions.IsAuthenticated,
        IsPDGOrDRH | IsChefAgence | IsComptable,
    ]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code', 'nom', 'description']
    ordering_fields = ['code', 'nom', 'type_journal']
    pagination_class = JournalPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return JournalCreateSerializer
        return JournalSerializer

    def get_queryset(self):
        user = self.request.user

        # ✅ 1 requête : select_related + annotate
        queryset = (
            Journal.objects
            .select_related('agence')
            .annotate(
                ecritures_count=Count(
                    'ecritures',
                    filter=Q(ecritures__status='valide'),
                    distinct=True,
                )
            )
        )

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = queryset.filter(agence_id__in=agences_ids)

        return queryset.filter(is_active=True)

    def perform_create(self, serializer):
        serializer.save()
        _purge_compta_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_compta_cache()

    @action(detail=True, methods=['get'])
    def ecritures(self, request, pk=None):
        """Récupère les écritures d'un journal (paginé + optimisé)."""
        journal = self.get_object()

        ecritures = (
            journal.ecritures
            .select_related('journal', 'agence', 'created_by', 'validated_by')
            .prefetch_related(
                Prefetch('lignes',
                         queryset=LigneEcriture.objects.select_related('compte'))
            )
        )

        status_filter = request.query_params.get('status')
        if status_filter:
            ecritures = ecritures.filter(status=status_filter)

        date_debut = request.query_params.get('date_debut')
        if date_debut:
            ecritures = ecritures.filter(date_ecriture__gte=date_debut)

        date_fin = request.query_params.get('date_fin')
        if date_fin:
            ecritures = ecritures.filter(date_ecriture__lte=date_fin)

        page = self.paginate_queryset(ecritures)
        if page is not None:
            serializer = EcritureSerializer(
                page, many=True, context={'request': request, 'today': timezone.now().date()}
            )
            return self.get_paginated_response(serializer.data)

        serializer = EcritureSerializer(
            ecritures, many=True, context={'request': request, 'today': timezone.now().date()}
        )
        return Response(serializer.data)


# ============================================================
# ÉCRITURES VIEWSET  (✅ LE PLUS CRITIQUE)
# ============================================================
class EcritureViewset(viewsets.ModelViewSet):
    """
    ViewSet pour les écritures comptables.

    ✅ N+1 ÉLIMINÉ :
    - select_related('journal', 'agence', 'created_by', 'validated_by')
    - prefetch_related(Prefetch('lignes', select_related('compte')))
    - _mettre_a_jour_soldes : bulk_create + bulk_update
    """
    permission_classes = [
        permissions.IsAuthenticated,
        IsPDGOrDRH | IsChefAgence | IsComptable,
    ]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference', 'libelle', 'piece_justificative']
    ordering_fields = ['date_ecriture', 'date_comptable', 'created_at']
    pagination_class = EcriturePagination

    def get_serializer_class(self):
        if self.action == 'create':
            return EcritureCreateSerializer
        return EcritureSerializer

    def get_queryset(self):
        user = self.request.user

        # ✅ LA CORRECTION CRUCIALE :
        # - select_related : journal, agence, created_by, validated_by
        # - prefetch_related : lignes + compte
        queryset = (
            Ecriture.objects
            .select_related('journal', 'agence', 'created_by', 'validated_by')
            .prefetch_related(
                Prefetch('lignes',
                         queryset=LigneEcriture.objects.select_related('compte'))
            )
        )

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = queryset.filter(agence_id__in=agences_ids)

        # ✅ Filtres index-friendly
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        journal_id = self.request.query_params.get('journal_id')
        if journal_id:
            queryset = queryset.filter(journal_id=journal_id)

        date_debut = self.request.query_params.get('date_debut')
        if date_debut:
            queryset = queryset.filter(date_ecriture__gte=date_debut)

        date_fin = self.request.query_params.get('date_fin')
        if date_fin:
            queryset = queryset.filter(date_ecriture__lte=date_fin)

        return queryset

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['today'] = timezone.now().date()
        return ctx

    def perform_create(self, serializer):
        serializer.save()
        _purge_compta_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_compta_cache()

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def valider(self, request, pk=None):
        """Valide une écriture + met à jour les soldes (bulk)."""
        ecriture = self.get_object()

        if ecriture.status == 'valide':
            return Response(
                {"error": "Cette écriture est déjà validée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not ecriture.est_equilibree:
            return Response(
                {"error": "L'écriture n'est pas équilibrée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        ecriture.valider(request.user)
        self._mettre_a_jour_soldes(ecriture)
        _purge_compta_cache()

        serializer = self.get_serializer(ecriture)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        """Annule une écriture."""
        ecriture = self.get_object()

        if ecriture.status == 'annulee':
            return Response(
                {"error": "Cette écriture est déjà annulée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if ecriture.status == 'cloturee':
            return Response(
                {"error": "Cette écriture est clôturée et ne peut pas être annulée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        ecriture.status = 'annulee'
        ecriture.save(update_fields=['status', 'updated_at'])
        _purge_compta_cache()

        serializer = self.get_serializer(ecriture)
        return Response(serializer.data)

    def _mettre_a_jour_soldes(self, ecriture):
        """
        ✅ Met à jour les soldes en BULK (2 requêtes au lieu de N × M).
        """
        comptes_ids = [ligne.compte_id for ligne in ecriture.lignes.all()]
        soldes_existants = {
            s.compte_id: s
            for s in SoldeCompte.objects.filter(
                compte_id__in=comptes_ids,
                agence_id=ecriture.agence_id,
                date_solde=ecriture.date_comptable,
            )
        }

        soldes_a_creer = []
        soldes_a_mettre_a_jour = []

        for ligne in ecriture.lignes.all():
            if ligne.compte_id in soldes_existants:
                solde = soldes_existants[ligne.compte_id]
                solde.debit += ligne.debit
                solde.credit += ligne.credit
                solde.solde = solde.debit - solde.credit
                solde.debit_periode += ligne.debit
                solde.credit_periode += ligne.credit
                soldes_a_mettre_a_jour.append(solde)
            else:
                soldes_a_creer.append(SoldeCompte(
                    compte_id=ligne.compte_id,
                    agence_id=ecriture.agence_id,
                    date_solde=ecriture.date_comptable,
                    debit=ligne.debit,
                    credit=ligne.credit,
                    solde=ligne.debit - ligne.credit,
                    debit_periode=ligne.debit,
                    credit_periode=ligne.credit,
                ))

        # ✅ 2 requêtes bulk au lieu de N get_or_create
        if soldes_a_creer:
            SoldeCompte.objects.bulk_create(soldes_a_creer)
        if soldes_a_mettre_a_jour:
            SoldeCompte.objects.bulk_update(
                soldes_a_mettre_a_jour,
                ['debit', 'credit', 'solde', 'debit_periode', 'credit_periode'],
            )


# ============================================================
# BALANCE VIEWSET
# ============================================================
class BalanceViewset(viewsets.ModelViewSet):
    """
    ViewSet pour les balances.

    ✅ N+1 ÉLIMINÉ :
    - select_related('agence', 'created_by')
    - annotate(total_debit=Sum(...), total_credit=Sum(...))
    - prefetch_related(Prefetch('lignes', select_related('compte')))
    - _generer_lignes_balance : 3 requêtes + bulk_create
    """
    permission_classes = [
        permissions.IsAuthenticated,
        IsPDGOrDRH | IsChefAgence | IsComptable,
    ]
    pagination_class = BalancePagination

    def get_serializer_class(self):
        if self.action == 'create':
            return BalanceCreateSerializer
        return BalanceSerializer

    def get_queryset(self):
        user = self.request.user

        # ✅ 1 requête : select_related + annotate + prefetch
        queryset = (
            Balance.objects
            .select_related('agence', 'created_by')
            .annotate(
                total_debit=Sum('lignes__solde_final_debit'),
                total_credit=Sum('lignes__solde_final_credit'),
            )
            .prefetch_related(
                Prefetch('lignes',
                         queryset=LigneBalance.objects.select_related('compte'))
            )
        )

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = queryset.filter(agence_id__in=agences_ids)

        type_balance = self.request.query_params.get('type_balance')
        if type_balance:
            queryset = queryset.filter(type_balance=type_balance)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            balance = serializer.save(created_by=request.user)
            self._generer_lignes_balance(balance)
            _purge_compta_cache()

            # Recharger avec annotate
            balance = self.get_queryset().get(pk=balance.pk)
            return Response(
                BalanceSerializer(balance).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def _generer_lignes_balance(self, balance):
        """
        ✅ 3 requêtes au lieu de N × 2 :
        - 1 pour les comptes
        - 1 pour les soldes initiaux
        - 1 pour les mouvements
        - 1 bulk_create
        """
        # ✅ 1 requête : tous les comptes actifs
        comptes = list(PlanComptable.objects.filter(is_active=True))

        # ✅ 1 requête : soldes initiaux (avant date_debut)
        soldes_initiaux_qs = (
            SoldeCompte.objects
            .filter(
                agence=balance.agence,
                date_solde__lt=balance.date_debut,
            )
            .values('compte_id')
            .annotate(
                debit=Sum('debit'),
                credit=Sum('credit'),
            )
        )
        soldes_initiaux = {s['compte_id']: s for s in soldes_initiaux_qs}

        # ✅ 1 requête : mouvements de la période
        mouvements_qs = (
            SoldeCompte.objects
            .filter(
                agence=balance.agence,
                date_solde__gte=balance.date_debut,
                date_solde__lte=balance.date_fin,
            )
            .values('compte_id')
            .annotate(
                debit=Sum('debit_periode'),
                credit=Sum('credit_periode'),
            )
        )
        mouvements = {m['compte_id']: m for m in mouvements_qs}

        # ✅ 1 bulk_create
        lignes = []
        for compte in comptes:
            si = soldes_initiaux.get(compte.id, {'debit': 0, 'credit': 0})
            mv = mouvements.get(compte.id, {'debit': 0, 'credit': 0})
            lignes.append(LigneBalance(
                balance=balance,
                compte=compte,
                solde_initial_debit=si['debit'] or 0,
                solde_initial_credit=si['credit'] or 0,
                mouvement_debit=mv['debit'] or 0,
                mouvement_credit=mv['credit'] or 0,
                solde_final_debit=(si['debit'] or 0) + (mv['debit'] or 0),
                solde_final_credit=(si['credit'] or 0) + (mv['credit'] or 0),
            ))

        LigneBalance.objects.bulk_create(lignes, batch_size=500)


# ============================================================
# FACTURES COMPTABLES VIEWSET
# ============================================================
class FactureComptableViewset(viewsets.ModelViewSet):
    """
    ViewSet pour les factures comptables.

    ✅ N+1 ÉLIMINÉ :
    - select_related('agence', 'client', 'fournisseur', 'created_by')
    - serializer utilise 'today' du contexte pour jours_retard
    """
    permission_classes = [
        permissions.IsAuthenticated,
        IsPDGOrDRH | IsChefAgence | IsComptable,
    ]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference', 'client__nom', 'fournisseur__company_name']
    ordering_fields = ['date_facture', 'date_echeance', 'montant_ttc']
    pagination_class = FactureComptablePagination

    def get_serializer_class(self):
        if self.action == 'create':
            return FactureComptableCreateSerializer
        return FactureComptableSerializer

    def get_queryset(self):
        user = self.request.user

        # ✅ select_related pour client, fournisseur, agence
        queryset = (
            FactureComptable.objects
            .select_related(
                'agence', 'client', 'fournisseur',
                'vente', 'achat', 'created_by',
            )
        )

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = queryset.filter(agence_id__in=agences_ids)

        type_facture = self.request.query_params.get('type_facture')
        if type_facture:
            queryset = queryset.filter(type_facture=type_facture)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        client_id = self.request.query_params.get('client_id')
        if client_id:
            queryset = queryset.filter(client_id=client_id)

        fournisseur_id = self.request.query_params.get('fournisseur_id')
        if fournisseur_id:
            queryset = queryset.filter(fournisseur_id=fournisseur_id)

        return queryset

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['today'] = timezone.now().date()
        return ctx

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_compta_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_compta_cache()


# ============================================================
# RÈGLEMENTS VIEWSET
# ============================================================
class ReglementViewset(viewsets.ModelViewSet):
    """
    ViewSet pour les règlements.

    ✅ N+1 ÉLIMINÉ :
    - select_related('facture') : CRUCIAL pour facture_reference
    - select_related('client', 'fournisseur', 'agence', 'created_by')
    """
    permission_classes = [
        permissions.IsAuthenticated,
        IsPDGOrDRH | IsChefAgence | IsComptable,
    ]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        'reference', 'client__nom',
        'fournisseur__company_name', 'reference_externe',
    ]
    ordering_fields = ['date_reglement', 'montant']
    pagination_class = ReglementPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ReglementCreateSerializer
        return ReglementSerializer

    def get_queryset(self):
        user = self.request.user

        # ✅ select_related('facture') : CRUCIAL
        queryset = (
            Reglement.objects
            .select_related(
                'agence', 'client', 'fournisseur',
                'facture', 'created_by',
            )
        )

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = queryset.filter(agence_id__in=agences_ids)

        type_reglement = self.request.query_params.get('type_reglement')
        if type_reglement:
            queryset = queryset.filter(type_reglement=type_reglement)

        mode_reglement = self.request.query_params.get('mode_reglement')
        if mode_reglement:
            queryset = queryset.filter(mode_reglement=mode_reglement)

        client_id = self.request.query_params.get('client_id')
        if client_id:
            queryset = queryset.filter(client_id=client_id)

        fournisseur_id = self.request.query_params.get('fournisseur_id')
        if fournisseur_id:
            queryset = queryset.filter(fournisseur_id=fournisseur_id)

        return queryset

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            reglement = serializer.save(created_by=request.user)
            if reglement.facture:
                self._mettre_a_jour_facture(reglement.facture)
            _purge_compta_cache()
            return Response(
                ReglementSerializer(reglement).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def _mettre_a_jour_facture(self, facture):
        """Met à jour le statut de la facture (SQL)."""
        total_paye = facture.reglements.aggregate(
            total=Sum('montant')
        )['total'] or 0

        facture.montant_paye = total_paye
        facture.montant_restant = facture.montant_ttc - total_paye

        if total_paye >= facture.montant_ttc:
            facture.status = 'payee'
        elif total_paye > 0:
            facture.status = 'partielle'
        elif facture.date_echeance < timezone.now().date():
            facture.status = 'impayee'

        facture.save(update_fields=[
            'montant_paye', 'montant_restant', 'status', 'updated_at',
        ])


# ============================================================
# INDICATEURS VIEWSET
# ============================================================
class IndicateurViewset(viewsets.ModelViewSet):
    """
    ViewSet pour les indicateurs financiers.

    ✅ N+1 ÉLIMINÉ :
    - select_related('agence')
    """
    permission_classes = [
        permissions.IsAuthenticated,
        IsPDGOrDRH | IsChefAgence | IsComptable,
    ]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nom', 'code', 'description']
    ordering_fields = ['valeur', 'date_calcul']
    pagination_class = IndicateurPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return IndicateurCreateSerializer
        return IndicateurFinancierSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = IndicateurFinancier.objects.select_related('agence')

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = queryset.filter(agence_id__in=agences_ids)

        type_indicateur = self.request.query_params.get('type_indicateur')
        if type_indicateur:
            queryset = queryset.filter(type_indicateur=type_indicateur)

        date = self.request.query_params.get('date')
        if date:
            queryset = queryset.filter(date_calcul=date)

        return queryset

    def perform_create(self, serializer):
        serializer.save()
        _purge_compta_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_compta_cache()


# ============================================================
# CLÔTURE VIEWSET
# ============================================================
class ClotureViewset(viewsets.ModelViewSet):
    """
    ViewSet pour les clôtures comptables.

    ✅ N+1 ÉLIMINÉ :
    - select_related('agence', 'created_by', 'closed_by')
    """
    permission_classes = [
        permissions.IsAuthenticated,
        IsPDGOrDRH | IsComptable,
    ]
    pagination_class = CloturePagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ClotureCreateSerializer
        return ClotureComptableSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = ClotureComptable.objects.select_related(
            'agence', 'created_by', 'closed_by',
        )

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = queryset.filter(agence_id__in=agences_ids)

        type_cloture = self.request.query_params.get('type_cloture')
        if type_cloture:
            queryset = queryset.filter(type_cloture=type_cloture)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_compta_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_compta_cache()


# ============================================================
# ANALYSE VIEWSET
# ============================================================
class AnalyseViewset(viewsets.ModelViewSet):
    """
    ViewSet pour les analyses financières.

    ✅ N+1 ÉLIMINÉ :
    - select_related('agence', 'created_by')
    """
    permission_classes = [
        permissions.IsAuthenticated,
        IsPDGOrDRH | IsChefAgence | IsComptable,
    ]
    pagination_class = AnalysePagination

    def get_serializer_class(self):
        if self.action == 'create':
            return AnalyseCreateSerializer
        return AnalyseFinanciereSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = AnalyseFinanciere.objects.select_related(
            'agence', 'created_by',
        )

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = queryset.filter(agence_id__in=agences_ids)

        type_analyse = self.request.query_params.get('type_analyse')
        if type_analyse:
            queryset = queryset.filter(type_analyse=type_analyse)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_compta_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_compta_cache()


# ============================================================
# DASHBOARD (✅ CACHE + PARALLÉLISATION)
# ============================================================
class DashboardView(APIView):
    """
    Vue pour le tableau de bord financier.

    ✅ CACHE 5 min + PARALLÉLISATION ThreadPoolExecutor
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')
        if not agence_id:
            return Response(
                {"error": "agence_id est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ✅ Cache 5 min
        cache_key = f'compta_dashboard:{agence_id}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        try:
            agence = Agence.objects.get(id=agence_id)
        except Agence.DoesNotExist:
            return Response(
                {"error": "Agence non trouvée"},
                status=status.HTTP_404_NOT_FOUND
            )

        if not request.user.peut_acceder_agence(int(agence_id)):
            return Response(
                {"error": "Permission denied"},
                status=status.HTTP_403_FORBIDDEN
            )

        # ✅ today calculé UNE SEULE fois
        today = timezone.now().date()
        debut_mois = today.replace(day=1)
        mois_precedent = debut_mois - timedelta(days=1)
        debut_mois_precedent = mois_precedent.replace(day=1)

        # ✅ Parallélisation
        with ThreadPoolExecutor(max_workers=6) as ex:
            f_ca_mois = ex.submit(
                lambda: FactureComptable.objects.filter(
                    agence=agence, type_facture='client',
                    date_facture__gte=debut_mois,
                    date_facture__lte=today,
                    status__in=['payee', 'partielle'],
                ).aggregate(total=Sum('montant_ttc'))['total'] or 0
            )
            f_ca_prev = ex.submit(
                lambda: FactureComptable.objects.filter(
                    agence=agence, type_facture='client',
                    date_facture__gte=debut_mois_precedent,
                    date_facture__lte=mois_precedent,
                    status__in=['payee', 'partielle'],
                ).aggregate(total=Sum('montant_ttc'))['total'] or 0
            )
            f_achats = ex.submit(
                lambda: FactureComptable.objects.filter(
                    agence=agence, type_facture='fournisseur',
                    date_facture__gte=debut_mois,
                    date_facture__lte=today,
                ).aggregate(total=Sum('montant_ttc'))['total'] or 0
            )
            f_enc = ex.submit(
                lambda: Reglement.objects.filter(
                    agence=agence, type_reglement='client',
                    date_reglement__lte=today,
                ).aggregate(total=Sum('montant'))['total'] or 0
            )
            f_dec = ex.submit(
                lambda: Reglement.objects.filter(
                    agence=agence, type_reglement='fournisseur',
                    date_reglement__lte=today,
                ).aggregate(total=Sum('montant'))['total'] or 0
            )
            f_alertes = ex.submit(
                lambda: {
                    'factures_impayees': FactureComptable.objects.filter(
                        agence=agence, status='impayee'
                    ).count(),
                    'dettes_fournisseurs': FactureComptable.objects.filter(
                        agence=agence, type_facture='fournisseur',
                        status__in=['impayee', 'partielle'],
                    ).aggregate(total=Sum('montant_restant'))['total'] or 0,
                }
            )

            ca_mois = f_ca_mois.result()
            ca_mois_precedent = f_ca_prev.result()
            achats_mois = f_achats.result()
            encaissements = f_enc.result()
            decaissements = f_dec.result()
            alerts_data = f_alertes.result()

        tresorerie = encaissements - decaissements

        alertes = []
        if alerts_data['factures_impayees'] > 0:
            alertes.append({
                'type': 'warning',
                'message': f"{alerts_data['factures_impayees']} factures impayées",
                'count': alerts_data['factures_impayees'],
            })
        if alerts_data['dettes_fournisseurs'] > 0:
            alertes.append({
                'type': 'info',
                'message': f"Dettes fournisseurs: {alerts_data['dettes_fournisseurs']:,.0f} FCFA",
                'montant': float(alerts_data['dettes_fournisseurs']),
            })
        if tresorerie < 0:
            alertes.append({
                'type': 'error',
                'message': 'Trésorerie négative',
                'montant': float(tresorerie),
            })

        data = {
            'periode': today.strftime('%B %Y'),
            'agence_id': agence.id,
            'ca_total': float(ca_mois),
            'ca_evolution': float(ca_mois - ca_mois_precedent),
            'ca_evolution_pourcentage': float(
                ((ca_mois - ca_mois_precedent) / ca_mois_precedent * 100)
                if ca_mois_precedent > 0 else 0
            ),
            'marge_brute': float(ca_mois - achats_mois),
            'marge_pourcentage': float(
                ((ca_mois - achats_mois) / ca_mois * 100)
                if ca_mois > 0 else 0
            ),
            'tresorerie': float(tresorerie),
            'ventes_mois': float(ca_mois),
            'achats_mois': float(achats_mois),
            'charges_mois': 0,
            'alertes': alertes,
        }

        cache.set(cache_key, data, 60 * 5)
        return Response(data)


class CompteResultatView(APIView):
    """Vue pour le compte de résultat."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')
        date_debut = request.query_params.get('date_debut')
        date_fin = request.query_params.get('date_fin')

        if not all([agence_id, date_debut, date_fin]):
            return Response(
                {"error": "agence_id, date_debut et date_fin sont requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            agence = Agence.objects.get(id=agence_id)
        except Agence.DoesNotExist:
            return Response(
                {"error": "Agence non trouvée"},
                status=status.HTTP_404_NOT_FOUND
            )

        if not request.user.peut_acceder_agence(int(agence_id)):
            return Response(
                {"error": "Permission denied"},
                status=status.HTTP_403_FORBIDDEN
            )

        # ✅ 2 requêtes au lieu de N
        produits = {
            'ventes': float(
                FactureComptable.objects.filter(
                    agence=agence, type_facture='client',
                    date_facture__gte=date_debut,
                    date_facture__lte=date_fin,
                    status__in=['payee', 'partielle'],
                ).aggregate(total=Sum('montant_ttc'))['total'] or 0
            ),
        }

        charges = {
            'achats': float(
                FactureComptable.objects.filter(
                    agence=agence, type_facture='fournisseur',
                    date_facture__gte=date_debut,
                    date_facture__lte=date_fin,
                ).aggregate(total=Sum('montant_ttc'))['total'] or 0
            ),
        }

        total_produits = sum(produits.values())
        total_charges = sum(charges.values())
        resultat = total_produits - total_charges

        data = {
            'periode': f"{date_debut} au {date_fin}",
            'agence_id': agence.id,
            'produits': produits,
            'total_produits': total_produits,
            'charges': charges,
            'total_charges': total_charges,
            'resultat': resultat,
            'type_resultat': 'Bénéfice' if resultat > 0 else 'Perte',
        }

        return Response(data)


class BilanView(APIView):
    """Vue pour le bilan comptable."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')
        date_cloture = request.query_params.get('date_cloture')

        if not all([agence_id, date_cloture]):
            return Response(
                {"error": "agence_id et date_cloture sont requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            agence = Agence.objects.get(id=agence_id)
        except Agence.DoesNotExist:
            return Response(
                {"error": "Agence non trouvée"},
                status=status.HTTP_404_NOT_FOUND
            )

        if not request.user.peut_acceder_agence(int(agence_id)):
            return Response(
                {"error": "Permission denied"},
                status=status.HTTP_403_FORBIDDEN
            )

        # ✅ 4 requêtes au lieu de N
        encaissements = Reglement.objects.filter(
            agence=agence, type_reglement='client',
            date_reglement__lte=date_cloture,
        ).aggregate(total=Sum('montant'))['total'] or 0

        decaissements = Reglement.objects.filter(
            agence=agence, type_reglement='fournisseur',
            date_reglement__lte=date_cloture,
        ).aggregate(total=Sum('montant'))['total'] or 0

        creances = FactureComptable.objects.filter(
            agence=agence, type_facture='client',
            date_facture__lte=date_cloture,
            status__in=['impayee', 'partielle', 'envoyee'],
        ).aggregate(total=Sum('montant_restant'))['total'] or 0

        dettes = FactureComptable.objects.filter(
            agence=agence, type_facture='fournisseur',
            date_facture__lte=date_cloture,
            status__in=['impayee', 'partielle', 'recue'],
        ).aggregate(total=Sum('montant_restant'))['total'] or 0

        actif = {
            'tresorerie': float(encaissements - decaissements),
            'creances': float(creances),
        }
        passif = {'dettes_fournisseurs': float(dettes)}

        total_actif = sum(actif.values())
        total_passif = sum(passif.values())

        data = {
            'date': date_cloture,
            'agence_id': agence.id,
            'actif': actif,
            'total_actif': total_actif,
            'passif': passif,
            'total_passif': total_passif,
            'est_equilibre': total_actif == total_passif,
        }

        return Response(data)


class TresorerieView(APIView):
    """Vue pour le suivi de trésorerie."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')
        date_debut = request.query_params.get('date_debut')
        date_fin = request.query_params.get('date_fin')

        if not all([agence_id, date_debut, date_fin]):
            return Response(
                {"error": "agence_id, date_debut et date_fin sont requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            agence = Agence.objects.get(id=agence_id)
        except Agence.DoesNotExist:
            return Response(
                {"error": "Agence non trouvée"},
                status=status.HTTP_404_NOT_FOUND
            )

        if not request.user.peut_acceder_agence(int(agence_id)):
            return Response(
                {"error": "Permission denied"},
                status=status.HTTP_403_FORBIDDEN
            )

        # ✅ 4 requêtes au lieu de N
        solde_initial = Reglement.objects.filter(
            agence=agence, date_reglement__lt=date_debut,
        ).aggregate(
            encaissements=Sum('montant', filter=Q(type_reglement='client')),
            decaissements=Sum('montant', filter=Q(type_reglement='fournisseur')),
        )
        solde_init = (
            (solde_initial['encaissements'] or 0) -
            (solde_initial['decaissements'] or 0)
        )

        encaissements_qs = (
            Reglement.objects
            .filter(
                agence=agence, type_reglement='client',
                date_reglement__gte=date_debut,
                date_reglement__lte=date_fin,
            )
            .select_related('client')
        )

        decaissements_qs = (
            Reglement.objects
            .filter(
                agence=agence, type_reglement='fournisseur',
                date_reglement__gte=date_debut,
                date_reglement__lte=date_fin,
            )
            .select_related('fournisseur')
        )

        total_enc = encaissements_qs.aggregate(total=Sum('montant'))['total'] or 0
        total_dec = decaissements_qs.aggregate(total=Sum('montant'))['total'] or 0

        data = {
            'agence_id': agence.id,
            'date_debut': date_debut,
            'date_fin': date_fin,
            'solde_initial': float(solde_init),
            'encaissements': float(total_enc),
            'decaissements': float(total_dec),
            'solde_final': float(solde_init + total_enc - total_dec),
            'details_encaissements': ReglementSerializer(
                encaissements_qs[:100], many=True
            ).data,
            'details_decaissements': ReglementSerializer(
                decaissements_qs[:100], many=True
            ).data,
        }

        return Response(data)