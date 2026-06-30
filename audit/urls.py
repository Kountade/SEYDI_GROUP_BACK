from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AuditLogViewset

router = DefaultRouter()
router.register('logs', AuditLogViewset, basename='audit-logs')

urlpatterns = [
    path('', include(router.urls)),
]
