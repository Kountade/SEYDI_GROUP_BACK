# inventaire/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Sum
from .models import StockMovement, WarehouseStock, Warehouse
from produits.models import Product


@receiver(post_save, sender=StockMovement)
def update_warehouse_stock(sender, instance, created, **kwargs):
    """
    Met à jour le stock par entrepôt lors d'un mouvement.
    ⚠️ NE CRÉE PAS de Lot automatiquement.

    IMPORTANT: Ce signal gère TOUS les mouvements, y compris les ajouts manuels.
    """
    if not created:
        return

    # Éviter la double mise à jour si explicitement demandé
    if getattr(instance, '_skip_signal', False):
        print(
            f"⏭️ Signal ignoré pour {instance.reference} (_skip_signal=True)")
        return

    print(
        f"🔄 Traitement du mouvement {instance.reference} - type={instance.movement_type}")

    # ===== ENTRÉE (in, return, return_customer, adjustment positif) =====
    if instance.to_warehouse:
        warehouse_stock, created_ws = WarehouseStock.objects.get_or_create(
            product=instance.product,
            warehouse=instance.to_warehouse,
            variant=instance.variant,
            defaults={
                'quantity': 0,
                'minimum_stock': instance.product.minimum_stock or 5,
                'maximum_stock': instance.product.maximum_stock,
            }
        )
        old_qty = warehouse_stock.quantity
        warehouse_stock.quantity = old_qty + instance.quantity
        warehouse_stock.updated_by = instance.created_by
        warehouse_stock.save()
        print(
            f"  ➕ Entrée: {instance.product.name} @ {instance.to_warehouse.name}: {old_qty} → {warehouse_stock.quantity}")

        # Mettre à jour le stock global du produit
        _update_product_total_stock(instance.product)

    # ===== SORTIE (out, transfer sortant, scrap, quarantine, adjustment négatif) =====
    if instance.from_warehouse:
        warehouse_stock = WarehouseStock.objects.filter(
            product=instance.product,
            warehouse=instance.from_warehouse,
            variant=instance.variant,
        ).first()

        if warehouse_stock:
            old_qty = warehouse_stock.quantity
            warehouse_stock.quantity = max(0, old_qty - instance.quantity)
            warehouse_stock.updated_by = instance.created_by
            warehouse_stock.save()
            print(
                f"  ➖ Sortie: {instance.product.name} @ {instance.from_warehouse.name}: {old_qty} → {warehouse_stock.quantity}")
        else:
            print(
                f"  ⚠️ Pas de stock trouvé pour {instance.product.name} @ {instance.from_warehouse.name}")

        # Mettre à jour le stock global du produit
        _update_product_total_stock(instance.product)


def _update_product_total_stock(product):
    """Met à jour le stock_quantity global du produit"""
    total_stock = WarehouseStock.objects.filter(product=product).aggregate(
        total=Sum('quantity')
    )['total'] or 0
    if product.stock_quantity != total_stock:
        product.stock_quantity = total_stock
        product.save(update_fields=['stock_quantity', 'updated_at'])
        print(f"  📊 Stock global {product.name}: {total_stock}")


@receiver(post_save, sender=Warehouse)
def create_default_warehouse_stock(sender, instance, created, **kwargs):
    """Crée les entrées de stock par défaut pour un nouvel entrepôt"""
    if created:
        products = Product.objects.filter(is_active=True)
        for product in products:
            WarehouseStock.objects.get_or_create(
                product=product,
                warehouse=instance,
                defaults={
                    'quantity': 0,
                    'minimum_stock': product.minimum_stock or 5,
                    'maximum_stock': product.maximum_stock,
                }
            )
