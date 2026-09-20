# inventaire/views.py

from django.shortcuts import render
from rest_framework import viewsets, generics, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Q, F, OuterRef, Subquery
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction
from datetime import timedelta

from .models import *
from .serializers import *
from users.permissions import (
    HasAgenceAccess,
    IsPDG,
    IsChefAgence,
    IsPDGOrChefAgence,
)
from produits.models import Product, ProductVariant, ProductPricing


# ============================================================
# UTILITAIRE : Recalcul des totaux d'un inventaire
# ============================================================

def recalc_inventory_totals(inventory):
    """Recalcule et sauvegarde les totaux d'un inventaire."""
    items = inventory.items.all()
    inventory.total_items = items.count()
    inventory.total_differences = items.exclude(difference=0).count()
    inventory.total_difference_value = sum(
        (item.difference_value or 0) for item in items
    )
    inventory.save(update_fields=[
        'total_items', 'total_differences',
        'total_difference_value', 'updated_at'
    ])
    return inventory


def get_product_purchase_price(product, warehouse):
    """
    ✅ Récupère le prix d'achat d'un produit pour un entrepôt donné.
    Le prix est stocké dans ProductPricing (par entrepôt), pas dans Product.
    """
    if not product or not warehouse:
        return 0
    pricing = ProductPricing.objects.filter(
        product=product,
        warehouse=warehouse,
        is_current=True,
    ).first()
    if pricing and pricing.purchase_price is not None:
        return pricing.purchase_price
    return 0


# ============================================================
# TRANSFER VIEWSET
# ============================================================

class TransferViewSet(viewsets.ModelViewSet):
    """ViewSet pour la gestion des transferts entre agences"""
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
        try:
            transfer = self.get_object()
            if transfer.status != 'draft':
                return Response(
                    {'error': 'Seul un transfert en brouillon peut être soumis'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not request.user.peut_acceder_agence(transfer.to_agence.id):
                return Response(
                    {'error': 'Action non autorisée'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if (transfer.from_agence.type_agence != 'principale'
                    or transfer.to_agence.type_agence != 'secondaire'):
                return Response(
                    {'error': "Transfert non autorisé"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            transfer.status = 'pending_approval'
            transfer.save()
            return Response(TransferDetailSerializer(transfer).data)
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        try:
            transfer = self.get_object()
            if transfer.status != 'pending_approval':
                return Response(
                    {'error': f"Statut actuel: {transfer.status}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not request.user.peut_acceder_agence(transfer.from_agence.id):
                return Response(
                    {'error': "Action non autorisée"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            from_warehouse = get_default_warehouse(transfer.from_agence)
            if not from_warehouse:
                return Response(
                    {'error': f"Entrepôt source non configuré"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            stock_insuffisant = []
            items_sans_stock = []

            for item in transfer.items.all():
                from_stock = WarehouseStock.objects.filter(
                    product=item.product,
                    warehouse=from_warehouse,
                    variant=item.variant,
                ).first()
                if not from_stock:
                    items_sans_stock.append({
                        'product': item.product.name,
                        'reference': item.product.reference,
                        'demande': item.quantity,
                    })
                    continue
                if from_stock.quantity < item.quantity:
                    stock_insuffisant.append({
                        'product': item.product.name,
                        'reference': item.product.reference,
                        'disponible': from_stock.quantity,
                        'demande': item.quantity,
                    })

            if items_sans_stock:
                return Response(
                    {'error': "Certains produits n'ont pas de stock",
                     'details': items_sans_stock},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if stock_insuffisant:
                return Response(
                    {'error': "Stock insuffisant",
                     'details': stock_insuffisant},
                    status=status.HTTP_400_BAD_REQUEST,
                )

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
                    notes=f"Transfert sortant {transfer.reference}",
                    created_by=request.user,
                )
                items_traites.append({
                    'product': item.product.name,
                    'quantity': item.quantity,
                    'movement_reference': movement.reference,
                })

            transfer.status = 'approved'
            transfer.approved_by = request.user
            transfer.approved_at = timezone.now()
            transfer.save()

            for item in transfer.items.all():
                total_stock = WarehouseStock.objects.filter(
                    product=item.product
                ).aggregate(total=Sum('quantity'))['total'] or 0
                if item.product.stock_quantity != total_stock:
                    item.product.stock_quantity = total_stock
                    item.product.save(
                        update_fields=['stock_quantity', 'updated_at'])

            return Response({
                'success': True,
                'message': 'Transfert approuvé',
                'transfer': TransferDetailSerializer(transfer).data,
                'items_processed': items_traites,
            })
        except Exception as e:
            return Response(
                {'error': f"Erreur: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def start_transit(self, request, pk=None):
        try:
            transfer = self.get_object()
            if transfer.status != 'approved':
                return Response(
                    {'error': f"Statut actuel: {transfer.status}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            transfer.status = 'in_transit'
            transfer.save()
            return Response({
                'success': True,
                'message': 'Transfert en transit',
                'transfer': TransferDetailSerializer(transfer).data,
            })
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def receive(self, request, pk=None):
        try:
            transfer = self.get_object()
            if transfer.status not in ['in_transit', 'partial']:
                return Response(
                    {'error': f"Statut actuel: {transfer.status}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not request.user.peut_acceder_agence(transfer.to_agence.id):
                return Response(
                    {'error': 'Action non autorisée'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            received_items = request.data.get('items', [])
            if not received_items:
                return Response(
                    {'error': 'La liste des articles reçus est requise'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            to_warehouse = get_default_warehouse(transfer.to_agence)
            if not to_warehouse:
                return Response(
                    {'error': f"Entrepôt destination non configuré"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            all_completed = True
            items_recus = []

            for item_data in received_items:
                item_id = item_data.get('item_id')
                quantity_received = item_data.get('quantity', 0)
                if quantity_received <= 0:
                    continue

                try:
                    transfer_item = TransferItem.objects.get(
                        id=item_id, transfer=transfer
                    )
                except TransferItem.DoesNotExist:
                    return Response(
                        {'error': f'Article {item_id} non trouvé'},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                remaining = transfer_item.quantity - transfer_item.quantity_received
                if quantity_received > remaining:
                    return Response(
                        {'error': f"Quantité dépasse le restant pour {transfer_item.product.name}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                transfer_item.quantity_received += quantity_received
                transfer_item.save()

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
                    created_by=request.user,
                )

                items_recus.append({
                    'product': transfer_item.product.name,
                    'quantity_received': quantity_received,
                    'movement_reference': movement.reference,
                })

                if transfer_item.quantity_received < transfer_item.quantity:
                    all_completed = False

            transfer.status = 'completed' if all_completed else 'partial'
            if all_completed:
                transfer.completed_date = timezone.now().date()
            transfer.save()

            produits_modifies = set()
            for item_data in received_items:
                item_id = item_data.get('item_id')
                if item_id:
                    ti = TransferItem.objects.get(id=item_id)
                    produits_modifies.add(ti.product.id)

            for product_id in produits_modifies:
                product = Product.objects.get(id=product_id)
                total_stock = WarehouseStock.objects.filter(
                    product=product
                ).aggregate(total=Sum('quantity'))['total'] or 0
                if product.stock_quantity != total_stock:
                    product.stock_quantity = total_stock
                    product.save(update_fields=[
                                 'stock_quantity', 'updated_at'])

            return Response({
                'success': True,
                'message': 'Transfert réceptionné',
                'all_completed': all_completed,
                'transfer': TransferDetailSerializer(transfer).data,
                'received_items': items_recus,
            })
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        try:
            transfer = self.get_object()
            if transfer.status != 'pending_approval':
                return Response(
                    {'error': "La demande doit être en attente d'approbation"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not request.user.peut_acceder_agence(transfer.from_agence.id):
                return Response(
                    {'error': 'Action non autorisée'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            reason = request.data.get('reason', '')
            if not reason:
                return Response(
                    {'error': 'Une raison est requise'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            transfer.status = 'rejected'
            transfer.rejected_reason = reason
            transfer.save()
            return Response({
                'success': True,
                'message': 'Transfert rejeté',
                'transfer': TransferDetailSerializer(transfer).data,
            })
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, pk=None):
        try:
            transfer = self.get_object()
            if transfer.status not in ['draft', 'pending_approval']:
                return Response(
                    {'error': 'Ce transfert ne peut pas être annulé'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            transfer.status = 'cancelled'
            transfer.save()
            return Response({
                'success': True,
                'message': 'Transfert annulé',
                'transfer': TransferDetailSerializer(transfer).data,
            })
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['get'])
    def status(self, request, pk=None):
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
                    'completion_percentage': round(
                        (item.quantity_received / item.quantity * 100), 2
                    ) if item.quantity > 0 else 0,
                    'unit_price': str(item.unit_price),
                    'notes': item.notes,
                })
            return Response({
                'transfer_id': transfer.id,
                'reference': transfer.reference,
                'status': transfer.status,
                'status_display': transfer.get_status_display(),
                'items': items_status,
                'total_items': len(items_status),
            })
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['post'])
    def update_waybill(self, request, pk=None):
        try:
            transfer = self.get_object()
            waybill = request.data.get('waybill')
            if not waybill:
                return Response(
                    {'error': 'Le numéro de bon de livraison est requis'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            transfer.waybill = waybill
            transfer.save()
            return Response({
                'success': True,
                'waybill': transfer.waybill,
                'transfer': TransferDetailSerializer(transfer).data,
            })
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['get'])
    def printable(self, request, pk=None):
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
                    'notes': item.notes,
                })
            return Response({
                'transfer': {
                    'reference': transfer.reference,
                    'from_agence': transfer.from_agence.nom,
                    'to_agence': transfer.to_agence.nom,
                    'status': transfer.get_status_display(),
                    'waybill': transfer.waybill,
                    'notes': transfer.notes,
                },
                'items': items_data,
                'summary': {
                    'total_items': len(items_data),
                    'total_quantity': sum(i['quantity'] for i in items_data),
                    'total_value': str(total_value),
                },
            })
        except Exception as e:
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ============================================================
# WAREHOUSE VIEWSET
# ============================================================

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


# ============================================================
# LOCATION VIEWSET
# ============================================================

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


# ============================================================
# STOCK MOVEMENT VIEWSET
# ============================================================

class StockMovementViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        qs = StockMovement.objects.select_related(
            'product', 'variant', 'from_warehouse', 'to_warehouse', 'created_by'
        ).all()

        if user.is_superuser or user.is_staff:
            pass
        elif user.est_pdg() or user.est_drh():
            pass
        else:
            agences_ids = list(user.get_agences().values_list('id', flat=True))
            if agences_ids:
                qs = qs.filter(
                    Q(from_warehouse__agence_id__in=agences_ids) |
                    Q(to_warehouse__agence_id__in=agences_ids)
                )
            else:
                qs = qs.none()

        movement_type = self.request.query_params.get('movement_type')
        if movement_type:
            qs = qs.filter(movement_type=movement_type)

        product = self.request.query_params.get('product')
        if product:
            try:
                qs = qs.filter(product_id=int(product))
            except (ValueError, TypeError):
                pass

        warehouse = self.request.query_params.get('warehouse')
        if warehouse:
            try:
                wid = int(warehouse)
                qs = qs.filter(
                    Q(from_warehouse_id=wid) | Q(to_warehouse_id=wid)
                )
            except (ValueError, TypeError):
                pass

        date_debut = self.request.query_params.get('date_debut')
        if date_debut:
            qs = qs.filter(movement_date__date__gte=date_debut)

        date_fin = self.request.query_params.get('date_fin')
        if date_fin:
            qs = qs.filter(movement_date__date__lte=date_fin)

        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(reference__icontains=search) |
                Q(product__name__icontains=search) |
                Q(product__reference__icontains=search) |
                Q(notes__icontains=search)
            )

        return qs.order_by('-movement_date')

    def get_serializer_class(self):
        if self.action == 'list':
            return StockMovementListSerializer
        if self.action == 'retrieve':
            return StockMovementDetailSerializer
        return StockMovementCreateSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def export(self, request):
        import csv
        from django.http import HttpResponse
        qs = self.get_queryset()
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="mouvements_stock_{timezone.now().date()}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow([
            'Référence', 'Type', 'Produit', 'Référence produit', 'Quantité',
            'Entrepôt source', 'Entrepôt destination', 'Prix unitaire',
            'Total', 'Date', 'Créé par', 'Notes'
        ])
        for m in qs:
            writer.writerow([
                m.reference,
                m.get_movement_type_display(),
                m.product.name if m.product else '',
                m.product.reference if m.product else '',
                m.quantity,
                m.from_warehouse.name if m.from_warehouse else '',
                m.to_warehouse.name if m.to_warehouse else '',
                m.unit_price,
                m.total_price,
                m.movement_date.strftime('%Y-%m-%d %H:%M:%S'),
                m.created_by.email if m.created_by else '',
                m.notes or '',
            ])
        return response


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


# ============================================================
# INVENTORY COUNT VIEWSET ✅ COMPLET ET CORRIGÉ
# ============================================================

class InventoryCountViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des inventaires.

    Workflow :
        draft → in_progress → completed → validated
                          ↘ cancelled ↙
    """
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

    # ============================================================
    # ✅ PUT/PATCH : interception des changements de statut
    # ============================================================
    def update(self, request, *args, **kwargs):
        """
        Intercepte les changements de statut :
        - status='in_progress' → appelle start() (génère les items)
        - status='completed'   → appelle complete()
        - status='validated'   → appelle validate()
        - status='cancelled'   → appelle cancel()
        """
        instance = self.get_object()
        new_status = request.data.get('status')

        if new_status and new_status != instance.status:
            if new_status == 'in_progress':
                return self.start(request, pk=kwargs.get('pk'))
            elif new_status == 'completed':
                return self.complete(request, pk=kwargs.get('pk'))
            elif new_status == 'validated':
                return self.validate(request, pk=kwargs.get('pk'))
            elif new_status == 'cancelled':
                return self.cancel(request, pk=kwargs.get('pk'))

        return super().update(request, *args, **kwargs)

    # ============================================================
    # ✅ ACTION : start (draft → in_progress + génération des items)
    # ============================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def start(self, request, pk=None):
        """
        Démarre l'inventaire :
        - Vérifie le statut (draft)
        - Génère les InventoryCountItem depuis WarehouseStock
        - Récupère les prix depuis ProductPricing (par entrepôt)
        - Passe le statut à 'in_progress'
        """
        inventory = self.get_object()

        if inventory.status != 'draft':
            return Response(
                {'error': f"Seul un inventaire en brouillon peut être démarré. "
                          f"Statut actuel: {inventory.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if inventory.items.exists():
            return Response(
                {'error': "Les articles ont déjà été générés",
                 'items_count': inventory.items.count()},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Récupérer le stock de l'entrepôt
        stocks = WarehouseStock.objects.filter(
            warehouse=inventory.warehouse
        ).select_related('product', 'variant')

        if not stocks.exists():
            return Response(
                {'error': f"Aucun stock à inventorier dans l'entrepôt "
                          f"'{inventory.warehouse.name}'. "
                          f"Ajoutez d'abord du stock via /stocks/ajouter."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ✅ Créer les items en récupérant le prix depuis ProductPricing
        items_to_create = []
        for stock in stocks:
            # ✅ Récupérer le prix d'achat depuis ProductPricing (par entrepôt)
            pricing = ProductPricing.objects.filter(
                product=stock.product,
                warehouse=inventory.warehouse,
                is_current=True,
            ).first()

            unit_price = pricing.purchase_price if pricing else 0

            items_to_create.append(InventoryCountItem(
                inventory=inventory,
                product=stock.product,
                variant=stock.variant,
                theoretical_quantity=stock.quantity,
                counted_quantity=0,
                unit_price=unit_price,
                is_counted=False,
            ))

        InventoryCountItem.objects.bulk_create(items_to_create)

        inventory.status = 'in_progress'
        inventory.save()
        recalc_inventory_totals(inventory)

        return Response({
            'success': True,
            'message': f'{len(items_to_create)} article(s) généré(s)',
            'items_count': len(items_to_create),
            'inventory': InventoryCountDetailSerializer(
                inventory, context={'request': request}
            ).data,
        })

    # ============================================================
    # ✅ ACTION : complete (in_progress → completed)
    # ============================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def complete(self, request, pk=None):
        """Termine l'inventaire : recalcule les totaux, passe à 'completed'."""
        inventory = self.get_object()

        if inventory.status != 'in_progress':
            return Response(
                {'error': f"Seul un inventaire en cours peut être terminé. "
                          f"Statut actuel: {inventory.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        recalc_inventory_totals(inventory)
        inventory.status = 'completed'
        inventory.save()

        return Response({
            'success': True,
            'message': 'Inventaire terminé',
            'inventory': InventoryCountDetailSerializer(
                inventory, context={'request': request}
            ).data,
        })

    # ============================================================
    # ✅ ACTION : validate (completed → validated + ajustements)
    # ============================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def validate(self, request, pk=None):
        """Valide définitivement l'inventaire + crée les ajustements."""
        inventory = self.get_object()

        if inventory.status != 'completed':
            return Response(
                {'error': f"Seul un inventaire terminé peut être validé. "
                          f"Statut actuel: {inventory.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        create_movements = request.data.get('create_movements', True)
        notes = request.data.get('notes', '')

        movements_created = []
        products_updated = set()

        if create_movements:
            for item in inventory.items.exclude(difference=0):
                movement = StockMovement.objects.create(
                    movement_type='adjustment',
                    reference_type='inventory',
                    reference_id=inventory.id,
                    product=item.product,
                    variant=item.variant,
                    quantity=abs(item.difference),
                    to_warehouse=inventory.warehouse if item.difference > 0 else None,
                    from_warehouse=inventory.warehouse if item.difference < 0 else None,
                    unit_price=item.unit_price,
                    notes=f"Ajustement inventaire {inventory.reference} "
                          f"(théorique: {item.theoretical_quantity}, "
                          f"compté: {item.counted_quantity})",
                    created_by=request.user,
                )
                movements_created.append(movement.reference)
                products_updated.add(item.product_id)

        for product_id in products_updated:
            product = Product.objects.get(id=product_id)
            total_stock = WarehouseStock.objects.filter(
                product=product
            ).aggregate(total=Sum('quantity'))['total'] or 0
            if product.stock_quantity != total_stock:
                product.stock_quantity = total_stock
                product.save(update_fields=['stock_quantity', 'updated_at'])

        inventory.status = 'validated'
        inventory.validated_by = request.user
        if notes:
            inventory.notes = (inventory.notes or '') + f"\n[Validation] {notes}"
        inventory.save()

        return Response({
            'success': True,
            'message': f'Inventaire validé. {len(movements_created)} ajustement(s) créé(s).',
            'movements_created': movements_created,
            'products_updated': len(products_updated),
            'inventory': InventoryCountDetailSerializer(
                inventory, context={'request': request}
            ).data,
        })

    # ============================================================
    # ✅ ACTION : cancel
    # ============================================================
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Annule un inventaire."""
        inventory = self.get_object()

        if inventory.status == 'validated':
            return Response(
                {'error': "Un inventaire validé ne peut plus être annulé"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if inventory.status == 'cancelled':
            return Response(
                {'error': "Cet inventaire est déjà annulé"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        inventory.status = 'cancelled'
        inventory.save()

        return Response({
            'success': True,
            'message': 'Inventaire annulé',
            'inventory': InventoryCountDetailSerializer(
                inventory, context={'request': request}
            ).data,
        })

    # ============================================================
    # ✅ ACTION : update_item (PATCH /inventory-counts/{id}/items/{item_id}/)
    # ============================================================
    @action(
        detail=True,
        methods=['patch'],
        url_path=r'items/(?P<item_id>[^/.]+)',
    )
    @transaction.atomic
    def update_item(self, request, pk=None, item_id=None):
        """Met à jour un item de l'inventaire (saisie du comptage)."""
        inventory = self.get_object()

        if inventory.status not in ['in_progress', 'draft']:
            return Response(
                {'error': f"Impossible de modifier les items d'un inventaire "
                          f"en statut '{inventory.status}'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            item = inventory.items.get(id=item_id)
        except InventoryCountItem.DoesNotExist:
            return Response(
                {'error': 'Article non trouvé dans cet inventaire'},
                status=status.HTTP_404_NOT_FOUND,
            )

        counted = request.data.get('counted_quantity')
        if counted is None:
            return Response(
                {'error': 'counted_quantity est requis'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            counted = int(counted)
            if counted < 0:
                raise ValueError
        except (ValueError, TypeError):
            return Response(
                {'error': 'counted_quantity doit être un entier positif ou zéro'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        item.counted_quantity = counted
        item.is_counted = request.data.get('is_counted', True)
        item.save()

        recalc_inventory_totals(inventory)

        return Response({
            'success': True,
            'item': InventoryCountItemSerializer(item).data,
            'inventory': {
                'total_items': inventory.total_items,
                'total_differences': inventory.total_differences,
                'total_difference_value': str(inventory.total_difference_value),
            },
        })

    # ============================================================
    # ✅ ACTION : list_items (GET /inventory-counts/{id}/items/)
    # ============================================================
    @action(detail=True, methods=['get'], url_path='items')
    def list_items(self, request, pk=None):
        """Liste tous les items d'un inventaire."""
        inventory = self.get_object()
        items = inventory.items.all().select_related('product', 'variant')
        serializer = InventoryCountItemSerializer(items, many=True)
        return Response(serializer.data)

    # ============================================================
    # ✅ ACTION : generate_items (alias de start)
    # ============================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def generate_items(self, request, pk=None):
        """Alias de start()."""
        return self.start(request, pk)


# ============================================================
# INVENTORY COUNT VALIDATE VIEW (URL historique)
# ============================================================

class InventoryCountValidateView(generics.UpdateAPIView):
    queryset = InventoryCount.objects.all()
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def update(self, request, *args, **kwargs):
        inventory = self.get_object()

        if inventory.status != 'completed':
            return Response(
                {'error': "L'inventaire doit être terminé pour être validé"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = InventoryCountValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        create_movements = serializer.validated_data.get('create_movements', True)
        movements_created = []
        products_updated = set()

        if create_movements:
            for item in inventory.items.exclude(difference=0):
                movement = StockMovement.objects.create(
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
                    created_by=request.user,
                )
                movements_created.append(movement.reference)
                products_updated.add(item.product_id)

        for product_id in products_updated:
            product = Product.objects.get(id=product_id)
            total_stock = WarehouseStock.objects.filter(
                product=product
            ).aggregate(total=Sum('quantity'))['total'] or 0
            if product.stock_quantity != total_stock:
                product.stock_quantity = total_stock
                product.save(update_fields=['stock_quantity', 'updated_at'])

        inventory.status = 'validated'
        inventory.validated_by = request.user
        inventory.save()

        return Response({
            'success': True,
            'message': f'Inventaire validé. {len(movements_created)} ajustement(s).',
            'movements_created': movements_created,
            'inventory': InventoryCountDetailSerializer(inventory).data,
        })


# ============================================================
# INVENTORY COUNT GENERATE VIEW ✅ CORRIGÉE
# ============================================================

class InventoryCountGenerateView(generics.CreateAPIView):
    """Crée un inventaire ET génère immédiatement ses items."""
    serializer_class = InventoryCountCreateSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        warehouse_id = request.data.get('warehouse')
        if not warehouse_id:
            return Response(
                {'error': 'warehouse est requis'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        warehouse = get_object_or_404(Warehouse, id=warehouse_id)

        inventory = InventoryCount.objects.create(
            warehouse=warehouse,
            scheduled_date=request.data.get('scheduled_date'),
            notes=request.data.get('notes'),
            counted_by=request.user,
            status='in_progress',
        )

        stocks = WarehouseStock.objects.filter(
            warehouse=warehouse
        ).select_related('product', 'variant')

        items_to_create = []
        for stock in stocks:
            # ✅ Récupérer le prix depuis ProductPricing
            pricing = ProductPricing.objects.filter(
                product=stock.product,
                warehouse=warehouse,
                is_current=True,
            ).first()
            unit_price = pricing.purchase_price if pricing else 0

            items_to_create.append(InventoryCountItem(
                inventory=inventory,
                product=stock.product,
                variant=stock.variant,
                theoretical_quantity=stock.quantity,
                counted_quantity=0,
                unit_price=unit_price,
                is_counted=False,
            ))

        if items_to_create:
            InventoryCountItem.objects.bulk_create(items_to_create)

        recalc_inventory_totals(inventory)

        return Response(
            InventoryCountDetailSerializer(inventory).data,
            status=status.HTTP_201_CREATED,
        )


# ============================================================
# STOCK ALERT VIEWSET
# ============================================================

class StockAlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockAlert.objects.all()
    serializer_class = StockAlertSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return StockAlert.objects.filter(status='active')
        agences_ids = user.get_agences().values_list('id', flat=True)
        return StockAlert.objects.filter(
            status='active',
            warehouse__agence_id__in=agences_ids,
        )


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


# ============================================================
# LOT VIEWSET
# ============================================================

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
        if self.action == 'retrieve':
            return LotDetailSerializer
        return LotCreateSerializer


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
        expiry_limit = timezone.now().date() + timedelta(days=30)
        return Lot.objects.filter(
            expiry_date__lte=expiry_limit,
            expiry_date__gte=timezone.now().date(),
            quantity__gt=0,
        )


# ============================================================
# QUALITY CONTROL VIEWSET
# ============================================================

class QualityControlViewSet(viewsets.ModelViewSet):
    queryset = QualityControl.objects.all()
    serializer_class = QualityControlSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]


# ============================================================
# WAREHOUSE STOCK VIEWSET
# ============================================================

class WarehouseStockViewSet(viewsets.ModelViewSet):
    serializer_class = WarehouseStockSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_permissions(self):
        if self.action in [
            'create', 'update', 'partial_update', 'destroy',
            'adjust_stock', 'add_stock', 'initialize_stock',
        ]:
            return [IsAuthenticated(), IsPDGOrChefAgence()]
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

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def add_stock(self, request):
        """Ajoute du stock à un produit dans un entrepôt avec traçabilité."""
        product_id = request.data.get('product_id')
        warehouse_id = request.data.get('warehouse_id')
        quantity = request.data.get('quantity')
        variant_id = request.data.get('variant_id')
        notes = request.data.get('notes', 'Ajout manuel de stock')
        unit_price = request.data.get('unit_price', 0) or 0

        if not product_id or not warehouse_id:
            return Response(
                {'error': 'product_id et warehouse_id sont requis'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            quantity = int(quantity)
            if quantity <= 0:
                return Response(
                    {'error': 'La quantité doit être supérieure à 0'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (ValueError, TypeError):
            return Response(
                {'error': 'La quantité doit être un nombre entier valide'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            return Response({'error': 'Produit non trouvé'}, status=404)

        try:
            warehouse = Warehouse.objects.get(id=warehouse_id)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Entrepôt non trouvé'}, status=404)

        if not request.user.est_pdg() and not request.user.peut_acceder_agence(warehouse.agence.id):
            return Response(
                {'error': 'Accès non autorisé à cet entrepôt'},
                status=status.HTTP_403_FORBIDDEN,
            )

        variant = None
        if variant_id:
            try:
                variant = ProductVariant.objects.get(id=variant_id, product=product)
            except ProductVariant.DoesNotExist:
                return Response(
                    {'error': 'Variante non trouvée pour ce produit'},
                    status=404,
                )

        existing_stock = WarehouseStock.objects.filter(
            product=product, warehouse=warehouse, variant=variant
        ).first()
        old_quantity = existing_stock.quantity if existing_stock else 0

        try:
            movement = StockMovement.objects.create(
                movement_type='in',
                reference_type='manual',
                product=product,
                variant=variant,
                quantity=quantity,
                to_warehouse=warehouse,
                unit_price=unit_price,
                notes=notes,
                created_by=request.user,
            )
            movement_ref = movement.reference
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {'error': f'Erreur lors de la création du mouvement: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        warehouse_stock = WarehouseStock.objects.get(
            product=product, warehouse=warehouse, variant=variant
        )

        total_stock = WarehouseStock.objects.filter(product=product).aggregate(
            total=Sum('quantity')
        )['total'] or 0
        if product.stock_quantity != total_stock:
            product.stock_quantity = total_stock
            product.save(update_fields=['stock_quantity', 'updated_at'])

        serializer = self.get_serializer(warehouse_stock)
        return Response(
            {
                'success': True,
                'message': f'Stock ajouté : {old_quantity} → {warehouse_stock.quantity} unités',
                'was_created': existing_stock is None,
                'old_quantity': old_quantity,
                'added_quantity': quantity,
                'new_quantity': warehouse_stock.quantity,
                'total_product_stock': total_stock,
                'movement_reference': movement_ref,
                'stock': serializer.data,
            },
            status=status.HTTP_200_OK if existing_stock else status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def adjust_stock(self, request, pk=None):
        warehouse_stock = self.get_object()
        new_quantity = request.data.get('quantity')
        reason = request.data.get('reason', 'Ajustement manuel')

        if new_quantity is None:
            return Response({'error': 'quantity requis'}, status=400)

        try:
            new_quantity = int(new_quantity)
            if new_quantity < 0:
                return Response(
                    {'error': 'La quantité ne peut pas être négative'},
                    status=400,
                )
        except (ValueError, TypeError):
            return Response(
                {'error': 'La quantité doit être un nombre entier'},
                status=400,
            )

        old_quantity = warehouse_stock.quantity
        difference = new_quantity - old_quantity

        if difference == 0:
            serializer = self.get_serializer(warehouse_stock)
            return Response({
                'message': 'Aucun changement de quantité',
                'stock': serializer.data,
            })

        try:
            movement = StockMovement.objects.create(
                movement_type='adjustment',
                reference_type='manual',
                product=warehouse_stock.product,
                variant=warehouse_stock.variant,
                quantity=abs(difference),
                to_warehouse=warehouse_stock.warehouse if difference > 0 else None,
                from_warehouse=warehouse_stock.warehouse if difference < 0 else None,
                unit_price=0,
                notes=f"Ajustement manuel: {reason} ({old_quantity} → {new_quantity})",
                created_by=request.user,
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {'error': f'Erreur création mouvement: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        warehouse_stock.refresh_from_db()

        product = warehouse_stock.product
        total_stock = WarehouseStock.objects.filter(product=product).aggregate(
            total=Sum('quantity')
        )['total'] or 0
        if product.stock_quantity != total_stock:
            product.stock_quantity = total_stock
            product.save(update_fields=['stock_quantity', 'updated_at'])

        serializer = self.get_serializer(warehouse_stock)
        return Response({
            'success': True,
            'message': f'Stock ajusté de {old_quantity} à {new_quantity}',
            'movement_reference': movement.reference,
            'stock': serializer.data,
        })

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def initialize_stock(self, request):
        product_id = request.data.get('product_id')
        warehouse_id = request.data.get('warehouse_id')
        quantity = request.data.get('quantity', 0)

        if not product_id or not warehouse_id:
            return Response(
                {'error': 'product_id et warehouse_id requis'},
                status=400,
            )

        try:
            quantity = int(quantity)
            if quantity < 0:
                return Response(
                    {'error': 'La quantité ne peut pas être négative'},
                    status=400,
                )
        except (ValueError, TypeError):
            return Response({'error': 'Quantité invalide'}, status=400)

        try:
            product = Product.objects.get(id=product_id)
            warehouse = Warehouse.objects.get(id=warehouse_id)
        except Product.DoesNotExist:
            return Response({'error': 'Produit non trouvé'}, status=404)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Entrepôt non trouvé'}, status=404)

        if not request.user.est_pdg() and not request.user.peut_acceder_agence(warehouse.agence.id):
            return Response({'error': 'Accès non autorisé'}, status=403)

        existing_stock = WarehouseStock.objects.filter(
            product=product, warehouse=warehouse, variant=None
        ).first()

        if existing_stock:
            difference = quantity - existing_stock.quantity
            if difference != 0:
                StockMovement.objects.create(
                    movement_type='adjustment',
                    reference_type='manual',
                    product=product,
                    quantity=abs(difference),
                    to_warehouse=warehouse if difference > 0 else None,
                    from_warehouse=warehouse if difference < 0 else None,
                    unit_price=0,
                    notes=f"Initialisation: {existing_stock.quantity} → {quantity}",
                    created_by=request.user,
                )
                existing_stock.refresh_from_db()

            serializer = self.get_serializer(existing_stock)
            return Response(serializer.data, status=200)

        if quantity > 0:
            StockMovement.objects.create(
                movement_type='in',
                reference_type='manual',
                product=product,
                quantity=quantity,
                to_warehouse=warehouse,
                unit_price=0,
                notes="Initialisation de stock",
                created_by=request.user,
            )

        warehouse_stock = WarehouseStock.objects.get(
            product=product, warehouse=warehouse, variant=None
        )

        total_stock = WarehouseStock.objects.filter(product=product).aggregate(
            total=Sum('quantity')
        )['total'] or 0
        product.stock_quantity = total_stock
        product.save(update_fields=['stock_quantity', 'updated_at'])

        serializer = self.get_serializer(warehouse_stock)
        return Response(serializer.data, status=201)


# ============================================================
# LOCATION BY WAREHOUSE
# ============================================================

class LocationByWarehouseView(generics.ListAPIView):
    serializer_class = LocationSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get_queryset(self):
        warehouse_id = self.kwargs['warehouse_id']
        return Location.objects.filter(warehouse_id=warehouse_id, is_active=True)


# ============================================================
# INVENTORY DASHBOARD ✅ CORRIGÉ
# ============================================================

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
        today = timezone.now().date()
        in_30_days = today + timedelta(days=30)

        # ✅ Calcul de la valeur du stock via ProductPricing (par entrepôt)
        # Sous-requête pour récupérer le prix d'achat actuel d'un produit
        pricing_subquery = ProductPricing.objects.filter(
            product=OuterRef('pk'),
            is_current=True,
        ).values('purchase_price')[:1]

        products_with_price = products.annotate(
            current_purchase_price=Subquery(pricing_subquery)
        )

        total_stock_value = 0
        for product in products_with_price:
            price = product.current_purchase_price or 0
            total_stock_value += (product.stock_quantity or 0) * price

        data = {
            'total_warehouses': warehouses.count(),
            'total_products': products.count(),
            'total_stock_value': total_stock_value,
            'low_stock_count': products.filter(
                stock_quantity__lte=F('minimum_stock')
            ).count(),
            'out_of_stock_count': products.filter(stock_quantity=0).count(),
            'pending_transfers': Transfer.objects.filter(
                Q(from_agence__warehouses__in=warehouses) |
                Q(to_agence__warehouses__in=warehouses),
                status__in=['pending_approval', 'approved', 'in_transit'],
            ).distinct().count(),
            'pending_inventories': InventoryCount.objects.filter(
                warehouse__in=warehouses, status='in_progress'
            ).count(),
            'active_alerts': StockAlert.objects.filter(
                warehouse__in=warehouses, status='active'
            ).count(),
            'expiring_soon': Lot.objects.filter(
                warehouse__in=warehouses,
                expiry_date__lte=in_30_days,
                expiry_date__gte=today,
                quantity__gt=0,
            ).count(),
        }
        return Response(data)