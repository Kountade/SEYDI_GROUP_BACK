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


# views.py
# views.py
class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    # ou [IsAuthenticated, HasAgenceAccess] si nécessaire
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return SupplierListSerializer
        elif self.action == 'retrieve':
            return SupplierDetailSerializer
        return SupplierCreateUpdateSerializer

    # Supprimer perform_create et perform_update qui utilisaient created_by/updated_by
    # Ou les laisser vides sans passer d'arguments supplémentaires
    def perform_create(self, serializer):
        serializer.save()  # Ne plus passer created_by

    def perform_update(self, serializer):
        serializer.save()  # Ne plus passer updated_by


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
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial)

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
            serializer = PurchaseOrderUpdateStatusSerializer(
                instance, data=request.data, partial=True)
        else:
            serializer = self.get_serializer(
                instance, data=request.data, partial=True)

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

# purchases/views.py - AJOUTEZ cette vue

class PurchaseOrderItemReceiptHistoryView(generics.ListAPIView):
    """Historique des réceptions pour une ligne de commande"""
    serializer_class = PurchaseReceiptItemSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    
    def get_queryset(self):
        order_item_id = self.kwargs['order_item_id']
        return PurchaseReceiptItem.objects.filter(
            order_item_id=order_item_id
        ).order_by('-receipt__created_at')

    
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


# purchases/views.py - Si vous avez une vue personnalisée

class PurchaseReceiptCreateView(generics.CreateAPIView):
    serializer_class = PurchaseReceiptCreateSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def perform_create(self, serializer):
        # Le serializer gère déjà tout
        serializer.save()

# purchases/views.py

from rest_framework import viewsets, generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q
from django.utils import timezone
from rest_framework.decorators import action
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess


class PurchaseOrdersReceivableView(generics.ListAPIView):
    """Liste des commandes pouvant être réceptionnées"""
    serializer_class = PurchaseOrderListSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        
        if user.est_pdg() or user.est_drh():
            queryset = PurchaseOrder.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = PurchaseOrder.objects.filter(agence_id__in=agences_ids)
        
        # ✅ Filtrer les commandes qui peuvent être réceptionnées
        # Exclure: draft, received, cancelled, rejected
        # Inclure: confirmed, sent, in_transit, partially_received
        queryset = queryset.exclude(
            status__in=['draft', 'received', 'cancelled', 'rejected']
        )
        
        # ✅ Filtrer pour garder uniquement celles avec des articles restants
        result = []
        for order in queryset:
            has_remaining = any(
                item.quantity_ordered > item.quantity_received 
                for item in order.items.all()
            )
            if has_remaining:
                result.append(order.id)
        
        # Trier : partiellement reçues en premier
        orders = queryset.filter(id__in=result)
        return orders.order_by(
            '-status'  # partially_received vient après received dans l'ordre alphabétique
        )

# purchases/views.py - PurchaseReceiptViewSet COMPLET CORRIGÉ

from rest_framework import viewsets, generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from decimal import Decimal
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess
from inventaire.models import StockMovement, Warehouse


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
        if self.action == 'generate_invoice':
            return None
        return PurchaseReceiptCreateSerializer

    # ============================================================
    # ✅ GENERATE INVOICE - CORRIGÉ AVEC total_received_amount
    # ============================================================

    @action(detail=True, methods=['post'])
    def generate_invoice(self, request, pk=None):
        """
        ✅ Génère une facture pour une réception
        Utilise total_received_amount comme Sodepci
        """
        receipt = self.get_object()
        
        # Vérifier si une facture existe déjà
        if receipt.invoices.exists():
            return Response(
                {'error': 'Une facture existe déjà pour cette réception'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # ✅ Calculer le total de la réception avec la propriété
        total_reception = receipt.total_received_amount
        
        print(f"💰 TOTAL RÉCEPTION CALCULÉ: {total_reception}")
        print(f"📦 NOMBRE D'ITEMS: {receipt.items.count()}")
        
        # Vérifier si le montant est valide
        if total_reception <= 0:
            return Response(
                {'error': f'Le montant total de la réception est nul ({total_reception})'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        purchase_order = receipt.purchase_order
        
        # ✅ Créer la facture avec le total calculé
        invoice = Invoice.objects.create(
            agence=purchase_order.agence,
            supplier=purchase_order.supplier,
            purchase_receipt=receipt,
            purchase_order=purchase_order,
            created_by=request.user,
            invoice_date=receipt.receipt_date or timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=30),
            invoice_type='purchase',
            is_auto_generated=True,
            notes=f"Facture générée depuis la réception {receipt.receipt_number}",
            status='pending',
            subtotal=total_reception,
            tax_total=Decimal('0'),
            discount=Decimal('0'),
            shipping_cost=Decimal('0'),
            total=total_reception,
            amount_paid=Decimal('0'),
            amount_remaining=total_reception
        )
        
        print(f"📄 FACTURE CRÉÉE: {invoice.invoice_number} - Total: {invoice.total}")
        
        # ✅ Créer les lignes de facture
        items_created = 0
        for item in receipt.items.all():
            order_item = item.order_item
            if order_item:
                InvoiceItem.objects.create(
                    invoice=invoice,
                    receipt_item=item,
                    product=order_item.product,
                    variant=order_item.variant,
                    description=f"{order_item.product.name} - Commande {purchase_order.order_number}",
                    quantity=item.quantity,
                    unit_price=order_item.unit_price,
                    discount_rate=order_item.discount_rate or Decimal('0'),
                    tax_rate=Decimal('0'),
                )
                items_created += 1
                print(f"  ➕ Ligne: {order_item.product.name} - {order_item.unit_price} x {item.quantity}")
        
        if items_created == 0:
            invoice.delete()
            return Response(
                {'error': 'Aucune ligne de facture créée'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # ✅ Recalculer les totaux après création des items
        invoice.refresh_from_db()
        subtotal = sum(item.total for item in invoice.items.all())
        invoice.subtotal = subtotal
        invoice.total = subtotal
        invoice.amount_remaining = subtotal - invoice.amount_paid
        invoice.save(update_fields=['subtotal', 'total', 'amount_remaining'])
        
        print(f"✅ FACTURE FINALISÉE: {invoice.invoice_number} - Total: {invoice.total}")
        
        # ✅ Retourner la facture créée
        serializer = InvoiceSerializer(invoice, context={'request': request})
        return Response({
            'success': True,
            'message': f'Facture {invoice.invoice_number} créée avec succès',
            'invoice': serializer.data,
            'total': str(invoice.total),
            'receipt_total': str(total_reception),
            'items_count': items_created
        }, status=status.HTTP_201_CREATED)

    # ============================================================
    # ✅ GET INVOICE - Récupérer la facture associée
    # ============================================================

    @action(detail=True, methods=['get'])
    def invoice(self, request, pk=None):
        """
        ✅ Récupère la facture associée à une réception
        """
        receipt = self.get_object()
        invoice = receipt.invoices.first()
        
        if not invoice:
            return Response(
                {'error': 'Aucune facture associée à cette réception'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = InvoiceSerializer(invoice, context={'request': request})
        return Response(serializer.data)

    # ============================================================
    # ✅ CREATE OR UPDATE INVOICE
    # ============================================================

    @action(detail=True, methods=['post'])
    def create_or_update_invoice(self, request, pk=None):
        """
        ✅ Crée ou met à jour la facture d'une réception
        """
        receipt = self.get_object()
        
        # ✅ Calculer le total avec la propriété
        total_reception = receipt.total_received_amount
        
        if total_reception <= 0:
            return Response(
                {'error': f'Le montant total de la réception est nul ({total_reception})'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Vérifier si une facture existe déjà
        if receipt.invoices.exists():
            # Mettre à jour la facture existante
            invoice = receipt.invoices.first()
            
            # Supprimer les anciens items
            invoice.items.all().delete()
            
            # Mettre à jour les montants
            invoice.subtotal = total_reception
            invoice.total = total_reception
            invoice.amount_remaining = total_reception - invoice.amount_paid
            invoice.save(update_fields=['subtotal', 'total', 'amount_remaining'])
        else:
            # Créer une nouvelle facture
            purchase_order = receipt.purchase_order
            
            invoice = Invoice.objects.create(
                agence=purchase_order.agence,
                supplier=purchase_order.supplier,
                purchase_receipt=receipt,
                purchase_order=purchase_order,
                created_by=request.user,
                invoice_date=receipt.receipt_date or timezone.now().date(),
                due_date=timezone.now().date() + timezone.timedelta(days=30),
                invoice_type='purchase',
                is_auto_generated=True,
                notes=f"Facture générée depuis la réception {receipt.receipt_number}",
                status='pending',
                subtotal=total_reception,
                tax_total=Decimal('0'),
                discount=Decimal('0'),
                shipping_cost=Decimal('0'),
                total=total_reception,
                amount_paid=Decimal('0'),
                amount_remaining=total_reception
            )
        
        # Créer les lignes de facture
        items_created = 0
        for item in receipt.items.all():
            order_item = item.order_item
            if order_item:
                InvoiceItem.objects.create(
                    invoice=invoice,
                    receipt_item=item,
                    product=order_item.product,
                    variant=order_item.variant,
                    description=f"{order_item.product.name} - Commande {receipt.purchase_order.order_number}",
                    quantity=item.quantity,
                    unit_price=order_item.unit_price,
                    discount_rate=order_item.discount_rate or Decimal('0'),
                    tax_rate=Decimal('0'),
                )
                items_created += 1
        
        # Recalculer les totaux
        invoice.refresh_from_db()
        subtotal = sum(item.total for item in invoice.items.all())
        invoice.subtotal = subtotal
        invoice.total = subtotal
        invoice.amount_remaining = subtotal - invoice.amount_paid
        invoice.save()
        
        serializer = InvoiceSerializer(invoice, context={'request': request})
        return Response({
            'success': True,
            'message': f'Facture {invoice.invoice_number} mise à jour',
            'invoice': serializer.data,
            'total': str(invoice.total),
            'receipt_total': str(total_reception),
            'items_count': items_created
        })

    # ============================================================
    # ✅ GET RECEIPT TOTALS - Obtenir les totaux de la réception
    # ============================================================

    @action(detail=True, methods=['get'])
    def totals(self, request, pk=None):
        """
        ✅ Récupère les totaux de la réception
        """
        receipt = self.get_object()
        
        return Response({
            'receipt_id': receipt.id,
            'receipt_number': receipt.receipt_number,
            'total_received_amount': str(receipt.total_received_amount),
            'total_received_quantity': receipt.total_received_quantity,
            'items_count': receipt.items_count,
            'is_completed': receipt.is_completed,
            'has_invoice': receipt.invoices.exists(),
            'invoice_number': receipt.invoices.first().invoice_number if receipt.invoices.exists() else None,
            'items': receipt.get_items_summary()
        })

    # ============================================================
    # ✅ GET AVAILABLE FOR INVOICE - Réceptions disponibles
    # ============================================================

    @action(detail=False, methods=['get'])
    def available_for_invoice(self, request):
        """
        ✅ Récupère les réceptions disponibles pour facturation
        """
        purchase_order_id = request.query_params.get('purchase_order')
        supplier_id = request.query_params.get('supplier')
        
        queryset = self.get_queryset().filter(
            invoices__isnull=True  # Pas encore de facture
        )
        
        if purchase_order_id:
            queryset = queryset.filter(purchase_order_id=purchase_order_id)
        if supplier_id:
            queryset = queryset.filter(purchase_order__supplier_id=supplier_id)
        
        # Filtrer les réceptions avec un total > 0
        result = []
        for receipt in queryset:
            if receipt.total_received_amount > 0:
                result.append({
                    'id': receipt.id,
                    'receipt_number': receipt.receipt_number,
                    'purchase_order': receipt.purchase_order.id,
                    'purchase_order_number': receipt.purchase_order.order_number,
                    'supplier': receipt.purchase_order.supplier.id,
                    'supplier_name': receipt.purchase_order.supplier.company_name,
                    'receipt_date': receipt.receipt_date,
                    'total_received_amount': str(receipt.total_received_amount),
                    'items_count': receipt.items_count
                })
        
        return Response(result)

    # ============================================================
    # ✅ GET RECEIPT STATS - Statistiques
    # ============================================================

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        ✅ Récupère les statistiques des réceptions
        """
        queryset = self.get_queryset()
        
        total_receipts = queryset.count()
        total_received_amount = 0
        total_items = 0
        
        for receipt in queryset:
            total_received_amount += receipt.total_received_amount
            total_items += receipt.items_count
        
        return Response({
            'total_receipts': total_receipts,
            'total_received_amount': str(total_received_amount),
            'total_items': total_items,
            'avg_receipt_value': str(total_received_amount / total_receipts if total_receipts > 0 else 0)
        })

    # ============================================================
    # ✅ CREATE RECEIPT WITH AUTO INVOICE
    # ============================================================

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        ✅ Crée une réception et génère automatiquement la facture
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        receipt = serializer.save()
        
        # ✅ Générer automatiquement la facture
        try:
            if receipt.total_received_amount > 0:
                # Appeler generate_invoice
                invoice_response = self.generate_invoice(request, pk=receipt.id)
                if invoice_response.status_code == 201:
                    invoice_data = invoice_response.data
                    print(f"✅ Facture auto-générée: {invoice_data.get('invoice', {}).get('invoice_number')}")
        except Exception as e:
            print(f"⚠️ Erreur génération auto-facture: {str(e)}")
        
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)



# purchases/views.py - PurchaseReceiptViewSet COMPLET CORRIGÉ

from rest_framework import viewsets, generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from decimal import Decimal
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess
from inventaire.models import StockMovement, Warehouse

# purchases/views.py - PurchaseReceiptViewSet COMPLET CORRIGÉ

from rest_framework import viewsets, generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from decimal import Decimal
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess
from inventaire.models import StockMovement, Warehouse



# purchases/views.py - PurchaseReceiptViewSet COMPLET CORRIGÉ

from rest_framework import viewsets, generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from decimal import Decimal
from datetime import timedelta
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess
from inventaire.models import StockMovement, Warehouse


class PurchaseReceiptViewSet(viewsets.ModelViewSet):
    """ViewSet pour les réceptions"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    queryset = PurchaseReceipt.objects.all()
    lookup_field = 'pk'

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
        if self.action == 'generate_invoice':
            return None
        return PurchaseReceiptCreateSerializer

    # ============================================================
    # ✅ GENERATE INVOICE - CORRIGÉ
    # ============================================================

    @action(detail=True, methods=['post'], url_path='generate_invoice')
    def generate_invoice(self, request, pk=None):
        """
        ✅ Génère une facture pour une réception
        """
        try:
            # ✅ Récupérer la réception avec le pk passé en paramètre
            receipt = self.get_object()
            
            if not receipt:
                return Response(
                    {'error': f'Réception avec ID {pk} non trouvée'},
                    status=status.HTTP_404_NOT_FOUND
                )

            print(f"🔍 RÉCEPTION: {receipt.receipt_number}")
            print(f"📦 ID: {receipt.id}")
            print(f"📦 ITEMS COUNT: {receipt.items.count()}")

            if receipt.invoices.exists():
                return Response(
                    {'error': 'Une facture existe déjà pour cette réception'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # ✅ Calculer le total
            total_reception = Decimal('0')
            items_for_invoice = []

            for item in receipt.items.all():
                order_item = item.order_item
                if order_item:
                    price = order_item.unit_price or Decimal('0')
                    qty = item.quantity or 0
                    total_ligne = price * qty
                    total_reception += total_ligne

                    items_for_invoice.append({
                        'order_item': order_item,
                        'receipt_item': item,
                        'quantity': qty,
                        'unit_price': price,
                        'product': order_item.product,
                        'variant': order_item.variant,
                        'discount_rate': order_item.discount_rate or Decimal('0'),
                    })
                    print(f"  - {order_item.product.name}: {qty} x {price} = {total_ligne}")

            print(f"💰 TOTAL RÉCEPTION: {total_reception}")

            if total_reception <= 0:
                return Response(
                    {'error': f'Le montant total de la réception est nul ({total_reception})'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if len(items_for_invoice) == 0:
                return Response(
                    {'error': 'Aucun item valide trouvé dans la réception'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            purchase_order = receipt.purchase_order

            # ✅ CRÉER LA FACTURE
            invoice = Invoice.objects.create(
                agence=purchase_order.agence,
                supplier=purchase_order.supplier,
                purchase_receipt=receipt,
                purchase_order=purchase_order,
                created_by=request.user,
                invoice_date=receipt.receipt_date or timezone.now().date(),
                due_date=timezone.now().date() + timedelta(days=30),
                invoice_type='purchase',
                is_auto_generated=True,
                notes=f"Facture générée depuis la réception {receipt.receipt_number}",
                status='pending',
                subtotal=total_reception,
                tax_total=Decimal('0'),
                discount=Decimal('0'),
                shipping_cost=Decimal('0'),
                total=total_reception,
                amount_paid=Decimal('0'),
                amount_remaining=total_reception
            )

            print(f"📄 FACTURE CRÉÉE: {invoice.invoice_number}")

            # ✅ CRÉER LES LIGNES DE FACTURE
            for item_data in items_for_invoice:
                InvoiceItem.objects.create(
                    invoice=invoice,
                    receipt_item=item_data['receipt_item'],
                    product=item_data['product'],
                    variant=item_data['variant'],
                    description=f"{item_data['product'].name} - Commande {purchase_order.order_number}",
                    quantity=item_data['quantity'],
                    unit_price=item_data['unit_price'],
                    discount_rate=item_data['discount_rate'],
                    tax_rate=Decimal('0'),
                )
                print(f"  ➕ Ligne: {item_data['product'].name} - {item_data['unit_price']} x {item_data['quantity']}")

            # ✅ RECALCULER LES TOTAUX
            invoice.refresh_from_db()
            subtotal = sum(item.total for item in invoice.items.all())
            invoice.subtotal = subtotal
            invoice.total = subtotal
            invoice.amount_remaining = subtotal - invoice.amount_paid
            invoice.save(update_fields=['subtotal', 'total', 'amount_remaining'])

            print(f"✅ FACTURE FINALISÉE: {invoice.invoice_number} - Total: {invoice.total}")

            serializer = InvoiceSerializer(invoice, context={'request': request})
            return Response({
                'success': True,
                'message': f'Facture {invoice.invoice_number} créée avec succès',
                'invoice': serializer.data,
                'total': str(invoice.total),
                'receipt_total': str(total_reception),
                'items_count': len(items_for_invoice)
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            print(f"❌ ERREUR: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response(
                {'error': f'Erreur lors de la génération: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # ✅ GET INVOICE
    # ============================================================

    @action(detail=True, methods=['get'], url_path='invoice')
    def get_invoice(self, request, pk=None):
        """Récupère la facture associée à une réception"""
        receipt = self.get_object()
        invoice = receipt.invoices.first()

        if not invoice:
            return Response(
                {'error': 'Aucune facture associée à cette réception'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = InvoiceSerializer(invoice, context={'request': request})
        return Response(serializer.data)

    # ============================================================
    # ✅ GET TOTALS
    # ============================================================

    @action(detail=True, methods=['get'], url_path='totals')
    def get_totals(self, request, pk=None):
        """Récupère les totaux de la réception"""
        receipt = self.get_object()

        return Response({
            'receipt_id': receipt.id,
            'receipt_number': receipt.receipt_number,
            'total_received_amount': str(receipt.total_received_amount),
            'total_received_quantity': receipt.total_received_quantity,
            'items_count': receipt.items_count,
            'has_invoice': receipt.invoices.exists(),
            'invoice_number': receipt.invoices.first().invoice_number if receipt.invoices.exists() else None,
            'invoice_id': receipt.invoices.first().id if receipt.invoices.exists() else None,
            'items': [
                {
                    'id': item.id,
                    'product': item.order_item.product.name if item.order_item else 'N/A',
                    'quantity': item.quantity,
                    'unit_price': str(item.order_item.unit_price) if item.order_item else '0',
                    'total': str(item.order_item.unit_price * item.quantity) if item.order_item else '0'
                }
                for item in receipt.items.all()
            ]
        })

    # ============================================================
    # ✅ CREATE - AVEC AUTO GÉNÉRATION DE FACTURE (CORRIGÉ)
    # ============================================================

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        ✅ Crée une réception et génère automatiquement la facture
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        receipt = serializer.save()

        print(f"✅ RÉCEPTION CRÉÉE: {receipt.receipt_number}")
        print(f"📦 ID: {receipt.id}")
        print(f"📦 ITEMS: {receipt.items.count()}")
        print(f"💰 TOTAL: {receipt.total_received_amount}")

        # ✅ GÉNÉRER LA FACTURE EN UTILISANT DIRECTEMENT LA LOGIQUE
        try:
            if receipt.total_received_amount > 0 and receipt.items.count() > 0:
                # ✅ Appeler generate_invoice avec le bon pk
                # Créer un faux request avec le bon pk
                from django.test import RequestFactory
                factory = RequestFactory()
                
                # ✅ PASSER pk DANS L'URL ET DANS self.kwargs
                fake_request = factory.post(f'/purchase-receipts/{receipt.id}/generate_invoice/')
                fake_request.user = request.user
                fake_request.data = {}
                
                # ✅ Définir self.kwargs pour que get_object fonctionne
                self.kwargs = {'pk': receipt.id}
                
                # Appeler generate_invoice
                response = self.generate_invoice(fake_request, pk=receipt.id)
                
                if response.status_code == 201:
                    print(f"✅ Facture auto-générée avec succès")
                    # Ajouter l'info de la facture dans la réponse
                    serializer.data['invoice_generated'] = True
                    serializer.data['invoice_data'] = response.data
                else:
                    print(f"⚠️ Erreur génération facture: {response.data}")
                    serializer.data['invoice_generated'] = False
                    serializer.data['invoice_error'] = response.data
        except Exception as e:
            print(f"⚠️ Erreur génération auto-facture: {str(e)}")
            import traceback
            traceback.print_exc()
            serializer.data['invoice_generated'] = False
            serializer.data['invoice_error'] = str(e)

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    # ============================================================
    # ✅ RETRIEVE
    # ============================================================

    def retrieve(self, request, *args, **kwargs):
        """Récupère les détails d'une réception"""
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        data = serializer.data
        data['total_received_amount'] = str(instance.total_received_amount)
        data['total_received_quantity'] = instance.total_received_quantity
        data['items_count'] = instance.items_count
        data['has_invoice'] = instance.invoices.exists()

        if instance.invoices.exists():
            invoice = instance.invoices.first()
            data['invoice_number'] = invoice.invoice_number
            data['invoice_id'] = invoice.id
            data['invoice_total'] = str(invoice.total)

        return Response(data)

    # ============================================================
    # ✅ AVAILABLE FOR INVOICE
    # ============================================================

    @action(detail=False, methods=['get'], url_path='available-for-invoice')
    def available_for_invoice(self, request):
        """Récupère les réceptions disponibles pour facturation"""
        purchase_order_id = request.query_params.get('purchase_order')
        supplier_id = request.query_params.get('supplier')

        queryset = self.get_queryset().filter(invoices__isnull=True)

        if purchase_order_id:
            queryset = queryset.filter(purchase_order_id=purchase_order_id)
        if supplier_id:
            queryset = queryset.filter(purchase_order__supplier_id=supplier_id)

        result = []
        for receipt in queryset:
            total = receipt.total_received_amount
            if total > 0:
                result.append({
                    'id': receipt.id,
                    'receipt_number': receipt.receipt_number,
                    'purchase_order': receipt.purchase_order.id,
                    'purchase_order_number': receipt.purchase_order.order_number,
                    'supplier': receipt.purchase_order.supplier.id,
                    'supplier_name': receipt.purchase_order.supplier.company_name,
                    'receipt_date': receipt.receipt_date,
                    'total_received_amount': str(total),
                    'items_count': receipt.items_count
                })

        return Response(result)




class InvoiceViewSet(viewsets.ModelViewSet):
    """ViewSet pour les factures"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    queryset = Invoice.objects.all()
    
    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return Invoice.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return Invoice.objects.filter(agence_id__in=agences_ids)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return InvoiceCreateSerializer
        return InvoiceSerializer
    
    @action(detail=True, methods=['post'])
    def add_payment(self, request, pk=None):
        """Ajouter un paiement à une facture"""
        invoice = self.get_object()
        
        serializer = PaymentCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            payment = serializer.save()
            return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'])
    def payments(self, request, pk=None):
        """Récupérer les paiements d'une facture"""
        invoice = self.get_object()
        payments = invoice.payments.all()
        serializer = PaymentSerializer(payments, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Annuler une facture"""
        invoice = self.get_object()
        
        if invoice.amount_paid > 0:
            return Response(
                {'error': 'Impossible d\'annuler une facture qui a des paiements'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        invoice.status = 'cancelled'
        invoice.is_active = False
        invoice.save()
        
        return Response(InvoiceSerializer(invoice).data)


class PaymentViewSet(viewsets.ModelViewSet):
    """ViewSet pour les paiements"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    
    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return Payment.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return Payment.objects.filter(agence_id__in=agences_ids)
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class InvoiceStatsView(generics.GenericAPIView):
    """Statistiques des factures"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    
    def get(self, request):
        user = request.user
        
        if user.est_pdg() or user.est_drh():
            invoices = Invoice.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            invoices = Invoice.objects.filter(agence_id__in=agences_ids)
        
        stats = {
            'total_invoices': invoices.count(),
            'total_amount': invoices.aggregate(total=Sum('total'))['total'] or 0,
            'paid_amount': invoices.aggregate(total=Sum('amount_paid'))['total'] or 0,
            'remaining_amount': invoices.aggregate(total=Sum('amount_remaining'))['total'] or 0,
            'pending': invoices.filter(status='pending').count(),
            'partial': invoices.filter(status='partial').count(),
            'paid': invoices.filter(status='paid').count(),
            'overdue': invoices.filter(status='overdue').count(),
            'cancelled': invoices.filter(status='cancelled').count(),
        }
        
        return Response(stats)


class PaymentStatsView(generics.GenericAPIView):
    """Statistiques des paiements"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    
    def get(self, request):
        user = request.user
        
        if user.est_pdg() or user.est_drh():
            payments = Payment.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            payments = Payment.objects.filter(agence_id__in=agences_ids)
        
        today = timezone.now().date()
        week_start = today - timezone.timedelta(days=7)
        month_start = today - timezone.timedelta(days=30)
        
        stats = {
            'total': payments.count(),
            'amount_today': payments.filter(payment_date=today).aggregate(total=Sum('amount'))['total'] or 0,
            'amount_week': payments.filter(payment_date__gte=week_start).aggregate(total=Sum('amount'))['total'] or 0,
            'amount_month': payments.filter(payment_date__gte=month_start).aggregate(total=Sum('amount'))['total'] or 0,
            'pending': payments.filter(status='pending').count(),
            'completed': payments.filter(status='completed').count(),
            'failed': payments.filter(status='failed').count(),
        }
        
        return Response(stats)


class InvoicePaymentsView(generics.ListAPIView):
    """Liste des paiements d'une facture"""
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    
    def get_queryset(self):
        invoice_id = self.kwargs['pk']
        return Payment.objects.filter(invoice_id=invoice_id)