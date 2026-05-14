# inventaire/signals.py - Créez ce fichier

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import StockMovement, WarehouseStock, Warehouse
from produits.models import Product


@receiver(post_save, sender=StockMovement)
def update_warehouse_stock(sender, instance, created, **kwargs):
    """Met à jour le stock par entrepôt lors d'un mouvement"""
    if not created:
        return
    
    # Pour les entrées
    if instance.to_warehouse:
        warehouse_stock, created = WarehouseStock.objects.get_or_create(
            product=instance.product,
            warehouse=instance.to_warehouse,
            variant=instance.variant,
            defaults={
                'quantity': 0,
                'minimum_stock': instance.product.minimum_stock,
                'maximum_stock': instance.product.maximum_stock
            }
        )
        warehouse_stock.quantity += instance.quantity
        warehouse_stock.updated_by = instance.created_by
        warehouse_stock.save()
        
        # Mettre à jour le stock global du produit
        product = instance.product
        product.stock_quantity = WarehouseStock.objects.filter(product=product).aggregate(
            total=models.Sum('quantity')
        )['total'] or 0
        product.save()
    
    # Pour les sorties
    if instance.from_warehouse:
        warehouse_stock = WarehouseStock.objects.filter(
            product=instance.product,
            warehouse=instance.from_warehouse,
            variant=instance.variant
        ).first()
        if warehouse_stock:
            warehouse_stock.quantity -= instance.quantity
            warehouse_stock.updated_by = instance.created_by
            warehouse_stock.save()
            
            # Mettre à jour le stock global du produit
            product = instance.product
            product.stock_quantity = WarehouseStock.objects.filter(product=product).aggregate(
                total=models.Sum('quantity')
            )['total'] or 0
            product.save()


@receiver(post_save, sender=Warehouse)
def create_default_warehouse_stock(sender, instance, created, **kwargs):
    """Crée les entrées de stock pour un nouvel entrepôt"""
    if created:
        products = Product.objects.filter(is_active=True)
        for product in products:
            WarehouseStock.objects.get_or_create(
                product=product,
                warehouse=instance,
                defaults={
                    'quantity': 0,
                    'minimum_stock': product.minimum_stock,
                    'maximum_stock': product.maximum_stock
                }
            )