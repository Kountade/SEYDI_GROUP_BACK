from .models import Supplier
from django.utils import timezone
from rest_framework import serializers
from .models import *
from produits.serializers import ProductListSerializer, ProductVariantSerializer
from users.serializers import UserSerializer, AgenceSimpleSerializer
from inventaire.serializers import WarehouseSerializer
# purchases/serializers.py

# ... autres imports ...
from rest_framework import serializers
from django.db import models
from django.db import transaction
from django.utils import timezone
from .models import *
from produits.serializers import ProductListSerializer, ProductVariantSerializer
from users.serializers import UserSerializer, AgenceSimpleSerializer
from inventaire.serializers import WarehouseSerializer

# ...


class SupplierContactSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = SupplierContact
        fields = '__all__'

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"


class SupplierListSerializer(serializers.ModelSerializer):
    supplier_type_display = serializers.CharField(
        source='get_supplier_type_display', read_only=True)

# serializers.py (version simplifiée)


class SupplierListSerializer(serializers.ModelSerializer):
    """Sérializer pour la liste des fournisseurs (champs essentiels)"""
    class Meta:
        model = Supplier
        fields = (
            'id', 'code', 'company_name', 'email', 'phone',
            'city', 'country', 'is_active'
        )


class SupplierDetailSerializer(serializers.ModelSerializer):
    """Sérializer pour le détail d'un fournisseur (tous les champs)"""
    class Meta:
        model = Supplier
        fields = (
            'id', 'code', 'company_name', 'email', 'phone',
            'address', 'city', 'country', 'is_active', 'notes',
            'created_at', 'updated_at'
        )
        read_only_fields = ('created_at', 'updated_at')


class SupplierCreateUpdateSerializer(serializers.ModelSerializer):
    """Sérializer pour la création/modification"""
    class Meta:
        model = Supplier
        fields = (
            'code', 'company_name', 'email', 'phone',
            'address', 'city', 'country', 'is_active', 'notes'
        )


class SupplierEvaluationSerializer(serializers.ModelSerializer):
    evaluator_name = serializers.CharField(
        source='evaluator.email', read_only=True)

    class Meta:
        model = SupplierEvaluation
        fields = '__all__'
        read_only_fields = ('total_score', 'created_at')


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)
    remaining = serializers.IntegerField(
        source='remaining_quantity', read_only=True)

    class Meta:
        model = PurchaseOrderItem
        fields = '__all__'
        read_only_fields = ('subtotal', 'tax_amount',
                            'total', 'created_at', 'purchase_order')


class PurchaseOrderListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source='supplier.company_name', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    urgency_display = serializers.CharField(
        source='get_urgency_display', read_only=True)
    items_count = serializers.IntegerField(
        source='items.count', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True, default=None)
    items = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = ('id', 'order_number', 'supplier_name', 'agence_nom', 'order_date', 'expected_date',
                  'status', 'status_display', 'urgency', 'urgency_display', 'total',
                  'items_count', 'supplier_reference', 'warehouse_name', 'items')

    def get_items(self, obj):
        return [
            {
                'id': item.id,
                'product': item.product.id,
                'product_name': item.product.name,
                'product_reference': item.product.reference,
                'quantity_ordered': item.quantity_ordered,
                'quantity_received': item.quantity_received,
                'unit_price': item.unit_price,
                'total': item.total,
                'remaining_quantity': item.remaining_quantity,
                'is_fully_received': item.is_fully_received
            }
            for item in obj.items.all()
        ]


class PurchaseOrderDetailSerializer(serializers.ModelSerializer):
    supplier = SupplierListSerializer(read_only=True)
    agence = AgenceSimpleSerializer(read_only=True)
    warehouse = WarehouseSerializer(read_only=True)
    items = PurchaseOrderItemSerializer(many=True, read_only=True)
    created_by = UserSerializer(read_only=True)
    validated_by = UserSerializer(read_only=True)
    receipts = serializers.SerializerMethodField()
    waybills = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = '__all__'

    def get_receipts(self, obj):
        return PurchaseReceiptSerializer(obj.receipts.all(), many=True).data

    def get_waybills(self, obj):
        return WaybillSerializer(obj.waybills.all(), many=True).data


class PurchaseOrderCreateUpdateSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            'supplier',
            'supplier_reference',
            'agence',
            'expected_date',
            'urgency',
            'warehouse',
            'shipping_address',
            'notes',
            'internal_notes',
            'terms_conditions',
            'items'
        ]
        read_only_fields = ('order_number', 'created_by', 'validated_by',
                            'created_at', 'updated_at', 'order_date')

    def validate(self, data):
        if not data.get('shipping_address') and not data.get('warehouse'):
            raise serializers.ValidationError({
                'shipping_address': 'L\'adresse de livraison ou l\'entrepôt de réception est obligatoire'
            })

        if not data.get('items'):
            raise serializers.ValidationError({
                'items': 'Au moins un produit est requis'
            })

        for item in data.get('items', []):
            if not item.get('product'):
                raise serializers.ValidationError({
                    'items': 'Chaque ligne doit avoir un produit sélectionné'
                })
            if item.get('quantity_ordered', 0) <= 0:
                raise serializers.ValidationError({
                    'items': 'La quantité doit être supérieure à 0'
                })
            if item.get('unit_price', 0) <= 0:
                raise serializers.ValidationError({
                    'items': 'Le prix unitaire doit être supérieur à 0'
                })

        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        order = PurchaseOrder.objects.create(**validated_data)

        for item_data in items_data:
            PurchaseOrderItem.objects.create(purchase_order=order, **item_data)

        order.calculate_totals()
        return order

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                PurchaseOrderItem.objects.create(
                    purchase_order=instance, **item_data)

        instance.calculate_totals()
        return instance

# Ajoutez dans serializers.py


class PurchaseOrderUpdateStatusSerializer(serializers.ModelSerializer):
    """Serializer spécifique pour la mise à jour du statut"""

    class Meta:
        model = PurchaseOrder
        fields = ['status']

    def validate_status(self, value):
        instance = self.instance
        if instance:
            allowed_transitions = {
                'draft': ['sent', 'cancelled'],
                'sent': ['confirmed', 'cancelled'],
                'confirmed': ['in_transit', 'cancelled'],
                'in_transit': ['partially_received', 'received'],
                'partially_received': ['received'],
            }

            current_status = instance.status
            if current_status in allowed_transitions:
                if value not in allowed_transitions[current_status]:
                    raise serializers.ValidationError(
                        f"Transition non autorisée: {current_status} -> {value}"
                    )
            elif current_status not in ['draft', 'sent', 'confirmed', 'in_transit', 'partially_received']:
                raise serializers.ValidationError(
                    f"Impossible de modifier le statut: la commande est {dict(PurchaseOrder.STATUS_CHOICES).get(current_status, current_status)}"
                )

        return value


class PurchaseReceiptItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source='order_item.product.name', read_only=True)
    product_reference = serializers.CharField(
        source='order_item.product.reference', read_only=True)
    product_id = serializers.IntegerField(
        source='order_item.product.id', read_only=True)

    class Meta:
        model = PurchaseReceiptItem
        fields = '__all__'

# Ajoutez ou modifiez dans serializers.py


class PurchaseReceiptSerializer(serializers.ModelSerializer):
    items = PurchaseReceiptItemSerializer(many=True, read_only=True)
    received_by_name = serializers.CharField(
        source='received_by.email', read_only=True)

    # Ajoutez ces champs calculés
    total_value = serializers.SerializerMethodField()
    total_costs = serializers.SerializerMethodField()
    supplier_name = serializers.SerializerMethodField()
    order_number = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseReceipt
        fields = '__all__'
        read_only_fields = ('receipt_number', 'created_at')

    def get_total_value(self, obj):
        """Calcule la valeur totale des marchandises reçues"""
        total = 0
        for item in obj.items.all():
            # Utiliser le prix unitaire du moment de la réception
            total += item.order_item.unit_price * item.quantity
        return total

    def get_total_costs(self, obj):
        """Calcule le total des frais annexes"""
        # Si vous avez des frais liés à la réception
        total = obj.costs.aggregate(total=models.Sum(
            'amount_in_local_currency'))['total']
        return total or 0

    def get_supplier_name(self, obj):
        """Retourne le nom du fournisseur"""
        return obj.purchase_order.supplier.company_name if obj.purchase_order else None

    def get_order_number(self, obj):
        """Retourne le numéro de commande"""
        return obj.purchase_order.order_number if obj.purchase_order else None


# purchases/serializers.py - PurchaseReceiptCreateSerializer COMPLET

# purchases/serializers.py

from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from django.db import models
from .models import *
from produits.serializers import ProductListSerializer, ProductVariantSerializer
from users.serializers import UserSerializer, AgenceSimpleSerializer
from inventaire.serializers import WarehouseSerializer

# purchases/serializers.py - PurchaseReceiptCreateSerializer COMPLET CORRIGÉ

# purchases/serializers.py - PurchaseReceiptCreateSerializer COMPLET

class PurchaseReceiptCreateSerializer(serializers.ModelSerializer):
    items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True
    )
    costs = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        write_only=True
    )
    waybill_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True
    )

    class Meta:
        model = PurchaseReceipt
        fields = [
            'purchase_order', 'notes', 'items', 'costs', 'waybill_ids',
            'caisse_destination', 'compte_destination'
        ]
        read_only_fields = ('receipt_number', 'created_at', 'received_by')

    def validate_purchase_order(self, value):
        if isinstance(value, PurchaseOrder):
            purchase_order_id = value.id
        else:
            purchase_order_id = value

        try:
            purchase_order = PurchaseOrder.objects.get(id=purchase_order_id)
            return purchase_order
        except PurchaseOrder.DoesNotExist:
            raise serializers.ValidationError("Commande non trouvée")

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Au moins un article est requis")

        for idx, item in enumerate(value):
            if 'order_item' not in item:
                raise serializers.ValidationError({
                    f'items[{idx}]': "Le champ 'order_item' est requis"
                })

            if 'quantity' not in item:
                raise serializers.ValidationError({
                    f'items[{idx}]': "Le champ 'quantity' est requis"
                })

            quantity = item.get('quantity', 0)
            if quantity <= 0:
                raise serializers.ValidationError({
                    f'items[{idx}]': "La quantité doit être supérieure à 0"
                })

            try:
                order_item = PurchaseOrderItem.objects.get(id=item['order_item'])
                item['order_item_obj'] = order_item

                remaining = order_item.quantity_ordered - order_item.quantity_received
                if quantity > remaining:
                    raise serializers.ValidationError({
                        f'items[{idx}]':
                        f"Impossible de recevoir {quantity} unités. "
                        f"Quantité restante: {remaining}"
                    })

                expiry_date = item.get('expiry_date')
                if expiry_date:
                    from datetime import datetime
                    try:
                        if isinstance(expiry_date, str):
                            expiry_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()
                        if expiry_date < datetime.now().date():
                            raise serializers.ValidationError({
                                f'items[{idx}]':
                                "La date d'expiration ne peut pas être dans le passé"
                            })
                    except ValueError:
                        raise serializers.ValidationError({
                            f'items[{idx}]':
                            "Format de date invalide (YYYY-MM-DD)"
                        })

            except PurchaseOrderItem.DoesNotExist:
                raise serializers.ValidationError({
                    f'items[{idx}]':
                    f"Ligne de commande {item['order_item']} introuvable"
                })
            except Exception as e:
                raise serializers.ValidationError({
                    f'items[{idx}]': f"Erreur: {str(e)}"
                })

        return value

    def validate(self, data):
        purchase_order = data.get('purchase_order')

        if not purchase_order:
            raise serializers.ValidationError({
                'purchase_order': 'La commande est obligatoire'
            })

        if purchase_order.status == 'draft':
            raise serializers.ValidationError({
                'purchase_order':
                'Cette commande est un brouillon. Elle doit être confirmée avant réception.'
            })

        if purchase_order.status == 'received':
            raise serializers.ValidationError({
                'purchase_order': 'Cette commande est déjà entièrement reçue.'
            })

        if purchase_order.status == 'cancelled':
            raise serializers.ValidationError({
                'purchase_order': 'Cette commande est annulée.'
            })

        if purchase_order.status not in ['confirmed', 'sent', 'in_transit', 'partially_received']:
            raise serializers.ValidationError({
                'purchase_order':
                f'Cette commande (statut: {purchase_order.get_status_display()}) ne peut pas être réceptionnée.'
            })

        has_items_to_receive = any(
            item.get('quantity', 0) > 0 for item in data.get('items', [])
        )
        if not has_items_to_receive:
            raise serializers.ValidationError({
                'items': 'Au moins un article doit être reçu'
            })

        return data

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        costs_data = validated_data.pop('costs', [])
        waybill_ids = validated_data.pop('waybill_ids', [])
        purchase_order = validated_data.pop('purchase_order')

        # Générer le numéro de réception
        last_receipt = PurchaseReceipt.objects.order_by('-id').first()
        if last_receipt:
            try:
                last_num = int(last_receipt.receipt_number.replace('REC', ''))
                receipt_number = f"REC{str(last_num + 1).zfill(6)}"
            except (ValueError, AttributeError):
                receipt_number = "REC000001"
        else:
            receipt_number = "REC000001"

        # ✅ CRÉER LA RÉCEPTION
        receipt = PurchaseReceipt.objects.create(
            receipt_number=receipt_number,
            purchase_order=purchase_order,
            notes=validated_data.get('notes', ''),
            received_by=self.context['request'].user,
            caisse_destination=validated_data.get('caisse_destination'),
            compte_destination=validated_data.get('compte_destination')
            # auto_invoice est True par défaut
        )

        print(f"✅ RÉCEPTION CRÉÉE: {receipt.receipt_number}")

        # ✅ CRÉER LES LIGNES DE RÉCEPTION
        for item_data in items_data:
            order_item = item_data.pop('order_item_obj')
            quantity_received = item_data['quantity']

            remaining = order_item.quantity_ordered - order_item.quantity_received
            if quantity_received > remaining:
                raise serializers.ValidationError({
                    'items':
                    f"Impossible de recevoir {quantity_received} de "
                    f"{order_item.product.name}. Quantité restante: {remaining}"
                })

            receipt_item = PurchaseReceiptItem.objects.create(
                receipt=receipt,
                order_item=order_item,
                quantity=quantity_received,
                quality_checked=item_data.get('quality_checked', False),
                quality_ok=item_data.get('quality_ok', True),
                quality_notes=item_data.get('quality_notes', ''),
                lot_number=item_data.get('lot_number', ''),
                serial_numbers=item_data.get('serial_numbers', []),
                expiry_date=item_data.get('expiry_date') or None,
                notes=item_data.get('notes', '')
            )

            order_item.quantity_received += quantity_received
            order_item.save()

            self._update_stock_on_receipt(
                purchase_order=purchase_order,
                order_item=order_item,
                quantity=quantity_received,
                item_data=item_data
            )

        # Ajouter les frais
        for cost_data in costs_data:
            ReceiptCost.objects.create(receipt=receipt, **cost_data)

        # Mettre à jour le statut de la commande
        self._update_order_status(purchase_order)

        # ✅ FORCER LE RAFFRAÎCHISSEMENT
        receipt.refresh_from_db()

        print(f"✅ RÉCEPTION FINALISÉE: {receipt.receipt_number}")
        print(f"📦 ITEMS: {receipt.items.count()}")
        print(f"💰 TOTAL: {receipt.total_received_amount}")

        return receipt

    def _update_order_status(self, purchase_order):
        all_items = purchase_order.items.all()

        fully_received = 0
        partially_received = 0

        for item in all_items:
            if item.is_fully_received:
                fully_received += 1
            elif item.is_partially_received:
                partially_received += 1

        total_items = all_items.count()

        if fully_received == total_items:
            purchase_order.status = 'received'
            purchase_order.received_date = timezone.now().date()
        elif fully_received > 0 or partially_received > 0:
            purchase_order.status = 'partially_received'

        purchase_order.save()

    def _update_stock_on_receipt(self, purchase_order, order_item, quantity, item_data=None):
        from inventaire.models import StockMovement, Warehouse, Lot, StockAlert

        try:
            with transaction.atomic():
                if purchase_order.warehouse:
                    warehouse = purchase_order.warehouse
                else:
                    warehouse = Warehouse.objects.filter(
                        agence=purchase_order.agence,
                        is_default=True
                    ).first()
                    if not warehouse:
                        warehouse = Warehouse.objects.filter(
                            agence=purchase_order.agence).first()
                    if not warehouse:
                        raise Exception(
                            f"Aucun entrepôt configuré pour l'agence {purchase_order.agence.nom}")

                StockMovement.objects.create(
                    movement_type='in',
                    reference_type='purchase',
                    reference_id=purchase_order.id,
                    product=order_item.product,
                    variant=order_item.variant,
                    quantity=quantity,
                    to_warehouse=warehouse,
                    unit_price=order_item.unit_price,
                    total_price=order_item.unit_price * quantity,
                    notes=f"Réception commande {purchase_order.order_number}",
                    created_by=self.context['request'].user
                )

                product = order_item.product
                product.stock_quantity += quantity
                product.save()

                if item_data and item_data.get('lot_number'):
                    lot, created = Lot.objects.get_or_create(
                        lot_number=item_data['lot_number'],
                        product=product,
                        defaults={
                            'warehouse': warehouse,
                            'quantity': quantity,
                            'expiry_date': item_data.get('expiry_date'),
                            'manufacturing_date': timezone.now().date(),
                            'supplier': purchase_order.supplier.company_name,
                            'purchase_order': purchase_order.order_number
                        }
                    )
                    if not created:
                        lot.quantity += quantity
                        lot.save()

        except Exception as e:
            raise serializers.ValidationError(
                f"Erreur lors de la mise à jour du stock: {str(e)}")



class PurchaseReceiptDetailSerializer(serializers.ModelSerializer):
    items = PurchaseReceiptItemSerializer(many=True, read_only=True)
    received_by_name = serializers.CharField(
        source='received_by.email', read_only=True)
    costs = serializers.SerializerMethodField()
    # waybills = serializers.SerializerMethodField()  # ← COMMENTEZ OU SUPPRIMEZ CETTE LIGNE
    total_costs = serializers.SerializerMethodField()

    # Ajoutez ces champs
    total_value = serializers.SerializerMethodField()
    supplier_name = serializers.SerializerMethodField()
    order_number = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseReceipt
        fields = '__all__'
        read_only_fields = ('receipt_number', 'created_at')

    def get_costs(self, obj):
        return ReceiptCostSerializer(obj.costs.all(), many=True).data

    # COMMENTEZ OU SUPPRIMEZ CETTE MÉTHODE
    # def get_waybills(self, obj):
    #     return WaybillSerializer(obj.waybills.all(), many=True).data

    def get_total_costs(self, obj):
        total = obj.costs.aggregate(total=models.Sum(
            'amount_in_local_currency'))['total']
        return total or 0

    def get_total_value(self, obj):
        """Calcule la valeur totale des marchandises reçues"""
        total = 0
        for item in obj.items.all():
            total += item.order_item.unit_price * item.quantity
        return total

    def get_supplier_name(self, obj):
        return obj.purchase_order.supplier.company_name if obj.purchase_order else None

    def get_order_number(self, obj):
        return obj.purchase_order.order_number if obj.purchase_order else None


class TransporterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transporter
        fields = '__all__'


class WaybillSerializer(serializers.ModelSerializer):
    transporter_name = serializers.CharField(
        source='transporter.name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.email', read_only=True)

    class Meta:
        model = Waybill
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at', 'created_by')


class ReceiptCostSerializer(serializers.ModelSerializer):
    cost_type_display = serializers.CharField(
        source='get_cost_type_display', read_only=True)
    receipt_number = serializers.CharField(
        source='receipt.receipt_number', read_only=True)

    class Meta:
        model = ReceiptCost
        fields = '__all__'
        read_only_fields = ('amount_in_local_currency', 'created_at')


class ReceiptCostAllocationSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    allocation_method_display = serializers.CharField(
        source='get_allocation_method_display', read_only=True)

    class Meta:
        model = ReceiptCostAllocation
        fields = '__all__'


class PurchasePriceHistorySerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    supplier_name = serializers.CharField(
        source='supplier.company_name', read_only=True)

    class Meta:
        model = PurchasePriceHistory
        fields = '__all__'


class SupplierCatalogSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source='supplier.company_name', read_only=True)
    imported_by_name = serializers.CharField(
        source='imported_by.email', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = SupplierCatalog
        fields = '__all__'
        read_only_fields = ('import_date', 'imported_by',
                            'products_imported', 'status', 'error_log')


class SupplierCatalogImportSerializer(serializers.Serializer):
    file = serializers.FileField()
    supplier = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    file_format = serializers.ChoiceField(choices=['csv', 'excel'])


class PurchaseAlertSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    supplier_name = serializers.CharField(
        source='supplier.company_name', read_only=True)
    alert_type_display = serializers.CharField(
        source='get_alert_type_display', read_only=True)

    class Meta:
        model = PurchaseAlert
        fields = '__all__'


class PurchaseOrderStatsSerializer(serializers.Serializer):
    total_orders = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    average_order_value = serializers.DecimalField(
        max_digits=10, decimal_places=2)
    pending_orders = serializers.IntegerField()
    late_orders = serializers.IntegerField()
    top_suppliers = serializers.ListField(child=serializers.DictField())
    monthly_spending = serializers.ListField(child=serializers.DictField())


# purchases/serializers.py - Ajoutez ces sérializers

class InvoiceItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    
    class Meta:
        model = InvoiceItem
        fields = '__all__'
        read_only_fields = ('subtotal', 'tax_amount', 'total', 'created_at')

# purchases/serializers.py - Assurez-vous que PaymentSerializer est importé

class PaymentSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.email', read_only=True)
    
    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('payment_number', 'created_at', 'updated_at')


# purchases/serializers.py - Corrigez InvoiceSerializer

class InvoiceSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.company_name', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items = InvoiceItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    payment_progress = serializers.FloatField(read_only=True)
    is_fully_paid = serializers.BooleanField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Invoice
        fields = '__all__'
        read_only_fields = ('invoice_number', 'created_at', 'updated_at')


class InvoiceCreateSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, required=False)  # ✅ Rendre optionnel pour la création auto
    
    class Meta:
        model = Invoice
        fields = [
            'supplier', 'agence', 'purchase_receipt', 'purchase_order',
            'invoice_date', 'due_date', 'invoice_type', 'discount',
            'shipping_cost', 'notes', 'internal_notes', 'items'
        ]
        read_only_fields = ('invoice_number', 'created_at', 'updated_at')
    
    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        invoice = Invoice.objects.create(**validated_data)
        
        # Si des items sont fournis, les créer
        for item_data in items_data:
            InvoiceItem.objects.create(invoice=invoice, **item_data)
        
        # ✅ Recalculer les totaux à partir des items
        invoice.subtotal = sum(item.subtotal for item in invoice.items.all())
        invoice.tax_total = sum(item.tax_amount for item in invoice.items.all())
        invoice.total = invoice.subtotal + invoice.tax_total - invoice.discount + invoice.shipping_cost
        invoice.amount_remaining = invoice.total
        invoice.save()
        
        return invoice

class PaymentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            'invoice', 'amount', 'payment_method', 'payment_date',
            'caisse', 'compte_bancaire', 'reference_number', 'notes'
        ]
        read_only_fields = ('payment_number', 'created_at', 'updated_at')
    
    def validate(self, data):
        invoice = data.get('invoice')
        amount = data.get('amount')
        
        if amount > invoice.amount_remaining:
            raise serializers.ValidationError(
                f"Le montant ({amount}) dépasse le montant restant ({invoice.amount_remaining})"
            )
        
        # Vérifier qu'une destination est spécifiée
        caisse = data.get('caisse')
        compte = data.get('compte_bancaire')
        
        if not caisse and not compte:
            raise serializers.ValidationError(
                "Veuillez spécifier une caisse ou un compte bancaire"
            )
        
        if caisse and compte:
            raise serializers.ValidationError(
                "Veuillez choisir une seule destination (caisse ou compte)"
            )
        
        return data
    
    def create(self, validated_data):
        invoice = validated_data.get('invoice')
        amount = validated_data.get('amount')
        
        # Créer le paiement
        payment = Payment.objects.create(
            **validated_data,
            payment_number=f"PAY{str(Payment.objects.count() + 1).zfill(6)}",
            created_by=self.context['request'].user,
            status='completed'
        )
        
        # Mettre à jour la facture
        invoice.amount_paid += amount
        invoice.save()
        
        # Créer le mouvement de trésorerie
        payment.create_treasury_movement()
        
        return payment