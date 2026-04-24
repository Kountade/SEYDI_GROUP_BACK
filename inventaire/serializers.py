from rest_framework import serializers
from .models import *
from produits.serializers import ProductListSerializer, ProductVariantSerializer
from users.serializers import UserSerializer, AgenceSimpleSerializer


class WarehouseSerializer(serializers.ModelSerializer):
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    manager_name = serializers.CharField(source='manager.email', read_only=True)
    locations_count = serializers.IntegerField(source='locations.count', read_only=True)
    warehouse_type_display = serializers.CharField(source='get_warehouse_type_display', read_only=True)

    class Meta:
        model = Warehouse
        fields = '__all__'


class WarehouseDetailSerializer(serializers.ModelSerializer):
    locations = serializers.SerializerMethodField()
    manager = UserSerializer(read_only=True)
    agence = AgenceSimpleSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = Warehouse
        fields = '__all__'

    def get_locations(self, obj):
        return LocationSerializer(obj.locations.filter(is_active=True), many=True).data


class WarehouseCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at', 'created_by')


class LocationSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)
    warehouse_code = serializers.CharField(source='warehouse.code', read_only=True)

    class Meta:
        model = Location
        fields = '__all__'


class StockMovementListSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(source='product.reference', read_only=True)
    from_warehouse_name = serializers.CharField(source='from_warehouse.name', read_only=True)
    to_warehouse_name = serializers.CharField(source='to_warehouse.name', read_only=True)
    movement_type_display = serializers.CharField(source='get_movement_type_display', read_only=True)
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)

    class Meta:
        model = StockMovement
        fields = '__all__'


class StockMovementDetailSerializer(serializers.ModelSerializer):
    product = ProductListSerializer(read_only=True)
    variant = ProductVariantSerializer(read_only=True)
    from_warehouse = WarehouseSerializer(read_only=True)
    to_warehouse = WarehouseSerializer(read_only=True)
    from_location = LocationSerializer(read_only=True)
    to_location = LocationSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = StockMovement
        fields = '__all__'


class StockMovementCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMovement
        fields = '__all__'
        read_only_fields = ('reference', 'total_price', 'movement_date', 'created_by')

    def validate(self, data):
        # Vérifier le stock disponible pour les sorties
        if data.get('movement_type') in ['out', 'transfer']:
            product = data.get('product')
            quantity = data.get('quantity', 0)

            if product and product.stock_quantity < quantity:
                raise serializers.ValidationError(
                    f"Stock insuffisant. Disponible: {product.stock_quantity}"
                )

        # Vérifier que les entrepôts sont différents pour un transfert
        if data.get('movement_type') == 'transfer':
            from_wh = data.get('from_warehouse')
            to_wh = data.get('to_warehouse')
            if from_wh and to_wh and from_wh == to_wh:
                raise serializers.ValidationError(
                    "Les entrepôts source et destination doivent être différents"
                )

        return data


class TransferListSerializer(serializers.ModelSerializer):
    from_warehouse_name = serializers.CharField(source='from_warehouse.name', read_only=True)
    to_warehouse_name = serializers.CharField(source='to_warehouse.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)

    class Meta:
        model = Transfer
        fields = '__all__'


class TransferItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(source='product.reference', read_only=True)
    remaining = serializers.IntegerField(source='remaining_quantity', read_only=True)

    class Meta:
        model = TransferItem
        fields = '__all__'


class TransferDetailSerializer(serializers.ModelSerializer):
    from_warehouse = WarehouseSerializer(read_only=True)
    to_warehouse = WarehouseSerializer(read_only=True)
    items = TransferItemSerializer(many=True, read_only=True)
    created_by = UserSerializer(read_only=True)
    validated_by = UserSerializer(read_only=True)

    class Meta:
        model = Transfer
        fields = '__all__'


class TransferCreateSerializer(serializers.ModelSerializer):
    items = TransferItemSerializer(many=True)

    class Meta:
        model = Transfer
        fields = '__all__'
        read_only_fields = ('reference', 'created_at', 'updated_at', 'created_by', 'validated_by', 'completed_date')

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        transfer = Transfer.objects.create(**validated_data)

        for item_data in items_data:
            TransferItem.objects.create(transfer=transfer, **item_data)

        return transfer

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                TransferItem.objects.create(transfer=instance, **item_data)

        return instance


class InventoryCountListSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    counted_by_name = serializers.CharField(source='counted_by.email', read_only=True)

    class Meta:
        model = InventoryCount
        fields = '__all__'


class InventoryCountItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(source='product.reference', read_only=True)

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
    items = InventoryCountItemSerializer(many=True)

    class Meta:
        model = InventoryCount
        fields = '__all__'
        read_only_fields = ('reference', 'count_date', 'total_items', 'total_differences',
                            'total_difference_value', 'created_at', 'updated_at', 'counted_by', 'validated_by')

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        inventory = InventoryCount.objects.create(**validated_data)

        for item_data in items_data:
            product = item_data['product']
            item_data['unit_price'] = product.purchase_price
            InventoryCountItem.objects.create(inventory=inventory, **item_data)

        inventory.total_items = inventory.items.count()
        inventory.total_differences = inventory.items.filter(difference__gt=0).count()
        inventory.total_difference_value = sum(item.difference_value for item in inventory.items.all())
        inventory.save()

        return inventory


class InventoryCountValidateSerializer(serializers.Serializer):
    """Validation d'un inventaire"""
    notes = serializers.CharField(required=False, allow_blank=True)
    create_movements = serializers.BooleanField(default=True)


class StockAlertSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(source='product.reference', read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)
    alert_type_display = serializers.CharField(source='get_alert_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = StockAlert
        fields = '__all__'


class LotListSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)
    location_code = serializers.CharField(source='location.code', read_only=True)
    quality_status_display = serializers.CharField(source='get_quality_status_display', read_only=True)

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
        return QualityControlSerializer(obj.quality_controls.all(), many=True).data


class QualityControlSerializer(serializers.ModelSerializer):
    inspector_name = serializers.CharField(source='inspector.email', read_only=True)
    result_display = serializers.CharField(source='get_result_display', read_only=True)

    class Meta:
        model = QualityControl
        fields = '__all__'


class InventoryDashboardSerializer(serializers.Serializer):
    """Statistiques pour le dashboard inventaire"""
    total_warehouses = serializers.IntegerField()
    total_products = serializers.IntegerField()
    total_stock_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    low_stock_count = serializers.IntegerField()
    out_of_stock_count = serializers.IntegerField()
    pending_transfers = serializers.IntegerField()
    pending_inventories = serializers.IntegerField()
    active_alerts = serializers.IntegerField()
    expiring_soon = serializers.IntegerField()