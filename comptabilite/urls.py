# comptabilite/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register(r'plan-comptable', PlanComptableViewset, basename='plan-comptable')
router.register(r'journaux', JournalViewset, basename='journal')
router.register(r'ecritures', EcritureViewset, basename='ecriture')
router.register(r'balances', BalanceViewset, basename='balance')
router.register(r'factures-comptables', FactureComptableViewset, basename='facture-comptable')
router.register(r'reglements', ReglementViewset, basename='reglement')
router.register(r'indicateurs', IndicateurViewset, basename='indicateur')
router.register(r'clotures', ClotureViewset, basename='cloture')
router.register(r'analyses', AnalyseViewset, basename='analyse')

urlpatterns = [
    path('', include(router.urls)),

    # ✅ AJOUTER L'URL DIRECTE POUR TRESORERIE
    path('tresorerie/', TresorerieView.as_view(), name='tresorerie'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('compte-resultat/', CompteResultatView.as_view(), name='compte-resultat'),
    path('bilan/', BilanView.as_view(), name='bilan'),
]