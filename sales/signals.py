# sales/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
import logging

from .models import Vente, Facture

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Vente)
def create_facture_on_approve(sender, instance, created, **kwargs):
    """
    Crée automatiquement une facture lorsqu'une vente est approuvée.
    """
    # Ne s'exécute que si la vente est approuvée
    if instance.status != 'approved':
        return

    # Éviter les récursions infinies
    if hasattr(instance, '_facture_processing'):
        return

    # Vérifier si une facture existe déjà
    if Facture.objects.filter(vente=instance).exists():
        return

    try:
        # Marquer pour éviter les appels en cascade
        instance._facture_processing = True

        # Créer la facture
        date_echeance = timezone.now().date() + timezone.timedelta(days=30)

        facture = Facture.objects.create(
            vente=instance,
            client=instance.client,
            agence=instance.agence,
            cree_par=instance.approved_by or instance.vendeur,
            type_facture='finale',
            date_facture=timezone.now().date(),
            date_echeance=date_echeance,
            conditions_paiement='Paiement à 30 jours',
            notes=f"Facture générée automatiquement à l'approbation de la vente {instance.reference}",
            sous_total=instance.sous_total,
            tva=instance.tva,
            total_ttc=instance.total,
            montant_paye=instance.montant_paye,
            montant_restant=instance.total - instance.montant_paye
        )

        logger.info(
            f"✅ Facture {facture.reference} créée automatiquement via signal pour la vente {instance.reference}")

    except Exception as e:
        logger.error(
            f"❌ Erreur lors de la création automatique de la facture via signal: {str(e)}")
    finally:
        # Nettoyer le flag
        if hasattr(instance, '_facture_processing'):
            del instance._facture_processing

# Votre signal existant pour la mise à jour du statut


@receiver(post_save, sender=Facture)
def update_vente_status(sender, instance, created, **kwargs):
    """Met à jour le statut de la vente quand la facture est payée"""
    # Utiliser le même mécanisme pour éviter les boucles
    if hasattr(instance, '_updating_vente'):
        return

    if instance.montant_paye >= instance.total_ttc:
        vente = instance.vente
        if vente and vente.status == 'approved' and vente.montant_paye >= vente.total:
            instance._updating_vente = True
            vente.status = 'completed'
            vente.save()
            instance._updating_vente = False
