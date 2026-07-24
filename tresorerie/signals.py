from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import MouvementTresorerie, TresorerieJournaliere


@receiver(post_save, sender=MouvementTresorerie)
def update_tresorerie_journaliere(sender, instance, created, **kwargs):
    """Met à jour la trésorerie journalière après un mouvement"""
    if instance.status == 'effectue':
        date = instance.date_mouvement.date()
        agence = instance.agence

        treso, _ = TresorerieJournaliere.objects.get_or_create(
            date=date,
            agence=agence
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

        treso.save()
