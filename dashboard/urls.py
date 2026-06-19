from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DashboardViewSet, StatistiquesViewSet, AnalysesViewSet

router = DefaultRouter()
router.register(r'dashboard', DashboardViewSet, basename='dashboard')
router.register(r'statistiques', StatistiquesViewSet, basename='statistiques')
router.register(r'analyses', AnalysesViewSet, basename='analyses')

urlpatterns = [
    path('', include(router.urls)),
]
