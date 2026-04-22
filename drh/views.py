from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from datetime import date

from .models import (
    Departement, Poste, Employe, Contrat,
    TypeConge, DemandeConge, Pointage
)
from .serializers import (
    DepartementSerializer, PosteSerializer,
    EmployeListSerializer, EmployeSerializer, EmployeCreateSerializer,
    ContratSerializer, TypeCongeSerializer,
    DemandeCongeSerializer, PointageSerializer
)


# ============================================================
# PERMISSIONS
# ============================================================

class IsDRHOrPDG(permissions.BasePermission):
    """Permission pour DRH ou PDG uniquement"""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role_global in ['pdg', 'drh']


# ============================================================
# VIEWSETS DE BASE
# ============================================================

class DepartementViewSet(viewsets.ModelViewSet):
    queryset = Departement.objects.all()
    serializer_class = DepartementSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['agence', 'est_actif']
    search_fields = ['nom', 'code']


class PosteViewSet(viewsets.ModelViewSet):
    queryset = Poste.objects.all()
    serializer_class = PosteSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['departement', 'niveau', 'est_actif']
    search_fields = ['nom', 'code']


# ============================================================
# VIEWSETS EMPLOYÉ
# ============================================================

class EmployeViewSet(viewsets.ModelViewSet):
    queryset = Employe.objects.select_related('poste', 'departement', 'agence', 'user')
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['agence', 'departement', 'poste', 'est_actif', 'sexe']
    search_fields = ['nom', 'prenom', 'email', 'matricule']
    ordering_fields = ['nom', 'prenom', 'date_embauche']

    def get_serializer_class(self):
        if self.action == 'list':
            return EmployeListSerializer
        elif self.action == 'create':
            return EmployeCreateSerializer
        return EmployeSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsDRHOrPDG()]
        return [permissions.IsAuthenticated()]

    @action(detail=True, methods=['get'])
    def contrats(self, request, pk=None):
        employe = self.get_object()
        contrats = employe.contrats.all()
        serializer = ContratSerializer(contrats, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def pointages(self, request, pk=None):
        employe = self.get_object()
        pointages = employe.pointages.all()[:50]
        serializer = PointageSerializer(pointages, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def demandes_conges(self, request, pk=None):
        employe = self.get_object()
        demandes = employe.demandes_conges.all()
        serializer = DemandeCongeSerializer(demandes, many=True)
        return Response(serializer.data)


# ============================================================
# VIEWSETS CONTRAT
# ============================================================

class ContratViewSet(viewsets.ModelViewSet):
    queryset = Contrat.objects.select_related('employe')
    serializer_class = ContratSerializer
    permission_classes = [permissions.IsAuthenticated, IsDRHOrPDG]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['employe', 'type_contrat', 'statut']
    search_fields = ['reference', 'employe__nom', 'employe__prenom']

    @action(detail=True, methods=['post'])
    def signer(self, request, pk=None):
        contrat = self.get_object()
        contrat.statut = 'signe'
        contrat.date_signature = date.today()
        contrat.save()
        return Response({'message': 'Contrat signé'})

    @action(detail=True, methods=['post'])
    def terminer(self, request, pk=None):
        contrat = self.get_object()
        contrat.statut = 'termine'
        contrat.save()
        return Response({'message': 'Contrat terminé'})


# ============================================================
# VIEWSETS CONGÉS
# ============================================================

class TypeCongeViewSet(viewsets.ModelViewSet):
    queryset = TypeConge.objects.all()
    serializer_class = TypeCongeSerializer
    permission_classes = [permissions.IsAuthenticated, IsDRHOrPDG]
    filter_backends = [filters.SearchFilter]
    search_fields = ['nom', 'code']


class DemandeCongeViewSet(viewsets.ModelViewSet):
    queryset = DemandeConge.objects.select_related('employe', 'type_conge')
    serializer_class = DemandeCongeSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['employe', 'type_conge', 'statut']

    def get_permissions(self):
        if self.action in ['create', 'destroy']:
            return [permissions.IsAuthenticated()]
        return [IsDRHOrPDG()]

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        demande = self.get_object()
        demande.statut = 'validee'
        demande.save()
        return Response({'message': 'Demande validée'})

    @action(detail=True, methods=['post'])
    def refuser(self, request, pk=None):
        demande = self.get_object()
        demande.statut = 'refusee'
        demande.motif_refus = request.data.get('motif_refus', '')
        demande.save()
        return Response({'message': 'Demande refusée'})


# ============================================================
# VIEWSETS POINTAGE
# ============================================================

class PointageViewSet(viewsets.ModelViewSet):
    queryset = Pointage.objects.select_related('employe')
    serializer_class = PointageSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['employe', 'type_pointage']

    def get_queryset(self):
        queryset = super().get_queryset()
        date_debut = self.request.query_params.get('date_debut')
        date_fin = self.request.query_params.get('date_fin')
        if date_debut:
            queryset = queryset.filter(date_heure__date__gte=date_debut)
        if date_fin:
            queryset = queryset.filter(date_heure__date__lte=date_fin)
        return queryset

    @action(detail=False, methods=['post'])
    def pointer(self, request):
        try:
            employe = Employe.objects.get(user=request.user)
        except Employe.DoesNotExist:
            return Response({'error': 'Employé non trouvé'}, status=404)

        pointage = Pointage.objects.create(
            employe=employe,
            type_pointage=request.data.get('type_pointage', 'entree')
        )
        serializer = self.get_serializer(pointage)
        return Response(serializer.data, status=201)


# ============================================================
# VIEWSETS STATISTIQUES
# ============================================================

class StatistiquesViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, IsDRHOrPDG]

    def list(self, request):
        return Response({
            'total_employes': Employe.objects.count(),
            'employes_actifs': Employe.objects.filter(est_actif=True).count(),
            'total_departements': Departement.objects.filter(est_actif=True).count(),
            'total_postes': Poste.objects.filter(est_actif=True).count(),
            'contrats_en_cours': Contrat.objects.filter(statut='en_cours').count(),
            'demandes_en_attente': DemandeConge.objects.filter(statut='en_attente').count(),
            'hommes': Employe.objects.filter(sexe='M', est_actif=True).count(),
            'femmes': Employe.objects.filter(sexe='F', est_actif=True).count(),
        })