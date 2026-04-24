from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from django.conf import settings
from django.conf.urls.static import static

router = DefaultRouter()
router.register('suppliers', SupplierViewSet, basename='suppliers')
router.register('purchase-orders', PurchaseOrderViewSet, basename='purchase-orders')
router.register('purchase-receipts', PurchaseReceiptViewSet, basename='purchase-receipts')
router.register('transporters', TransporterViewSet, basename='transporters')
router.register('waybills', WaybillViewSet, basename='waybills')
router.register('receipt-costs', ReceiptCostViewSet, basename='receipt-costs')
router.register('supplier-catalogs', SupplierCatalogViewSet, basename='supplier-catalogs')
router.register('purchase-alerts', PurchaseAlertViewSet, basename='purchase-alerts')
router.register('price-history', PurchasePriceHistoryViewSet, basename='price-history')

urlpatterns = [
    path('', include(router.urls)),
    
    # Endpoints supplémentaires (non-CRUD)
    path('dashboard/stats/', PurchaseDashboardView.as_view(), name='purchase-dashboard'),
    path('purchase-orders/by-supplier/<int:supplier_id>/', PurchaseOrderBySupplierView.as_view(), name='purchase-orders-by-supplier'),
    path('purchase-orders/by-agence/<int:agence_id>/', PurchaseOrderByAgenceView.as_view(), name='purchase-orders-by-agence'),
    path('purchase-orders/<int:pk>/validate/', PurchaseOrderValidateView.as_view(), name='purchase-order-validate'),
    path('purchase-orders/<int:pk>/cancel/', PurchaseOrderCancelView.as_view(), name='purchase-order-cancel'),
    path('purchase-orders/<int:pk>/send/', PurchaseOrderSendView.as_view(), name='purchase-order-send'),
    path('purchase-receipts/by-order/<int:order_id>/', PurchaseReceiptByOrderView.as_view(), name='purchase-receipts-by-order'),
    path('suppliers/<int:pk>/evaluate/', SupplierEvaluateView.as_view(), name='supplier-evaluate'),
    path('suppliers/<int:pk>/statistics/', SupplierStatisticsView.as_view(), name='supplier-statistics'),
    path('supplier-catalogs/<int:pk>/import/', SupplierCatalogImportView.as_view(), name='supplier-catalog-import'),
    path('waybills/by-order/<int:order_id>/', WaybillByOrderView.as_view(), name='waybills-by-order'),
    path('waybills/<int:pk>/update-status/', WaybillUpdateStatusView.as_view(), name='waybill-update-status'),
    path('receipt-costs/by-receipt/<int:receipt_id>/', ReceiptCostByReceiptView.as_view(), name='receipt-costs-by-receipt'),
    path('receipt-costs/<int:pk>/allocate/', ReceiptCostAllocateView.as_view(), name='receipt-cost-allocate'),
]

# Ajouter la configuration pour servir les fichiers média en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)