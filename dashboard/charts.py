# dashboard/charts.py
"""
Générateur de données pour graphiques professionnels.
Retourne des structures prêtes à l'emploi pour Chart.js.
"""

from decimal import Decimal
from datetime import timedelta
from django.db.models import Sum, Count, Q, F, Avg
from django.utils import timezone
from django.db.models.functions import TruncMonth

from . import utils
# ============================================================
# HELPERS
# ============================================================


def _to_float(value):
    """Convertit en float de façon sécurisée."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


# ============================================================
# GRAPHIQUES CIRCULAIRES (PIE / DOUGHNUT)
# ============================================================

def get_repartition_ventes_par_statut(agences_ids=None):
    """Camembert : répartition des ventes par statut."""
    from sales.models import Vente

    qs = Vente.objects.all()
    if agences_ids:
        qs = qs.filter(agence_id__in=agences_ids)

    statuts = {
        'draft': ('Brouillon', '#94a3b8'),
        'pending_approval': ('En attente', '#f59e0b'),
        'approved': ('Approuvée', '#3b82f6'),
        'completed': ('Complétée', '#10b981'),
        'rejected': ('Rejetée', '#ef4444'),
        'cancelled': ('Annulée', '#6b7280'),
    }

    data = []
    for code, (label, color) in statuts.items():
        count = qs.filter(status=code).count()
        if count > 0:
            data.append({
                'label': label,
                'value': count,
                'color': color,
            })

    return {
        'title': 'Répartition des ventes par statut',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_produits_par_categorie(agences_ids=None):
    """Camembert : répartition des produits par catégorie."""
    from produits.models import Category, Product

    qs = Product.objects.filter(is_active=True)
    if agences_ids:
        qs = qs.filter(
            warehouse_stocks__warehouse__agence_id__in=agences_ids
        ).distinct()

    categories = qs.values('category__name').annotate(
        total=Count('id')
    ).order_by('-total')[:10]

    colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
              '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#84cc16']

    data = []
    for i, cat in enumerate(categories):
        if cat['category__name']:
            data.append({
                'label': cat['category__name'],
                'value': cat['total'],
                'color': colors[i % len(colors)],
            })

    return {
        'title': 'Produits par catégorie',
        'type': 'pie',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_stock_par_entrepot(agences_ids=None):
    """Doughnut : répartition du stock par entrepôt."""
    from inventaire.models import Warehouse, WarehouseStock

    warehouses = Warehouse.objects.filter(is_active=True)
    if agences_ids:
        warehouses = warehouses.filter(agence_id__in=agences_ids)

    colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
              '#ec4899', '#14b8a6', '#f97316']

    data = []
    for i, wh in enumerate(warehouses[:8]):
        total = WarehouseStock.objects.filter(
            warehouse=wh
        ).aggregate(total=Sum('quantity'))['total'] or 0
        if total > 0:
            data.append({
                'label': wh.name,
                'value': total,
                'color': colors[i % len(colors)],
            })

    return {
        'title': 'Stock par entrepôt',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_clients_par_type(agences_ids=None):
    """Camembert : répartition des clients par type."""
    from sales.models import Client

    qs = Client.objects.filter(is_active=True)

    types = {
        'particulier': ('Particulier', '#3b82f6'),
        'entreprise': ('Entreprise', '#10b981'),
        'revendeur': ('Revendeur', '#f59e0b'),
    }

    data = []
    for code, (label, color) in types.items():
        count = qs.filter(client_type=code).count()
        if count > 0:
            data.append({
                'label': label,
                'value': count,
                'color': color,
            })

    return {
        'title': 'Clients par type',
        'type': 'pie',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_mouvements_par_type(agences_ids=None):
    """Doughnut : répartition des mouvements de stock par type."""
    from inventaire.models import StockMovement

    qs = StockMovement.objects.all()
    if agences_ids:
        qs = qs.filter(
            Q(from_warehouse__agence_id__in=agences_ids) |
            Q(to_warehouse__agence_id__in=agences_ids)
        )

    types = {
        'in': ('Entrée', '#10b981'),
        'out': ('Sortie', '#ef4444'),
        'transfer': ('Transfert', '#3b82f6'),
        'adjustment': ('Ajustement', '#f59e0b'),
        'return': ('Retour', '#8b5cf6'),
        'scrap': ('Rebut', '#6b7280'),
    }

    data = []
    for code, (label, color) in types.items():
        count = qs.filter(movement_type=code).count()
        if count > 0:
            data.append({
                'label': label,
                'value': count,
                'color': color,
            })

    return {
        'title': 'Mouvements de stock par type',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_transferts_par_statut(agences_ids=None):
    """Camembert : répartition des transferts par statut."""
    from inventaire.models import Transfer

    qs = Transfer.objects.all()
    if agences_ids:
        qs = qs.filter(
            Q(from_agence_id__in=agences_ids) | Q(to_agence_id__in=agences_ids)
        )

    statuts = {
        'draft': ('Brouillon', '#94a3b8'),
        'pending_approval': ('En attente', '#f59e0b'),
        'approved': ('Approuvé', '#3b82f6'),
        'in_transit': ('En transit', '#8b5cf6'),
        'partial': ('Partiel', '#f97316'),
        'completed': ('Terminé', '#10b981'),
        'rejected': ('Rejeté', '#ef4444'),
        'cancelled': ('Annulé', '#6b7280'),
    }

    data = []
    for code, (label, color) in statuts.items():
        count = qs.filter(status=code).count()
        if count > 0:
            data.append({
                'label': label,
                'value': count,
                'color': color,
            })

    return {
        'title': 'Transferts par statut',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_factures_par_statut(agences_ids=None):
    """Camembert : répartition des factures clients par statut."""
    from sales.models import Facture

    qs = Facture.objects.all()
    if agences_ids:
        qs = qs.filter(agence_id__in=agences_ids)

    statuts = {
        'draft': ('Brouillon', '#94a3b8'),
        'sent': ('Envoyée', '#3b82f6'),
        'paid': ('Payée', '#10b981'),
        'partially_paid': ('Partielle', '#f59e0b'),
        'overdue': ('En retard', '#ef4444'),
        'cancelled': ('Annulée', '#6b7280'),
    }

    data = []
    for code, (label, color) in statuts.items():
        count = qs.filter(status=code).count()
        if count > 0:
            data.append({
                'label': label,
                'value': count,
                'color': color,
            })

    return {
        'title': 'Factures clients par statut',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_achats_par_statut(agences_ids=None):
    """Camembert : répartition des commandes d'achat par statut."""
    from purchases.models import PurchaseOrder

    qs = PurchaseOrder.objects.all()
    if agences_ids:
        qs = qs.filter(agence_id__in=agences_ids)

    statuts = {
        'draft': ('Brouillon', '#94a3b8'),
        'sent': ('Envoyée', '#3b82f6'),
        'confirmed': ('Confirmée', '#8b5cf6'),
        'in_transit': ('En transit', '#f59e0b'),
        'partially_received': ('Partielle', '#f97316'),
        'received': ('Reçue', '#10b981'),
        'cancelled': ('Annulée', '#6b7280'),
        'rejected': ('Rejetée', '#ef4444'),
    }

    data = []
    for code, (label, color) in statuts.items():
        count = qs.filter(status=code).count()
        if count > 0:
            data.append({
                'label': label,
                'value': count,
                'color': color,
            })

    return {
        'title': 'Commandes d\'achat par statut',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_employes_par_departement(agences_ids=None):
    """Camembert : répartition des employés par département."""
    from hr.models import Employee, Department

    qs = Employee.objects.filter(work_status='active')

    departements = qs.values('department__name').annotate(
        total=Count('id')
    ).order_by('-total')[:10]

    colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
              '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#84cc16']

    data = []
    for i, dept in enumerate(departements):
        if dept['department__name']:
            data.append({
                'label': dept['department__name'],
                'value': dept['total'],
                'color': colors[i % len(colors)],
            })

    return {
        'title': 'Employés par département',
        'type': 'pie',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_utilisateurs_par_role():
    """Doughnut : répartition des utilisateurs par rôle."""
    from users.models import CustomUser, RoleAgence

    roles = RoleAgence.objects.filter(est_actif=True)

    data = []

    # Rôles globaux
    pdg = CustomUser.objects.filter(role_global='pdg').count()
    drh = CustomUser.objects.filter(role_global='drh').count()
    if pdg > 0:
        data.append({'label': 'PDG', 'value': pdg, 'color': '#dc2626'})
    if drh > 0:
        data.append({'label': 'DRH', 'value': drh, 'color': '#9333ea'})

    # Rôles par agence
    chefs = roles.filter(role='chef_agence').values('user').distinct().count()
    commerciaux = roles.filter(role='commercial').values(
        'user').distinct().count()
    gestionnaires = roles.filter(role='gestionnaire_stock').values(
        'user').distinct().count()
    comptables = roles.filter(role='comptable').values(
        'user').distinct().count()

    if chefs > 0:
        data.append({'label': 'Chefs d\'agence',
                    'value': chefs, 'color': '#3b82f6'})
    if commerciaux > 0:
        data.append({'label': 'Commerciaux',
                    'value': commerciaux, 'color': '#10b981'})
    if gestionnaires > 0:
        data.append({'label': 'Gestionnaires stock',
                    'value': gestionnaires, 'color': '#f59e0b'})
    if comptables > 0:
        data.append(
            {'label': 'Comptables', 'value': comptables, 'color': '#8b5cf6'})

    return {
        'title': 'Utilisateurs par rôle',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_ca_par_agence(agences_ids=None):
    """Doughnut : répartition du CA par agence."""
    from sales.models import Vente

    qs = Vente.objects.filter(status='completed')
    if agences_ids:
        qs = qs.filter(agence_id__in=agences_ids)

    agences = qs.values('agence__nom').annotate(
        total=Sum('total')
    ).order_by('-total')[:8]

    colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
              '#ec4899', '#14b8a6', '#f97316']

    data = []
    for i, ag in enumerate(agences):
        if ag['agence__nom'] and ag['total']:
            data.append({
                'label': ag['agence__nom'],
                'value': _to_float(ag['total']),
                'color': colors[i % len(colors)],
            })

    return {
        'title': 'Chiffre d\'affaires par agence',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_depenses_par_categorie(agences_ids=None, periode='mois'):
    """Camembert : répartition des dépenses par catégorie."""
    from purchases.models import PurchaseOrder
    from tresorerie.models import Frais

    date_debut, date_fin = utils.get_periode_dates(periode)

    data = []

    # Achats (fournisseurs)
    achats = PurchaseOrder.objects.filter(
        status='received',
        order_date__gte=date_debut,
        order_date__lte=date_fin
    )
    if agences_ids:
        achats = achats.filter(agence_id__in=agences_ids)
    total_achats = _to_float(achats.aggregate(total=Sum('total'))['total'])
    if total_achats > 0:
        data.append(
            {'label': 'Achats', 'value': total_achats, 'color': '#ef4444'})

    # Frais par catégorie
    frais = Frais.objects.filter(
        status='paye',
        date_frais__gte=date_debut,
        date_frais__lte=date_fin
    )
    if agences_ids:
        frais = frais.filter(agence_id__in=agences_ids)

    frais_par_cat = frais.values('categorie').annotate(
        total=Sum('montant')
    ).order_by('-total')[:6]

    colors = ['#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1']

    for i, f in enumerate(frais_par_cat):
        if f['total']:
            label = dict(Frais.CATEGORIE_FRAIS).get(
                f['categorie'], f['categorie'])
            data.append({
                'label': label,
                'value': _to_float(f['total']),
                'color': colors[i % len(colors)],
            })

    return {
        'title': 'Dépenses par catégorie',
        'type': 'pie',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_tresorerie(agences_ids=None):
    """Doughnut : répartition de la trésorerie (caisses vs banques)."""
    from tresorerie.models import Caisse, CompteBancaire

    caisses = Caisse.objects.filter(is_active=True)
    comptes = CompteBancaire.objects.filter(is_active=True)
    if agences_ids:
        caisses = caisses.filter(agence_id__in=agences_ids)
        comptes = comptes.filter(agence_id__in=agences_ids)

    solde_caisses = _to_float(caisses.aggregate(
        total=Sum('solde_actuel'))['total'])
    solde_banques = _to_float(comptes.aggregate(
        total=Sum('solde_actuel'))['total'])

    data = []
    if solde_caisses > 0:
        data.append(
            {'label': 'Caisses', 'value': solde_caisses, 'color': '#10b981'})
    if solde_banques > 0:
        data.append({'label': 'Comptes bancaires',
                    'value': solde_banques, 'color': '#3b82f6'})

    return {
        'title': 'Répartition de la trésorerie',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_alertes(agences_ids=None):
    """Doughnut : répartition des alertes par module."""
    alertes = utils.get_alertes_globales(agences_ids)

    modules = {}
    for a in alertes:
        modules[a['module']] = modules.get(a['module'], 0) + 1

    colors_map = {
        'Inventaire': '#3b82f6',
        'Ventes': '#10b981',
        'Achats': '#f59e0b',
        'Trésorerie': '#8b5cf6',
        'RH': '#ec4899',
    }

    data = [
        {'label': module, 'value': count,
            'color': colors_map.get(module, '#6b7280')}
        for module, count in modules.items()
    ]

    return {
        'title': 'Alertes par module',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_rh(agences_ids=None):
    """Camembert : répartition des employés par statut."""
    from hr.models import Employee

    employees = Employee.objects.all()

    statuts = {
        'active': ('Actif', '#10b981'),
        'on_leave': ('En congé', '#f59e0b'),
        'sick': ('Maladie', '#ef4444'),
        'remote': ('Télétravail', '#3b82f6'),
        'suspended': ('Suspendu', '#6b7280'),
        'terminated': ('Licencié', '#991b1b'),
    }

    data = []
    for code, (label, color) in statuts.items():
        count = employees.filter(work_status=code).count()
        if count > 0:
            data.append({
                'label': label,
                'value': count,
                'color': color,
            })

    return {
        'title': 'Employés par statut',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


# ============================================================
# GRAPHIQUES À BARRES
# ============================================================

def get_top_produits_bar(agences_ids=None, limit=8):
    """Barres : top produits vendus."""
    from sales.models import VenteItem

    items = VenteItem.objects.filter(vente__status='completed')
    if agences_ids:
        items = items.filter(vente__agence_id__in=agences_ids)

    data = list(items.values(
        'product__name'
    ).annotate(
        quantite=Sum('quantity'),
        total=Sum('total')
    ).order_by('-quantite')[:limit])

    return {
        'title': 'Top produits vendus',
        'type': 'bar',
        'labels': [d['product__name'] for d in data],
        'datasets': [{
            'label': 'Quantité vendue',
            'data': [d['quantite'] for d in data],
            'color': '#3b82f6',
        }],
    }


def get_ventes_vs_achats_bar(agences_ids=None):
    """Barres : comparaison ventes vs achats sur 12 mois."""
    from sales.models import Vente
    from purchases.models import PurchaseOrder

    today = timezone.now().date()
    debut = today.replace(day=1) - timedelta(days=30 * 11)

    mois_fr = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
               'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']

    # Ventes
    ventes = Vente.objects.filter(
        status='completed', date_vente__date__gte=debut)
    if agences_ids:
        ventes = ventes.filter(agence_id__in=agences_ids)
    ventes_data = ventes.annotate(mois=TruncMonth('date_vente')).values(
        'mois').annotate(total=Sum('total')).order_by('mois')

    # Achats
    achats = PurchaseOrder.objects.filter(
        status='received', order_date__gte=debut)
    if agences_ids:
        achats = achats.filter(agence_id__in=agences_ids)
    achats_data = achats.annotate(mois=TruncMonth('order_date')).values(
        'mois').annotate(total=Sum('total')).order_by('mois')

    # Fusionner
    labels = []
    ventes_vals = []
    achats_vals = []

    for item in ventes_data:
        if item['mois']:
            labels.append(
                f"{mois_fr[item['mois'].month - 1]} {item['mois'].year}")
            ventes_vals.append(_to_float(item['total']))
            achats_item = next(
                (a for a in achats_data if a['mois'] == item['mois']), None
            )
            achats_vals.append(
                _to_float(achats_item['total']) if achats_item else 0)

    return {
        'title': 'Ventes vs Achats (12 mois)',
        'type': 'bar',
        'labels': labels,
        'datasets': [
            {'label': 'Ventes', 'data': ventes_vals, 'color': '#10b981'},
            {'label': 'Achats', 'data': achats_vals, 'color': '#ef4444'},
        ],
    }


# ============================================================
# GRAPHIQUES EN LIGNE
# ============================================================

def get_evolution_tresorerie(agences_ids=None):
    """Ligne : évolution de la trésorerie sur 12 mois."""
    from tresorerie.models import MouvementTresorerie

    today = timezone.now().date()
    debut = today.replace(day=1) - timedelta(days=30 * 11)

    qs = MouvementTresorerie.objects.filter(
        status='effectue',
        date_mouvement__date__gte=debut
    )
    if agences_ids:
        qs = qs.filter(agence_id__in=agences_ids)

    mois_fr = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
               'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']

    encaissements = qs.filter(type_mouvement='encaissement').annotate(
        mois=TruncMonth('date_mouvement')
    ).values('mois').annotate(total=Sum('montant')).order_by('mois')

    decaissements = qs.filter(type_mouvement='decaissement').annotate(
        mois=TruncMonth('date_mouvement')
    ).values('mois').annotate(total=Sum('montant')).order_by('mois')

    labels = []
    enc_vals = []
    dec_vals = []
    solde_vals = []
    solde = 0

    all_mois = sorted(set(
        [e['mois'] for e in encaissements if e['mois']] +
        [d['mois'] for d in decaissements if d['mois']]
    ))

    for mois in all_mois:
        labels.append(f"{mois_fr[mois.month - 1]} {mois.year}")
        enc = next((e['total']
                   for e in encaissements if e['mois'] == mois), 0) or 0
        dec = next((d['total']
                   for d in decaissements if d['mois'] == mois), 0) or 0
        enc_vals.append(_to_float(enc))
        dec_vals.append(_to_float(dec))
        solde += _to_float(enc) - _to_float(dec)
        solde_vals.append(solde)

    return {
        'title': 'Évolution de la trésorerie',
        'type': 'line',
        'labels': labels,
        'datasets': [
            {'label': 'Encaissements', 'data': enc_vals, 'color': '#10b981'},
            {'label': 'Décaissements', 'data': dec_vals, 'color': '#ef4444'},
            {'label': 'Solde cumulé', 'data': solde_vals, 'color': '#3b82f6'},
        ],
    }


# ============================================================
# TOUS LES CHARTS
# ============================================================

def get_all_charts(agences_ids=None, periode='mois'):
    """Retourne TOUS les graphiques en un seul appel."""
    return {
        # Circulaires
        'ventes_par_statut': get_repartition_ventes_par_statut(agences_ids),
        'produits_par_categorie': get_repartition_produits_par_categorie(agences_ids),
        'stock_par_entrepot': get_repartition_stock_par_entrepot(agences_ids),
        'clients_par_type': get_repartition_clients_par_type(agences_ids),
        'mouvements_par_type': get_repartition_mouvements_par_type(agences_ids),
        'transferts_par_statut': get_repartition_transferts_par_statut(agences_ids),
        'factures_par_statut': get_repartition_factures_par_statut(agences_ids),
        'achats_par_statut': get_repartition_achats_par_statut(agences_ids),
        'employes_par_departement': get_repartition_employes_par_departement(agences_ids),
        'utilisateurs_par_role': get_repartition_utilisateurs_par_role(),
        'ca_par_agence': get_repartition_ca_par_agence(agences_ids),
        'depenses_par_categorie': get_repartition_depenses_par_categorie(agences_ids, periode),
        'tresorerie': get_repartition_tresorerie(agences_ids),
        'alertes': get_repartition_alertes(agences_ids),
        'rh_par_statut': get_repartition_rh(agences_ids),

        # Barres
        'top_produits_bar': get_top_produits_bar(agences_ids),
        'ventes_vs_achats': get_ventes_vs_achats_bar(agences_ids),

        # Lignes
        'evolution_tresorerie': get_evolution_tresorerie(agences_ids),
    }
