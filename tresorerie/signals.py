from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Sum, Q
from .models import MouvementTresorerie, TresorerieJournaliere


@receiver(post_save, sender=MouvementTresorerie)
def update_tresorerie_journaliere(sender, instance, **kwargs):
    """
    Met à jour ou crée l'enregistrement de trésorerie journalière
    pour la date et l'agence du mouvement.
    Se déclenche uniquement si le mouvement est effectué.
    """
    # Ignorer les mouvements non effectués
    if instance.status != 'effectue':
        return

    # Récupérer la date et l'agence
    date = instance.date_mouvement.date()
    agence = instance.agence

    # Agréger tous les mouvements effectués du jour pour cette agence
    mouvements_jour = MouvementTresorerie.objects.filter(
        agence=agence,
        date_mouvement__date=date,
        status='effectue'
    )

    # Calcul des totaux
    total_entrees = mouvements_jour.filter(
        type_mouvement='encaissement').aggregate(Sum('montant'))['montant__sum'] or 0
    total_sorties = mouvements_jour.filter(
        type_mouvement='decaissement').aggregate(Sum('montant'))['montant__sum'] or 0
    nb_entrees = mouvements_jour.filter(type_mouvement='encaissement').count()
    nb_sorties = mouvements_jour.filter(type_mouvement='decaissement').count()
    nb_operations = mouvements_jour.count()

    # Détails par source (exemple)
    entrees_ventes = mouvements_jour.filter(
        source_type='vente', type_mouvement='encaissement').aggregate(Sum('montant'))['montant__sum'] or 0
    entrees_reglements = mouvements_jour.filter(
        source_type='reglement', type_mouvement='encaissement').aggregate(Sum('montant'))['montant__sum'] or 0
    sorties_achats = mouvements_jour.filter(
        source_type='achat', type_mouvement='decaissement').aggregate(Sum('montant'))['montant__sum'] or 0
    sorties_frais = mouvements_jour.filter(
        source_type='frais', type_mouvement='decaissement').aggregate(Sum('montant'))['montant__sum'] or 0
    sorties_salaires = mouvements_jour.filter(
        source_type='salaire', type_mouvement='decaissement').aggregate(Sum('montant'))['montant__sum'] or 0

    # Soldes d'ouverture et de fermeture (à adapter selon votre logique)
    # Exemple : on prend le solde de la veille comme ouverture
    jour_precedent = TresorerieJournaliere.objects.filter(
        agence=agence,
        date__lt=date
    ).order_by('-date').first()
    solde_ouverture = jour_precedent.solde_fermeture if jour_precedent else 0

    solde_fermeture = solde_ouverture + total_entrees - total_sorties

    # Mise à jour ou création de l'enregistrement
    treso, created = TresorerieJournaliere.objects.update_or_create(
        date=date,
        agence=agence,
        defaults={
            'solde_ouverture': solde_ouverture,
            'solde_fermeture': solde_fermeture,
            'total_entrees': total_entrees,
            'total_sorties': total_sorties,
            'entrees_ventes': entrees_ventes,
            'entrees_reglements': entrees_reglements,
            'entrees_autres': total_entrees - entrees_ventes - entrees_reglements,
            'sorties_achats': sorties_achats,
            'sorties_frais': sorties_frais,
            'sorties_salaires': sorties_salaires,
            'sorties_autres': total_sorties - sorties_achats - sorties_frais - sorties_salaires,
            'nb_operations': nb_operations,
            'nb_entrees': nb_entrees,
            'nb_sorties': nb_sorties,
        }
    )

    if created:
        print(f"✅ Journal trésorerie créé pour {agence.nom} le {date}")
    else:
        print(f"🔄 Journal trésorerie mis à jour pour {agence.nom} le {date}")
