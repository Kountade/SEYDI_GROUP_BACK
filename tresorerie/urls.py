# tresorerie/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    TresorerieGlobalView, AlertesTresorerieView,
    TresorerieDashboardView,          # ✅ AJOUT
    CaisseViewset, CompteBancaireViewset,
    MouvementTresorerieViewset, FraisViewset,
    PrevisionTresorerieViewset, RapprochementBancaireViewset,
    TresorerieJournaliereViewset,
)

router = DefaultRouter()
router.register('caisses', CaisseViewset, basename='caisses')
router.register('comptes-bancaires', CompteBancaireViewset,
                basename='comptes-bancaires')
router.register('mouvements', MouvementTresorerieViewset,
                basename='mouvements')
router.register('frais', FraisViewset, basename='frais')
router.register('previsions', PrevisionTresorerieViewset,
                basename='previsions')
router.register('rapprochements', RapprochementBancaireViewset,
                basename='rapprochements')
router.register('tresorerie-journaliere',
                TresorerieJournaliereViewset, basename='tresorerie-journaliere')

urlpatterns = [
    # ✅ ALIAS : /tresorerie/?agence_id=X → dashboard global
    path('tresorerie/', TresorerieDashboardView.as_view(),
         name='tresorerie-dashboard'),
    path('tresorerie/global/', TresorerieGlobalView.as_view(),
         name='tresorerie-global'),
    path('tresorerie/alertes/', AlertesTresorerieView.as_view(),
         name='tresorerie-alertes'),
    path('', include(router.urls)),
]
