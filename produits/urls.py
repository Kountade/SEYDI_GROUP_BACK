# products/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from django.conf import settings
from django.conf.urls.static import static

router = DefaultRouter()
router.register('categories', CategoryViewset, basename='categories')
router.register('brands', BrandViewset, basename='brands')
router.register('units', UnitViewset, basename='units')
router.register('products', ProductViewset, basename='products')
router.register('variants', ProductVariantViewset, basename='variants')

urlpatterns = [
    path('', include(router.urls)),
]

# Ajouter la configuration pour servir les fichiers média en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
