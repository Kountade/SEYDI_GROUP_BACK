# sales/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Facture


@receiver(post_save, sender=Facture)
def update_vente_status(sender, instance, created, **kwargs):
    """Met à jour le statut de la vente quand la facture est payée"""
    if instance.montant_paye >= instance.total_ttc:
        vente = instance.vente
        if vente.status == 'approved' and vente.montant_paye >= vente.total:
            vente.status = 'completed'
            vente.save()