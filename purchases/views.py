from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess
from inventaire.models import StockMovement, Warehouse
from rest_framework import viewsets, generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser  # ← NOUVEAU
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess, IsPDGOrDRH, CanManagePurchases


# ... le reste de votre code ...

class SupplierViewSet(viewsets.ModelViewSet):
    """ViewSet pour les fournisseurs"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        return Supplier.objects.all()

    def get_serializer_class(self):
        if self.action == 'list':
            return SupplierListSerializer
        if self.action == 'retrieve':
            return SupplierDetailSerializer
        return SupplierCreateUpdateSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class SupplierEvaluateView(generics.CreateAPIView):
    """Évaluer un fournisseur"""
    serializer_class = SupplierEvaluationSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def perform_create(self, serializer):
        supplier = get_object_or_404(Supplier, id=self.kwargs['pk'])
        serializer.save(supplier=supplier, evaluator=self.request.user)


class SupplierStatisticsView(generics.RetrieveAPIView):
    """Statistiques d'un fournisseur"""
    queryset = Supplier.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def retrieve(self, request, *args, **kwargs):
        supplier = self.get_object()
        
        orders = supplier.purchase_orders.all()
        
        data = {
            'total_orders': orders.count(),
            'total_spent': orders.filter(status='received').aggregate(total=Sum('total'))['total'] or 0,
            'average_order_value': orders.filter(status='received').aggregate(avg=Sum('total')/Count('id'))['avg'] or 0,
            'on_time_delivery_rate': supplier.on_time_delivery_rate,
            'average_delivery_delay': supplier.average_delivery_delay,
            'products_count': supplier.purchase_orders.values('items__product').distinct().count(),
        }
        
        return Response(data)


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    """ViewSet pour les commandes d'achat"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return PurchaseOrder.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return PurchaseOrder.objects.filter(agence_id__in=agences_ids)

    def get_serializer_class(self):
        if self.action == 'list':
            return PurchaseOrderListSerializer
        if self.action == 'retrieve':
            return PurchaseOrderDetailSerializer
        return PurchaseOrderCreateUpdateSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PurchaseOrderBySupplierView(generics.ListAPIView):
    """Commandes par fournisseur"""
    serializer_class = PurchaseOrderListSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        supplier_id = self.kwargs['supplier_id']
        return PurchaseOrder.objects.filter(supplier_id=supplier_id)


class PurchaseOrderByAgenceView(generics.ListAPIView):
    """Commandes par agence"""
    serializer_class = PurchaseOrderListSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        agence_id = self.kwargs['agence_id']
        return PurchaseOrder.objects.filter(agence_id=agence_id)


class PurchaseOrderValidateView(generics.UpdateAPIView):
    """Valider une commande d'achat"""
    queryset = PurchaseOrder.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        if order.status != 'draft':
            return Response({'error': 'Seul un brouillon peut être validé'}, status=status.HTTP_400_BAD_REQUEST)
        
        order.status = 'confirmed'
        order.confirmed_date = timezone.now().date()
        order.validated_by = request.user
        order.save()
        
        return Response(PurchaseOrderDetailSerializer(order).data)


class PurchaseOrderSendView(generics.UpdateAPIView):
    """Envoyer une commande au fournisseur"""
    queryset = PurchaseOrder.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        if order.status != 'confirmed':
            return Response({'error': 'La commande doit être confirmée avant envoi'}, status=status.HTTP_400_BAD_REQUEST)
        
        order.status = 'sent'
        order.save()
        
        # Ici vous pouvez ajouter l'envoi d'email au fournisseur
        # send_email_to_supplier(order)
        
        return Response(PurchaseOrderDetailSerializer(order).data)


class PurchaseOrderCancelView(generics.UpdateAPIView):
    """Annuler une commande d'achat"""
    queryset = PurchaseOrder.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        if order.status in ['received', 'cancelled']:
            return Response({'error': 'Cette commande ne peut pas être annulée'}, status=status.HTTP_400_BAD_REQUEST)
        
        order.status = 'cancelled'
        order.save()
        
        return Response(PurchaseOrderDetailSerializer(order).data)


class PurchaseReceiptViewSet(viewsets.ModelViewSet):
    """ViewSet pour les réceptions"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return PurchaseReceipt.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return PurchaseReceipt.objects.filter(purchase_order__agence_id__in=agences_ids)

    def get_serializer_class(self):
        if self.action == 'list':
            return PurchaseReceiptSerializer
        if self.action == 'retrieve':
            return PurchaseReceiptDetailSerializer
        return PurchaseReceiptCreateSerializer


class PurchaseReceiptByOrderView(generics.ListAPIView):
    """Réceptions par commande"""
    serializer_class = PurchaseReceiptSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        order_id = self.kwargs['order_id']
        return PurchaseReceipt.objects.filter(purchase_order_id=order_id)


class TransporterViewSet(viewsets.ModelViewSet):
    """ViewSet pour les transporteurs"""
    queryset = Transporter.objects.all()
    serializer_class = TransporterSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]


class WaybillViewSet(viewsets.ModelViewSet):
    """ViewSet pour les bons de transport"""
    queryset = Waybill.objects.all()
    serializer_class = WaybillSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class WaybillByOrderView(generics.ListAPIView):
    """Bons de transport par commande"""
    serializer_class = WaybillSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        order_id = self.kwargs['order_id']
        return Waybill.objects.filter(purchase_order_id=order_id)


class WaybillUpdateStatusView(generics.UpdateAPIView):
    """Mettre à jour le statut d'un bon de transport"""
    queryset = Waybill.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        waybill = self.get_object()
        new_status = request.data.get('status')
        
        if new_status not in dict(Waybill.STATUS_CHOICES):
            return Response({'error': 'Statut invalide'}, status=status.HTTP_400_BAD_REQUEST)
        
        waybill.status = new_status
        
        # Mettre à jour les dates selon le statut
        if new_status == 'arrived':
            waybill.actual_arrival = timezone.now().date()
        elif new_status == 'cleared':
            waybill.customs_clearance_date = timezone.now().date()
        elif new_status == 'delivered':
            waybill.delivery_date = timezone.now().date()
        
        waybill.save()
        
        return Response(WaybillSerializer(waybill).data)


class ReceiptCostViewSet(viewsets.ModelViewSet):
    """ViewSet pour les frais de réception"""
    queryset = ReceiptCost.objects.all()
    serializer_class = ReceiptCostSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]


class ReceiptCostByReceiptView(generics.ListAPIView):
    """Frais par réception"""
    serializer_class = ReceiptCostSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        receipt_id = self.kwargs['receipt_id']
        return ReceiptCost.objects.filter(receipt_id=receipt_id)


class ReceiptCostAllocateView(generics.CreateAPIView):
    """Allouer des frais aux produits"""
    serializer_class = ReceiptCostAllocationSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def perform_create(self, serializer):
        receipt_cost = get_object_or_404(ReceiptCost, id=self.kwargs['pk'])
        serializer.save(receipt_cost=receipt_cost)


class SupplierCatalogViewSet(viewsets.ModelViewSet):
    """ViewSet pour les catalogues fournisseurs"""
    queryset = SupplierCatalog.objects.all()
    serializer_class = SupplierCatalogSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    parser_classes = [MultiPartParser, FormParser]


class SupplierCatalogImportView(generics.UpdateAPIView):
    """Importer un catalogue fournisseur"""
    queryset = SupplierCatalog.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        catalog = self.get_object()
        catalog.status = 'processing'
        catalog.save()
        
        try:
            # Logique d'import du fichier
            # À implémenter selon le format (CSV, Excel)
            
            catalog.status = 'completed'
            catalog.products_imported = 0  # À mettre à jour avec le vrai nombre
            catalog.save()
            
        except Exception as e:
            catalog.status = 'failed'
            catalog.error_log = str(e)
            catalog.save()
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(SupplierCatalogSerializer(catalog).data)


class PurchaseAlertViewSet(viewsets.ModelViewSet):
    """ViewSet pour les alertes d'achat"""
    queryset = PurchaseAlert.objects.filter(is_active=True)
    serializer_class = PurchaseAlertSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]


class PurchasePriceHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet pour l'historique des prix (lecture seule)"""
    queryset = PurchasePriceHistory.objects.all()
    serializer_class = PurchasePriceHistorySerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]


class PurchaseDashboardView(generics.GenericAPIView):
    """Dashboard achats"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get(self, request):
        user = request.user
        
        # Filtrer par agence
        if user.est_pdg() or user.est_drh():
            orders = PurchaseOrder.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            orders = PurchaseOrder.objects.filter(agence_id__in=agences_ids)
        
        # Commandes en retard
        today = timezone.now().date()
        late_orders = orders.filter(
            expected_date__lt=today,
            status__in=['confirmed', 'sent', 'in_transit']
        )
        
        data = {
            'total_orders': orders.count(),
            'total_amount': orders.filter(status='received').aggregate(total=Sum('total'))['total'] or 0,
            'average_order_value': orders.filter(status='received').aggregate(avg=Sum('total')/Count('id'))['avg'] or 0,
            'pending_orders': orders.filter(status__in=['draft', 'sent', 'confirmed']).count(),
            'late_orders': late_orders.count(),
            'total_suppliers': Supplier.objects.filter(is_active=True).count(),
            'monthly_spending': self._get_monthly_spending(orders),
            'top_suppliers': self._get_top_suppliers(orders),
        }
        
        return Response(data)
    
    def _get_monthly_spending(self, orders):
        """Récupère les dépenses mensuelles"""
        from django.db.models.functions import TruncMonth
        
        monthly = orders.filter(status='received').annotate(
            month=TruncMonth('order_date')
        ).values('month').annotate(
            total=Sum('total')
        ).order_by('-month')[:12]
        
        return list(monthly)
    
    def _get_top_suppliers(self, orders):
        """Récupère les meilleurs fournisseurs"""
        top = orders.filter(status='received').values(
            'supplier__company_name'
        ).annotate(
            total=Sum('total'),
            count=Count('id')
        ).order_by('-total')[:5]
        
        return list(top)