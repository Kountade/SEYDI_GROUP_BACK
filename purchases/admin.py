from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import *  # ← Ceci importe TOUS les modèles

# Ne PAS redéfinir les modèles ici !


class SupplierContactInline(admin.TabularInline):
    model = SupplierContact
    extra = 1
    fields = ['first_name', 'last_name', 'email', 'phone', 'is_primary', 'is_active']


class SupplierEvaluationInline(admin.TabularInline):
    model = SupplierEvaluation
    extra = 0
    readonly_fields = ['total_score', 'created_at']
    fields = ['quality_score', 'price_score', 'delivery_score', 'communication_score', 
              'responsiveness_score', 'total_score', 'comments', 'created_at']
    can_delete = False
    max_num = 0


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['code', 'company_name', 'supplier_type', 'contact_name', 'email', 'phone', 'rating', 'is_preferred', 'is_active']
    list_filter = ['supplier_type', 'is_active', 'is_preferred', 'is_blocked', 'rating', 'country']
    search_fields = ['code', 'company_name', 'contact_name', 'email', 'phone', 'tax_id']
    readonly_fields = ['created_at', 'updated_at', 'total_orders', 'total_spent', 
                       'average_delivery_delay', 'on_time_delivery_rate']
    inlines = [SupplierContactInline, SupplierEvaluationInline]
    
    fieldsets = (
        ('Informations de base', {
            'fields': ('code', 'company_name', 'supplier_type', 'registration_number', 'tax_id')
        }),
        ('Contact principal', {
            'fields': ('contact_name', 'contact_title', 'email', 'phone', 'mobile', 'fax', 'website')
        }),
        ('Adresse', {
            'fields': ('address', 'address_line2', 'city', 'state', 'postal_code', 'country')
        }),
        ('Informations bancaires', {
            'fields': ('bank_name', 'bank_account', 'bank_swift', 'bank_iban'),
            'classes': ('collapse',)
        }),
        ('Conditions commerciales', {
            'fields': ('payment_terms', 'delivery_terms', 'currency', 'lead_time_days', 
                      'minimum_order_amount', 'discount_rate')
        }),
        ('Évaluation', {
            'fields': ('rating', 'is_preferred', 'performance_score')
        }),
        ('Statistiques', {
            'fields': ('total_orders', 'total_spent', 'average_delivery_delay', 'on_time_delivery_rate'),
            'classes': ('collapse',)
        }),
        ('Statut', {
            'fields': ('is_active', 'is_blocked', 'blocking_reason')
        }),
        ('Notes', {
            'fields': ('notes', 'internal_notes')
        }),
        ('Métadonnées', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['block_suppliers', 'unblock_suppliers', 'mark_as_preferred']
    
    def block_suppliers(self, request, queryset):
        queryset.update(is_blocked=True)
    block_suppliers.short_description = "Bloquer les fournisseurs sélectionnés"
    
    def unblock_suppliers(self, request, queryset):
        queryset.update(is_blocked=False, blocking_reason='')
    unblock_suppliers.short_description = "Débloquer les fournisseurs sélectionnés"
    
    def mark_as_preferred(self, request, queryset):
        queryset.update(is_preferred=True)
    mark_as_preferred.short_description = "Marquer comme fournisseurs préférés"
    
    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        else:
            obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(SupplierContact)
class SupplierContactAdmin(admin.ModelAdmin):
    list_display = ['first_name', 'last_name', 'supplier', 'email', 'phone', 'is_primary', 'is_active']
    list_filter = ['is_primary', 'is_active', 'supplier']
    search_fields = ['first_name', 'last_name', 'email']


@admin.register(SupplierEvaluation)
class SupplierEvaluationAdmin(admin.ModelAdmin):
    list_display = ['supplier', 'quality_score', 'price_score', 'delivery_score', 'total_score', 'evaluation_date']
    list_filter = ['evaluation_date', 'supplier']
    search_fields = ['supplier__company_name']
    readonly_fields = ['total_score', 'created_at', 'evaluation_date']


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 1
    readonly_fields = ['subtotal', 'tax_amount', 'total']
    fields = ['product', 'variant', 'quantity_ordered', 'quantity_received', 
              'unit_price', 'discount_rate', 'tax_rate', 'subtotal', 'total']


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'supplier', 'agence', 'status', 'order_date', 'expected_date', 'total', 'urgency']
    list_filter = ['status', 'urgency', 'order_date', 'expected_date', 'agence']
    search_fields = ['order_number', 'supplier_reference', 'supplier__company_name']
    readonly_fields = ['order_number', 'order_date', 'created_at', 'updated_at', 'subtotal', 'tax_total', 'total']
    inlines = [PurchaseOrderItemInline]
    date_hierarchy = 'order_date'
    
    fieldsets = (
        ('Références', {
            'fields': ('order_number', 'supplier_reference', 'supplier', 'agence', 'warehouse')
        }),
        ('Dates', {
            'fields': ('order_date', 'expected_date', 'confirmed_date', 'shipped_date', 'received_date')
        }),
        ('Statut', {
            'fields': ('status', 'urgency')
        }),
        ('Financier', {
            'fields': ('subtotal', 'tax_total', 'shipping_cost', 'discount', 'total', 'currency', 'exchange_rate')
        }),
        ('Livraison', {
            'fields': ('shipping_address', 'shipping_method', 'tracking_number', 'carrier')
        }),
        ('Documents', {
            'fields': ('order_file',)
        }),
        ('Notes', {
            'fields': ('notes', 'internal_notes', 'terms_conditions')
        }),
        ('Métadonnées', {
            'fields': ('created_by', 'validated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['confirm_orders', 'send_orders', 'cancel_orders']
    
    def confirm_orders(self, request, queryset):
        from django.utils import timezone
        queryset.filter(status='draft').update(status='confirmed', confirmed_date=timezone.now().date())
    confirm_orders.short_description = "Confirmer les commandes sélectionnées"
    
    def send_orders(self, request, queryset):
        queryset.filter(status='confirmed').update(status='sent')
    send_orders.short_description = "Marquer comme envoyées"
    
    def cancel_orders(self, request, queryset):
        queryset.exclude(status__in=['received', 'cancelled']).update(status='cancelled')
    cancel_orders.short_description = "Annuler les commandes sélectionnées"
    
    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class PurchaseReceiptItemInline(admin.TabularInline):
    model = PurchaseReceiptItem
    extra = 1
    fields = ['order_item', 'quantity', 'quality_checked', 'quality_ok', 'lot_number', 'expiry_date']


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'purchase_order', 'receipt_date', 'received_by', 'total_quantity']
    list_filter = ['receipt_date', 'purchase_order__supplier']
    search_fields = ['receipt_number', 'purchase_order__order_number']
    inlines = [PurchaseReceiptItemInline]
    readonly_fields = ['receipt_number', 'receipt_date', 'created_at']
    
    def total_quantity(self, obj):
        return sum(item.quantity for item in obj.items.all())
    total_quantity.short_description = "Quantité totale"


@admin.register(PurchaseReceiptItem)
class PurchaseReceiptItemAdmin(admin.ModelAdmin):
    list_display = ['receipt', 'order_item', 'quantity', 'quality_ok', 'lot_number']
    list_filter = ['quality_ok', 'quality_checked']
    search_fields = ['receipt__receipt_number', 'order_item__product__name', 'lot_number']


@admin.register(Transporter)
class TransporterAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'contact_person', 'phone', 'email', 'is_active', 'is_preferred']
    list_filter = ['is_active', 'is_preferred']
    search_fields = ['code', 'name', 'contact_person', 'email']


@admin.register(Waybill)
class WaybillAdmin(admin.ModelAdmin):
    list_display = ['waybill_number', 'purchase_order', 'transporter', 'status', 'issue_date', 'estimated_arrival']
    list_filter = ['status', 'issue_date', 'transporter']
    search_fields = ['waybill_number', 'container_number']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'issue_date'
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('waybill_number', 'purchase_order', 'transporter')
        }),
        ('Dates', {
            'fields': ('issue_date', 'estimated_arrival', 'actual_arrival', 'customs_clearance_date', 'delivery_date')
        }),
        ('Itinéraire', {
            'fields': ('origin', 'destination', 'port_of_loading', 'port_of_discharge')
        }),
        ('Colisage', {
            'fields': ('container_number', 'seal_number', 'number_of_packages', 'weight_kg', 'volume_m3')
        }),
        ('Statut et documents', {
            'fields': ('status', 'waybill_file', 'notes')
        }),
        ('Métadonnées', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(ReceiptCost)
class ReceiptCostAdmin(admin.ModelAdmin):
    list_display = ['receipt', 'cost_type', 'amount', 'currency', 'amount_in_local_currency', 'is_billable']
    list_filter = ['cost_type', 'currency', 'is_billable']
    search_fields = ['receipt__receipt_number', 'description', 'reference_number']
    readonly_fields = ['amount_in_local_currency', 'created_at']


class ReceiptCostAllocationInline(admin.TabularInline):
    model = ReceiptCostAllocation
    extra = 1
    fields = ['product', 'variant', 'quantity', 'allocated_amount', 'allocation_method']


# Ne pas réenregistrer ReceiptCost ici car déjà fait plus haut
# On ajoute juste l'inline à la classe existante
ReceiptCostAdmin.inlines = [ReceiptCostAllocationInline]


@admin.register(ReceiptCostAllocation)
class ReceiptCostAllocationAdmin(admin.ModelAdmin):
    list_display = ['receipt_cost', 'product', 'allocated_amount', 'allocation_method', 'quantity']
    list_filter = ['allocation_method']
    search_fields = ['receipt_cost__receipt__receipt_number', 'product__name']


@admin.register(PurchasePriceHistory)
class PurchasePriceHistoryAdmin(admin.ModelAdmin):
    list_display = ['product', 'supplier', 'price', 'currency', 'quantity', 'date']
    list_filter = ['supplier', 'currency', 'date']
    search_fields = ['product__name', 'supplier__company_name']
    readonly_fields = ['date']
    date_hierarchy = 'date'


@admin.register(SupplierCatalog)
class SupplierCatalogAdmin(admin.ModelAdmin):
    list_display = ['name', 'supplier', 'file_format', 'status', 'products_imported', 'import_date']
    list_filter = ['file_format', 'status', 'supplier']
    search_fields = ['name', 'supplier__company_name']
    readonly_fields = ['import_date', 'imported_by', 'products_imported', 'status', 'error_log']


@admin.register(PurchaseAlert)
class PurchaseAlertAdmin(admin.ModelAdmin):
    list_display = ['product', 'supplier', 'alert_type', 'is_active', 'created_at']
    list_filter = ['alert_type', 'is_active']
    search_fields = ['product__name', 'message']
    readonly_fields = ['created_at']
    actions = ['resolve_alerts']
    
    def resolve_alerts(self, request, queryset):
        from django.utils import timezone
        queryset.update(is_active=False, resolved_at=timezone.now(), resolved_by=request.user)
    resolve_alerts.short_description = "Résoudre les alertes sélectionnées"