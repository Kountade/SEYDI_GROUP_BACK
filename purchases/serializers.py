from django.utils import timezone
from rest_framework import serializers
from .models import *
from produits.serializers import ProductListSerializer, ProductVariantSerializer
from users.serializers import UserSerializer, AgenceSimpleSerializer
from inventaire.serializers import WarehouseSerializer


class SupplierContactSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = SupplierContact
        fields = '__all__'

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"


class SupplierListSerializer(serializers.ModelSerializer):
    supplier_type_display = serializers.CharField(source='get_supplier_type_display', read_only=True)

    class Meta:
        model = Supplier
        fields = ('id', 'code', 'company_name', 'supplier_type', 'supplier_type_display',
                  'contact_name', 'email', 'phone', 'city', 'country',
                  'rating', 'is_preferred', 'is_active', 'total_orders')


class SupplierDetailSerializer(serializers.ModelSerializer):
    contacts = SupplierContactSerializer(many=True, read_only=True)
    evaluations = serializers.SerializerMethodField()
    payment_terms_display = serializers.CharField(source='get_payment_terms_display', read_only=True)
    delivery_terms_display = serializers.CharField(source='get_delivery_terms_display', read_only=True)

    class Meta:
        model = Supplier
        fields = '__all__'

    def get_evaluations(self, obj):
        return SupplierEvaluationSerializer(obj.evaluations.all()[:5], many=True).data


class SupplierCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at', 'created_by', 'updated_by',
                            'total_orders', 'total_spent', 'average_delivery_delay',
                            'on_time_delivery_rate')


class SupplierEvaluationSerializer(serializers.ModelSerializer):
    evaluator_name = serializers.CharField(source='evaluator.email', read_only=True)

    class Meta:
        model = SupplierEvaluation
        fields = '__all__'
        read_only_fields = ('total_score', 'created_at')


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(source='product.reference', read_only=True)
    remaining = serializers.IntegerField(source='remaining_quantity', read_only=True)

    class Meta:
        model = PurchaseOrderItem
        fields = '__all__'
        read_only_fields = ('subtotal', 'tax_amount', 'total', 'created_at', 'purchase_order')


class PurchaseOrderListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.company_name', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    urgency_display = serializers.CharField(source='get_urgency_display', read_only=True)
    items_count = serializers.IntegerField(source='items.count', read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True, default=None)
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
                'remaining_quantity': item.remaining_quantity
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
                PurchaseOrderItem.objects.create(purchase_order=instance, **item_data)

        instance.calculate_totals()
        return instance


class PurchaseReceiptItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='order_item.product.name', read_only=True)
    product_reference = serializers.CharField(source='order_item.product.reference', read_only=True)
    product_id = serializers.IntegerField(source='order_item.product.id', read_only=True)

    class Meta:
        model = PurchaseReceiptItem
        fields = '__all__'


class PurchaseReceiptSerializer(serializers.ModelSerializer):
    items = PurchaseReceiptItemSerializer(many=True, read_only=True)
    received_by_name = serializers.CharField(source='received_by.email', read_only=True)
    total_costs = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseReceipt
        fields = '__all__'
        read_only_fields = ('receipt_number', 'created_at')

    def get_total_costs(self, obj):
        total = obj.costs.aggregate(total=models.Sum('amount_in_local_currency'))['total']
        return total or 0


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
        fields = ['purchase_order', 'notes', 'items', 'costs', 'waybill_ids']
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

                if order_item.remaining_quantity < quantity:
                    raise serializers.ValidationError({
                        f'items[{idx}]': f"La quantité reçue ({quantity}) dépasse la quantité restante ({order_item.remaining_quantity})"
                    })

            except PurchaseOrderItem.DoesNotExist:
                raise serializers.ValidationError({
                    f'items[{idx}]': "Ligne de commande introuvable"
                })

        return value

    def validate(self, data):
        purchase_order = data.get('purchase_order')

        if not purchase_order:
            raise serializers.ValidationError({
                'purchase_order': 'La commande est obligatoire'
            })

        if purchase_order.status not in ['confirmed', 'in_transit', 'partially_received']:
            raise serializers.ValidationError({
                'purchase_order': f'Cette commande (statut: {purchase_order.get_status_display()}) ne peut pas être réceptionnée'
            })

        return data

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

        # Créer la réception
        receipt = PurchaseReceipt.objects.create(
            receipt_number=receipt_number,
            purchase_order=purchase_order,
            notes=validated_data.get('notes', ''),
            received_by=self.context['request'].user
        )

        # Ajouter les frais
        for cost_data in costs_data:
            ReceiptCost.objects.create(receipt=receipt, **cost_data)

        # Associer les bons de transport
        if waybill_ids:
            receipt.waybills.set(waybill_ids)

        # Créer les lignes de réception
        for item_data in items_data:
            order_item = item_data.pop('order_item_obj')
            quantity_received = item_data['quantity']

            PurchaseReceiptItem.objects.create(
                receipt=receipt,
                order_item=order_item,
                quantity=quantity_received,
                quality_checked=item_data.get('quality_checked', False),
                quality_ok=item_data.get('quality_ok', True),
                quality_notes=item_data.get('quality_notes', ''),
                lot_number=item_data.get('lot_number', ''),
                serial_numbers=item_data.get('serial_numbers', []),
                expiry_date=item_data.get('expiry_date', None) or None,
                notes=item_data.get('notes', '')
            )

            order_item.quantity_received += quantity_received
            order_item.save()

            # Mettre à jour le stock
            self._update_stock_on_receipt(
                purchase_order=purchase_order,
                order_item=order_item,
                quantity=quantity_received,
                item_data=item_data
            )

        # Mettre à jour le statut de la commande
        all_items = purchase_order.items.all()
        all_received = all(
            item.quantity_received >= item.quantity_ordered
            for item in all_items
        )

        if all_received:
            purchase_order.status = 'received'
            purchase_order.received_date = timezone.now().date()
        else:
            purchase_order.status = 'partially_received'
        purchase_order.save()

        return receipt

    def _update_stock_on_receipt(self, purchase_order, order_item, quantity, item_data=None):
        """Met à jour le stock dans l'entrepôt"""
        from inventaire.models import StockMovement, Warehouse, Lot, StockAlert
        from django.db import transaction

        try:
            with transaction.atomic():
                # Récupérer l'entrepôt
                if purchase_order.warehouse:
                    warehouse = purchase_order.warehouse
                else:
                    warehouse = Warehouse.objects.filter(
                        agence=purchase_order.agence,
                        is_default=True
                    ).first()
                    if not warehouse:
                        warehouse = Warehouse.objects.filter(agence=purchase_order.agence).first()
                    if not warehouse:
                        raise Exception(f"Aucun entrepôt configuré pour l'agence {purchase_order.agence.nom}")

                # Créer un mouvement de stock
                stock_movement = StockMovement.objects.create(
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

                # Mettre à jour le stock du produit
                product = order_item.product
                product.stock_quantity += quantity
                product.save()

                # Gestion des lots
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

                # Vérifier les alertes
                if product.maximum_stock and product.stock_quantity > product.maximum_stock:
                    StockAlert.objects.create(
                        product=product,
                        warehouse=warehouse,
                        alert_type='overstock',
                        current_quantity=product.stock_quantity,
                        threshold=product.maximum_stock,
                        message=f"Surstock pour {product.name}"
                    )

                return stock_movement

        except Exception as e:
            raise serializers.ValidationError(f"Erreur lors de la mise à jour du stock: {str(e)}")


class PurchaseReceiptDetailSerializer(serializers.ModelSerializer):
    items = PurchaseReceiptItemSerializer(many=True, read_only=True)
    received_by_name = serializers.CharField(source='received_by.email', read_only=True)
    costs = serializers.SerializerMethodField()
    waybills = serializers.SerializerMethodField()
    total_costs = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseReceipt
        fields = '__all__'
        read_only_fields = ('receipt_number', 'created_at')

    def get_costs(self, obj):
        return ReceiptCostSerializer(obj.costs.all(), many=True).data

    def get_waybills(self, obj):
        return WaybillSerializer(obj.waybills.all(), many=True).data

    def get_total_costs(self, obj):
        total = obj.costs.aggregate(total=models.Sum('amount_in_local_currency'))['total']
        return total or 0


class TransporterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transporter
        fields = '__all__'


class WaybillSerializer(serializers.ModelSerializer):
    transporter_name = serializers.CharField(source='transporter.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.email', read_only=True)

    class Meta:
        model = Waybill
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at', 'created_by')


class ReceiptCostSerializer(serializers.ModelSerializer):
    cost_type_display = serializers.CharField(source='get_cost_type_display', read_only=True)
    receipt_number = serializers.CharField(source='receipt.receipt_number', read_only=True)

    class Meta:
        model = ReceiptCost
        fields = '__all__'
        read_only_fields = ('amount_in_local_currency', 'created_at')


class ReceiptCostAllocationSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    allocation_method_display = serializers.CharField(source='get_allocation_method_display', read_only=True)

    class Meta:
        model = ReceiptCostAllocation
        fields = '__all__'


class PurchasePriceHistorySerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    supplier_name = serializers.CharField(source='supplier.company_name', read_only=True)

    class Meta:
        model = PurchasePriceHistory
        fields = '__all__'


class SupplierCatalogSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.company_name', read_only=True)
    imported_by_name = serializers.CharField(source='imported_by.email', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = SupplierCatalog
        fields = '__all__'
        read_only_fields = ('import_date', 'imported_by', 'products_imported', 'status', 'error_log')


class SupplierCatalogImportSerializer(serializers.Serializer):
    file = serializers.FileField()
    supplier = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    file_format = serializers.ChoiceField(choices=['csv', 'excel'])


class PurchaseAlertSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    supplier_name = serializers.CharField(source='supplier.company_name', read_only=True)
    alert_type_display = serializers.CharField(source='get_alert_type_display', read_only=True)

    class Meta:
        model = PurchaseAlert
        fields = '__all__'


class PurchaseOrderStatsSerializer(serializers.Serializer):
    total_orders = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    average_order_value = serializers.DecimalField(max_digits=10, decimal_places=2)
    pending_orders = serializers.IntegerField()
    late_orders = serializers.IntegerField()
    top_suppliers = serializers.ListField(child=serializers.DictField())
    monthly_spending = serializers.ListField(child=serializers.DictField())