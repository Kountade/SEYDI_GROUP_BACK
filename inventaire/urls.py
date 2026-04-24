from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from django.conf import settings
from django.conf.urls.static import static

router = DefaultRouter()
router.register('warehouses', WarehouseViewSet, basename='warehouses')
router.register('locations', LocationViewSet, basename='locations')
router.register('stock-movements', StockMovementViewSet, basename='stock-movements')
router.register('transfers', TransferViewSet, basename='transfers')
router.register('inventory-counts', InventoryCountViewSet, basename='inventory-counts')
router.register('stock-alerts', StockAlertViewSet, basename='stock-alerts')
router.register('lots', LotViewSet, basename='lots')
router.register('quality-controls', QualityControlViewSet, basename='quality-controls')

urlpatterns = [
    path('', include(router.urls)),
    
    # Endpoints supplémentaires (non-CRUD)
    path('dashboard/stats/', InventoryDashboardView.as_view(), name='inventory-dashboard'),
    path('stock-movements/by-product/<int:product_id>/', StockMovementByProductView.as_view(), name='stock-movements-by-product'),
    path('stock-movements/by-warehouse/<int:warehouse_id>/', StockMovementByWarehouseView.as_view(), name='stock-movements-by-warehouse'),
    path('transfers/<int:pk>/validate/', TransferValidateView.as_view(), name='transfer-validate'),
    path('transfers/<int:pk>/receive/', TransferReceiveView.as_view(), name='transfer-receive'),
    path('transfers/<int:pk>/cancel/', TransferCancelView.as_view(), name='transfer-cancel'),
    path('inventory-counts/<int:pk>/validate/', InventoryCountValidateView.as_view(), name='inventory-count-validate'),
    path('inventory-counts/<int:pk>/generate/', InventoryCountGenerateView.as_view(), name='inventory-count-generate'),
    path('lots/by-product/<int:product_id>/', LotByProductView.as_view(), name='lots-by-product'),
    path('lots/expiring-soon/', ExpiringLotsView.as_view(), name='expiring-lots'),
    path('stock-alerts/resolve/<int:pk>/', ResolveStockAlertView.as_view(), name='resolve-stock-alert'),
    path('stock-alerts/acknowledge/<int:pk>/', AcknowledgeStockAlertView.as_view(), name='acknowledge-stock-alert'),
    path('warehouses/<int:warehouse_id>/locations/', LocationByWarehouseView.as_view(), name='locations-by-warehouse'),
]

# Ajouter la configuration pour servir les fichiers média en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)