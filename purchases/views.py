# users/views.py - Version complète et corrigée
from django.shortcuts import render
from rest_framework import viewsets, generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess
from inventaire.models import StockMovement, Warehouse


class SupplierViewSet(viewsets.ModelViewSet):
    """ViewSet pour les fournisseurs"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    queryset = Supplier.objects.all()

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
    queryset = PurchaseOrder.objects.all()

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
        if self.action == 'partial_update' and 'status' in self.request.data:
            return PurchaseOrderUpdateStatusSerializer
        return PurchaseOrderCreateUpdateSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        
        if serializer.is_valid():
            self.perform_update(serializer)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        instance = self.get_object()
        
        new_status = request.data.get('status')
        old_status = instance.status
        
        # Utiliser le serializer approprié
        if new_status and len(request.data) == 1:
            serializer = PurchaseOrderUpdateStatusSerializer(instance, data=request.data, partial=True)
        else:
            serializer = self.get_serializer(instance, data=request.data, partial=True)
        
        if serializer.is_valid():
            # Gérer les dates associées au changement de statut
            if new_status and new_status != old_status:
                if new_status == 'confirmed' and old_status == 'draft':
                    instance.confirmed_date = timezone.now().date()
                    instance.validated_by = request.user
                elif new_status == 'sent' and old_status in ['draft', 'confirmed']:
                    if old_status == 'confirmed':
                        instance.shipped_date = timezone.now().date()
                elif new_status == 'in_transit' and old_status == 'confirmed':
                    instance.shipped_date = timezone.now().date()
                elif new_status == 'received' and old_status in ['in_transit', 'partially_received']:
                    instance.received_date = timezone.now().date()
            
            serializer.save()
            
            # Retourner les données complètes
            full_serializer = PurchaseOrderDetailSerializer(instance)
            return Response(full_serializer.data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def perform_update(self, serializer):
        serializer.save()

    # Actions supplémentaires pour le changement de statut
    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Confirmer une commande (brouillon -> confirmée)"""
        order = self.get_object()
        if order.status != 'draft':
            return Response({'error': 'Seul un brouillon peut être confirmé'}, status=status.HTTP_400_BAD_REQUEST)
        
        order.status = 'confirmed'
        order.confirmed_date = timezone.now().date()
        order.validated_by = request.user
        order.save()
        
        return Response(PurchaseOrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """Envoyer une commande au fournisseur (confirmée -> envoyée)"""
        order = self.get_object()
        if order.status != 'confirmed':
            return Response({'error': 'Seule une commande confirmée peut être envoyée'}, status=status.HTTP_400_BAD_REQUEST)
        
        order.status = 'sent'
        order.shipped_date = timezone.now().date()
        order.save()
        
        return Response(PurchaseOrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'])
    def mark_in_transit(self, request, pk=None):
        """Marquer comme en transit (confirmée/sent -> en transit)"""
        order = self.get_object()
        if order.status not in ['confirmed', 'sent']:
            return Response({'error': 'Seule une commande confirmée ou envoyée peut être marquée en transit'}, status=status.HTTP_400_BAD_REQUEST)
        
        order.status = 'in_transit'
        order.save()
        
        return Response(PurchaseOrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'])
    def receive(self, request, pk=None):
        """Marquer comme reçue (en transit/partiellement reçue -> reçue)"""
        order = self.get_object()
        if order.status not in ['in_transit', 'partially_received']:
            return Response({'error': 'Seule une commande en transit ou partiellement reçue peut être marquée reçue'}, status=status.HTTP_400_BAD_REQUEST)
        
        order.status = 'received'
        order.received_date = timezone.now().date()
        order.save()
        
        return Response(PurchaseOrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Annuler une commande"""
        order = self.get_object()
        if order.status in ['received', 'cancelled']:
            return Response({'error': 'Cette commande ne peut pas être annulée'}, status=status.HTTP_400_BAD_REQUEST)
        
        order.status = 'cancelled'
        order.save()
        
        return Response(PurchaseOrderDetailSerializer(order).data)


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


class PurchaseReceiptViewSet(viewsets.ModelViewSet):
    """ViewSet pour les réceptions"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    queryset = PurchaseReceipt.objects.all()

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
            catalog.status = 'completed'
            catalog.products_imported = 0
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
        
        if user.est_pdg() or user.est_drh():
            orders = PurchaseOrder.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            orders = PurchaseOrder.objects.filter(agence_id__in=agences_ids)
        
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
        from django.db.models.functions import TruncMonth
        
        monthly = orders.filter(status='received').annotate(
            month=TruncMonth('order_date')
        ).values('month').annotate(
            total=Sum('total')
        ).order_by('-month')[:12]
        
        return list(monthly)
    
    def _get_top_suppliers(self, orders):
        top = orders.filter(status='received').values(
            'supplier__company_name'
        ).annotate(
            total=Sum('total'),
            count=Count('id')
        ).order_by('-total')[:5]
        
        return list(top)