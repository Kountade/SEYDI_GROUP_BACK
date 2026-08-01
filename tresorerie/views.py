# tresorerie/views.py
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q, Sum, Count
from django.utils import timezone
from datetime import timedelta
from .models import *
from .serializers import *
from .permissions import *
from users.permissions import IsPDG, IsDRH, IsPDGOrDRH, IsChefAgence, IsComptable


# ============================================================
# TRÉSORERIE GLOBALE (API View pour le dashboard)
# ============================================================

class TresorerieGlobalView(APIView):
    """Vue pour le solde global de trésorerie"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')

        # Filtrer par agence si spécifié
        caisses_qs = Caisse.objects.filter(is_active=True)
        comptes_qs = CompteBancaire.objects.filter(is_active=True)

        if agence_id:
            caisses_qs = caisses_qs.filter(agence_id=agence_id)
            comptes_qs = comptes_qs.filter(agence_id=agence_id)

        # Calculer les soldes
        solde_caisses = caisses_qs.aggregate(
            total=Sum('solde_actuel'))['total'] or 0
        solde_banques = comptes_qs.aggregate(
            total=Sum('solde_actuel'))['total'] or 0
        solde_global = solde_caisses + solde_banques

        data = {
            'solde_global': solde_global,
            'solde_caisses': solde_caisses,
            'solde_banques': solde_banques,
            'nb_caisses': caisses_qs.count(),
            'nb_comptes': comptes_qs.count()
        }

        serializer = TresorerieGlobalSerializer(data)
        return Response(serializer.data)


# ============================================================
# ALERTES TRÉSORERIE (API View)
# ============================================================

class AlertesTresorerieView(APIView):
    """Vue pour les alertes de trésorerie"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')

        alertes = []

        # Filtrer les caisses par agence
        caisses_qs = Caisse.objects.filter(is_active=True)
        if agence_id:
            caisses_qs = caisses_qs.filter(agence_id=agence_id)

        # Vérifier les caisses sous seuil
        for caisse in caisses_qs:
            if caisse.est_sous_seuil_min:
                alertes.append({
                    'id': f'caisse_{caisse.id}',
                    'type': 'warning',
                    'message': f'Caisse {caisse.nom} sous le seuil minimum ({caisse.solde_actuel} < {caisse.seuil_min})',
                    'est_active': True,
                    'caisse_id': caisse.id,
                    'caisse_nom': caisse.nom
                })
            if caisse.est_sur_seuil_max:
                alertes.append({
                    'id': f'caisse_max_{caisse.id}',
                    'type': 'info',
                    'message': f'Caisse {caisse.nom} dépasse le seuil maximum ({caisse.solde_actuel} > {caisse.seuil_max})',
                    'est_active': True,
                    'caisse_id': caisse.id,
                    'caisse_nom': caisse.nom
                })

        # Vérifier les comptes bancaires avec solde bas
        comptes_qs = CompteBancaire.objects.filter(is_active=True)
        if agence_id:
            comptes_qs = comptes_qs.filter(agence_id=agence_id)

        for compte in comptes_qs:
            if compte.solde_actuel < 0:
                alertes.append({
                    'id': f'compte_{compte.id}',
                    'type': 'error',
                    'message': f'Compte {compte.nom} en négatif ({compte.solde_actuel})',
                    'est_active': True,
                    'compte_id': compte.id,
                    'compte_nom': compte.nom
                })

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

    def get_serializer_class(self):
        if self.action == 'create':
            return CaisseCreateSerializer
        return CaisseSerializer

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return Caisse.objects.filter(is_active=True)
        agences_ids = user.get_agences().values_list('id', flat=True)
        return Caisse.objects.filter(agence_id__in=agences_ids, is_active=True)

    @action(detail=True, methods=['get'])
    def mouvements(self, request, pk=None):
        caisse = self.get_object()
        mouvements = caisse.mouvements.filter(
            status='effectue').order_by('-date_mouvement')
        serializer = MouvementTresorerieSerializer(mouvements, many=True)
        return Response(serializer.data)


# ============================================================
# COMPTE BANCAIRE VIEWSET
# ============================================================

class CompteBancaireViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated,
                          IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['banque', 'nom', 'numero_compte', 'code']
    ordering_fields = ['banque', 'nom', 'solde_actuel']

    # ✅ CORRIGÉ: get_serializer_class avec tous les serializers
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CompteBancaireCreateSerializer
        return CompteBancaireSerializer

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return CompteBancaire.objects.filter(is_active=True)
        agences_ids = user.get_agences().values_list('id', flat=True)
        return CompteBancaire.objects.filter(agence_id__in=agences_ids, is_active=True)

    @action(detail=True, methods=['get'])
    def mouvements(self, request, pk=None):
        compte = self.get_object()
        mouvements = compte.mouvements.filter(
            status='effectue').order_by('-date_mouvement')
        serializer = MouvementTresorerieSerializer(mouvements, many=True)
        return Response(serializer.data)


# ============================================================
# MOUVEMENT DE TRÉSORERIE VIEWSET
# ============================================================

class MouvementTresorerieViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated,
                          IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference', 'libelle', 'source_reference']
    ordering_fields = ['date_mouvement', 'montant', 'created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return MouvementTresorerieCreateSerializer
        return MouvementTresorerieSerializer

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            queryset = MouvementTresorerie.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = MouvementTresorerie.objects.filter(
                agence_id__in=agences_ids)

        # Filtres
        type_mouvement = self.request.query_params.get('type_mouvement')
        if type_mouvement:
            queryset = queryset.filter(type_mouvement=type_mouvement)

        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)

        date_debut = self.request.query_params.get('date_debut')
        if date_debut:
            queryset = queryset.filter(date_mouvement__date__gte=date_debut)

        date_fin = self.request.query_params.get('date_fin')
        if date_fin:
            queryset = queryset.filter(date_mouvement__date__lte=date_fin)

        return queryset.select_related('agence', 'caisse', 'compte_bancaire', 'created_by')

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        mouvement = self.get_object()
        if mouvement.status == 'effectue':
            return Response({"error": "Ce mouvement est déjà effectué"}, status=status.HTTP_400_BAD_REQUEST)

        mouvement.status = 'effectue'
        mouvement.valide_par = request.user
        mouvement.date_validation = timezone.now()
        mouvement._mettre_a_jour_soldes()
        mouvement.save()

        serializer = self.get_serializer(mouvement)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        mouvement = self.get_object()
        if mouvement.status == 'effectue':
            # Inverser les soldes
            if mouvement.caisse:
                if mouvement.type_mouvement == 'encaissement':
                    mouvement.caisse.solde_actuel -= mouvement.montant
                else:
                    mouvement.caisse.solde_actuel += mouvement.montant
                mouvement.caisse.save()

            if mouvement.compte_bancaire:
                if mouvement.type_mouvement == 'encaissement':
                    mouvement.compte_bancaire.solde_actuel -= mouvement.montant
                else:
                    mouvement.compte_bancaire.solde_actuel += mouvement.montant
                mouvement.compte_bancaire.save()

        mouvement.status = 'annule'
        mouvement.save()

        serializer = self.get_serializer(mouvement)
        return Response(serializer.data)


# ============================================================
# FRAIS VIEWSET
# ============================================================
class FraisViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated,
                          IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference', 'titre', 'beneficiaire']
    ordering_fields = ['date_frais', 'montant', 'created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return FraisCreateSerializer
        return FraisSerializer

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            queryset = Frais.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = Frais.objects.filter(agence_id__in=agences_ids)

        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)

        categorie = self.request.query_params.get('categorie')
        if categorie:
            queryset = queryset.filter(categorie=categorie)

        return queryset.select_related('agence', 'created_by')

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        frais = self.get_object()
        if frais.status == 'valide':
            return Response({"error": "Ce frais est déjà validé"}, status=status.HTTP_400_BAD_REQUEST)

        frais.status = 'valide'
        frais.valide_par = request.user
        frais.date_validation = timezone.now()
        frais.save()

        serializer = self.get_serializer(frais)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def payer(self, request, pk=None):
        frais = self.get_object()
        if frais.status == 'paye':
            return Response({"error": "Ce frais est déjà payé"}, status=status.HTTP_400_BAD_REQUEST)

        frais.status = 'paye'
        frais.date_paiement = timezone.now().date()
        frais.save()

        serializer = self.get_serializer(frais)
        return Response(serializer.data)
# ============================================================
# PRÉVISIONS VIEWSET
# ============================================================


class PrevisionTresorerieViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated,
                          IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference', 'titre']
    ordering_fields = ['date_debut', 'montant_prevu', 'created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PrevisionTresorerieCreateSerializer
        return PrevisionTresorerieSerializer

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            queryset = PrevisionTresorerie.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = PrevisionTresorerie.objects.filter(
                agence_id__in=agences_ids)

        type_prevision = self.request.query_params.get('type_prevision')
        if type_prevision:
            queryset = queryset.filter(type_prevision=type_prevision)

        statut = self.request.query_params.get('statut')
        if statut:
            queryset = queryset.filter(statut=statut)

        return queryset.select_related('agence', 'created_by')


# ============================================================
# RAPPROCHEMENT VIEWSET
# ============================================================

class RapprochementBancaireViewset(viewsets.ModelViewSet):
    permission_classes = [
        permissions.IsAuthenticated, IsPDGOrDRH | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference']
    ordering_fields = ['date_debut', 'created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return RapprochementBancaireCreateSerializer
        return RapprochementBancaireSerializer

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            queryset = RapprochementBancaire.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = RapprochementBancaire.objects.filter(
                agence_id__in=agences_ids)

        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)

        return queryset.select_related('agence', 'compte_bancaire', 'created_by')

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        rapprochement = self.get_object()
        if rapprochement.status == 'complete':
            return Response({"error": "Ce rapprochement est déjà complet"}, status=status.HTTP_400_BAD_REQUEST)

        rapprochement.status = 'complete'
        rapprochement.valide_par = request.user
        rapprochement.date_validation = timezone.now()
        rapprochement.save()

        serializer = self.get_serializer(rapprochement)
        return Response(serializer.data)


# ============================================================
# TRÉSORERIE JOURNALIÈRE VIEWSET
# ============================================================

class TresorerieJournaliereViewset(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated,
                          IsPDGOrDRH | IsChefAgence | IsComptable]
    serializer_class = TresorerieJournaliereSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['date']

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            queryset = TresorerieJournaliere.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = TresorerieJournaliere.objects.filter(
                agence_id__in=agences_ids)

        date_debut = self.request.query_params.get('date_debut')
        if date_debut:
            queryset = queryset.filter(date__gte=date_debut)

        date_fin = self.request.query_params.get('date_fin')
        if date_fin:
            queryset = queryset.filter(date__lte=date_fin)

        return queryset.select_related('agence')
