# tresorerie/views.py

from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import Q, Sum, Count, F
from django.core.cache import cache
from django.utils import timezone

from .models import *
from .serializers import *
from .pagination import (
    CaissePagination, ComptePagination, MouvementPagination,
    FraisPagination, PrevisionPagination, RapprochementPagination,
    TresorerieJournalierePagination,
)
from .permissions import *
from users.permissions import IsPDG, IsDRH, IsPDGOrDRH, IsChefAgence, IsComptable


# ============================================================
# CACHE
# ============================================================
def _purge_tresorerie_cache():
    try:
        cache.delete_pattern('tresorerie_*')
    except Exception:
        cache.clear()


# ============================================================
# TRÉSORERIE GLOBALE (CACHE 60s)
# ============================================================
class TresorerieGlobalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')
        cache_key = f'tresorerie_global_{agence_id or "all"}'

        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        caisses_qs = Caisse.objects.filter(is_active=True)
        comptes_qs = CompteBancaire.objects.filter(is_active=True)

        if agence_id:
            caisses_qs = caisses_qs.filter(agence_id=agence_id)
            comptes_qs = comptes_qs.filter(agence_id=agence_id)

        caisses_agg = caisses_qs.aggregate(
            solde=Sum('solde_actuel'), count=Count('id'),
        )
        comptes_agg = comptes_qs.aggregate(
            solde=Sum('solde_actuel'), count=Count('id'),
        )

        solde_caisses = caisses_agg['solde'] or 0
        solde_banques = comptes_agg['solde'] or 0

        data = {
            'solde_global': solde_caisses + solde_banques,
            'solde_caisses': solde_caisses,
            'solde_banques': solde_banques,
            'nb_caisses': caisses_agg['count'] or 0,
            'nb_comptes': comptes_agg['count'] or 0,
        }

        cache.set(cache_key, data, 60)
        serializer = TresorerieGlobalSerializer(data)
        return Response(serializer.data)


# ============================================================
# ALERTES TRÉSORERIE (CACHE 60s)
# ============================================================
class AlertesTresorerieView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')
        cache_key = f'tresorerie_alertes_{agence_id or "all"}'

        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        alertes = []

        caisses_qs = Caisse.objects.filter(is_active=True)
        if agence_id:
            caisses_qs = caisses_qs.filter(agence_id=agence_id)

        # ✅ Filtrage 100 % SQL (pas de boucle Python)
        caisses_sous_seuil = caisses_qs.filter(solde_actuel__lt=F('seuil_min'))
        caisses_sur_seuil = caisses_qs.filter(
            seuil_max__gt=0, solde_actuel__gt=F('seuil_max')
        )

        for c in caisses_sous_seuil.values('id', 'nom', 'solde_actuel', 'seuil_min'):
            alertes.append({
                'id': f"caisse_{c['id']}",
                'type': 'warning',
                'message': f"Caisse {c['nom']} sous le seuil minimum "
                           f"({c['solde_actuel']} < {c['seuil_min']})",
                           'est_active': True,
                           'caisse_id': c['id'],
                           'caisse_nom': c['nom'],
                           })

        for c in caisses_sur_seuil.values('id', 'nom', 'solde_actuel', 'seuil_max'):
            alertes.append({
                'id': f"caisse_max_{c['id']}",
                'type': 'info',
                'message': f"Caisse {c['nom']} dépasse le seuil maximum "
                           f"({c['solde_actuel']} > {c['seuil_max']})",
                           'est_active': True,
                           'caisse_id': c['id'],
                           'caisse_nom': c['nom'],
                           })

        comptes_qs = CompteBancaire.objects.filter(is_active=True)
        if agence_id:
            comptes_qs = comptes_qs.filter(agence_id=agence_id)

        comptes_negatifs = comptes_qs.filter(solde_actuel__lt=0)
        for c in comptes_negatifs.values('id', 'nom', 'solde_actuel'):
            alertes.append({
                'id': f"compte_{c['id']}",
                'type': 'error',
                'message': f"Compte {c['nom']} en négatif ({c['solde_actuel']})",
                'est_active': True,
                'compte_id': c['id'],
                'compte_nom': c['nom'],
            })

        cache.set(cache_key, alertes, 60)
        return Response(alertes)


# ============================================================
# CAISSE VIEWSET
# ============================================================
class CaisseViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated,
                          IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code', 'nom', 'description']
    ordering_fields = ['code', 'nom', 'solde_actuel']
    pagination_class = CaissePagination

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CaisseCreateSerializer
        return CaisseSerializer

    def get_queryset(self):
        user = self.request.user
        qs = (
            Caisse.objects
            .select_related('agence', 'responsable', 'created_by')
            .annotate(
                mouvements_count_annotated=Count(
                    'mouvements',
                    filter=Q(mouvements__status='effectue'),
                    distinct=True,
                )
            )
        )

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            qs = qs.filter(agence_id__in=agences_ids)

        return qs.filter(is_active=True)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_tresorerie_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_tresorerie_cache()

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        _purge_tresorerie_cache()

    @action(detail=True, methods=['get'])
    def mouvements(self, request, pk=None):
        caisse = self.get_object()
        qs = (
            caisse.mouvements
            .filter(status='effectue')
            .select_related('agence', 'caisse', 'compte_bancaire', 'created_by', 'valide_par')
            .order_by('-date_mouvement')
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(
                MouvementTresorerieSerializer(page, many=True).data
            )
        return Response(MouvementTresorerieSerializer(qs, many=True).data)


# ============================================================
# COMPTE BANCAIRE VIEWSET
# ============================================================
class CompteBancaireViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated,
                          IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['banque', 'nom', 'numero_compte', 'code']
    ordering_fields = ['banque', 'nom', 'solde_actuel']
    pagination_class = ComptePagination

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CompteBancaireCreateSerializer
        return CompteBancaireSerializer

    def get_queryset(self):
        user = self.request.user
        qs = CompteBancaire.objects.select_related('agence', 'created_by')

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            qs = qs.filter(agence_id__in=agences_ids)

        return qs.filter(is_active=True)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_tresorerie_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_tresorerie_cache()

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        _purge_tresorerie_cache()

    @action(detail=True, methods=['get'])
    def mouvements(self, request, pk=None):
        compte = self.get_object()
        qs = (
            compte.mouvements
            .filter(status='effectue')
            .select_related('agence', 'caisse', 'compte_bancaire', 'created_by', 'valide_par')
            .order_by('-date_mouvement')
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(
                MouvementTresorerieSerializer(page, many=True).data
            )
        return Response(MouvementTresorerieSerializer(qs, many=True).data)


# ============================================================
# MOUVEMENT DE TRÉSORERIE VIEWSET
# ============================================================
class MouvementTresorerieViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated,
                          IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference', 'libelle', 'source_reference']
    ordering_fields = ['date_mouvement', 'montant', 'created_at']
    pagination_class = MouvementPagination

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return MouvementTresorerieCreateSerializer
        return MouvementTresorerieSerializer

    def get_queryset(self):
        user = self.request.user
        qs = (
            MouvementTresorerie.objects
            .select_related('agence', 'caisse', 'compte_bancaire',
                            'created_by', 'valide_par', 'ecriture')
        )

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            qs = qs.filter(agence_id__in=agences_ids)

        params = self.request.query_params

        t = params.get('type_mouvement')
        if t:
            qs = qs.filter(type_mouvement=t)

        s = params.get('status')
        if s:
            qs = qs.filter(status=s)

        date_debut = params.get('date_debut')
        if date_debut:
            qs = qs.filter(date_mouvement__date__gte=date_debut)

        date_fin = params.get('date_fin')
        if date_fin:
            qs = qs.filter(date_mouvement__date__lte=date_fin)

        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_tresorerie_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_tresorerie_cache()

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        mouvement = self.get_object()
        if mouvement.status == 'effectue':
            return Response(
                {"error": "Ce mouvement est déjà effectué"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mouvement.status = 'effectue'
        mouvement.valide_par = request.user
        mouvement.date_validation = timezone.now()
        # ✅ La méthode save() du modèle gère les soldes → pas d'appel manuel
        mouvement.save()
        _purge_tresorerie_cache()

        return Response(self.get_serializer(mouvement).data)

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        mouvement = self.get_object()
        # ✅ La méthode save() gère l'inversion si ancien=effectue → nouveau!=effectue
        mouvement.status = 'annule'
        mouvement.save()
        _purge_tresorerie_cache()

        return Response(self.get_serializer(mouvement).data)


# ============================================================
# FRAIS VIEWSET
# ============================================================
class FraisViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated,
                          IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference', 'titre', 'beneficiaire']
    ordering_fields = ['date_frais', 'montant', 'created_at']
    pagination_class = FraisPagination

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return FraisCreateSerializer
        return FraisSerializer

    def get_queryset(self):
        user = self.request.user
        qs = (
            Frais.objects
            .select_related(
                'agence', 'created_by', 'valide_par',
                'caisse_destination', 'compte_destination', 'mouvement',
            )
        )

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            qs = qs.filter(agence_id__in=agences_ids)

        params = self.request.query_params

        s = params.get('status')
        if s:
            qs = qs.filter(status=s)

        c = params.get('categorie')
        if c:
            qs = qs.filter(categorie=c)

        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_tresorerie_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_tresorerie_cache()

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        frais = self.get_object()
        if frais.status == 'valide':
            return Response(
                {"error": "Ce frais est déjà validé"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        frais.status = 'valide'
        frais.valide_par = request.user
        frais.date_validation = timezone.now()
        frais.save()
        _purge_tresorerie_cache()
        return Response(self.get_serializer(frais).data)

    @action(detail=True, methods=['post'])
    def payer(self, request, pk=None):
        frais = self.get_object()
        if frais.status == 'paye':
            return Response(
                {"error": "Ce frais est déjà payé"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        frais.status = 'paye'
        frais.date_paiement = timezone.now().date()
        # ✅ Le save() du modèle crée le mouvement de trésorerie associé
        frais.save()
        _purge_tresorerie_cache()
        return Response(self.get_serializer(frais).data)


# ============================================================
# PRÉVISIONS VIEWSET
# ============================================================
class PrevisionTresorerieViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated,
                          IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference', 'titre']
    ordering_fields = ['date_debut', 'montant_prevu', 'created_at']
    pagination_class = PrevisionPagination

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PrevisionTresorerieCreateSerializer
        return PrevisionTresorerieSerializer

    def get_queryset(self):
        user = self.request.user
        qs = PrevisionTresorerie.objects.select_related('agence', 'created_by')

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            qs = qs.filter(agence_id__in=agences_ids)

        params = self.request.query_params

        tp = params.get('type_prevision')
        if tp:
            qs = qs.filter(type_prevision=tp)

        s = params.get('statut')
        if s:
            qs = qs.filter(statut=s)

        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_tresorerie_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_tresorerie_cache()


# ============================================================
# RAPPROCHEMENT VIEWSET
# ============================================================
class RapprochementBancaireViewset(viewsets.ModelViewSet):
    permission_classes = [
        permissions.IsAuthenticated, IsPDGOrDRH | IsComptable,
    ]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference']
    ordering_fields = ['date_debut', 'created_at']
    pagination_class = RapprochementPagination

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return RapprochementBancaireCreateSerializer
        return RapprochementBancaireSerializer

    def get_queryset(self):
        user = self.request.user
        qs = RapprochementBancaire.objects.select_related(
            'agence', 'compte_bancaire', 'created_by', 'valide_par',
        )

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            qs = qs.filter(agence_id__in=agences_ids)

        s = self.request.query_params.get('status')
        if s:
            qs = qs.filter(status=s)

        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _purge_tresorerie_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_tresorerie_cache()

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        rapprochement = self.get_object()
        if rapprochement.status == 'complete':
            return Response(
                {"error": "Ce rapprochement est déjà complet"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rapprochement.status = 'complete'
        rapprochement.valide_par = request.user
        rapprochement.date_validation = timezone.now()
        rapprochement.save()
        _purge_tresorerie_cache()
        return Response(self.get_serializer(rapprochement).data)


# ============================================================
# TRÉSORERIE JOURNALIÈRE VIEWSET
# ============================================================
class TresorerieJournaliereViewset(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated,
                          IsPDGOrDRH | IsChefAgence | IsComptable]
    serializer_class = TresorerieJournaliereSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['date']
    pagination_class = TresorerieJournalierePagination

    def get_queryset(self):
        user = self.request.user
        qs = TresorerieJournaliere.objects.select_related('agence')

        if not (user.est_pdg() or user.est_drh()):
            agences_ids = user.get_agences().values_list('id', flat=True)
            qs = qs.filter(agence_id__in=agences_ids)

        params = self.request.query_params

        date_debut = params.get('date_debut')
        if date_debut:
            qs = qs.filter(date__gte=date_debut)

        date_fin = params.get('date_fin')
        if date_fin:
            qs = qs.filter(date__lte=date_fin)

        return qs
