from django.contrib import admin
from django.utils.html import format_html
from .models import *


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'warehouse_type', 'agence', 'city', 'is_active', 'is_default']
    list_filter = ['warehouse_type', 'is_active', 'is_default', 'agence', 'country']
    search_fields = ['code', 'name', 'address', 'city']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Informations de base', {
            'fields': ('code', 'name', 'warehouse_type', 'agence')
        }),
        ('Adresse', {
            'fields': ('address', 'city', 'postal_code', 'country')
        }),
        ('Contact', {
            'fields': ('phone', 'email', 'manager')
        }),
        ('Options', {
            'fields': ('is_active', 'is_default')
        }),
        ('Métadonnées', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ['code', 'warehouse', 'aisle', 'rack', 'shelf', 'is_active']
    list_filter = ['is_active', 'warehouse']
    search_fields = ['code', 'warehouse__name', 'aisle', 'rack', 'shelf']
    list_editable = ['is_active']


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ['reference', 'product', 'movement_type', 'quantity', 'unit_price', 'movement_date']
    list_filter = ['movement_type', 'reference_type', 'movement_date']
    search_fields = ['reference', 'product__name', 'product__reference']
    readonly_fields = ['reference', 'total_price', 'movement_date']
    date_hierarchy = 'movement_date'
    
    fieldsets = (
        ('Référence', {
            'fields': ('reference', 'movement_type', 'reference_type', 'reference_id')
        }),
        ('Produit', {
            'fields': ('product', 'variant', 'quantity')
        }),
        ('Entrepôts', {
            'fields': ('from_warehouse', 'to_warehouse', 'from_location', 'to_location')
        }),
        ('Financier', {
            'fields': ('unit_price', 'total_price')
        }),
        ('Autres', {
            'fields': ('notes', 'created_by', 'movement_date')
        })
    )


class TransferItemInline(admin.TabularInline):
    model = TransferItem
    extra = 1
    readonly_fields = ['remaining_quantity']
    fields = ['product', 'variant', 'quantity', 'quantity_received', 'unit_price', 'remaining_quantity']


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ['reference', 'from_warehouse', 'to_warehouse', 'status', 'transfer_date', 'expected_date']
    list_filter = ['status', 'transfer_date', 'from_warehouse', 'to_warehouse']
    search_fields = ['reference', 'waybill']
    inlines = [TransferItemInline]
    readonly_fields = ['reference', 'created_at', 'updated_at']
    
    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status == 'completed':
            return self.readonly_fields + ['status', 'from_warehouse', 'to_warehouse']
        return self.readonly_fields


@admin.register(InventoryCount)
class InventoryCountAdmin(admin.ModelAdmin):
    list_display = ['reference', 'warehouse', 'status', 'count_date', 'total_items', 'total_differences']
    list_filter = ['status', 'count_date', 'warehouse']
    search_fields = ['reference', 'notes']
    readonly_fields = ['reference', 'created_at', 'updated_at']
    date_hierarchy = 'count_date'


class InventoryCountItemInline(admin.TabularInline):
    model = InventoryCountItem
    extra = 1
    readonly_fields = ['difference', 'difference_value']
    fields = ['product', 'variant', 'theoretical_quantity', 'counted_quantity', 'difference', 'unit_price', 'difference_value']


# Ne pas redéfinir InventoryCountAdmin ici ! Utilisez la classe existante
# Ajoutez simplement l'inline à la classe existante
InventoryCountAdmin.inlines = [InventoryCountItemInline]


@admin.register(StockAlert)
class StockAlertAdmin(admin.ModelAdmin):
    list_display = ['product', 'warehouse', 'alert_type', 'status', 'current_quantity', 'threshold', 'created_at']
    list_filter = ['alert_type', 'status', 'warehouse']
    search_fields = ['product__name', 'message']
    readonly_fields = ['created_at']
    actions = ['resolve_alerts', 'acknowledge_alerts']
    
    def resolve_alerts(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='resolved', resolved_at=timezone.now())
    resolve_alerts.short_description = "Marquer comme résolues"
    
    def acknowledge_alerts(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='acknowledged', acknowledged_by=request.user, acknowledged_at=timezone.now())
    acknowledge_alerts.short_description = "Marquer comme reconnues"


@admin.register(Lot)
class LotAdmin(admin.ModelAdmin):
    list_display = ['lot_number', 'product', 'quantity', 'warehouse', 'expiry_date', 'quality_status', 'is_expired_display']
    list_filter = ['quality_status', 'warehouse', 'product']
    search_fields = ['lot_number', 'serial_number', 'product__name']
    readonly_fields = ['created_at', 'updated_at']
    
    def is_expired_display(self, obj):
        return obj.is_expired
    is_expired_display.boolean = True
    is_expired_display.short_description = "Expiré"


@admin.register(QualityControl)
class QualityControlAdmin(admin.ModelAdmin):
    list_display = ['lot', 'result', 'control_date', 'inspector']
    list_filter = ['result']
    search_fields = ['lot__lot_number', 'notes']
    readonly_fields = ['control_date']