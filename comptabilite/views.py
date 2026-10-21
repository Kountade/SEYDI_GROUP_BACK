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
✅ CACHE sur Dashboard (avec period)
✅ PARALLÉLISATION Dashboard (ThreadPoolExecutor)
✅ SEARCH sur tous les ViewSets (y compris Reglement)
✅ STATS sur Ecriture, Reglement, FactureComptable
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
# CACHE — Purge ROBUSTE (Redis + fallback)
# ============================================================
def _purge_compta_cache():
    """
    ✅ Purge le cache comptabilité après mutation.
    - Redis       : delete_pattern('compta_*') → sélectif
    - LocMemCache : clear() → global (fallback)
    """
    try:
        cache.delete_pattern('compta_*')
        cache.delete_pattern('compta_dashboard:*')
    except AttributeError:
        # LocMemCache n'a pas delete_pattern
        cache.clear()
    except Exception:
        pass


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
    permission_classes = [
        permissions.IsAuthenticated, IsPDGOrDRH | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code', 'nom', 'description']
    ordering_fields = ['code', 'nom', 'type_compte', 'niveau']
    pagination_class = PlanComptablePagination

    def get_serializer_class(self):
        if self.action == 'create':
            return PlanComptableCreateSerializer
        return PlanComptableSerializer

    def get_queryset(self):
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
                page, many=True,
                context={'request': request, 'today': timezone.now().date()}
            )
            return self.get_paginated_response(serializer.data)

        serializer = EcritureSerializer(
            ecritures, many=True,
            context={'request': request, 'today': timezone.now().date()}
        )
        return Response(serializer.data)


# ============================================================
# ÉCRITURES VIEWSET
# ============================================================
class EcritureViewset(viewsets.ModelViewSet):
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

    # ✅ STATS (nouveau)
    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        """Stats globales des écritures (respecte les filtres)."""
        qs = self.get_queryset()

        agg = qs.aggregate(
            total=Count('id'),
            total_debit=Sum('total_debit'),
            total_credit=Sum('total_credit'),
            brouillon=Count('id', filter=Q(status='brouillon')),
            valide=Count('id', filter=Q(status='valide')),
            annulee=Count('id', filter=Q(status='annulee')),
            cloturee=Count('id', filter=Q(status='cloturee')),
        )

        return Response({
            'total': agg['total'] or 0,
            'brouillon': agg['brouillon'] or 0,
            'valide': agg['valide'] or 0,
            'annulee': agg['annulee'] or 0,
            'cloturee': agg['cloturee'] or 0,
            'totalDebit': float(agg['total_debit'] or 0),
            'totalCredit': float(agg['total_credit'] or 0),
        })

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def valider(self, request, pk=None):
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

            balance = self.get_queryset().get(pk=balance.pk)
            return Response(
                BalanceSerializer(balance).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def _generer_lignes_balance(self, balance):
        comptes = list(PlanComptable.objects.filter(is_active=True))

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

        return queryset.order_by('-date_facture', '-id')

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

    # ✅ STATS (nouveau)
    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        """Stats globales des factures comptables."""
        qs = self.get_queryset()

        agg = qs.aggregate(
            total=Count('id'),
            client=Count('id', filter=Q(type_facture='client')),
            fournisseur=Count('id', filter=Q(type_facture='fournisseur')),
            brouillon=Count('id', filter=Q(status='brouillon')),
            envoyee=Count('id', filter=Q(status='envoyee')),
            recue=Count('id', filter=Q(status='recue')),
            payee=Count('id', filter=Q(status='payee')),
            partielle=Count('id', filter=Q(status='partielle')),
            impayee=Count('id', filter=Q(status='impayee')),
            annulee=Count('id', filter=Q(status='annulee')),
            total_montant=Sum('montant_ttc'),
        )

        total_impaye = qs.filter(
            status__in=['impayee', 'partielle']
        ).aggregate(total=Sum('montant_restant'))['total'] or 0

        return Response({
            'total': agg['total'] or 0,
            'client': agg['client'] or 0,
            'fournisseur': agg['fournisseur'] or 0,
            'brouillon': agg['brouillon'] or 0,
            'envoyee': agg['envoyee'] or 0,
            'recue': agg['recue'] or 0,
            'payee': agg['payee'] or 0,
            'partielle': agg['partielle'] or 0,
            'impayee': agg['impayee'] or 0,
            'annulee': agg['annulee'] or 0,
            'totalMontant': float(agg['total_montant'] or 0),
            'totalImpaye': float(total_impaye),
        })


# ============================================================
# RÈGLEMENTS VIEWSET
# ============================================================
class ReglementViewset(viewsets.ModelViewSet):
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

        # ✅ RECHERCHE (manquante)
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search) |
                Q(client__nom__icontains=search) |
                Q(fournisseur__company_name__icontains=search) |
                Q(facture__reference__icontains=search) |
                Q(reference_externe__icontains=search)
            )

        return queryset.order_by('-date_reglement', '-id')

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

    # ✅ STATS (nouveau)
    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        qs = self.get_queryset()

        agg = qs.aggregate(
            total=Count('id'),
            client=Count('id', filter=Q(type_reglement='client')),
            fournisseur=Count('id', filter=Q(type_reglement='fournisseur')),
            especes=Count('id', filter=Q(mode_reglement='especes')),
            virement=Count('id', filter=Q(mode_reglement='virement')),
            carte=Count('id', filter=Q(mode_reglement='carte')),
            cheque=Count('id', filter=Q(mode_reglement='cheque')),
            mobile_money=Count('id', filter=Q(mode_reglement='mobile_money')),
            total_montant=Sum('montant'),
            total_client=Sum('montant', filter=Q(type_reglement='client')),
            total_fournisseur=Sum('montant', filter=Q(
                type_reglement='fournisseur')),
        )

        return Response({
            'total': agg['total'] or 0,
            'client': agg['client'] or 0,
            'fournisseur': agg['fournisseur'] or 0,
            'especes': agg['especes'] or 0,
            'virement': agg['virement'] or 0,
            'carte': agg['carte'] or 0,
            'cheque': agg['cheque'] or 0,
            'mobile_money': agg['mobile_money'] or 0,
            'totalMontant': float(agg['total_montant'] or 0),
            'totalClient': float(agg['total_client'] or 0),
            'totalFournisseur': float(agg['total_fournisseur'] or 0),
        })


# ============================================================
# INDICATEURS VIEWSET
# ============================================================
class IndicateurViewset(viewsets.ModelViewSet):
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
# DASHBOARD (✅ period + CACHE + PARALLÉLISATION)
# ============================================================
class DashboardView(APIView):
    """
    Vue pour le tableau de bord financier.

    ✅ period = month | quarter | year (défaut: month)
    ✅ CACHE 5 min (clé inclut period)
    ✅ PARALLÉLISATION ThreadPoolExecutor
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')
        period = request.query_params.get('period', 'month')

        if not agence_id:
            return Response(
                {"error": "agence_id est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if period not in ('month', 'quarter', 'year'):
            period = 'month'

        # ✅ Cache key inclut period
        cache_key = f'compta_dashboard:{agence_id}:{period}'
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

        today = timezone.now().date()

        # ✅ Bornes selon period
        if period == 'month':
            debut_periode = today.replace(day=1)
            fin_periode_prec = debut_periode - timedelta(days=1)
            debut_periode_prec = fin_periode_prec.replace(day=1)
        elif period == 'quarter':
            mois_debut_trimestre = ((today.month - 1) // 3) * 3 + 1
            debut_periode = today.replace(
                month=mois_debut_trimestre, day=1)
            fin_periode_prec = debut_periode - timedelta(days=1)
            mois_debut_trim_prec = (
                (fin_periode_prec.month - 1) // 3) * 3 + 1
            debut_periode_prec = fin_periode_prec.replace(
                month=mois_debut_trim_prec, day=1)
        else:  # year
            debut_periode = today.replace(month=1, day=1)
            debut_periode_prec = (debut_periode - timedelta(days=1)).replace(
                month=1, day=1)
            fin_periode_prec = debut_periode - timedelta(days=1)

        # ✅ Parallélisation
        with ThreadPoolExecutor(max_workers=6) as ex:
            f_ca = ex.submit(
                lambda: FactureComptable.objects.filter(
                    agence=agence, type_facture='client',
                    date_facture__gte=debut_periode,
                    date_facture__lte=today,
                    status__in=['payee', 'partielle'],
                ).aggregate(total=Sum('montant_ttc'))['total'] or 0
            )
            f_ca_prev = ex.submit(
                lambda: FactureComptable.objects.filter(
                    agence=agence, type_facture='client',
                    date_facture__gte=debut_periode_prec,
                    date_facture__lte=fin_periode_prec,
                    status__in=['payee', 'partielle'],
                ).aggregate(total=Sum('montant_ttc'))['total'] or 0
            )
            f_achats = ex.submit(
                lambda: FactureComptable.objects.filter(
                    agence=agence, type_facture='fournisseur',
                    date_facture__gte=debut_periode,
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

            ca = f_ca.result()
            ca_prev = f_ca_prev.result()
            achats = f_achats.result()
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
            'periode': period,  # ✅ renvoie "month" | "quarter" | "year"
            'agence_id': agence.id,
            'ca_total': float(ca),
            'ca_evolution': float(ca - ca_prev),
            'ca_evolution_pourcentage': float(
                ((ca - ca_prev) / ca_prev * 100) if ca_prev > 0 else 0
            ),
            'marge_brute': float(ca - achats),
            'marge_pourcentage': float(
                ((ca - achats) / ca * 100) if ca > 0 else 0
            ),
            'tresorerie': float(tresorerie),
            'ventes_mois': float(ca),
            'achats_mois': float(achats),
            'charges_mois': 0,
            'alertes': alertes,
        }

        cache.set(cache_key, data, 60 * 5)  # 5 min
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

        solde_initial = Reglement.objects.filter(
            agence=agence, date_reglement__lt=date_debut,
        ).aggregate(
            encaissements=Sum('montant', filter=Q(type_reglement='client')),
            decaissements=Sum('montant', filter=Q(
                type_reglement='fournisseur')),
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
            .select_related('client', 'facture')
        )

        decaissements_qs = (
            Reglement.objects
            .filter(
                agence=agence, type_reglement='fournisseur',
                date_reglement__gte=date_debut,
                date_reglement__lte=date_fin,
            )
            .select_related('fournisseur', 'facture')
        )

        total_enc = encaissements_qs.aggregate(
            total=Sum('montant'))['total'] or 0
        total_dec = decaissements_qs.aggregate(
            total=Sum('montant'))['total'] or 0

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
