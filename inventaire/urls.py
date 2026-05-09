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
    
    # ============================================
    # DASHBOARD & STATISTIQUES
    # ============================================
    path('dashboard/stats/', InventoryDashboardView.as_view(), name='inventory-dashboard'),
    
    # ============================================
    # MOUVEMENTS DE STOCK
    # ============================================
    path('stock-movements/by-product/<int:product_id>/', 
         StockMovementByProductView.as_view(), 
         name='stock-movements-by-product'),
    path('stock-movements/by-warehouse/<int:warehouse_id>/', 
         StockMovementByWarehouseView.as_view(), 
         name='stock-movements-by-warehouse'),
    
    # ============================================
    # TRANSFERTS - WORKFLOW COMPLET (METHODES POST)
    # ============================================
    # Étape 1: Soumettre la demande (chef agence destination)
    path('transfers/<int:pk>/submit/', 
         TransferViewSet.as_view({'post': 'submit'}), 
         name='transfer-submit'),
    
    # Étape 2: Approuver le transfert (chef agence source) - DÉBLOQUE LE STOCK
    path('transfers/<int:pk>/approve/', 
         TransferViewSet.as_view({'post': 'approve'}), 
         name='transfer-approve'),
    
    # Étape 3: Démarrer le transit (après préparation physique)
    path('transfers/<int:pk>/start-transit/', 
         TransferViewSet.as_view({'post': 'start_transit'}), 
         name='transfer-start-transit'),
    
    # Étape 4: Réceptionner le transfert (chef agence destination) - CRÉDITE LE STOCK
    path('transfers/<int:pk>/receive/', 
         TransferViewSet.as_view({'post': 'receive'}), 
         name='transfer-receive'),
    
    # Actions supplémentaires
    path('transfers/<int:pk>/reject/', 
         TransferViewSet.as_view({'post': 'reject'}), 
         name='transfer-reject'),
    
    path('transfers/<int:pk>/cancel/', 
         TransferViewSet.as_view({'post': 'cancel'}), 
         name='transfer-cancel'),
    
    # Anciens endpoints (à garder pour compatibilité ou supprimer si plus utilisés)
    path('transfers/<int:pk>/validate/', 
         TransferValidateView.as_view(), 
         name='transfer-validate'),
    
    # ============================================
    # INVENTAIRES
    # ============================================
    path('inventory-counts/<int:pk>/validate/', 
         InventoryCountValidateView.as_view(), 
         name='inventory-count-validate'),
    path('inventory-counts/<int:pk>/generate/', 
         InventoryCountGenerateView.as_view(), 
         name='inventory-count-generate'),
    
    # ============================================
    # LOTS
    # ============================================
    path('lots/by-product/<int:product_id>/', 
         LotByProductView.as_view(), 
         name='lots-by-product'),
    path('lots/expiring-soon/', 
         ExpiringLotsView.as_view(), 
         name='expiring-lots'),
    
    # ============================================
    # ALERTES STOCK
    # ============================================
    path('stock-alerts/resolve/<int:pk>/', 
         ResolveStockAlertView.as_view(), 
         name='resolve-stock-alert'),
    path('stock-alerts/acknowledge/<int:pk>/', 
         AcknowledgeStockAlertView.as_view(), 
         name='acknowledge-stock-alert'),
    
    # ============================================
    # EMPLACEMENTS PAR ENTREPÔT
    # ============================================
    path('warehouses/<int:warehouse_id>/locations/', 
         LocationByWarehouseView.as_view(), 
         name='locations-by-warehouse'),
]

# Ajouter la configuration pour servir les fichiers média en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)