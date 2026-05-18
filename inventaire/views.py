from django.shortcuts import render
from rest_framework import viewsets, generics, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Sum, Q, F  # Sum est déjà ici
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess, IsPDG, IsChefAgence
from produits.models import Product


# inventaire/views.py - TransferViewSet complet corrigé

from django.shortcuts import render
from rest_framework import viewsets, generics, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Q, F
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess, IsPDG, IsChefAgence
from produits.models import Product


class TransferViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des transferts entre agences
    """
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
        """Soumettre un transfert pour approbation"""
        try:
            transfer = self.get_object()
            
            if transfer.status != 'draft':
                return Response(
                    {'error': 'Seul un transfert en brouillon peut être soumis'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if not request.user.peut_acceder_agence(transfer.to_agence.id):
                return Response(
                    {'error': 'Action non autorisée'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if transfer.from_agence.type_agence != 'principale' or transfer.to_agence.type_agence != 'secondaire':
                return Response(
                    {'error': 'Transfert non autorisé: l\'agence source doit être principale et la destination secondaire'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            transfer.status = 'pending_approval'
            transfer.save()
            
            return Response(TransferDetailSerializer(transfer).data)
            
        except Exception as e:
            return Response(
                {'error': f'Erreur lors de la soumission: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        """Approuver un transfert et diminuer le stock dans l'entrepôt source"""
        try:
            transfer = self.get_object()
            
            # Vérification du statut
            if transfer.status != 'pending_approval':
                return Response(
                    {'error': f'La demande doit être en attente d\'approbation. Statut actuel: {transfer.status}'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Vérification des droits
            if not request.user.peut_acceder_agence(transfer.from_agence.id):
                return Response(
                    {'error': 'Seul un responsable de l\'agence principale peut approuver'}, 
                    status=status.HTTP_403_FORBIDDEN
                )

            # Récupération des entrepôts
            from_warehouse = get_default_warehouse(transfer.from_agence)
            
            if not from_warehouse:
                return Response(
                    {'error': f'Entrepôt source non configuré pour l\'agence {transfer.from_agence.nom}'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Vérification des stocks dans l'entrepôt source
            stock_insuffisant = []
            items_sans_stock = []
            
            for item in transfer.items.all():
                from_stock = WarehouseStock.objects.filter(
                    product=item.product,
                    warehouse=from_warehouse,
                    variant=item.variant
                ).first()
                
                if not from_stock:
                    items_sans_stock.append({
                        'product': item.product.name,
                        'reference': item.product.reference,
                        'demande': item.quantity
                    })
                    continue
                
                if from_stock.quantity < item.quantity:
                    stock_insuffisant.append({
                        'product': item.product.name,
                        'reference': item.product.reference,
                        'disponible': from_stock.quantity,
                        'demande': item.quantity,
                        'manquant': item.quantity - from_stock.quantity
                    })

            if items_sans_stock:
                return Response(
                    {
                        'error': 'Certains produits n\'ont pas de stock configuré dans l\'entrepôt source',
                        'details': items_sans_stock
                    }, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            if stock_insuffisant:
                return Response(
                    {
                        'error': 'Stock insuffisant dans l\'entrepôt source',
                        'details': stock_insuffisant
                    }, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Créer les mouvements de sortie (le signal va gérer la mise à jour du stock)
            items_traites = []
            for item in transfer.items.all():
                movement = StockMovement.objects.create(
                    movement_type='transfer',
                    reference_type='transfer',
                    reference_id=transfer.id,
                    product=item.product,
                    variant=item.variant,
                    quantity=item.quantity,
                    from_warehouse=from_warehouse,
                    unit_price=item.unit_price,
                    notes=f"Transfert sortant {transfer.reference} vers {transfer.to_agence.nom}",
                    created_by=request.user
                )
                
                items_traites.append({
                    'product': item.product.name,
                    'quantity': item.quantity,
                    'movement_reference': movement.reference
                })

            # Mettre à jour le statut du transfert
            transfer.status = 'approved'
            transfer.approved_by = request.user
            transfer.approved_at = timezone.now()
            transfer.save()
            
            # Mettre à jour le stock global des produits
            for item in transfer.items.all():
                total_stock = WarehouseStock.objects.filter(product=item.product).aggregate(
                    total=Sum('quantity')
                )['total'] or 0
                if item.product.stock_quantity != total_stock:
                    item.product.stock_quantity = total_stock
                    item.product.save(update_fields=['stock_quantity', 'updated_at'])
            
            return Response({
                'success': True,
                'message': 'Transfert approuvé avec succès',
                'transfer': TransferDetailSerializer(transfer).data,
                'items_processed': items_traites
            })
            
        except Exception as e:
            return Response(
                {'error': f'Erreur lors de l\'approbation: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def start_transit(self, request, pk=None):
        """Démarrer le transit du transfert"""
        try:
            transfer = self.get_object()
            
            if transfer.status != 'approved':
                return Response(
                    {'error': f'Le transfert doit être approuvé. Statut actuel: {transfer.status}'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            transfer.status = 'in_transit'
            transfer.save()
            
            return Response({
                'success': True,
                'message': 'Transfert en transit',
                'transfer': TransferDetailSerializer(transfer).data
            })
            
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def receive(self, request, pk=None):
        """Réceptionner partiellement ou totalement un transfert"""
        try:
            transfer = self.get_object()
            
            # Vérification du statut
            if transfer.status not in ['in_transit', 'partial']:
                return Response(
                    {'error': f'Le transfert doit être en transit. Statut actuel: {transfer.status}'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Vérification des droits
            if not request.user.peut_acceder_agence(transfer.to_agence.id):
                return Response(
                    {'error': 'Action non autorisée'}, 
                    status=status.HTTP_403_FORBIDDEN
                )

            # Récupération des articles reçus
            received_items = request.data.get('items', [])
            if not received_items:
                return Response(
                    {'error': 'La liste des articles reçus est requise'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Récupération de l'entrepôt destination
            to_warehouse = get_default_warehouse(transfer.to_agence)
            if not to_warehouse:
                return Response(
                    {'error': f'Entrepôt destination non configuré pour {transfer.to_agence.nom}'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            all_completed = True
            items_recus = []
            
            for item_data in received_items:
                item_id = item_data.get('item_id')
                quantity_received = item_data.get('quantity', 0)
                
                if quantity_received <= 0:
                    continue
                    
                try:
                    transfer_item = TransferItem.objects.get(id=item_id, transfer=transfer)
                except TransferItem.DoesNotExist:
                    return Response(
                        {'error': f'Article avec ID {item_id} non trouvé dans ce transfert'}, 
                        status=status.HTTP_404_NOT_FOUND
                    )

                # Vérification des quantités
                remaining = transfer_item.quantity - transfer_item.quantity_received
                if quantity_received > remaining:
                    return Response(
                        {
                            'error': f'Quantité reçue pour {transfer_item.product.name} dépasse la quantité restante',
                            'product': transfer_item.product.name,
                            'quantite_recue': quantity_received,
                            'restant': remaining
                        }, 
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Mise à jour de la quantité reçue
                transfer_item.quantity_received += quantity_received
                transfer_item.save()

                # Créer le mouvement d'entrée (le signal va gérer la mise à jour du stock)
                movement = StockMovement.objects.create(
                    movement_type='transfer',
                    reference_type='transfer',
                    reference_id=transfer.id,
                    product=transfer_item.product,
                    variant=transfer_item.variant,
                    quantity=quantity_received,
                    to_warehouse=to_warehouse,
                    unit_price=transfer_item.unit_price,
                    notes=f"Réception transfert {transfer.reference}",
                    created_by=request.user
                )
                
                items_recus.append({
                    'product': transfer_item.product.name,
                    'quantity_received': quantity_received,
                    'total_received': transfer_item.quantity_received,
                    'total_ordered': transfer_item.quantity,
                    'movement_reference': movement.reference
                })

                if transfer_item.quantity_received < transfer_item.quantity:
                    all_completed = False

            # Mise à jour du statut du transfert
            transfer.status = 'completed' if all_completed else 'partial'
            if all_completed:
                transfer.completed_date = timezone.now().date()
            transfer.save()
            
            # Mettre à jour le stock global des produits concernés
            produits_modifies = set()
            for item_data in received_items:
                item_id = item_data.get('item_id')
                if item_id:
                    transfer_item = TransferItem.objects.get(id=item_id)
                    produits_modifies.add(transfer_item.product.id)
            
            for product_id in produits_modifies:
                product = Product.objects.get(id=product_id)
                total_stock = WarehouseStock.objects.filter(product=product).aggregate(
                    total=Sum('quantity')
                )['total'] or 0
                if product.stock_quantity != total_stock:
                    product.stock_quantity = total_stock
                    product.save(update_fields=['stock_quantity', 'updated_at'])
            
            return Response({
                'success': True,
                'message': 'Transfert réceptionné avec succès' if all_completed else 'Réception partielle effectuée',
                'all_completed': all_completed,
                'transfer': TransferDetailSerializer(transfer).data,
                'received_items': items_recus
            })
            
        except Exception as e:
            return Response(
                {'error': f'Erreur lors de la réception: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Rejeter un transfert"""
        try:
            transfer = self.get_object()
            
            if transfer.status != 'pending_approval':
                return Response(
                    {'error': 'La demande doit être en attente d\'approbation pour être rejetée'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if not request.user.peut_acceder_agence(transfer.from_agence.id):
                return Response(
                    {'error': 'Action non autorisée'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            reason = request.data.get('reason', '')
            if not reason:
                return Response(
                    {'error': 'Une raison est requise pour le rejet'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            transfer.status = 'rejected'
            transfer.rejected_reason = reason
            transfer.save()
            
            return Response({
                'success': True,
                'message': 'Transfert rejeté',
                'transfer': TransferDetailSerializer(transfer).data
            })
            
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, pk=None):
        """Annuler un transfert"""
        try:
            transfer = self.get_object()
            
            if transfer.status not in ['draft', 'pending_approval']:
                return Response(
                    {'error': 'Ce transfert ne peut pas être annulé car il est déjà en cours ou terminé'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            transfer.status = 'cancelled'
            transfer.save()
            
            return Response({
                'success': True,
                'message': 'Transfert annulé avec succès',
                'transfer': TransferDetailSerializer(transfer).data
            })
            
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def status(self, request, pk=None):
        """Obtenir le statut détaillé d'un transfert"""
        try:
            transfer = self.get_object()
            
            items_status = []
            for item in transfer.items.all():
                items_status.append({
                    'product_id': item.product.id,
                    'product_name': item.product.name,
                    'product_reference': item.product.reference,
                    'quantity_ordered': item.quantity,
                    'quantity_received': item.quantity_received,
                    'remaining': item.remaining_quantity,
                    'completion_percentage': round((item.quantity_received / item.quantity * 100), 2) if item.quantity > 0 else 0,
                    'unit_price': str(item.unit_price),
                    'total_value': str(item.quantity * item.unit_price),
                    'received_value': str(item.quantity_received * item.unit_price),
                    'notes': item.notes
                })
            
            return Response({
                'transfer_id': transfer.id,
                'reference': transfer.reference,
                'from_agence': transfer.from_agence.nom,
                'to_agence': transfer.to_agence.nom,
                'status': transfer.status,
                'status_display': transfer.get_status_display(),
                'transfer_date': transfer.transfer_date,
                'expected_date': transfer.expected_date,
                'completed_date': transfer.completed_date,
                'waybill': transfer.waybill,
                'notes': transfer.notes,
                'created_by': transfer.created_by.email if transfer.created_by else None,
                'created_at': transfer.created_at,
                'approved_by': transfer.approved_by.email if transfer.approved_by else None,
                'approved_at': transfer.approved_at,
                'rejected_reason': transfer.rejected_reason,
                'items': items_status,
                'total_items': len(items_status),
                'overall_completion': round(sum(item['completion_percentage'] for item in items_status) / len(items_status), 2) if items_status else 0
            })
            
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def update_waybill(self, request, pk=None):
        """Mettre à jour le numéro de bon de livraison"""
        try:
            transfer = self.get_object()
            waybill = request.data.get('waybill')
            
            if not waybill:
                return Response(
                    {'error': 'Le numéro de bon de livraison est requis'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            transfer.waybill = waybill
            transfer.save()
            
            return Response({
                'success': True,
                'message': 'Bon de livraison mis à jour',
                'waybill': transfer.waybill,
                'transfer': TransferDetailSerializer(transfer).data
            })
            
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def printable(self, request, pk=None):
        """Générer les données pour impression du bon de transfert"""
        try:
            transfer = self.get_object()
            
            items_data = []
            total_value = 0
            
            for item in transfer.items.all():
                item_total = item.quantity * item.unit_price
                total_value += item_total
                items_data.append({
                    'product_name': item.product.name,
                    'product_reference': item.product.reference,
                    'quantity': item.quantity,
                    'quantity_received': item.quantity_received,
                    'remaining': item.remaining_quantity,
                    'unit_price': str(item.unit_price),
                    'total': str(item_total),
                    'notes': item.notes
                })
            
            return Response({
                'transfer': {
                    'reference': transfer.reference,
                    'from_agence': transfer.from_agence.nom,
                    'to_agence': transfer.to_agence.nom,
                    'from_agence_address': transfer.from_agence.adresse,
                    'to_agence_address': transfer.to_agence.adresse,
                    'transfer_date': transfer.transfer_date,
                    'expected_date': transfer.expected_date,
                    'completed_date': transfer.completed_date,
                    'status': transfer.get_status_display(),
                    'waybill': transfer.waybill,
                    'notes': transfer.notes,
                    'created_by': transfer.created_by.get_full_name() if transfer.created_by else None,
                    'created_at': transfer.created_at,
                    'approved_by': transfer.approved_by.get_full_name() if transfer.approved_by else None,
                    'approved_at': transfer.approved_at
                },
                'items': items_data,
                'summary': {
                    'total_items': len(items_data),
                    'total_quantity': sum(item['quantity'] for item in items_data),
                    'total_received': sum(item['quantity_received'] for item in items_data),
                    'total_remaining': sum(item['remaining'] for item in items_data),
                    'total_value': str(total_value)
                }
            })
            
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
class WarehouseViewSet(viewsets.ModelViewSet):
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
    serializer_class = StockMovementListSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        product_id = self.kwargs['product_id']
        return StockMovement.objects.filter(product_id=product_id)


class StockMovementByWarehouseView(generics.ListAPIView):
    serializer_class = StockMovementListSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        warehouse_id = self.kwargs['warehouse_id']
        return StockMovement.objects.filter(
            Q(from_warehouse_id=warehouse_id) | Q(to_warehouse_id=warehouse_id)
        )



# inventaire/views.py - Version complète corrigée du TransferViewSet

from django.shortcuts import render
from rest_framework import viewsets, generics, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Q, F
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction
from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess, IsPDG, IsChefAgence
from produits.models import Product




class InventoryCountViewSet(viewsets.ModelViewSet):
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
    queryset = InventoryCount.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        inventory = self.get_object()
        serializer = InventoryCountValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if inventory.status != 'completed':
            return Response({'error': 'L\'inventaire doit être terminé'}, status=400)
        inventory.status = 'validated'
        inventory.validated_by = request.user
        if serializer.validated_data.get('create_movements'):
            for item in inventory.items.filter(difference__gt=0):
                StockMovement.objects.create(
                    movement_type='adjustment', reference_type='inventory', reference_id=inventory.id,
                    product=item.product, variant=item.variant, quantity=abs(item.difference),
                    to_warehouse=inventory.warehouse if item.difference > 0 else None,
                    from_warehouse=inventory.warehouse if item.difference < 0 else None,
                    unit_price=item.unit_price, notes=f"Ajustement inventaire {inventory.reference}",
                    created_by=request.user
                )
        inventory.save()
        return Response(InventoryCountDetailSerializer(inventory).data)


class InventoryCountGenerateView(generics.CreateAPIView):
    serializer_class = InventoryCountCreateSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def create(self, request, *args, **kwargs):
        warehouse_id = request.data.get('warehouse')
        warehouse = get_object_or_404(Warehouse, id=warehouse_id)
        products = Product.objects.filter(stock_quantity__gt=0)
        inventory = InventoryCount.objects.create(
            warehouse=warehouse, scheduled_date=request.data.get('scheduled_date'),
            notes=request.data.get('notes'), counted_by=request.user
        )
        for product in products:
            InventoryCountItem.objects.create(
                inventory=inventory, product=product,
                theoretical_quantity=product.stock_quantity, unit_price=product.purchase_price
            )
        inventory.total_items = inventory.items.count()
        inventory.save()
        return Response(InventoryCountDetailSerializer(inventory).data, status=201)


class StockAlertViewSet(viewsets.ReadOnlyModelViewSet):
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
    queryset = StockAlert.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        alert = self.get_object()
        alert.status = 'resolved'
        alert.resolved_at = timezone.now()
        alert.save()
        return Response(StockAlertSerializer(alert).data)


class AcknowledgeStockAlertView(generics.UpdateAPIView):
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
    serializer_class = LotListSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        product_id = self.kwargs['product_id']
        return Lot.objects.filter(product_id=product_id, quantity__gt=0)


class ExpiringLotsView(generics.ListAPIView):
    serializer_class = LotListSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        from datetime import timedelta
        expiry_limit = timezone.now().date() + timedelta(days=30)
        return Lot.objects.filter(expiry_date__lte=expiry_limit, expiry_date__gte=timezone.now().date(), quantity__gt=0)


class QualityControlViewSet(viewsets.ModelViewSet):
    queryset = QualityControl.objects.all()
    serializer_class = QualityControlSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]


class WarehouseStockViewSet(viewsets.ModelViewSet):
    serializer_class = WarehouseStockSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'adjust_stock']:
            return [IsAuthenticated(), IsPDG() | IsChefAgence()]
        return [IsAuthenticated(), HasAgenceAccess()]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg():
            return WarehouseStock.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        warehouses = Warehouse.objects.filter(agence_id__in=agences_ids)
        return WarehouseStock.objects.filter(warehouse__in=warehouses)

    @action(detail=False, methods=['get'])
    def by_warehouse(self, request):
        warehouse_id = request.query_params.get('warehouse_id')
        if not warehouse_id:
            return Response({'error': 'warehouse_id requis'}, status=400)
        stocks = self.get_queryset().filter(warehouse_id=warehouse_id)
        serializer = self.get_serializer(stocks, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_product(self, request):
        product_id = request.query_params.get('product_id')
        if not product_id:
            return Response({'error': 'product_id requis'}, status=400)
        stocks = self.get_queryset().filter(product_id=product_id)
        serializer = self.get_serializer(stocks, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        warehouse_id = request.query_params.get('warehouse_id')
        queryset = self.get_queryset()
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        low_stock_items = queryset.filter(quantity__lte=F('minimum_stock'))
        serializer = self.get_serializer(low_stock_items, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def adjust_stock(self, request, pk=None):
        warehouse_stock = self.get_object()
        new_quantity = request.data.get('quantity')
        reason = request.data.get('reason', 'Ajustement manuel')
        if new_quantity is None:
            return Response({'error': 'quantity requis'}, status=400)
        try:
            new_quantity = int(new_quantity)
            if new_quantity < 0:
                return Response({'error': 'La quantité ne peut pas être négative'}, status=400)
            old_quantity = warehouse_stock.quantity
            difference = new_quantity - old_quantity
            if difference != 0:
                movement_type = 'in' if difference > 0 else 'out'
                StockMovement.objects.create(
                    movement_type='adjustment', reference_type='manual',
                    product=warehouse_stock.product, variant=warehouse_stock.variant,
                    quantity=abs(difference),
                    to_warehouse=warehouse_stock.warehouse if difference > 0 else None,
                    from_warehouse=warehouse_stock.warehouse if difference < 0 else None,
                    unit_price=0, notes=f"Ajustement manuel: {reason}", created_by=request.user
                )
                warehouse_stock.quantity = new_quantity
                warehouse_stock.updated_by = request.user
                warehouse_stock.save()
                product = warehouse_stock.product
                total_stock = WarehouseStock.objects.filter(product=product).aggregate(total=Sum('quantity'))['total'] or 0
                product.stock_quantity = total_stock
                product.save()
            serializer = self.get_serializer(warehouse_stock)
            return Response({'message': f'Stock ajusté de {old_quantity} à {new_quantity}', 'stock': serializer.data})
        except ValueError:
            return Response({'error': 'La quantité doit être un nombre entier'}, status=400)

    @action(detail=False, methods=['post'])
    def initialize_stock(self, request):
        product_id = request.data.get('product_id')
        warehouse_id = request.data.get('warehouse_id')
        quantity = request.data.get('quantity', 0)
        if not product_id or not warehouse_id:
            return Response({'error': 'product_id et warehouse_id requis'}, status=400)
        try:
            product = Product.objects.get(id=product_id)
            warehouse = Warehouse.objects.get(id=warehouse_id)
            if not request.user.est_pdg() and not request.user.peut_acceder_agence(warehouse.agence.id):
                return Response({'error': 'Accès non autorisé'}, status=403)
            warehouse_stock, created = WarehouseStock.objects.get_or_create(
                product=product, warehouse=warehouse,
                defaults={'quantity': quantity, 'minimum_stock': product.minimum_stock,
                         'maximum_stock': product.maximum_stock, 'updated_by': request.user}
            )
            if not created:
                warehouse_stock.quantity = quantity
                warehouse_stock.updated_by = request.user
                warehouse_stock.save()
            total_stock = WarehouseStock.objects.filter(product=product).aggregate(total=Sum('quantity'))['total'] or 0
            product.stock_quantity = total_stock
            product.save()
            serializer = self.get_serializer(warehouse_stock)
            return Response(serializer.data, status=201)
        except Product.DoesNotExist:
            return Response({'error': 'Produit non trouvé'}, status=404)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Entrepôt non trouvé'}, status=404)


class LocationByWarehouseView(generics.ListAPIView):
    serializer_class = LocationSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        warehouse_id = self.kwargs['warehouse_id']
        return Location.objects.filter(warehouse_id=warehouse_id, is_active=True)


class InventoryDashboardView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get(self, request):
        user = request.user
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
                Q(from_agence__warehouses__in=warehouses) | Q(to_agence__warehouses__in=warehouses),
                status__in=['pending_approval', 'approved', 'in_transit']
            ).distinct().count(),
            'pending_inventories': InventoryCount.objects.filter(warehouse__in=warehouses, status='in_progress').count(),
            'active_alerts': StockAlert.objects.filter(warehouse__in=warehouses, status='active').count(),
            'expiring_soon': Lot.objects.filter(
                warehouse__in=warehouses,
                expiry_date__lte=timezone.now().date() + timezone.timedelta(days=30),
                expiry_date__gte=timezone.now().date(),
                quantity__gt=0
            ).count(),
        }
        return Response(data)