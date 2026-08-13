# tresorerie/signals.py - VERSION CORRIGÉE

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.db.models import Sum
from .models import MouvementTresorerie, TresorerieJournaliere
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=MouvementTresorerie)
def update_tresorerie_journaliere(sender, instance, created, **kwargs):
    """Met à jour la trésorerie journalière après un mouvement"""
    
    # ✅ Ne traiter que les mouvements effectués
    if instance.status != 'effectue':
        return

    try:
        date = instance.date_mouvement.date()
        agence = instance.agence

        # ✅ AJOUTER les defaults pour éviter l'erreur de champ manquant
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

        # Mettre à jour les totaux
        if instance.type_mouvement == 'encaissement':
            treso.total_entrees += instance.montant
            treso.nb_entrees += 1
        elif instance.type_mouvement == 'decaissement':
            treso.total_sorties += instance.montant
            treso.nb_sorties += 1

        treso.nb_operations += 1

        # Mettre à jour les détails par source
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
        elif instance.source_type == 'paiement_client':  # ✅ AJOUT pour vos paiements
            treso.entrees_reglements += instance.montant
        elif instance.type_mouvement == 'encaissement':
            treso.entrees_autres += instance.montant
        else:
            treso.sorties_autres += instance.montant

        # ✅ Si nouvelle entrée, calculer le solde d'ouverture
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

        # ✅ Mettre à jour le solde de fermeture
        treso.solde_fermeture = treso.solde_ouverture + treso.total_entrees - treso.total_sorties
        treso.save()

        logger.info(
            f"✅ Trésorerie journalière mise à jour - {date} | {agence.nom} | "
            f"Entrées: {treso.total_entrees} | Sorties: {treso.total_sorties}"
        )

    except Exception as e:
        # ⚠️ NE PAS lever l'exception pour ne pas bloquer le paiement
        logger.error(f"❌ Erreur mise à jour trésorerie journalière: {str(e)}")
        # Le paiement est déjà créé, on continue