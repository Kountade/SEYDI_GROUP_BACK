# dashboard/utils.py
"""
Fonctions utilitaires pour le calcul des statistiques du dashboard.
Centralise toutes les requêtes pour éviter la duplication.
"""

from decimal import Decimal
from datetime import timedelta
from django.db.models import Sum, Count, Q, F, Avg, Max
from django.utils import timezone
from django.db.models.functions import TruncMonth, Coalesce


# ============================================================
# HELPERS GÉNÉRAUX
# ============================================================

def get_agences_autorisees(user):
    """Retourne le queryset des agences accessibles à l'utilisateur."""
    if user.est_pdg() or user.est_drh():
        from users.models import Agence
        return Agence.objects.filter(est_active=True)
    return user.get_agences()


def get_agences_ids(user):
    """Retourne la liste des IDs des agences accessibles."""
    return list(get_agences_autorisees(user).values_list('id', flat=True))


def get_periode_dates(periode='mois'):
    """
    Retourne (date_debut, date_fin) selon la période demandée.
    periode: 'jour', 'semaine', 'mois', 'trimestre', 'annee'
    """
    today = timezone.now().date()
    if periode == 'jour':
        return today, today
    elif periode == 'semaine':
        return today - timedelta(days=today.weekday()), today
    elif periode == 'mois':
        return today.replace(day=1), today
    elif periode == 'trimestre':
        trimestre = (today.month - 1) // 3
        debut = today.replace(month=trimestre * 3 + 1, day=1)
        return debut, today
    elif periode == 'annee':
        return today.replace(month=1, day=1), today
    return today.replace(day=1), today


def safe_decimal(value):
    """Convertit en Decimal de façon sécurisée."""
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ============================================================
# STATS PRODUITS
# ============================================================

def get_stats_produits(agences_ids=None):
    """Statistiques des produits."""
    from produits.models import Product, Category, Brand, ProductVariant

    qs = Product.objects.filter(is_active=True)
    if agences_ids:
        qs = qs.filter(
            warehouse_stocks__warehouse__agence_id__in=agences_ids).distinct()

    return {
        'total': qs.count(),
        'actifs': qs.filter(is_active=True).count(),
        'inactifs': Product.objects.filter(is_active=False).count(),
        'en_vedette': qs.filter(is_featured=True).count(),
        'avec_variants': qs.filter(has_variants=True).count(),
        'stock_faible': qs.filter(stock_quantity__lte=F('minimum_stock'), stock_quantity__gt=0).count(),
        'rupture': qs.filter(stock_quantity=0).count(),
        'categories': Category.objects.filter(is_active=True).count(),
        'marques': Brand.objects.filter(is_active=True).count(),
        'variants': ProductVariant.objects.filter(is_active=True).count(),
        'valeur_stock': qs.aggregate(
            total=Sum(F('stock_quantity') * F('minimum_stock'))
        )['total'] or 0,
    }


# ============================================================
# STATS INVENTAIRE
# ============================================================

def get_stats_inventaire(agences_ids=None):
    """Statistiques de l'inventaire."""
    from inventaire.models import (
        Warehouse, StockMovement, Transfer, InventoryCount,
        StockAlert, Lot, WarehouseStock
    )

    warehouses = Warehouse.objects.filter(is_active=True)
    if agences_ids:
        warehouses = warehouses.filter(agence_id__in=agences_ids)

    today = timezone.now().date()
    in_30_days = today + timedelta(days=30)

    mouvements_qs = StockMovement.objects.all()
    if agences_ids:
        mouvements_qs = mouvements_qs.filter(
            Q(from_warehouse__agence_id__in=agences_ids) |
            Q(to_warehouse__agence_id__in=agences_ids)
        )

    transfers_qs = Transfer.objects.all()
    if agences_ids:
        transfers_qs = transfers_qs.filter(
            Q(from_agence_id__in=agences_ids) | Q(to_agence_id__in=agences_ids)
        )

    return {
        'entrepots': warehouses.count(),
        'mouvements_total': mouvements_qs.count(),
        'mouvements_jour': mouvements_qs.filter(movement_date__date=today).count(),
        'transferts_total': transfers_qs.count(),
        'transferts_en_attente': transfers_qs.filter(
            status__in=['pending_approval', 'approved', 'in_transit']
        ).count(),
        'transferts_en_transit': transfers_qs.filter(status='in_transit').count(),
        'inventaires_en_cours': InventoryCount.objects.filter(
            warehouse__in=warehouses, status='in_progress'
        ).count(),
        'alertes_actives': StockAlert.objects.filter(
            warehouse__in=warehouses, status='active'
        ).count(),
        'lots_expirant_bientot': Lot.objects.filter(
            warehouse__in=warehouses,
            expiry_date__lte=in_30_days,
            expiry_date__gte=today,
            quantity__gt=0
        ).count(),
        'lots_expires': Lot.objects.filter(
            warehouse__in=warehouses,
            expiry_date__lt=today,
            quantity__gt=0
        ).count(),
        'stock_faible': WarehouseStock.objects.filter(
            warehouse__in=warehouses,
            quantity__lte=F('minimum_stock'),
            quantity__gt=0
        ).count(),
        'valeur_stock_total': WarehouseStock.objects.filter(
            warehouse__in=warehouses
        ).aggregate(
            total=Sum(F('quantity') * F('product__prices__purchase_price'))
        )['total'] or 0,
    }


# ============================================================
# STATS VENTES
# ============================================================

def get_stats_ventes(agences_ids=None, periode='mois'):
    """Statistiques des ventes."""
    from sales.models import Vente, Facture, Paiement, Devis, Client

    date_debut, date_fin = get_periode_dates(periode)

    ventes = Vente.objects.all()
    if agences_ids:
        ventes = ventes.filter(agence_id__in=agences_ids)

    factures = Facture.objects.all()
    if agences_ids:
        factures = factures.filter(agence_id__in=agences_ids)

    paiements = Paiement.objects.all()
    if agences_ids:
        paiements = paiements.filter(
            Q(facture__agence_id__in=agences_ids) |
            Q(vente__agence_id__in=agences_ids)
        )

    clients = Client.objects.all()

    return {
        'ventes_total': ventes.count(),
        'ventes_jour': ventes.filter(date_vente__date=date_fin).count(),
        'ventes_periode': ventes.filter(
            date_vente__date__gte=date_debut,
            date_vente__date__lte=date_fin
        ).count(),
        'ca_total': ventes.filter(status='completed').aggregate(
            total=Sum('total')
        )['total'] or 0,
        'ca_periode': ventes.filter(
            status='completed',
            date_vente__date__gte=date_debut,
            date_vente__date__lte=date_fin
        ).aggregate(total=Sum('total'))['total'] or 0,
        'ventes_en_attente': ventes.filter(status='pending_approval').count(),
        'ventes_approuvees': ventes.filter(status='approved').count(),
        'ventes_completees': ventes.filter(status='completed').count(),
        'ventes_rejetees': ventes.filter(status='rejected').count(),
        'impayes': ventes.filter(
            est_paye=False, status__in=['approved', 'completed']
        ).aggregate(total=Sum('montant_du'))['total'] or 0,
        'factures_total': factures.count(),
        'factures_impayees': factures.filter(
            status__in=['pending', 'partially_paid', 'overdue']
        ).count(),
        'factures_en_retard': factures.filter(status='overdue').count(),
        'montant_impayes': factures.exclude(
            status__in=['paid', 'cancelled']
        ).aggregate(total=Sum('montant_restant'))['total'] or 0,
        'paiements_total': paiements.count(),
        'paiements_periode': paiements.filter(
            date_paiement__gte=date_debut,
            date_paiement__lte=date_fin
        ).aggregate(total=Sum('montant'))['total'] or 0,
        'clients_total': clients.count(),
        'clients_actifs': clients.filter(is_active=True).count(),
        'devis_en_attente': Devis.objects.filter(
            status__in=['draft', 'sent']
        ).count(),
        'panier_moyen': (ventes.filter(status='completed').aggregate(
            avg=Avg('total')
        )['avg'] or 0),
    }


# ============================================================
# STATS ACHATS
# ============================================================

def get_stats_achats(agences_ids=None, periode='mois'):
    """Statistiques des achats."""
    from purchases.models import (
        PurchaseOrder, PurchaseReceipt, Supplier, Invoice,
        Payment, Transporter, Waybill, PurchaseAlert
    )

    date_debut, date_fin = get_periode_dates(periode)

    orders = PurchaseOrder.objects.all()
    if agences_ids:
        orders = orders.filter(agence_id__in=agences_ids)

    receipts = PurchaseReceipt.objects.all()
    if agences_ids:
        receipts = receipts.filter(purchase_order__agence_id__in=agences_ids)

    invoices = Invoice.objects.all()
    if agences_ids:
        invoices = invoices.filter(agence_id__in=agences_ids)

    payments = Payment.objects.all()
    if agences_ids:
        payments = payments.filter(agence_id__in=agences_ids)

    today = timezone.now().date()
    late_orders = orders.filter(
        expected_date__lt=today,
        status__in=['confirmed', 'sent', 'in_transit']
    )

    return {
        'commandes_total': orders.count(),
        'commandes_jour': orders.filter(order_date=date_fin).count(),
        'commandes_periode': orders.filter(
            order_date__gte=date_debut,
            order_date__lte=date_fin
        ).count(),
        'commandes_en_attente': orders.filter(
            status__in=['draft', 'sent', 'confirmed']
        ).count(),
        'commandes_en_retard': late_orders.count(),
        'montant_total_achats': orders.filter(status='received').aggregate(
            total=Sum('total')
        )['total'] or 0,
        'montant_periode': orders.filter(
            status='received',
            order_date__gte=date_debut,
            order_date__lte=date_fin
        ).aggregate(total=Sum('total'))['total'] or 0,
        'receptions_total': receipts.count(),
        'receptions_jour': receipts.filter(receipt_date=date_fin).count(),
        'fournisseurs_total': Supplier.objects.count(),
        'fournisseurs_actifs': Supplier.objects.filter(is_active=True).count(),
        'factures_total': invoices.count(),
        'factures_impayees': invoices.filter(
            status__in=['pending', 'partial', 'overdue']
        ).count(),
        'montant_impayes': invoices.exclude(
            status__in=['paid', 'cancelled']
        ).aggregate(total=Sum('amount_remaining'))['total'] or 0,
        'paiements_total': payments.count(),
        'paiements_periode': payments.filter(
            payment_date__gte=date_debut,
            payment_date__lte=date_fin
        ).aggregate(total=Sum('amount'))['total'] or 0,
        'transporteurs': Transporter.objects.filter(is_active=True).count(),
        'bons_transport': Waybill.objects.count(),
        'alertes_achat': PurchaseAlert.objects.filter(is_active=True).count(),
    }


# ============================================================
# STATS TRÉSORERIE
# ============================================================

def get_stats_tresorerie(agences_ids=None, periode='mois'):
    """Statistiques de la trésorerie."""
    from tresorerie.models import (
        Caisse, CompteBancaire, MouvementTresorerie,
        Frais, PrevisionTresorerie, RapprochementBancaire
    )

    date_debut, date_fin = get_periode_dates(periode)

    caisses = Caisse.objects.filter(is_active=True)
    comptes = CompteBancaire.objects.filter(is_active=True)
    mouvements = MouvementTresorerie.objects.filter(status='effectue')

    if agences_ids:
        caisses = caisses.filter(agence_id__in=agences_ids)
        comptes = comptes.filter(agence_id__in=agences_ids)
        mouvements = mouvements.filter(agence_id__in=agences_ids)

    solde_caisses = caisses.aggregate(total=Sum('solde_actuel'))['total'] or 0
    solde_banques = comptes.aggregate(total=Sum('solde_actuel'))['total'] or 0

    return {
        'solde_global': solde_caisses + solde_banques,
        'solde_caisses': solde_caisses,
        'solde_banques': solde_banques,
        'nb_caisses': caisses.count(),
        'nb_comptes': comptes.count(),
        'caisses_sous_seuil': sum(1 for c in caisses if c.est_sous_seuil_min),
        'caisses_sur_seuil': sum(1 for c in caisses if c.est_sur_seuil_max),
        'mouvements_total': mouvements.count(),
        'mouvements_periode': mouvements.filter(
            date_mouvement__date__gte=date_debut,
            date_mouvement__date__lte=date_fin
        ).count(),
        'encaissements_periode': mouvements.filter(
            type_mouvement='encaissement',
            date_mouvement__date__gte=date_debut,
            date_mouvement__date__lte=date_fin
        ).aggregate(total=Sum('montant'))['total'] or 0,
        'decaissements_periode': mouvements.filter(
            type_mouvement='decaissement',
            date_mouvement__date__gte=date_debut,
            date_mouvement__date__lte=date_fin
        ).aggregate(total=Sum('montant'))['total'] or 0,
        'frais_total': Frais.objects.filter(
            agence_id__in=agences_ids
        ).count() if agences_ids else Frais.objects.count(),
        'frais_periode': Frais.objects.filter(
            agence_id__in=agences_ids,
            date_frais__gte=date_debut,
            date_frais__lte=date_fin
        ).aggregate(total=Sum('montant'))['total'] or 0 if agences_ids else 0,
        'frais_en_attente': Frais.objects.filter(
            status__in=['brouillon', 'en_attente']
        ).count(),
        'previsions_en_cours': PrevisionTresorerie.objects.filter(
            statut='en_cours'
        ).count(),
        'rapprochements_en_cours': RapprochementBancaire.objects.filter(
            status__in=['brouillon', 'en_cours', 'partiel']
        ).count(),
    }


# ============================================================
# STATS COMPTABILITÉ
# ============================================================

def get_stats_comptabilite(agences_ids=None, periode='mois'):
    """Statistiques de la comptabilité."""
    from comptabilite.models import (
        PlanComptable, Journal, Ecriture, LigneEcriture,
        Balance, FactureComptable, Reglement, IndicateurFinancier,
        ClotureComptable, AnalyseFinanciere
    )

    date_debut, date_fin = get_periode_dates(periode)

    ecritures = Ecriture.objects.filter(status='valide')
    if agences_ids:
        ecritures = ecritures.filter(agence_id__in=agences_ids)

    factures_cli = FactureComptable.objects.filter(type_facture='client')
    factures_fou = FactureComptable.objects.filter(type_facture='fournisseur')
    reglements = Reglement.objects.all()

    if agences_ids:
        factures_cli = factures_cli.filter(agence_id__in=agences_ids)
        factures_fou = factures_fou.filter(agence_id__in=agences_ids)
        reglements = reglements.filter(agence_id__in=agences_ids)

    return {
        'comptes_total': PlanComptable.objects.filter(is_active=True).count(),
        'journaux_total': Journal.objects.filter(is_active=True).count(),
        'ecritures_total': ecritures.count(),
        'ecritures_periode': ecritures.filter(
            date_ecriture__gte=date_debut,
            date_ecriture__lte=date_fin
        ).count(),
        'ecritures_brouillon': Ecriture.objects.filter(status='brouillon').count(),
        'total_debit': ecritures.aggregate(total=Sum('total_debit'))['total'] or 0,
        'total_credit': ecritures.aggregate(total=Sum('total_credit'))['total'] or 0,
        'balances_total': Balance.objects.count(),
        'factures_clients': factures_cli.count(),
        'factures_clients_impayees': factures_cli.filter(
            status__in=['impayee', 'partielle', 'envoyee']
        ).count(),
        'montant_clients_impayes': factures_cli.exclude(
            status__in=['payee', 'annulee']
        ).aggregate(total=Sum('montant_restant'))['total'] or 0,
        'factures_fournisseurs': factures_fou.count(),
        'factures_fournisseurs_impayees': factures_fou.filter(
            status__in=['impayee', 'partielle', 'recue']
        ).count(),
        'montant_fournisseurs_impayes': factures_fou.exclude(
            status__in=['payee', 'annulee']
        ).aggregate(total=Sum('montant_restant'))['total'] or 0,
        'reglements_total': reglements.count(),
        'reglements_periode': reglements.filter(
            date_reglement__gte=date_debut,
            date_reglement__lte=date_fin
        ).aggregate(total=Sum('montant'))['total'] or 0,
        'indicateurs': IndicateurFinancier.objects.count(),
        'clotures_en_cours': ClotureComptable.objects.filter(
            status__in=['ouverte', 'en_cours']
        ).count(),
        'analyses': AnalyseFinanciere.objects.count(),
    }


# ============================================================
# STATS RH
# ============================================================

def get_stats_rh():
    """Statistiques des ressources humaines."""
    from hr.models import (
        Employee, Department, Position, Leave, Attendance,
        Payroll, Recruitment, Candidate, Training, PerformanceReview,
        ExpenseClaim, Document
    )

    today = timezone.now().date()
    now = timezone.now()

    employees = Employee.objects.all()
    active = employees.filter(work_status='active')

    return {
        'employes_total': employees.count(),
        'employes_actifs': active.count(),
        'employes_conge': employees.filter(work_status='on_leave').count(),
        'employes_suspendus': employees.filter(work_status='suspended').count(),
        'departements': Department.objects.filter(is_active=True).count(),
        'postes': Position.objects.filter(is_active=True).count(),
        'conges_en_attente': Leave.objects.filter(status='pending').count(),
        'conges_approuves': Leave.objects.filter(status='approved').count(),
        'presences_jour': Attendance.objects.filter(date=today).count(),
        'absences_jour': Attendance.objects.filter(date=today, is_absent=True).count(),
        'retards_jour': Attendance.objects.filter(date=today, late_minutes__gt=0).count(),
        'paie_mois': Payroll.objects.filter(
            month=now.month, year=now.year
        ).aggregate(total=Sum('net_salary'))['total'] or 0,
        'paie_en_attente': Payroll.objects.filter(
            status__in=['draft', 'calculated', 'approved']
        ).count(),
        'recrutements_ouverts': Recruitment.objects.filter(
            status__in=['published', 'in_progress']
        ).count(),
        'candidats': Candidate.objects.count(),
        'candidats_en_attente': Candidate.objects.filter(
            status__in=['pending', 'reviewed', 'interview_scheduled']
        ).count(),
        'formations_en_cours': Training.objects.filter(
            status='in_progress'
        ).count(),
        'formations_planifiees': Training.objects.filter(status='planned').count(),
        'evaluations_performance': PerformanceReview.objects.count(),
        'notes_frais_en_attente': ExpenseClaim.objects.filter(
            status='pending'
        ).count(),
        'notes_frais_validees': ExpenseClaim.objects.filter(
            status='approved'
        ).count(),
        'notes_frais_payees': ExpenseClaim.objects.filter(status='paid').count(),
        'documents': Document.objects.count(),
        'masse_salariale': active.aggregate(total=Sum('base_salary'))['total'] or 0,
        'salaire_moyen': active.aggregate(avg=Avg('base_salary'))['avg'] or 0,
    }


# ============================================================
# STATS UTILISATEURS
# ============================================================

def get_stats_utilisateurs():
    """Statistiques des utilisateurs."""
    from users.models import CustomUser, Agence, RoleAgence

    users = CustomUser.objects.all()
    roles = RoleAgence.objects.filter(est_actif=True)

    return {
        'utilisateurs_total': users.count(),
        'utilisateurs_actifs': users.filter(is_active=True).count(),
        'utilisateurs_inactifs': users.filter(is_active=False).count(),
        'pdg': users.filter(role_global='pdg').count(),
        'drh': users.filter(role_global='drh').count(),
        'autres': users.filter(role_global='autre').count(),
        'agences_total': Agence.objects.filter(est_active=True).count(),
        'agences_principales': Agence.objects.filter(
            est_active=True, type_agence='principale'
        ).count(),
        'agences_secondaires': Agence.objects.filter(
            est_active=True, type_agence='secondaire'
        ).count(),
        'chefs_agence': roles.filter(role='chef_agence').count(),
        'commerciaux': roles.filter(role='commercial').count(),
        'gestionnaires_stock': roles.filter(role='gestionnaire_stock').count(),
        'comptables': roles.filter(role='comptable').count(),
    }


# ============================================================
# DONNÉES GRAPHIQUES
# ============================================================

def get_recettes_par_mois(agences_ids=None, nb_mois=12):
    """Recettes (ventes complétées) des N derniers mois."""
    from sales.models import Vente

    today = timezone.now().date()
    debut = (today.replace(day=1) - timedelta(days=30 * nb_mois))

    ventes = Vente.objects.filter(
        status='completed',
        date_vente__date__gte=debut
    )
    if agences_ids:
        ventes = ventes.filter(agence_id__in=agences_ids)

    data = ventes.annotate(
        mois=TruncMonth('date_vente')
    ).values('mois').annotate(
        montant=Sum('total'),
        nb=Count('id')
    ).order_by('mois')

    mois_fr = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
               'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']

    result = []
    for item in data:
        if item['mois']:
            result.append({
                'label': f"{mois_fr[item['mois'].month - 1]} {item['mois'].year}",
                'montant': float(item['montant'] or 0),
                'nb_ventes': item['nb'],
            })
    return result


def get_depenses_par_mois(agences_ids=None, nb_mois=12):
    """Dépenses (achats + frais) des N derniers mois."""
    from purchases.models import PurchaseOrder
    from tresorerie.models import Frais

    today = timezone.now().date()
    debut = (today.replace(day=1) - timedelta(days=30 * nb_mois))

    mois_fr = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
               'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']

    # Achats
    achats = PurchaseOrder.objects.filter(
        status='received',
        order_date__gte=debut
    )
    if agences_ids:
        achats = achats.filter(agence_id__in=agences_ids)

    achats_data = achats.annotate(
        mois=TruncMonth('order_date')
    ).values('mois').annotate(total=Sum('total')).order_by('mois')

    # Frais
    frais = Frais.objects.filter(
        status='paye',
        date_frais__gte=debut
    )
    if agences_ids:
        frais = frais.filter(agence_id__in=agences_ids)

    frais_data = frais.annotate(
        mois=TruncMonth('date_frais')
    ).values('mois').annotate(total=Sum('montant')).order_by('mois')

    # Fusionner
    result = {}
    for item in achats_data:
        if item['mois']:
            key = f"{mois_fr[item['mois'].month - 1]} {item['mois'].year}"
            result[key] = result.get(
                key, {'label': key, 'montant': 0, 'achats': 0, 'frais': 0})
            result[key]['achats'] = float(item['total'] or 0)
            result[key]['montant'] += float(item['total'] or 0)

    for item in frais_data:
        if item['mois']:
            key = f"{mois_fr[item['mois'].month - 1]} {item['mois'].year}"
            result[key] = result.get(
                key, {'label': key, 'montant': 0, 'achats': 0, 'frais': 0})
            result[key]['frais'] = float(item['total'] or 0)
            result[key]['montant'] += float(item['total'] or 0)

    return list(result.values())


def get_top_produits_vendus(agences_ids=None, limit=10):
    """Top des produits les plus vendus."""
    from sales.models import VenteItem

    items = VenteItem.objects.filter(
        vente__status='completed'
    )
    if agences_ids:
        items = items.filter(vente__agence_id__in=agences_ids)

    return list(items.values(
        'product__id', 'product__name', 'product__reference'
    ).annotate(
        quantite=Sum('quantity'),
        total=Sum('total')
    ).order_by('-quantite')[:limit])


def get_top_clients(agences_ids=None, limit=10):
    """Top des clients par chiffre d'affaires."""
    from sales.models import Vente

    ventes = Vente.objects.filter(
        status='completed',
        client__isnull=False
    )
    if agences_ids:
        ventes = ventes.filter(agence_id__in=agences_ids)

    return list(ventes.values(
        'client__id', 'client__nom', 'client__prenom', 'client__raison_sociale'
    ).annotate(
        total=Sum('total'),
        nb_ventes=Count('id')
    ).order_by('-total')[:limit])


def get_top_fournisseurs(agences_ids=None, limit=10):
    """Top des fournisseurs par montant d'achats."""
    from purchases.models import PurchaseOrder

    orders = PurchaseOrder.objects.filter(status='received')
    if agences_ids:
        orders = orders.filter(agence_id__in=agences_ids)

    return list(orders.values(
        'supplier__id', 'supplier__company_name'
    ).annotate(
        total=Sum('total'),
        nb_commandes=Count('id')
    ).order_by('-total')[:limit])


def get_dernieres_activites(agences_ids=None, limit=10):
    """Dernières activités (ventes, achats, transferts)."""
    from sales.models import Vente
    from purchases.models import PurchaseOrder
    from inventaire.models import Transfer

    activites = []

    # Ventes
    ventes = Vente.objects.all()
    if agences_ids:
        ventes = ventes.filter(agence_id__in=agences_ids)
    for v in ventes.order_by('-date_vente')[:limit]:
        activites.append({
            'type': 'vente',
            'reference': v.reference,
            'description': f"Vente à {v.client.nom if v.client else 'Client anonyme'}",
            'montant': float(v.total),
            'statut': v.status,
            'date': v.date_vente.isoformat(),
            'id': v.id,
        })

    # Achats
    orders = PurchaseOrder.objects.all()
    if agences_ids:
        orders = orders.filter(agence_id__in=agences_ids)
    for o in orders.order_by('-order_date')[:limit]:
        activites.append({
            'type': 'achat',
            'reference': o.order_number,
            'description': f"Commande à {o.supplier.company_name}",
            'montant': float(o.total),
            'statut': o.status,
            'date': o.order_date.isoformat(),
            'id': o.id,
        })

    # Transferts
    transfers = Transfer.objects.all()
    if agences_ids:
        transfers = transfers.filter(
            Q(from_agence_id__in=agences_ids) | Q(to_agence_id__in=agences_ids)
        )
    for t in transfers.order_by('-created_at')[:limit]:
        activites.append({
            'type': 'transfert',
            'reference': t.reference,
            'description': f"Transfert {t.from_agence.nom} → {t.to_agence.nom}",
            'montant': 0,
            'statut': t.status,
            'date': t.created_at.isoformat(),
            'id': t.id,
        })

    # Trier par date décroissante
    activites.sort(key=lambda x: x['date'], reverse=True)
    return activites[:limit]


def get_alertes_globales(agences_ids=None):
    """Alertes consolidées de tous les modules."""
    from inventaire.models import StockAlert, Lot
    from sales.models import Facture
    from purchases.models import Invoice, PurchaseAlert
    from tresorerie.models import Caisse
    from hr.models import Leave, ExpenseClaim

    today = timezone.now().date()
    in_30_days = today + timedelta(days=30)
    alertes = []

    # Alertes stock
    stock_alertes = StockAlert.objects.filter(status='active')
    if agences_ids:
        stock_alertes = stock_alertes.filter(
            warehouse__agence_id__in=agences_ids)
    for a in stock_alertes[:5]:
        alertes.append({
            'type': 'stock',
            'niveau': 'error' if a.alert_type == 'out_of_stock' else 'warning',
            'message': f"{a.get_alert_type_display()}: {a.product.name}",
            'details': a.message,
            'module': 'Inventaire',
        })

    # Lots expirant
    lots = Lot.objects.filter(
        expiry_date__lte=in_30_days,
        expiry_date__gte=today,
        quantity__gt=0
    )
    if agences_ids:
        lots = lots.filter(warehouse__agence_id__in=agences_ids)
    for l in lots[:5]:
        alertes.append({
            'type': 'expiry',
            'niveau': 'warning',
            'message': f"Lot expirant: {l.product.name}",
            'details': f"Expire le {l.expiry_date} - {l.quantity} unités",
            'module': 'Inventaire',
        })

    # Factures clients en retard
    factures = Facture.objects.filter(status='overdue')
    if agences_ids:
        factures = factures.filter(agence_id__in=agences_ids)
    for f in factures[:5]:
        alertes.append({
            'type': 'facture_client',
            'niveau': 'error',
            'message': f"Facture client en retard: {f.reference}",
            'details': f"Montant: {f.montant_restant} FCFA",
            'module': 'Ventes',
        })

    # Factures fournisseurs en retard
    invoices = Invoice.objects.filter(status='overdue')
    if agences_ids:
        invoices = invoices.filter(agence_id__in=agences_ids)
    for i in invoices[:5]:
        alertes.append({
            'type': 'facture_fournisseur',
            'niveau': 'error',
            'message': f"Facture fournisseur en retard: {i.invoice_number}",
            'details': f"Montant: {i.amount_remaining} FCFA",
            'module': 'Achats',
        })

    # Caisses sous seuil
    caisses = Caisse.objects.filter(is_active=True)
    if agences_ids:
        caisses = caisses.filter(agence_id__in=agences_ids)
    for c in caisses:
        if c.est_sous_seuil_min:
            alertes.append({
                'type': 'caisse',
                'niveau': 'warning',
                'message': f"Caisse sous seuil: {c.nom}",
                'details': f"Solde: {c.solde_actuel} - Seuil: {c.seuil_min}",
                'module': 'Trésorerie',
            })

    # Congés en attente
    conges = Leave.objects.filter(status='pending')
    if conges.count() > 0:
        alertes.append({
            'type': 'conge',
            'niveau': 'info',
            'message': f"{conges.count()} demande(s) de congé en attente",
            'details': "À traiter par le service RH",
            'module': 'RH',
        })

    # Notes de frais en attente
    notes = ExpenseClaim.objects.filter(status='pending')
    if notes.count() > 0:
        alertes.append({
            'type': 'note_frais',
            'niveau': 'info',
            'message': f"{notes.count()} note(s) de frais en attente",
            'details': "À valider par le service RH",
            'module': 'RH',
        })

    return alertes
