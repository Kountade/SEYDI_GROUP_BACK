# sales/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register('clients', ClientViewSet, basename='clients')
router.register('ventes', VenteViewSet, basename='ventes')
router.register('paiements', PaiementViewSet, basename='paiements')
router.register('factures', FactureViewSet, basename='factures')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/ventes/', DashboardVentesView.as_view(), name='dashboard-ventes'),
]