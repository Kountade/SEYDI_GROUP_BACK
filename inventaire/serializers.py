# inventaire/serializers.py
"""
Serializers pour l'application Inventaire.

✅ CORRECTIONS N+1 :
- Warehouse.locations_count     : lu depuis annotate du ViewSet (0 requête)
- StockMovementDetailSerializer : FK sérialisées en _id (évite le N+1)
- WarehouseDetail.locations     : utilise prefetch_related('locations') du ViewSet
- LotDetail.quality_controls    : utilise prefetch_related du ViewSet
- TransferItem.remaining        : propriété Python (0 requête)
- InventoryCountCreate          : bulk_create au lieu de N create()

✅ CORRECTIONS MÉTIER :
- InventoryCountCreate.total_differences = exclude(difference=0)
- WarehouseSerializer.locations_count = IntegerField (lu depuis annotate)
- Suppression de toute classe n'appartenant pas à 'inventaire'
"""

from rest_framework import serializers
from django.utils import timezone

from .models import *
from produits.serializers import ProductListSerializer, ProductVariantSerializer
from users.serializers import UserSerializer, AgenceSimpleSerializer


# ============================================================
# WAREHOUSE
# ============================================================

class WarehouseSerializer(serializers.ModelSerializer):
    """Serializer pour les entrepôts."""
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    agence_id = serializers.IntegerField(source='agence.id', read_only=True)
    manager_name = serializers.CharField(source='manager.email', read_only=True)
    warehouse_type_display = serializers.CharField(
        source='get_warehouse_type_display', read_only=True)
    # ✅ Lu depuis annotate du ViewSet (0 requête)
    locations_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Warehouse
        fields = (
            'id', 'code', 'name', 'warehouse_type', 'warehouse_type_display',
            'agence', 'agence_id', 'agence_nom',
            'address', 'city', 'postal_code', 'country',
            'phone', 'email', 'manager', 'manager_name',
            'is_active', 'is_default', 'locations_count',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at', 'created_by')


class WarehouseListSerializer(serializers.ModelSerializer):
    """✅ Serializer allégé pour les listes."""
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    agence_id = serializers.IntegerField(source='agence.id', read_only=True)
    manager_name = serializers.CharField(source='manager.email', read_only=True)
    warehouse_type_display = serializers.CharField(
        source='get_warehouse_type_display', read_only=True)
    # ✅ Lu depuis annotate du ViewSet (0 requête)
    locations_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Warehouse
        fields = (
            'id', 'code', 'name', 'warehouse_type', 'warehouse_type_display',
            'agence', 'agence_id', 'agence_nom',
            'address', 'city', 'postal_code', 'country',
            'phone', 'email', 'manager', 'manager_name',
            'is_active', 'is_default', 'locations_count',
            'created_at', 'updated_at',
        )


class WarehouseDetailSerializer(serializers.ModelSerializer):
    """Serializer détaillé avec relations complètes."""
    manager = UserSerializer(read_only=True)
    agence = AgenceSimpleSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    locations = serializers.SerializerMethodField()

    class Meta:
        model = Warehouse
        fields = '__all__'

    def get_locations(self, obj):
        # ✅ Utilise le prefetch_related du ViewSet si présent
        locations = getattr(obj, '_locations_prefetched', None)
        if locations is None:
            locations = obj.locations.filter(is_active=True)
        return LocationSerializer(locations, many=True).data


class WarehouseCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = (
            'code', 'name', 'warehouse_type', 'agence',
            'address', 'city', 'postal_code', 'country',
            'phone', 'email', 'manager',
            'is_active', 'is_default',
        )
        read_only_fields = ('id', 'created_at', 'updated_at', 'created_by')


# ============================================================
# LOCATION
# ============================================================

class LocationSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    warehouse_code = serializers.CharField(
        source='warehouse.code', read_only=True)

    class Meta:
        model = Location
        fields = '__all__'


# ============================================================
# STOCK MOVEMENT
# ============================================================

class StockMovementListSerializer(serializers.ModelSerializer):
    """✅ Serializer allégé pour les listes de mouvements."""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)
    from_warehouse_name = serializers.CharField(
        source='from_warehouse.name', read_only=True, allow_null=True)
    to_warehouse_name = serializers.CharField(
        source='to_warehouse.name', read_only=True, allow_null=True)
    movement_type_display = serializers.CharField(
        source='get_movement_type_display', read_only=True)
    reference_type_display = serializers.CharField(
        source='get_reference_type_display', read_only=True)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)

    class Meta:
        model = StockMovement
        fields = (
            'id', 'reference',
            'movement_type', 'movement_type_display',
            'reference_type', 'reference_type_display', 'reference_id',
            'product', 'product_name', 'product_reference',
            'variant',
            'quantity',
            'from_warehouse', 'from_warehouse_name',
            'to_warehouse', 'to_warehouse_name',
            'from_location', 'to_location',
            'unit_price', 'total_price',
            'movement_date', 'notes',
            'created_by', 'created_by_email',
        )


class StockMovementDetailSerializer(serializers.ModelSerializer):
    """
    ✅ Serializer détaillé avec FK en _id pour éviter le N+1.
    Si tu veux les objets complets, utilise select_related côté ViewSet
    et remplace les _id par les serializers correspondants.
    """
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)
    variant_sku = serializers.CharField(
        source='variant.sku', read_only=True, allow_null=True)
    from_warehouse_name = serializers.CharField(
        source='from_warehouse.name', read_only=True, allow_null=True)
    to_warehouse_name = serializers.CharField(
        source='to_warehouse.name', read_only=True, allow_null=True)
    from_location_code = serializers.CharField(
        source='from_location.code', read_only=True, allow_null=True)
    to_location_code = serializers.CharField(
        source='to_location.code', read_only=True, allow_null=True)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)
    movement_type_display = serializers.CharField(
        source='get_movement_type_display', read_only=True)
    reference_type_display = serializers.CharField(
        source='get_reference_type_display', read_only=True)

    class Meta:
        model = StockMovement
        fields = (
            'id', 'reference',
            'movement_type', 'movement_type_display',
            'reference_type', 'reference_type_display', 'reference_id',
            'product', 'product_name', 'product_reference',
            'variant', 'variant_sku',
            'quantity',
            'from_warehouse', 'from_warehouse_name',
            'to_warehouse', 'to_warehouse_name',
            'from_location', 'from_location_code',
            'to_location', 'to_location_code',
            'unit_price', 'total_price',
            'movement_date', 'notes',
            'created_by', 'created_by_email',
        )


class StockMovementCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMovement
        fields = (
            'movement_type', 'reference_type', 'reference_id',
            'product', 'variant', 'quantity',
            'from_warehouse', 'to_warehouse',
            'from_location', 'to_location',
            'unit_price', 'notes',
        )
        read_only_fields = ('reference', 'total_price',
                            'movement_date', 'created_by')

    def validate(self, data):
        if data.get('movement_type') in ['out', 'transfer']:
            product = data.get('product')
            quantity = data.get('quantity', 0)
            if product and product.stock_quantity < quantity:
                raise serializers.ValidationError(
                    f"Stock insuffisant. Disponible: {product.stock_quantity}"
                )
        if data.get('movement_type') == 'transfer':
            from_wh = data.get('from_warehouse')
            to_wh = data.get('to_warehouse')
            if from_wh and to_wh and from_wh == to_wh:
                raise serializers.ValidationError(
                    "Les entrepôts source et destination doivent être différents"
                )
        return data


# ============================================================
# TRANSFER
# ============================================================

class TransferItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)
    # ✅ Propriété Python (0 requête)
    remaining = serializers.IntegerField(
        source='remaining_quantity', read_only=True)

    class Meta:
        model = TransferItem
        fields = '__all__'
        extra_kwargs = {
            'transfer': {'required': False, 'read_only': True},
            'variant': {'required': False, 'allow_null': True},
            'notes': {'required': False, 'allow_blank': True},
            'quantity_received': {'required': False, 'default': 0},
        }


class TransferCreateSerializer(serializers.ModelSerializer):
    items = TransferItemSerializer(many=True, write_only=True)

    class Meta:
        model = Transfer
        fields = ('from_agence', 'to_agence',
                  'expected_date', 'notes', 'items')
        read_only_fields = (
            'reference', 'created_at', 'updated_at', 'created_by',
            'validated_by', 'completed_date', 'approved_by',
            'approved_at', 'rejected_reason',
        )

    def validate(self, data):
        from_agence = data.get('from_agence')
        to_agence = data.get('to_agence')
        items_data = data.get('items', [])

        if not from_agence or not to_agence:
            raise serializers.ValidationError("Les deux agences sont requises")
        if from_agence == to_agence:
            raise serializers.ValidationError(
                "Les agences source et destination doivent être différentes"
            )
        if from_agence.type_agence != 'principale':
            raise serializers.ValidationError(
                {"from_agence": "L'agence source doit être une agence principale"}
            )
        if to_agence.type_agence != 'secondaire':
            raise serializers.ValidationError(
                {"to_agence": "L'agence destination doit être une agence secondaire"}
            )

        user = self.context['request'].user
        if not user.peut_acceder_agence(to_agence.id):
            raise serializers.ValidationError(
                "Vous devez être rattaché à l'agence secondaire destinataire"
            )
        if not items_data:
            raise serializers.ValidationError(
                {"items": "Au moins un article est requis"})

        for i, item in enumerate(items_data):
            if not item.get('product'):
                raise serializers.ValidationError(
                    {"items": f"Article {i + 1}: le produit est requis"}
                )
            quantity = item.get('quantity', 0)
            if quantity <= 0:
                raise serializers.ValidationError(
                    {"items": f"Article {i + 1}: la quantité doit être positive"}
                )
            unit_price = item.get('unit_price', 0)
            if unit_price <= 0:
                raise serializers.ValidationError(
                    {"items": f"Article {i + 1}: le prix unitaire doit être positif"}
                )

        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        user = self.context['request'].user
        validated_data.pop('created_by', None)
        transfer = Transfer.objects.create(**validated_data, created_by=user)

        # ✅ bulk_create pour les items (1 seule requête)
        items = [
            TransferItem(
                transfer=transfer,
                product=item_data['product'],
                variant=item_data.get('variant'),
                quantity=int(item_data['quantity']),
                unit_price=float(item_data['unit_price']),
                notes=item_data.get('notes', ''),
            )
            for item_data in items_data
        ]
        TransferItem.objects.bulk_create(items)

        return transfer


class TransferListSerializer(serializers.ModelSerializer):
    from_agence_nom = serializers.CharField(
        source='from_agence.nom', read_only=True)
    to_agence_nom = serializers.CharField(
        source='to_agence.nom', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None)
    # ✅ Lu depuis annotate du ViewSet (0 requête)
    items_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Transfer
        fields = '__all__'


class TransferDetailSerializer(serializers.ModelSerializer):
    from_agence = AgenceSimpleSerializer(read_only=True)
    to_agence = AgenceSimpleSerializer(read_only=True)
    items = TransferItemSerializer(many=True, read_only=True)
    created_by = UserSerializer(read_only=True)
    validated_by = UserSerializer(read_only=True)
    approved_by = UserSerializer(read_only=True)

    class Meta:
        model = Transfer
        fields = '__all__'


# ============================================================
# INVENTORY COUNT
# ============================================================

class InventoryCountListSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    counted_by_name = serializers.CharField(
        source='counted_by.email', read_only=True, default=None)

    class Meta:
        model = InventoryCount
        fields = '__all__'


class InventoryCountItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)

    class Meta:
        model = InventoryCountItem
        fields = '__all__'
        read_only_fields = ('difference', 'difference_value')


class InventoryCountDetailSerializer(serializers.ModelSerializer):
    warehouse = WarehouseSerializer(read_only=True)
    items = InventoryCountItemSerializer(many=True, read_only=True)
    counted_by = UserSerializer(read_only=True)
    validated_by = UserSerializer(read_only=True)

    class Meta:
        model = InventoryCount
        fields = '__all__'


class InventoryCountCreateSerializer(serializers.ModelSerializer):
    items = InventoryCountItemSerializer(
        many=True, required=False, default=list)

    class Meta:
        model = InventoryCount
        fields = '__all__'
        read_only_fields = (
            'reference', 'count_date', 'total_items', 'total_differences',
            'total_difference_value', 'created_at', 'updated_at',
            'counted_by', 'validated_by',
        )

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        inventory = InventoryCount.objects.create(**validated_data)

        # ✅ Récupérer TOUS les prix en 1 requête
        product_ids = [item['product'].id for item in items_data if item.get('product')]
        from produits.models import ProductPricing
        pricing_map = {
            p.product_id: p.purchase_price
            for p in ProductPricing.objects.filter(
                product_id__in=product_ids,
                warehouse=inventory.warehouse,
                is_current=True,
            )
        }

        # ✅ bulk_create pour les items
        items = [
            InventoryCountItem(
                inventory=inventory,
                product=item_data['product'],
                variant=item_data.get('variant'),
                theoretical_quantity=item_data.get('theoretical_quantity', 0),
                counted_quantity=item_data.get('counted_quantity', 0),
                unit_price=pricing_map.get(item_data['product'].id, 0),
                is_counted=item_data.get('is_counted', False),
            )
            for item_data in items_data if item_data.get('product')
        ]
        InventoryCountItem.objects.bulk_create(items)

        # ✅ Recalcul en SQL
        from django.db.models import Sum, Count, Q, F
        aggregates = inventory.items.aggregate(
            total=Count('id'),
            # ✅ Corrigé : exclude(difference=0) = filter(~Q(difference=0))
            differences=Count('id', filter=~Q(difference=0)),
            diff_value=Sum(
                F('difference') * F('unit_price'),
                output_field=None,
            ),
        )
        inventory.total_items = aggregates['total'] or 0
        inventory.total_differences = aggregates['differences'] or 0
        inventory.total_difference_value = aggregates['diff_value'] or 0
        inventory.save(update_fields=[
            'total_items', 'total_differences',
            'total_difference_value', 'updated_at',
        ])

        return inventory


class InventoryCountValidateSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True)
    create_movements = serializers.BooleanField(default=True)


# ============================================================
# STOCK ALERT
# ============================================================

class StockAlertSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    alert_type_display = serializers.CharField(
        source='get_alert_type_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = StockAlert
        fields = '__all__'


# ============================================================
# LOT
# ============================================================

class LotListSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    location_code = serializers.CharField(
        source='location.code', read_only=True, allow_null=True)
    quality_status_display = serializers.CharField(
        source='get_quality_status_display', read_only=True)

    class Meta:
        model = Lot
        fields = '__all__'


class LotDetailSerializer(serializers.ModelSerializer):
    product = ProductListSerializer(read_only=True)
    warehouse = WarehouseSerializer(read_only=True)
    location = LocationSerializer(read_only=True)
    quality_controls = serializers.SerializerMethodField()

    class Meta:
        model = Lot
        fields = '__all__'

    def get_quality_controls(self, obj):
        # ✅ Utilise prefetch_related si présent
        qc = getattr(obj, '_quality_controls_prefetched', None)
        if qc is None:
            qc = obj.quality_controls.all()
        return QualityControlSerializer(qc, many=True).data


class LotCreateSerializer(serializers.ModelSerializer):
    """✅ Serializer dédié à la création manuelle d'un lot."""

    class Meta:
        model = Lot
        fields = (
            'id', 'product', 'warehouse', 'location',
            'lot_number', 'serial_number',
            'manufacturing_date', 'expiry_date', 'best_before_date',
            'quantity', 'quality_status',
            'supplier', 'purchase_order', 'notes',
        )
        read_only_fields = ('id',)

    def validate_quantity(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError(
                "La quantité doit être supérieure à 0")
        return value

    def validate(self, data):
        warehouse = data.get('warehouse')
        if warehouse and not warehouse.is_active:
            raise serializers.ValidationError(
                {"warehouse": "L'entrepôt sélectionné est inactif"}
            )
        expiry = data.get('expiry_date')
        if expiry and expiry < timezone.now().date():
            raise serializers.ValidationError(
                {"expiry_date": "La date d'expiration doit être future"}
            )
        mfg = data.get('manufacturing_date')
        if mfg and expiry and mfg >= expiry:
            raise serializers.ValidationError(
                {"expiry_date": "La date d'expiration doit être après la date de fabrication"}
            )
        lot_number = data.get('lot_number')
        if lot_number:
            qs = Lot.objects.filter(lot_number=lot_number)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"lot_number": f"Le numéro de lot '{lot_number}' existe déjà"}
                )
        return data


# ============================================================
# QUALITY CONTROL
# ============================================================

class QualityControlSerializer(serializers.ModelSerializer):
    inspector_name = serializers.CharField(
        source='inspector.email', read_only=True, default=None)
    result_display = serializers.CharField(
        source='get_result_display', read_only=True)

    class Meta:
        model = QualityControl
        fields = '__all__'


# ============================================================
# WAREHOUSE STOCK
# ============================================================

class WarehouseStockSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    location_code = serializers.CharField(
        source='location.code', read_only=True, allow_null=True)

    class Meta:
        model = WarehouseStock
        fields = '__all__'
        read_only_fields = ('id', 'last_updated')

    def validate_quantity(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "La quantité ne peut pas être négative")
        return value


# ============================================================
# DASHBOARD
# ============================================================

class InventoryDashboardSerializer(serializers.Serializer):
    total_warehouses = serializers.IntegerField()
    total_products = serializers.IntegerField()
    total_stock_value = serializers.DecimalField(
        max_digits=12, decimal_places=2)
    low_stock_count = serializers.IntegerField()
    out_of_stock_count = serializers.IntegerField()
    pending_transfers = serializers.IntegerField()
    pending_inventories = serializers.IntegerField()
    active_alerts = serializers.IntegerField()
    expiring_soon = serializers.IntegerField()