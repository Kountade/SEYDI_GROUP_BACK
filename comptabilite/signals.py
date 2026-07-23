# comptabilite/signals.py
"""
Signaux pour l'application Comptabilité
Création automatique des écritures, mise à jour des soldes, etc.
"""

from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db import transaction
from decimal import Decimal
from .models import (
    Ecriture, LigneEcriture, SoldeCompte,
    FactureComptable, Reglement, ClotureComptable,
    Balance, LigneBalance
)
from .utils import calculer_total_ecriture


# ============================================================
# SIGNAL : ÉCRITURES
# ============================================================

@receiver(pre_save, sender=Ecriture)
def ecriture_pre_save(sender, instance, **kwargs):
    """
    Avant la sauvegarde d'une écriture, calculer les totaux
    """
    if instance.pk:
        # Récupérer les lignes existantes
        lignes = LigneEcriture.objects.filter(ecriture=instance)
        total_debit = lignes.aggregate(total=models.Sum('debit'))[
            'total'] or Decimal('0')
        total_credit = lignes.aggregate(total=models.Sum('credit'))[
            'total'] or Decimal('0')
        instance.total_debit = total_debit
        instance.total_credit = total_credit


@receiver(post_save, sender=Ecriture)
def ecriture_post_save(sender, instance, created, **kwargs):
    """
    Après la sauvegarde d'une écriture, mettre à jour les soldes si validée
    """
    if instance.status == 'valide':
        mettre_a_jour_soldes(instance)


@receiver(post_save, sender=LigneEcriture)
def ligne_ecriture_post_save(sender, instance, created, **kwargs):
    """
    Après la sauvegarde d'une ligne d'écriture, mettre à jour les totaux de l'écriture
    """
    if instance.ecriture:
        totaux = calculer_total_ecriture(instance.ecriture.id)
        instance.ecriture.total_debit = totaux['debit']
        instance.ecriture.total_credit = totaux['credit']
        instance.ecriture.save(update_fields=['total_debit', 'total_credit'])


@receiver(post_delete, sender=LigneEcriture)
def ligne_ecriture_post_delete(sender, instance, **kwargs):
    """
    Après la suppression d'une ligne d'écriture, mettre à jour les totaux de l'écriture
    """
    if instance.ecriture:
        totaux = calculer_total_ecriture(instance.ecriture.id)
        instance.ecriture.total_debit = totaux['debit']
        instance.ecriture.total_credit = totaux['credit']
        instance.ecriture.save(update_fields=['total_debit', 'total_credit'])


# ============================================================
# SIGNAL : FACTURES COMPTABLES
# ============================================================

@receiver(pre_save, sender=FactureComptable)
def facture_comptable_pre_save(sender, instance, **kwargs):
    """
    Avant la sauvegarde d'une facture, calculer le montant restant
    """
    if instance.pk:
        # Calculer le montant payé à partir des règlements
        total_paye = instance.reglements.aggregate(
            total=models.Sum('montant')
        )['total'] or Decimal('0')
        instance.montant_paye = total_paye
        instance.montant_restant = instance.montant_ttc - total_paye

        # Mettre à jour le statut automatiquement
        if instance.montant_paye >= instance.montant_ttc:
            instance.status = 'payee'
        elif instance.montant_paye > 0:
            instance.status = 'partielle'
        elif instance.date_echeance < timezone.now().date():
            instance.status = 'impayee'


@receiver(post_save, sender=FactureComptable)
def facture_comptable_post_save(sender, instance, created, **kwargs):
    """
    Après la création d'une facture, créer l'écriture comptable automatiquement
    """
    if created and instance.status != 'annulee':
        creer_ecriture_facture(instance)


# ============================================================
# SIGNAL : RÈGLEMENTS
# ============================================================

@receiver(post_save, sender=Reglement)
def reglement_post_save(sender, instance, created, **kwargs):
    """
    Après la sauvegarde d'un règlement, mettre à jour la facture
    """
    if instance.facture:
        # Mettre à jour la facture
        instance.facture.save()

        # Créer l'écriture de règlement si la facture existe
        if created:
            creer_ecriture_reglement(instance)


# ============================================================
# FONCTIONS UTILITAIRES POUR LES SIGNALS
# ============================================================

def mettre_a_jour_soldes(ecriture):
    """
    Met à jour les soldes des comptes après validation d'une écriture
    """
    from django.db import models

    for ligne in ecriture.lignes.all():
        # Mettre à jour ou créer le solde pour la date
        solde, created = SoldeCompte.objects.get_or_create(
            compte=ligne.compte,
            agence=ecriture.agence,
            date_solde=ecriture.date_comptable,
            defaults={
                'debit': ligne.debit,
                'credit': ligne.credit,
                'solde': ligne.debit - ligne.credit,
                'debit_periode': ligne.debit,
                'credit_periode': ligne.credit
            }
        )

        if not created:
            solde.debit += ligne.debit
            solde.credit += ligne.credit
            solde.solde = solde.debit - solde.credit
            solde.debit_periode += ligne.debit
            solde.credit_periode += ligne.credit
            solde.save()


def creer_ecriture_facture(facture):
    """
    Crée automatiquement une écriture comptable pour une facture
    """
    from django.utils import timezone
    from .models import Journal, Ecriture, LigneEcriture, PlanComptable

    # Trouver le journal approprié
    journal_type = 'ventes' if facture.type_facture == 'client' else 'achats'
    try:
        journal = Journal.objects.get(
            agence=facture.agence,
            type_journal=journal_type,
            is_active=True
        )
    except Journal.DoesNotExist:
        # Journal par défaut
        journal = Journal.objects.filter(
            agence=facture.agence,
            is_active=True
        ).first()
        if not journal:
            return

    # Créer l'écriture
    libelle = f"Facture {facture.type_facture} {facture.reference}"
    ecriture = Ecriture.objects.create(
        journal=journal,
        agence=facture.agence,
        date_ecriture=facture.date_facture,
        date_comptable=facture.date_facture,
        libelle=libelle,
        piece_justificative=facture.reference,
        source_type='facture_comptable',
        source_id=facture.id,
        status='brouillon',
        created_by=facture.created_by
    )

    # Créer les lignes
    if facture.type_facture == 'client':
        # Facture client
        # Débit: Client (411)
        try:
            compte_client = PlanComptable.objects.get(
                code='411',
                is_active=True
            )
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=compte_client,
                debit=facture.montant_ttc,
                credit=0,
                libelle=f"Client {facture.client.nom if facture.client else ''}"
            )
        except PlanComptable.DoesNotExist:
            pass

        # Crédit: Ventes (701)
        try:
            compte_ventes = PlanComptable.objects.get(
                code='701',
                is_active=True
            )
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=compte_ventes,
                debit=0,
                credit=facture.montant_ht,
                libelle=f"Ventes {facture.reference}"
            )
        except PlanComptable.DoesNotExist:
            pass

        # Crédit: TVA (445)
        if facture.montant_tva > 0:
            try:
                compte_tva = PlanComptable.objects.get(
                    code='445',
                    is_active=True
                )
                LigneEcriture.objects.create(
                    ecriture=ecriture,
                    compte=compte_tva,
                    debit=0,
                    credit=facture.montant_tva,
                    libelle=f"TVA {facture.reference}"
                )
            except PlanComptable.DoesNotExist:
                pass

    else:
        # Facture fournisseur
        # Débit: Achats (601)
        try:
            compte_achats = PlanComptable.objects.get(
                code='601',
                is_active=True
            )
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=compte_achats,
                debit=facture.montant_ht,
                credit=0,
                libelle=f"Achats {facture.reference}"
            )
        except PlanComptable.DoesNotExist:
            pass

        # Débit: TVA (445)
        if facture.montant_tva > 0:
            try:
                compte_tva = PlanComptable.objects.get(
                    code='445',
                    is_active=True
                )
                LigneEcriture.objects.create(
                    ecriture=ecriture,
                    compte=compte_tva,
                    debit=facture.montant_tva,
                    credit=0,
                    libelle=f"TVA {facture.reference}"
                )
            except PlanComptable.DoesNotExist:
                pass

        # Crédit: Fournisseur (401)
        try:
            compte_fournisseur = PlanComptable.objects.get(
                code='401',
                is_active=True
            )
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=compte_fournisseur,
                debit=0,
                credit=facture.montant_ttc,
                libelle=f"Fournisseur {facture.fournisseur.company_name if facture.fournisseur else ''}"
            )
        except PlanComptable.DoesNotExist:
            pass

    # Mettre à jour les totaux
    totaux = calculer_total_ecriture(ecriture.id)
    ecriture.total_debit = totaux['debit']
    ecriture.total_credit = totaux['credit']
    ecriture.save(update_fields=['total_debit', 'total_credit'])


def creer_ecriture_reglement(reglement):
    """
    Crée automatiquement une écriture comptable pour un règlement
    """
    from .models import Journal, Ecriture, LigneEcriture, PlanComptable

    # Trouver le journal approprié
    journal_type = 'banque' if reglement.mode_reglement in [
        'virement', 'carte'] else 'caisse'
    try:
        journal = Journal.objects.get(
            agence=reglement.agence,
            type_journal=journal_type,
            is_active=True
        )
    except Journal.DoesNotExist:
        # Journal par défaut
        journal = Journal.objects.filter(
            agence=reglement.agence,
            is_active=True
        ).first()
        if not journal:
            return

    # Créer l'écriture
    libelle = f"Règlement {reglement.type_reglement} {reglement.reference}"
    ecriture = Ecriture.objects.create(
        journal=journal,
        agence=reglement.agence,
        date_ecriture=reglement.date_reglement,
        date_comptable=reglement.date_reglement,
        libelle=libelle,
        piece_justificative=reglement.reference,
        source_type='reglement',
        source_id=reglement.id,
        status='brouillon',
        created_by=reglement.created_by
    )

    # Créer les lignes
    if reglement.type_reglement == 'client':
        # Règlement client
        # Débit: Banque/Caisse
        compte_code = '512' if reglement.mode_reglement in [
            'virement', 'carte'] else '101'
        try:
            compte_banque = PlanComptable.objects.get(
                code=compte_code,
                is_active=True
            )
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=compte_banque,
                debit=reglement.montant,
                credit=0,
                libelle=f"Encaissement client {reglement.client.nom if reglement.client else ''}"
            )
        except PlanComptable.DoesNotExist:
            pass

        # Crédit: Client (411)
        try:
            compte_client = PlanComptable.objects.get(
                code='411',
                is_active=True
            )
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=compte_client,
                debit=0,
                credit=reglement.montant,
                libelle=f"Client {reglement.client.nom if reglement.client else ''}"
            )
        except PlanComptable.DoesNotExist:
            pass

    else:
        # Règlement fournisseur
        # Débit: Fournisseur (401)
        try:
            compte_fournisseur = PlanComptable.objects.get(
                code='401',
                is_active=True
            )
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=compte_fournisseur,
                debit=reglement.montant,
                credit=0,
                libelle=f"Fournisseur {reglement.fournisseur.company_name if reglement.fournisseur else ''}"
            )
        except PlanComptable.DoesNotExist:
            pass

        # Crédit: Banque/Caisse
        compte_code = '512' if reglement.mode_reglement in [
            'virement', 'carte'] else '101'
        try:
            compte_banque = PlanComptable.objects.get(
                code=compte_code,
                is_active=True
            )
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=compte_banque,
                debit=0,
                credit=reglement.montant,
                libelle=f"Décaissement fournisseur {reglement.fournisseur.company_name if reglement.fournisseur else ''}"
            )
        except PlanComptable.DoesNotExist:
            pass

    # Mettre à jour les totaux
    totaux = calculer_total_ecriture(ecriture.id)
    ecriture.total_debit = totaux['debit']
    ecriture.total_credit = totaux['credit']
    ecriture.save(update_fields=['total_debit', 'total_credit'])
