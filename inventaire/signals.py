# inventaire/signals.py - Version corrigée

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db import models as django_models  # Correction ici
from .models import StockMovement, WarehouseStock, Warehouse, Transfer, TransferItem
from produits.models import Product

# inventaire/signals.py - Version corrigée

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Sum
from .models import StockMovement, WarehouseStock, Warehouse
from produits.models import Product


@receiver(post_save, sender=StockMovement)
def update_warehouse_stock(sender, instance, created, **kwargs):
    """
    Met à jour le stock par entrepôt lors d'un mouvement
    IMPORTANT: Ne pas exécuter si le mouvement a déjà été traité manuellement
    """
    if not created:
        return
    
    # Éviter la double mise à jour (si déjà traité dans la vue)
    if hasattr(instance, '_stock_updated'):
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
        total_stock = WarehouseStock.objects.filter(product=product).aggregate(
            total=Sum('quantity')
        )['total'] or 0
        if product.stock_quantity != total_stock:
            product.stock_quantity = total_stock
            product.save(update_fields=['stock_quantity', 'updated_at'])
    
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
            total_stock = WarehouseStock.objects.filter(product=product).aggregate(
                total=Sum('quantity')
            )['total'] or 0
            if product.stock_quantity != total_stock:
                product.stock_quantity = total_stock
                product.save(update_fields=['stock_quantity', 'updated_at'])


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