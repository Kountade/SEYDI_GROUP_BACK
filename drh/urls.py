from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DepartementViewSet, PosteViewSet, EmployeViewSet,
    ContratViewSet, TypeCongeViewSet, DemandeCongeViewSet,
    PointageViewSet, StatistiquesViewSet
)

router = DefaultRouter()

# Routes de base
router.register('departements', DepartementViewSet, basename='departements')
router.register('postes', PosteViewSet, basename='postes')
router.register('employes', EmployeViewSet, basename='employes')

# Routes contrat
router.register('contrats', ContratViewSet, basename='contrats')

# Routes congés
router.register('types-conges', TypeCongeViewSet, basename='types-conges')
router.register('demandes-conges', DemandeCongeViewSet,
                basename='demandes-conges')

# Routes pointage
router.register('pointages', PointageViewSet, basename='pointages')

# Route statistiques
router.register('statistiques', StatistiquesViewSet, basename='statistiques')

urlpatterns = [
    path('', include(router.urls)),
]
