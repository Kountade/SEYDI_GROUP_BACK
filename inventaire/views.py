from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, generics, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Sum, Q, F
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess


class WarehouseViewSet(viewsets.ModelViewSet):
    """ViewSet pour les entrepôts"""
    queryset = Warehouse.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return Warehouse.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return Warehouse.objects.filter(agence_id__in=agences_ids)

    def get_serializer_class(self):
        if self.action == 'list':
            return WarehouseSerializer
        if self.action == 'retrieve':
            return WarehouseDetailSerializer
        return WarehouseCreateSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class LocationViewSet(viewsets.ModelViewSet):
    """ViewSet pour les emplacements"""
    queryset = Location.objects.all()
    serializer_class = LocationSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return Location.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return Location.objects.filter(warehouse__agence_id__in=agences_ids)


class StockMovementViewSet(viewsets.ModelViewSet):
    """ViewSet pour les mouvements de stock"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return StockMovement.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return StockMovement.objects.filter(
            Q(from_warehouse__agence_id__in=agences_ids) |
            Q(to_warehouse__agence_id__in=agences_ids)
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return StockMovementListSerializer
        if self.action == 'retrieve':
            return StockMovementDetailSerializer
        return StockMovementCreateSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class StockMovementByProductView(generics.ListAPIView):
    """Mouvements de stock par produit"""
    serializer_class = StockMovementListSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        product_id = self.kwargs['product_id']
        return StockMovement.objects.filter(product_id=product_id)


class StockMovementByWarehouseView(generics.ListAPIView):
    """Mouvements de stock par entrepôt"""
    serializer_class = StockMovementListSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        warehouse_id = self.kwargs['warehouse_id']
        return StockMovement.objects.filter(
            Q(from_warehouse_id=warehouse_id) | Q(to_warehouse_id=warehouse_id)
        )


from rest_framework import viewsets, generics, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import Transfer, TransferItem, StockMovement, Warehouse
from .serializers import (
    TransferListSerializer, TransferDetailSerializer, TransferCreateSerializer
)
from users.permissions import HasAgenceAccess
from produits.models import Product

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from .models import Transfer, TransferItem, StockMovement, get_default_warehouse
from .serializers import (
    TransferListSerializer, TransferDetailSerializer, TransferCreateSerializer
)
from users.permissions import HasAgenceAccess
from produits.models import Product

# inventaire/views.py - Ajouter ces méthodes dans TransferViewSet

class TransferViewSet(viewsets.ModelViewSet):
    """ViewSet pour les transferts avec workflow complet"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return Transfer.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return Transfer.objects.filter(
            Q(from_agence_id__in=agences_ids) | Q(to_agence_id__in=agences_ids)
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return TransferListSerializer
        if self.action == 'retrieve':
            return TransferDetailSerializer
        return TransferCreateSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """Soumettre la demande au chef d'agence principale"""
        transfer = self.get_object()
        if transfer.status != 'draft':
            return Response(
                {'error': 'Seul un transfert en brouillon peut être soumis'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Vérifier que l'utilisateur est le chef de l'agence destination
        if not request.user.peut_acceder_agence(transfer.to_agence.id):
            return Response(
                {'error': 'Vous n\'êtes pas autorisé à soumettre cette demande'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Vérifier que le transfert va bien d'une principale vers une secondaire
        if transfer.from_agence.type_agence != 'principale' or transfer.to_agence.type_agence != 'secondaire':
            return Response(
                {'error': 'Seules les demandes de l\'agence principale vers une agence secondaire sont autorisées'},
                status=status.HTTP_400_BAD_REQUEST
            )

        transfer.status = 'pending_approval'
        transfer.save()
        return Response(TransferDetailSerializer(transfer).data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        """
        Approuver le transfert (chef agence principale)
        Cette méthode DÉBLOQUE le stock de l'entrepôt source
        """
        transfer = self.get_object()
        
        if transfer.status != 'pending_approval':
            return Response(
                {'error': 'La demande doit être en attente d\'approbation'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Vérifier que l'utilisateur est le chef de l'agence source (principale)
        if not request.user.peut_acceder_agence(transfer.from_agence.id):
            return Response(
                {'error': 'Seul un responsable de l\'agence principale peut approuver'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Récupérer les entrepôts par défaut
        from_warehouse = get_default_warehouse(transfer.from_agence)
        to_warehouse = get_default_warehouse(transfer.to_agence)
        
        if not from_warehouse:
            return Response(
                {'error': f'L\'agence {transfer.from_agence.nom} n\'a aucun entrepôt configuré'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not to_warehouse:
            return Response(
                {'error': f'L\'agence {transfer.to_agence.nom} n\'a aucun entrepôt configuré'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Vérifier le stock dans l'entrepôt source
        for item in transfer.items.all():
            product = item.product
            stock_dispo = product.stock_quantity
            
            if stock_dispo < item.quantity:
                return Response(
                    {'error': f'Stock insuffisant pour {product.name}. Disponible: {stock_dispo}, demandé: {item.quantity}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # CRÉER LES MOUVEMENTS DE STOCK (SORTIE DE L'ENTREPÔT SOURCE)
        for item in transfer.items.all():
            # Mouvement de sortie (déstockage)
            StockMovement.objects.create(
                movement_type='transfer',
                reference_type='transfer',
                reference_id=transfer.id,
                product=item.product,
                variant=item.variant,
                quantity=item.quantity,
                from_warehouse=from_warehouse,
                unit_price=item.unit_price,
                notes=f"Transfert approuvé {transfer.reference} - Sortie vers {to_warehouse.name}",
                created_by=request.user
            )
            
            # Mettre à jour le stock produit (DÉBLOCAGE)
            product = item.product
            product.stock_quantity -= item.quantity
            product.save()
            
            # Créer une entrée en transit (optionnel)
            # On pourrait aussi créer un mouvement d'entrée plus tard lors de la réception

        transfer.status = 'approved'
        transfer.approved_by = request.user
        transfer.approved_at = timezone.now()
        transfer.save()

        return Response(TransferDetailSerializer(transfer).data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def start_transit(self, request, pk=None):
        """
        Démarrer le transit (après préparation physique)
        Status: approved -> in_transit
        """
        transfer = self.get_object()
        
        if transfer.status != 'approved':
            return Response(
                {'error': 'Le transfert doit être approuvé avant de démarrer le transit'},
                status=status.HTTP_400_BAD_REQUEST
            )

        transfer.status = 'in_transit'
        transfer.save()
        
        return Response(TransferDetailSerializer(transfer).data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def receive(self, request, pk=None):
        """
        RECEPTIONNER le transfert (chef agence destination)
        Valide la réception et crédite le stock de l'entrepôt destination
        """
        transfer = self.get_object()
        
        if transfer.status != 'in_transit' and transfer.status != 'partial':
            return Response(
                {'error': 'Le transfert doit être en transit pour être réceptionné'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Vérifier que l'utilisateur est le chef de l'agence destination
        if not request.user.peut_acceder_agence(transfer.to_agence.id):
            return Response(
                {'error': 'Seul un responsable de l\'agence destination peut réceptionner'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Récupérer les données de réception
        received_items = request.data.get('items', [])
        waybill = request.data.get('waybill', '')
        notes = request.data.get('notes', '')
        
        # Récupérer l'entrepôt destination
        to_warehouse = get_default_warehouse(transfer.to_agence)
        if not to_warehouse:
            return Response(
                {'error': f'L\'agence {transfer.to_agence.nom} n\'a aucun entrepôt configuré'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Mettre à jour les quantités reçues
        all_completed = True
        
        for item_data in received_items:
            item_id = item_data.get('item_id')
            quantity_received = item_data.get('quantity', 0)
            
            try:
                transfer_item = TransferItem.objects.get(id=item_id, transfer=transfer)
            except TransferItem.DoesNotExist:
                continue
            
            # Mettre à jour la quantité reçue
            transfer_item.quantity_received += quantity_received
            transfer_item.save()
            
            # CRÉER LE MOUVEMENT D'ENTRÉE (STOCK DESTINATION)
            StockMovement.objects.create(
                movement_type='transfer',
                reference_type='transfer',
                reference_id=transfer.id,
                product=transfer_item.product,
                variant=transfer_item.variant,
                quantity=quantity_received,
                to_warehouse=to_warehouse,
                unit_price=transfer_item.unit_price,
                notes=f"Réception transfert {transfer.reference} - {notes}",
                created_by=request.user
            )
            
            # Vérifier si l'article est complètement reçu
            if transfer_item.quantity_received < transfer_item.quantity:
                all_completed = False
        
        # Mettre à jour le statut global
        if all_completed:
            transfer.status = 'completed'
            transfer.completed_date = timezone.now().date()
        else:
            transfer.status = 'partial'
        
        if waybill:
            transfer.waybill = waybill
        
        transfer.save()
        
        return Response(TransferDetailSerializer(transfer).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Rejeter le transfert"""
        transfer = self.get_object()
        
        if transfer.status != 'pending_approval':
            return Response(
                {'error': 'La demande doit être en attente d\'approbation'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not request.user.peut_acceder_agence(transfer.from_agence.id):
            return Response(
                {'error': 'Action non autorisée'},
                status=status.HTTP_403_FORBIDDEN
            )

        reason = request.data.get('reason', '')
        transfer.status = 'rejected'
        transfer.rejected_reason = reason
        transfer.save()
        
        return Response(TransferDetailSerializer(transfer).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Annuler le transfert"""
        transfer = self.get_object()
        
        if transfer.status not in ['draft', 'pending_approval', 'approved']:
            return Response(
                {'error': 'Ce transfert ne peut pas être annulé'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        transfer.status = 'cancelled'
        transfer.save()
        
        return Response(TransferDetailSerializer(transfer).data)


class TransferValidateView(generics.UpdateAPIView):
    """Valider un transfert"""
    queryset = Transfer.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        transfer = self.get_object()
        if transfer.status != 'draft':
            return Response({'error': 'Seul un brouillon peut être validé'}, status=status.HTTP_400_BAD_REQUEST)
        
        transfer.status = 'pending'
        transfer.validated_by = request.user
        transfer.save()
        
        return Response(TransferDetailSerializer(transfer).data)


class TransferReceiveView(generics.UpdateAPIView):
    """Réceptionner un transfert"""
    queryset = Transfer.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        transfer = self.get_object()
        if transfer.status not in ['in_transit', 'partial']:
            return Response({'error': 'Le transfert doit être en transit'}, status=status.HTTP_400_BAD_REQUEST)
        
        items_data = request.data.get('items', [])
        from inventaire.models import StockMovement
        
        for item_data in items_data:
            transfer_item = TransferItem.objects.get(id=item_data['item_id'])
            quantity = item_data['quantity']
            
            # Créer le mouvement de stock
            StockMovement.objects.create(
                movement_type='transfer',
                reference_type='transfer',
                reference_id=transfer.id,
                product=transfer_item.product,
                variant=transfer_item.variant,
                quantity=quantity,
                from_warehouse=transfer.from_warehouse,
                to_warehouse=transfer.to_warehouse,
                unit_price=transfer_item.unit_price,
                notes=f"Transfert {transfer.reference}",
                created_by=request.user
            )
            
            # Mettre à jour la quantité reçue
            transfer_item.quantity_received += quantity
            transfer_item.save()
        
        # Vérifier si tout est reçu
        all_received = all(item.quantity_received >= item.quantity for item in transfer.items.all())
        if all_received:
            transfer.status = 'completed'
            transfer.completed_date = timezone.now().date()
        else:
            transfer.status = 'partial'
        transfer.save()
        
        return Response(TransferDetailSerializer(transfer).data)


class TransferCancelView(generics.UpdateAPIView):
    """Annuler un transfert"""
    queryset = Transfer.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        transfer = self.get_object()
        if transfer.status in ['completed', 'cancelled']:
            return Response({'error': 'Ce transfert ne peut pas être annulé'}, status=status.HTTP_400_BAD_REQUEST)
        
        transfer.status = 'cancelled'
        transfer.save()
        
        return Response(TransferDetailSerializer(transfer).data)


class InventoryCountViewSet(viewsets.ModelViewSet):
    """ViewSet pour les inventaires"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return InventoryCount.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return InventoryCount.objects.filter(warehouse__agence_id__in=agences_ids)

    def get_serializer_class(self):
        if self.action == 'list':
            return InventoryCountListSerializer
        if self.action == 'retrieve':
            return InventoryCountDetailSerializer
        return InventoryCountCreateSerializer

    def perform_create(self, serializer):
        serializer.save(counted_by=self.request.user)


class InventoryCountValidateView(generics.UpdateAPIView):
    """Valider un inventaire"""
    queryset = InventoryCount.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        inventory = self.get_object()
        serializer = InventoryCountValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        if inventory.status != 'completed':
            return Response({'error': 'L\'inventaire doit être terminé avant validation'}, status=status.HTTP_400_BAD_REQUEST)
        
        inventory.status = 'validated'
        inventory.validated_by = request.user
        
        if serializer.validated_data.get('create_movements'):
            from inventaire.models import StockMovement
            # Créer les mouvements d'ajustement
            for item in inventory.items.filter(difference__gt=0):
                StockMovement.objects.create(
                    movement_type='adjustment',
                    reference_type='inventory',
                    reference_id=inventory.id,
                    product=item.product,
                    variant=item.variant,
                    quantity=abs(item.difference),
                    to_warehouse=inventory.warehouse if item.difference > 0 else None,
                    from_warehouse=inventory.warehouse if item.difference < 0 else None,
                    unit_price=item.unit_price,
                    notes=f"Ajustement inventaire {inventory.reference}",
                    created_by=request.user
                )
        
        inventory.save()
        return Response(InventoryCountDetailSerializer(inventory).data)


class InventoryCountGenerateView(generics.CreateAPIView):
    """Générer un inventaire à partir du stock actuel"""
    serializer_class = InventoryCountCreateSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def create(self, request, *args, **kwargs):
        warehouse_id = request.data.get('warehouse')
        warehouse = get_object_or_404(Warehouse, id=warehouse_id)
        
        from produits.models import Product
        
        # Récupérer tous les produits avec leur stock
        products = Product.objects.filter(stock_quantity__gt=0)
        
        inventory = InventoryCount.objects.create(
            warehouse=warehouse,
            scheduled_date=request.data.get('scheduled_date'),
            notes=request.data.get('notes'),
            counted_by=request.user
        )
        
        for product in products:
            InventoryCountItem.objects.create(
                inventory=inventory,
                product=product,
                theoretical_quantity=product.stock_quantity,
                unit_price=product.purchase_price
            )
        
        inventory.total_items = inventory.items.count()
        inventory.save()
        
        return Response(InventoryCountDetailSerializer(inventory).data, status=status.HTTP_201_CREATED)


class StockAlertViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet pour les alertes de stock (lecture seule)"""
    queryset = StockAlert.objects.all()
    serializer_class = StockAlertSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return StockAlert.objects.filter(status='active')
        agences_ids = user.get_agences().values_list('id', flat=True)
        return StockAlert.objects.filter(status='active', warehouse__agence_id__in=agences_ids)


class ResolveStockAlertView(generics.UpdateAPIView):
    """Résoudre une alerte de stock"""
    queryset = StockAlert.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        alert = self.get_object()
        alert.status = 'resolved'
        alert.resolved_at = timezone.now()
        alert.save()
        return Response(StockAlertSerializer(alert).data)


class AcknowledgeStockAlertView(generics.UpdateAPIView):
    """Reconnaître une alerte de stock"""
    queryset = StockAlert.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        alert = self.get_object()
        alert.status = 'acknowledged'
        alert.acknowledged_by = request.user
        alert.acknowledged_at = timezone.now()
        alert.save()
        return Response(StockAlertSerializer(alert).data)


class LotViewSet(viewsets.ModelViewSet):
    """ViewSet pour les lots"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return Lot.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return Lot.objects.filter(warehouse__agence_id__in=agences_ids)

    def get_serializer_class(self):
        if self.action == 'list':
            return LotListSerializer
        return LotDetailSerializer


class LotByProductView(generics.ListAPIView):
    """Lots par produit"""
    serializer_class = LotListSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        product_id = self.kwargs['product_id']
        return Lot.objects.filter(product_id=product_id, quantity__gt=0)


class ExpiringLotsView(generics.ListAPIView):
    """Lots expirant prochainement (dans 30 jours)"""
    serializer_class = LotListSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        from django.utils import timezone
        from datetime import timedelta
        
        expiry_limit = timezone.now().date() + timedelta(days=30)
        return Lot.objects.filter(
            expiry_date__lte=expiry_limit,
            expiry_date__gte=timezone.now().date(),
            quantity__gt=0
        )


class QualityControlViewSet(viewsets.ModelViewSet):
    """ViewSet pour les contrôles qualité"""
    queryset = QualityControl.objects.all()
    serializer_class = QualityControlSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]


class LocationByWarehouseView(generics.ListAPIView):
    """Emplacements par entrepôt"""
    serializer_class = LocationSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        warehouse_id = self.kwargs['warehouse_id']
        return Location.objects.filter(warehouse_id=warehouse_id, is_active=True)


class InventoryDashboardView(generics.GenericAPIView):
    """Dashboard inventaire"""
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get(self, request):
        from produits.models import Product
        
        user = request.user
        
        # Filtrer par agence
        if user.est_pdg() or user.est_drh():
            warehouses = Warehouse.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            warehouses = Warehouse.objects.filter(agence_id__in=agences_ids)
        
        products = Product.objects.all()
        
        data = {
            'total_warehouses': warehouses.count(),
            'total_products': products.count(),
            'total_stock_value': products.aggregate(total=Sum(F('stock_quantity') * F('purchase_price')))['total'] or 0,
            'low_stock_count': products.filter(stock_quantity__lte=F('minimum_stock')).count(),
            'out_of_stock_count': products.filter(stock_quantity=0).count(),
            'pending_transfers': Transfer.objects.filter(
                Q(from_warehouse__in=warehouses) | Q(to_warehouse__in=warehouses),
                status__in=['pending', 'in_transit']
            ).count(),
            'pending_inventories': InventoryCount.objects.filter(warehouse__in=warehouses, status='in_progress').count(),
            'active_alerts': StockAlert.objects.filter(warehouse__in=warehouses, status='active').count(),
            'expiring_soon': Lot.objects.filter(
                warehouse__in=warehouses,
                expiry_date__lte=timezone.now().date() + timezone.timedelta(days=30),
                quantity__gt=0
            ).count(),
        }
        
        return Response(data)