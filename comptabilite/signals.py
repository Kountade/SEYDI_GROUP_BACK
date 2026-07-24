# comptabilite/signals.py - Version COMPLÈTE et CORRIGÉE
"""
Signaux pour l'application Comptabilité
Création automatique des écritures, mise à jour des soldes, etc.
"""

import logging
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db import models
from decimal import Decimal
from django.utils import timezone
from .models import (
    Ecriture, LigneEcriture, SoldeCompte,
    FactureComptable, Reglement, ClotureComptable,
    Balance, LigneBalance, Journal, PlanComptable
)
from .utils import calculer_total_ecriture

logger = logging.getLogger(__name__)


# ============================================================
# SIGNAL : ÉCRITURES
# ============================================================

@receiver(pre_save, sender=Ecriture)
def ecriture_pre_save(sender, instance, **kwargs):
    """
    Avant la sauvegarde d'une écriture, calculer les totaux
    """
    if instance.pk:
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
        total_paye = instance.reglements.aggregate(
            total=models.Sum('montant')
        )['total'] or Decimal('0')
        instance.montant_paye = total_paye
        instance.montant_restant = instance.montant_ttc - total_paye

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
        logger.info(f"📝 Signal déclenché pour facture {instance.reference}")
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
        instance.facture.save()
        if created:
            logger.info(
                f"📝 Signal déclenché pour règlement {instance.reference}")
            creer_ecriture_reglement(instance)


# ============================================================
# FONCTIONS UTILITAIRES POUR LES SIGNALS (CORRIGÉES)
# ============================================================

def mettre_a_jour_soldes(ecriture):
    """
    Met à jour les soldes des comptes après validation d'une écriture
    """
    for ligne in ecriture.lignes.all():
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
    ✅ CORRIGÉ : Avec logs et gestion des erreurs
    """
    logger.info(f"📝 Création écriture pour facture {facture.reference}")

    # 1. VÉRIFIER LES COMPTES NÉCESSAIRES
    comptes_necessaires = {
        'client': '411',
        'ventes': '701',
        'tva': '445',
        'achats': '601',
        'fournisseur': '401'
    }

    comptes_existants = {}
    for nom, code in comptes_necessaires.items():
        try:
            compte = PlanComptable.objects.get(code=code, is_active=True)
            comptes_existants[nom] = compte
            logger.info(f"✅ Compte {code} trouvé")
        except PlanComptable.DoesNotExist:
            logger.warning(f"⚠️ Compte {code} non trouvé !")
            comptes_existants[nom] = None

    # 2. TROUVER LE JOURNAL
    journal_type = 'ventes' if facture.type_facture == 'client' else 'achats'
    try:
        journal = Journal.objects.get(
            agence=facture.agence,
            type_journal=journal_type,
            is_active=True
        )
        logger.info(f"✅ Journal {journal.code} trouvé")
    except Journal.DoesNotExist:
        journal = Journal.objects.filter(
            agence=facture.agence,
            is_active=True
        ).first()
        if not journal:
            logger.error("❌ Aucun journal trouvé !")
            return
        logger.info(f"✅ Journal par défaut {journal.code} utilisé")

    # 3. CRÉER L'ÉCRITURE
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
    logger.info(f"✅ Écriture {ecriture.reference} créée")

    lignes_crees = 0

    # 4. CRÉER LES LIGNES
    if facture.type_facture == 'client':
        # Facture client
        if comptes_existants['client']:
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=comptes_existants['client'],
                debit=facture.montant_ttc,
                credit=0,
                libelle=f"Client {facture.client.nom if facture.client else ''}"
            )
            lignes_crees += 1
            logger.info(f"✅ Ligne Client créée: {facture.montant_ttc}")

        if comptes_existants['ventes']:
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=comptes_existants['ventes'],
                debit=0,
                credit=facture.montant_ht,
                libelle=f"Ventes {facture.reference}"
            )
            lignes_crees += 1
            logger.info(f"✅ Ligne Ventes créée: {facture.montant_ht}")

        if facture.montant_tva > 0 and comptes_existants['tva']:
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=comptes_existants['tva'],
                debit=0,
                credit=facture.montant_tva,
                libelle=f"TVA {facture.reference}"
            )
            lignes_crees += 1
            logger.info(f"✅ Ligne TVA créée: {facture.montant_tva}")

    else:
        # Facture fournisseur
        if comptes_existants['achats']:
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=comptes_existants['achats'],
                debit=facture.montant_ht,
                credit=0,
                libelle=f"Achats {facture.reference}"
            )
            lignes_crees += 1
            logger.info(f"✅ Ligne Achats créée: {facture.montant_ht}")

        if facture.montant_tva > 0 and comptes_existants['tva']:
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=comptes_existants['tva'],
                debit=facture.montant_tva,
                credit=0,
                libelle=f"TVA {facture.reference}"
            )
            lignes_crees += 1
            logger.info(f"✅ Ligne TVA créée: {facture.montant_tva}")

        if comptes_existants['fournisseur']:
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=comptes_existants['fournisseur'],
                debit=0,
                credit=facture.montant_ttc,
                libelle=f"Fournisseur {facture.fournisseur.company_name if facture.fournisseur else ''}"
            )
            lignes_crees += 1
            logger.info(f"✅ Ligne Fournisseur créée: {facture.montant_ttc}")

    # 5. METTRE À JOUR LES TOTAUX
    totaux = calculer_total_ecriture(ecriture.id)
    ecriture.total_debit = totaux['debit']
    ecriture.total_credit = totaux['credit']
    ecriture.save(update_fields=['total_debit', 'total_credit'])

    logger.info(
        f"✅ Écriture finalisée: {lignes_crees} lignes, {ecriture.total_debit} = {ecriture.total_credit}")

    if lignes_crees == 0:
        logger.warning("⚠️ Aucune ligne créée ! Vérifiez les comptes.")


def creer_ecriture_reglement(reglement):
    """
    Crée automatiquement une écriture comptable pour un règlement
    ✅ CORRIGÉ : Avec logs et gestion des erreurs
    """
    logger.info(f"📝 Création écriture pour règlement {reglement.reference}")

    # 1. VÉRIFIER LES COMPTES NÉCESSAIRES
    comptes_necessaires = {
        'client': '411',
        'fournisseur': '401',
        'banque': '512',
        'caisse': '101'
    }

    comptes_existants = {}
    for nom, code in comptes_necessaires.items():
        try:
            compte = PlanComptable.objects.get(code=code, is_active=True)
            comptes_existants[nom] = compte
            logger.info(f"✅ Compte {code} trouvé")
        except PlanComptable.DoesNotExist:
            logger.warning(f"⚠️ Compte {code} non trouvé !")
            comptes_existants[nom] = None

    # 2. TROUVER LE JOURNAL
    journal_type = 'banque' if reglement.mode_reglement in [
        'virement', 'carte'] else 'caisse'
    try:
        journal = Journal.objects.get(
            agence=reglement.agence,
            type_journal=journal_type,
            is_active=True
        )
        logger.info(f"✅ Journal {journal.code} trouvé")
    except Journal.DoesNotExist:
        journal = Journal.objects.filter(
            agence=reglement.agence,
            is_active=True
        ).first()
        if not journal:
            logger.error("❌ Aucun journal trouvé !")
            return
        logger.info(f"✅ Journal par défaut {journal.code} utilisé")

    # 3. CRÉER L'ÉCRITURE
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
    logger.info(f"✅ Écriture {ecriture.reference} créée")

    lignes_crees = 0

    # 4. CRÉER LES LIGNES
    if reglement.type_reglement == 'client':
        # Règlement client
        compte_code = 'banque' if reglement.mode_reglement in [
            'virement', 'carte'] else 'caisse'
        compte_source = comptes_existants.get(compte_code)

        if compte_source:
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=compte_source,
                debit=reglement.montant,
                credit=0,
                libelle=f"Encaissement client {reglement.client.nom if reglement.client else ''}"
            )
            lignes_crees += 1
            logger.info(f"✅ Ligne {compte_code} créée: {reglement.montant}")

        if comptes_existants['client']:
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=comptes_existants['client'],
                debit=0,
                credit=reglement.montant,
                libelle=f"Client {reglement.client.nom if reglement.client else ''}"
            )
            lignes_crees += 1
            logger.info(f"✅ Ligne Client créée: {reglement.montant}")

    else:
        # Règlement fournisseur
        if comptes_existants['fournisseur']:
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=comptes_existants['fournisseur'],
                debit=reglement.montant,
                credit=0,
                libelle=f"Fournisseur {reglement.fournisseur.company_name if reglement.fournisseur else ''}"
            )
            lignes_crees += 1
            logger.info(f"✅ Ligne Fournisseur créée: {reglement.montant}")

        compte_code = 'banque' if reglement.mode_reglement in [
            'virement', 'carte'] else 'caisse'
        compte_source = comptes_existants.get(compte_code)

        if compte_source:
            LigneEcriture.objects.create(
                ecriture=ecriture,
                compte=compte_source,
                debit=0,
                credit=reglement.montant,
                libelle=f"Décaissement fournisseur {reglement.fournisseur.company_name if reglement.fournisseur else ''}"
            )
            lignes_crees += 1
            logger.info(f"✅ Ligne {compte_code} créée: {reglement.montant}")

    # 5. METTRE À JOUR LES TOTAUX
    totaux = calculer_total_ecriture(ecriture.id)
    ecriture.total_debit = totaux['debit']
    ecriture.total_credit = totaux['credit']
    ecriture.save(update_fields=['total_debit', 'total_credit'])

    logger.info(
        f"✅ Écriture finalisée: {lignes_crees} lignes, {ecriture.total_debit} = {ecriture.total_credit}")

    if lignes_crees == 0:
        logger.warning("⚠️ Aucune ligne créée ! Vérifiez les comptes.")
