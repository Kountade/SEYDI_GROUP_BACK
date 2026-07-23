# comptabilite/utils.py
"""
Utilitaires pour l'application Comptabilité
Fonctions de calcul, formatage, validation, etc.
"""

from decimal import Decimal
from datetime import datetime, date
from django.db.models import Sum, Q
from django.utils import timezone
from .models import (
    PlanComptable, Journal, Ecriture, LigneEcriture,
    SoldeCompte, Balance, LigneBalance,
    FactureComptable, Reglement,
    ClotureComptable, IndicateurFinancier
)


# ============================================================
# FORMATAGE
# ============================================================

def format_amount(amount):
    """
    Formate un montant avec séparateur de milliers
    """
    if amount is None:
        return '0'
    try:
        amount = Decimal(str(amount))
        return f"{amount:,.2f}".replace(',', ' ').replace('.', ',')
    except:
        return '0'


def format_amount_short(amount):
    """
    Formate un montant en version courte (K, M, B)
    """
    if amount is None:
        return '0'
    try:
        amount = float(amount)
        if amount >= 1_000_000_000:
            return f"{amount/1_000_000_000:.1f}B"
        elif amount >= 1_000_000:
            return f"{amount/1_000_000:.1f}M"
        elif amount >= 1_000:
            return f"{amount/1_000:.1f}K"
        else:
            return f"{amount:.0f}"
    except:
        return '0'


def format_date(date_obj):
    """
    Formate une date en chaîne lisible
    """
    if not date_obj:
        return '-'
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.fromisoformat(date_obj)
        except:
            return date_obj
    return date_obj.strftime('%d/%m/%Y')


def format_datetime(dt_obj):
    """
    Formate un datetime en chaîne lisible
    """
    if not dt_obj:
        return '-'
    if isinstance(dt_obj, str):
        try:
            dt_obj = datetime.fromisoformat(dt_obj)
        except:
            return dt_obj
    return dt_obj.strftime('%d/%m/%Y %H:%M')


# ============================================================
# CALCULS COMPTABLES
# ============================================================

def calculer_solde_compte(compte_id, agence_id, date_solde=None):
    """
    Calcule le solde d'un compte à une date donnée
    """
    if not date_solde:
        date_solde = timezone.now().date()

    # Récupérer les lignes d'écriture validées
    lignes = LigneEcriture.objects.filter(
        compte_id=compte_id,
        ecriture__agence_id=agence_id,
        ecriture__status='valide',
        ecriture__date_comptable__lte=date_solde
    )

    total_debit = lignes.aggregate(total=Sum('debit'))['total'] or Decimal('0')
    total_credit = lignes.aggregate(total=Sum('credit'))[
        'total'] or Decimal('0')

    return {
        'debit': total_debit,
        'credit': total_credit,
        'solde': total_debit - total_credit
    }


def calculer_mouvements_periode(compte_id, agence_id, date_debut, date_fin):
    """
    Calcule les mouvements d'un compte sur une période
    """
    lignes = LigneEcriture.objects.filter(
        compte_id=compte_id,
        ecriture__agence_id=agence_id,
        ecriture__status='valide',
        ecriture__date_comptable__gte=date_debut,
        ecriture__date_comptable__lte=date_fin
    )

    total_debit = lignes.aggregate(total=Sum('debit'))['total'] or Decimal('0')
    total_credit = lignes.aggregate(total=Sum('credit'))[
        'total'] or Decimal('0')

    return {
        'debit': total_debit,
        'credit': total_credit
    }


def calculer_total_ecriture(ecriture_id):
    """
    Calcule les totaux d'une écriture
    """
    lignes = LigneEcriture.objects.filter(ecriture_id=ecriture_id)
    total_debit = lignes.aggregate(total=Sum('debit'))['total'] or Decimal('0')
    total_credit = lignes.aggregate(total=Sum('credit'))[
        'total'] or Decimal('0')

    return {
        'debit': total_debit,
        'credit': total_credit,
        'est_equilibree': total_debit == total_credit
    }


def verifier_equilibre_ecriture(lignes):
    """
    Vérifie qu'une liste de lignes est équilibrée
    """
    total_debit = sum(l.get('debit', 0) for l in lignes)
    total_credit = sum(l.get('credit', 0) for l in lignes)
    return total_debit == total_credit


# ============================================================
# GÉNÉRATION DE RÉFÉRENCES
# ============================================================

def generer_reference(prefix, model, field='reference'):
    """
    Génère une référence unique avec un préfixe et un numéro séquentiel
    """
    from datetime import datetime
    prefix_date = f"{prefix}{datetime.now().strftime('%Y%m')}"

    # Récupérer le dernier numéro
    last = model.objects.filter(
        **{f'{field}__startswith': prefix_date}).order_by('-id').first()

    if last:
        try:
            last_num = int(getattr(last, field).replace(prefix_date, ''))
            new_num = last_num + 1
        except (ValueError, AttributeError):
            new_num = 1
    else:
        new_num = 1

    return f"{prefix_date}{str(new_num).zfill(4)}"


def generer_reference_ecriture():
    """
    Génère une référence pour une écriture
    """
    return generer_reference('ECR', Ecriture)


def generer_reference_balance():
    """
    Génère une référence pour une balance
    """
    return generer_reference('BAL', Balance)


def generer_reference_facture_comptable(type_facture):
    """
    Génère une référence pour une facture comptable
    """
    prefix = 'FCL' if type_facture == 'client' else 'FOU'
    return generer_reference(prefix, FactureComptable)


def generer_reference_reglement(type_reglement):
    """
    Génère une référence pour un règlement
    """
    prefix = 'RCL' if type_reglement == 'client' else 'RFOU'
    return generer_reference(prefix, Reglement)


def generer_reference_cloture():
    """
    Génère une référence pour une clôture
    """
    return generer_reference('CLOT', ClotureComptable)


# ============================================================
# VALIDATIONS
# ============================================================

def valider_periode_comptable(date_debut, date_fin, agence_id):
    """
    Vérifie qu'une période comptable est valide
    """
    if date_debut > date_fin:
        return False, "La date début doit être antérieure à la date fin"

    # Vérifier qu'il n'y a pas de clôture sur cette période
    clotures = ClotureComptable.objects.filter(
        agence_id=agence_id,
        status__in=['cloturee', 'verrouillee'],
        date_debut__lte=date_fin,
        date_fin__gte=date_debut
    )

    if clotures.exists():
        return False, "La période est clôturée"

    return True, "Période valide"


def valider_compte_actif(compte_id):
    """
    Vérifie qu'un compte est actif
    """
    try:
        compte = PlanComptable.objects.get(id=compte_id, is_active=True)
        return True, compte
    except PlanComptable.DoesNotExist:
        return False, "Compte inactif ou inexistant"


def valider_journal_actif(journal_id):
    """
    Vérifie qu'un journal est actif
    """
    try:
        journal = Journal.objects.get(id=journal_id, is_active=True)
        return True, journal
    except Journal.DoesNotExist:
        return False, "Journal inactif ou inexistant"


def valider_montant_positif(montant):
    """
    Vérifie qu'un montant est positif
    """
    try:
        montant = Decimal(str(montant))
        if montant < 0:
            return False, "Le montant doit être positif"
        return True, montant
    except:
        return False, "Montant invalide"


# ============================================================
# CALCULS FINANCIERS
# ============================================================

def calculer_chiffre_affaires(agence_id, date_debut, date_fin):
    """
    Calcule le chiffre d'affaires sur une période
    """
    factures = FactureComptable.objects.filter(
        agence_id=agence_id,
        type_facture='client',
        date_facture__gte=date_debut,
        date_facture__lte=date_fin,
        status__in=['payee', 'partielle']
    )

    total = factures.aggregate(total=Sum('montant_ttc'))[
        'total'] or Decimal('0')
    return total


def calculer_achats(agence_id, date_debut, date_fin):
    """
    Calcule les achats sur une période
    """
    factures = FactureComptable.objects.filter(
        agence_id=agence_id,
        type_facture='fournisseur',
        date_facture__gte=date_debut,
        date_facture__lte=date_fin
    )

    total = factures.aggregate(total=Sum('montant_ttc'))[
        'total'] or Decimal('0')
    return total


def calculer_marge_brute(agence_id, date_debut, date_fin):
    """
    Calcule la marge brute sur une période
    """
    ca = calculer_chiffre_affaires(agence_id, date_debut, date_fin)
    achats = calculer_achats(agence_id, date_debut, date_fin)
    return ca - achats


def calculer_tresorerie(agence_id, date=None):
    """
    Calcule la trésorerie à une date donnée
    """
    if not date:
        date = timezone.now().date()

    encaissements = Reglement.objects.filter(
        agence_id=agence_id,
        type_reglement='client',
        date_reglement__lte=date
    ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

    decaissements = Reglement.objects.filter(
        agence_id=agence_id,
        type_reglement='fournisseur',
        date_reglement__lte=date
    ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

    return encaissements - decaissements


def calculer_creances_clients(agence_id, date=None):
    """
    Calcule les créances clients à une date donnée
    """
    if not date:
        date = timezone.now().date()

    factures = FactureComptable.objects.filter(
        agence_id=agence_id,
        type_facture='client',
        date_facture__lte=date,
        status__in=['impayee', 'partielle', 'envoyee']
    )

    total = factures.aggregate(total=Sum('montant_restant'))[
        'total'] or Decimal('0')
    return total


def calculer_dettes_fournisseurs(agence_id, date=None):
    """
    Calcule les dettes fournisseurs à une date donnée
    """
    if not date:
        date = timezone.now().date()

    factures = FactureComptable.objects.filter(
        agence_id=agence_id,
        type_facture='fournisseur',
        date_facture__lte=date,
        status__in=['impayee', 'partielle', 'recue']
    )

    total = factures.aggregate(total=Sum('montant_restant'))[
        'total'] or Decimal('0')
    return total


# ============================================================
# INDICATEURS FINANCIERS
# ============================================================

def calculer_indicateur_tresorerie(agence_id, date_debut, date_fin):
    """
    Calcule les indicateurs de trésorerie
    """
    solde_initial = calculer_tresorerie(agence_id, date_debut)
    solde_final = calculer_tresorerie(agence_id, date_fin)

    return {
        'solde_initial': solde_initial,
        'solde_final': solde_final,
        'variation': solde_final - solde_initial
    }


def calculer_indicateur_profitabilite(agence_id, date_debut, date_fin):
    """
    Calcule les indicateurs de profitabilité
    """
    ca = calculer_chiffre_affaires(agence_id, date_debut, date_fin)
    achats = calculer_achats(agence_id, date_debut, date_fin)
    marge = ca - achats

    return {
        'chiffre_affaires': ca,
        'achats': achats,
        'marge_brute': marge,
        'marge_pourcentage': (marge / ca * 100) if ca > 0 else 0
    }


def calculer_indicateur_liquidite(agence_id, date=None):
    """
    Calcule les indicateurs de liquidité
    """
    if not date:
        date = timezone.now().date()

    creances = calculer_creances_clients(agence_id, date)
    tresorerie = calculer_tresorerie(agence_id, date)
    dettes = calculer_dettes_fournisseurs(agence_id, date)

    actif_circulant = tresorerie + creances

    return {
        'actif_circulant': actif_circulant,
        'dettes_court_terme': dettes,
        'ratio_liquidite': (actif_circulant / dettes) if dettes > 0 else 0,
        'tresorerie': tresorerie,
        'creances': creances
    }


# ============================================================
# EXPORT ET RAPPORTS
# ============================================================

def preparer_donnees_balance(balance_id):
    """
    Prépare les données d'une balance pour export
    """
    try:
        balance = Balance.objects.get(id=balance_id)
        lignes = balance.lignes.all().select_related('compte')

        donnees = {
            'reference': balance.reference,
            'type_balance': balance.get_type_balance_display(),
            'agence': balance.agence.nom,
            'date_debut': format_date(balance.date_debut),
            'date_fin': format_date(balance.date_fin),
            'lignes': []
        }

        for ligne in lignes:
            donnees['lignes'].append({
                'compte': f"{ligne.compte.code} - {ligne.compte.nom}",
                'solde_initial_debit': format_amount(ligne.solde_initial_debit),
                'solde_initial_credit': format_amount(ligne.solde_initial_credit),
                'mouvement_debit': format_amount(ligne.mouvement_debit),
                'mouvement_credit': format_amount(ligne.mouvement_credit),
                'solde_final_debit': format_amount(ligne.solde_final_debit),
                'solde_final_credit': format_amount(ligne.solde_final_credit)
            })

        return donnees
    except Balance.DoesNotExist:
        return None


def preparer_donnees_compte_resultat(agence_id, date_debut, date_fin):
    """
    Prépare les données du compte de résultat
    """
    # Produits
    produits = {
        'ventes': calculer_chiffre_affaires(agence_id, date_debut, date_fin),
    }

    # Charges
    charges = {
        'achats': calculer_achats(agence_id, date_debut, date_fin),
    }

    total_produits = sum(produits.values())
    total_charges = sum(charges.values())
    resultat = total_produits - total_charges

    return {
        'periode': f"{format_date(date_debut)} au {format_date(date_fin)}",
        'produits': {k: format_amount(v) for k, v in produits.items()},
        'total_produits': format_amount(total_produits),
        'charges': {k: format_amount(v) for k, v in charges.items()},
        'total_charges': format_amount(total_charges),
        'resultat': format_amount(resultat),
        'type_resultat': 'Bénéfice' if resultat > 0 else 'Perte'
    }


def preparer_donnees_bilan(agence_id, date_cloture):
    """
    Prépare les données du bilan
    """
    # Actif
    actif = {
        'tresorerie': calculer_tresorerie(agence_id, date_cloture),
        'creances': calculer_creances_clients(agence_id, date_cloture),
    }

    # Passif
    passif = {
        'dettes_fournisseurs': calculer_dettes_fournisseurs(agence_id, date_cloture),
    }

    total_actif = sum(actif.values())
    total_passif = sum(passif.values())

    return {
        'date': format_date(date_cloture),
        'actif': {k: format_amount(v) for k, v in actif.items()},
        'total_actif': format_amount(total_actif),
        'passif': {k: format_amount(v) for k, v in passif.items()},
        'total_passif': format_amount(total_passif),
        'est_equilibre': total_actif == total_passif
    }
