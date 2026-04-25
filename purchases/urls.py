# purchases/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register('suppliers', views.SupplierViewSet, basename='suppliers')
router.register('purchase-orders', views.PurchaseOrderViewSet, basename='purchase-orders')
router.register('purchase-receipts', views.PurchaseReceiptViewSet, basename='purchase-receipts')
router.register('transporters', views.TransporterViewSet, basename='transporters')
router.register('waybills', views.WaybillViewSet, basename='waybills')
router.register('receipt-costs', views.ReceiptCostViewSet, basename='receipt-costs')
router.register('supplier-catalogs', views.SupplierCatalogViewSet, basename='supplier-catalogs')
router.register('purchase-alerts', views.PurchaseAlertViewSet, basename='purchase-alerts')
router.register('price-history', views.PurchasePriceHistoryViewSet, basename='price-history')

urlpatterns = [
    path('', include(router.urls)),
    
    # URLs supplémentaires
    path('suppliers/<int:pk>/evaluate/', views.SupplierEvaluateView.as_view(), name='supplier-evaluate'),
    path('suppliers/<int:pk>/statistics/', views.SupplierStatisticsView.as_view(), name='supplier-statistics'),
    
    path('purchase-orders/by-supplier/<int:supplier_id>/', views.PurchaseOrderBySupplierView.as_view(), name='purchase-orders-by-supplier'),
    path('purchase-orders/by-agence/<int:agence_id>/', views.PurchaseOrderByAgenceView.as_view(), name='purchase-orders-by-agence'),
    
    path('purchase-receipts/by-order/<int:order_id>/', views.PurchaseReceiptByOrderView.as_view(), name='purchase-receipts-by-order'),
    
    path('waybills/by-order/<int:order_id>/', views.WaybillByOrderView.as_view(), name='waybills-by-order'),
    path('waybills/<int:pk>/update-status/', views.WaybillUpdateStatusView.as_view(), name='waybill-update-status'),
    
    path('receipt-costs/by-receipt/<int:receipt_id>/', views.ReceiptCostByReceiptView.as_view(), name='receipt-costs-by-receipt'),
    path('receipt-costs/<int:pk>/allocate/', views.ReceiptCostAllocateView.as_view(), name='receipt-cost-allocate'),
    
    path('supplier-catalogs/<int:pk>/import/', views.SupplierCatalogImportView.as_view(), name='supplier-catalog-import'),
    
    path('dashboard/', views.PurchaseDashboardView.as_view(), name='purchase-dashboard'),
]