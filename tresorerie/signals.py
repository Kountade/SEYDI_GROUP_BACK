# tresorerie/signals.py - VERSION FINALE CORRIGÉE
# ============================================================
# Signaux pour la mise à jour automatique de la trésorerie
# ============================================================

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.db.models import Sum
from django.db import transaction
from .models import MouvementTresorerie, TresorerieJournaliere
import logging

logger = logging.getLogger(__name__)


# ============================================================
# SIGNAL 1 : Mise à jour de la trésorerie journalière
# ============================================================
@receiver(post_save, sender=MouvementTresorerie)
def update_tresorerie_journaliere(sender, instance, created, **kwargs):
    """
    Met à jour la trésorerie journalière après un mouvement.
    
    ⚠️ Ce signal NE DOIT PAS bloquer la création du paiement en cas d'erreur.
    Il utilise transaction.atomic() + select_for_update() pour éviter les race conditions.
    """
    
    # ✅ Ne traiter que les mouvements effectués
    if instance.status != 'effectue':
        logger.debug(
            f"⏭️ Mouvement {instance.reference} ignoré (status={instance.status})"
        )
        return

    try:
        date = instance.date_mouvement.date()
        agence = instance.agence

        # ✅ Transaction atomique pour éviter les race conditions
        with transaction.atomic():
            # ✅ get_or_create avec tous les defaults obligatoires
            treso, created_entry = TresorerieJournaliere.objects.get_or_create(
                date=date,
                agence=agence,
                defaults={
                    'solde_ouverture': 0,
                    'solde_fermeture': 0,
                    'total_entrees': 0,
                    'total_sorties': 0,
                    'entrees_ventes': 0,
                    'entrees_reglements': 0,
                    'entrees_autres': 0,
                    'sorties_achats': 0,
                    'sorties_frais': 0,
                    'sorties_salaires': 0,
                    'sorties_autres': 0,
                    'nb_operations': 0,
                    'nb_entrees': 0,
                    'nb_sorties': 0,
                }
            )

            # ✅ Recharger avec lock pour éviter les conflits concurrents
            treso = TresorerieJournaliere.objects.select_for_update().get(pk=treso.pk)

            # ============================================================
            # Mise à jour des totaux principaux
            # ============================================================
            if instance.type_mouvement == 'encaissement':
                treso.total_entrees += instance.montant
                treso.nb_entrees += 1
            elif instance.type_mouvement == 'decaissement':
                treso.total_sorties += instance.montant
                treso.nb_sorties += 1

            treso.nb_operations += 1

            # ============================================================
            # Mise à jour des détails par source
            # ============================================================
            if instance.source_type == 'vente':
                treso.entrees_ventes += instance.montant
                
            elif instance.source_type == 'reglement':
                treso.entrees_reglements += instance.montant
                
            elif instance.source_type == 'achat':
                treso.sorties_achats += instance.montant
                
            elif instance.source_type == 'frais':
                treso.sorties_frais += instance.montant
                
            elif instance.source_type == 'salaire':
                treso.sorties_salaires += instance.montant
                
            elif instance.source_type in ('paiement_client', 'paiement', 'payment'):
                # ✅ Paiements clients → entrées règlements
                if instance.type_mouvement == 'encaissement':
                    treso.entrees_reglements += instance.montant
                else:
                    treso.sorties_autres += instance.montant
                    
            elif instance.type_mouvement == 'encaissement':
                treso.entrees_autres += instance.montant
                
            else:
                treso.sorties_autres += instance.montant

            # ============================================================
            # Calcul du solde d'ouverture (si nouvelle entrée)
            # ============================================================
            if created_entry:
                mouvements_anterieurs = MouvementTresorerie.objects.filter(
                    agence=agence,
                    date_mouvement__date__lt=date,
                    status='effectue'
                )
                
                total_entrees_anterieures = mouvements_anterieurs.filter(
                    type_mouvement='encaissement'
                ).aggregate(total=Sum('montant'))['total'] or 0
                
                total_sorties_anterieures = mouvements_anterieurs.filter(
                    type_mouvement='decaissement'
                ).aggregate(total=Sum('montant'))['total'] or 0
                
                treso.solde_ouverture = total_entrees_anterieures - total_sorties_anterieures

            # ============================================================
            # Calcul du solde de fermeture
            # ============================================================
            treso.solde_fermeture = (
                treso.solde_ouverture 
                + treso.total_entrees 
                - treso.total_sorties
            )
            
            treso.save()

            logger.info(
                f"✅ Trésorerie journalière mise à jour - {date} | {agence.nom} | "
                f"Entrées: {treso.total_entrees} | Sorties: {treso.total_sorties} | "
                f"Solde fermeture: {treso.solde_fermeture}"
            )

    except Exception as e:
        # ⚠️ NE PAS lever l'exception pour ne pas bloquer le paiement
        # Le paiement est déjà créé, on log juste l'erreur
        logger.error(
            f"❌ Erreur mise à jour trésorerie journalière "
            f"(mouvement: {instance.reference}): {str(e)}"
        )


# ============================================================
# SIGNAL 2 : Mise à jour lors de la suppression d'un mouvement
# ============================================================
@receiver(post_delete, sender=MouvementTresorerie)
def update_tresorerie_journaliere_on_delete(sender, instance, **kwargs):
    """
    Met à jour la trésorerie journalière lors de la suppression d'un mouvement.
    """
    if instance.status != 'effectue':
        return

    try:
        date = instance.date_mouvement.date()
        agence = instance.agence

        with transaction.atomic():
            treso = TresorerieJournaliere.objects.filter(
                date=date,
                agence=agence
            ).first()

            if not treso:
                return

            treso = TresorerieJournaliere.objects.select_for_update().get(pk=treso.pk)

            # Inverser les totaux
            if instance.type_mouvement == 'encaissement':
                treso.total_entrees -= instance.montant
                treso.nb_entrees = max(0, treso.nb_entrees - 1)
            elif instance.type_mouvement == 'decaissement':
                treso.total_sorties -= instance.montant
                treso.nb_sorties = max(0, treso.nb_sorties - 1)

            treso.nb_operations = max(0, treso.nb_operations - 1)

            # Inverser les détails par source
            if instance.source_type == 'vente':
                treso.entrees_ventes = max(0, treso.entrees_ventes - instance.montant)
            elif instance.source_type == 'reglement':
                treso.entrees_reglements = max(0, treso.entrees_reglements - instance.montant)
            elif instance.source_type == 'achat':
                treso.sorties_achats = max(0, treso.sorties_achats - instance.montant)
            elif instance.source_type == 'frais':
                treso.sorties_frais = max(0, treso.sorties_frais - instance.montant)
            elif instance.source_type == 'salaire':
                treso.sorties_salaires = max(0, treso.sorties_salaires - instance.montant)
            elif instance.source_type in ('paiement_client', 'paiement', 'payment'):
                if instance.type_mouvement == 'encaissement':
                    treso.entrees_reglements = max(0, treso.entrees_reglements - instance.montant)
                else:
                    treso.sorties_autres = max(0, treso.sorties_autres - instance.montant)
            elif instance.type_mouvement == 'encaissement':
                treso.entrees_autres = max(0, treso.entrees_autres - instance.montant)
            else:
                treso.sorties_autres = max(0, treso.sorties_autres - instance.montant)

            # Recalculer le solde de fermeture
            treso.solde_fermeture = (
                treso.solde_ouverture 
                + treso.total_entrees 
                - treso.total_sorties
            )
            
            treso.save()

            logger.info(
                f"✅ Trésorerie journalière mise à jour (suppression) - {date} | {agence.nom}"
            )

    except Exception as e:
        logger.error(
            f"❌ Erreur mise à jour trésorerie journalière (suppression): {str(e)}"
        )