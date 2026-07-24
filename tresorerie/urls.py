from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register(r'caisses', CaisseViewset, basename='caisse')
router.register(r'comptes-bancaires', CompteBancaireViewset,
                basename='compte-bancaire')
router.register(r'mouvements', MouvementTresorerieViewset,
                basename='mouvement-tresorerie')
router.register(r'frais', FraisViewset, basename='frais')
router.register(r'previsions', PrevisionTresorerieViewset,
                basename='prevision')
router.register(r'rapprochements', RapprochementBancaireViewset,
                basename='rapprochement')
router.register(r'tresorerie-journaliere',
                TresorerieJournaliereViewset, basename='tresorerie-journaliere')

urlpatterns = [
    path('', include(router.urls)),
]
