# dashboard/charts.py
"""
Générateur de données pour graphiques professionnels.
Retourne des structures prêtes à l'emploi pour Recharts / Chart.js.

✅ Version complète avec TOUTES les fonctions :
- get_all_charts
- get_repartition_* (15 charts circulaires)
- get_top_produits_bar
- get_ventes_vs_achats_bar
- get_evolution_tresorerie
"""

from decimal import Decimal
from datetime import timedelta

from django.db.models import Sum, Count, Q, F, Avg
from django.db.models.functions import TruncMonth
from django.utils import timezone

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

    labels = {
        'draft': ('Brouillon', '#94a3b8'),
        'pending_approval': ('En attente', '#f59e0b'),
        'approved': ('Approuvée', '#3b82f6'),
        'completed': ('Complétée', '#10b981'),
        'rejected': ('Rejetée', '#ef4444'),
        'cancelled': ('Annulée', '#6b7280'),
    }
    color_map = {k: v[1] for k, v in labels.items()}

    raw = qs.values('status').annotate(value=Count('id')).order_by('-value')

    data = [
        {
            'label': labels.get(item['status'], (item['status'], None))[0],
            'value': item['value'],
            'color': color_map.get(item['status'], '#6b7280'),
        }
        for item in raw if item['value'] > 0
    ]

    return {
        'title': 'Répartition des ventes par statut',
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_produits_par_categorie(agences_ids=None):
    """Camembert : répartition des produits par catégorie."""
    from produits.models import Product

    qs = Product.objects.filter(is_active=True)
    if agences_ids:
        qs = qs.filter(
            warehouse_stocks__warehouse__agence_id__in=agences_ids
        ).distinct()

    categories = qs.values('category__name').annotate(
        value=Count('id')
    ).order_by('-value')[:10]

    colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
              '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#84cc16']

    data = [
        {
            'label': cat['category__name'],
            'value': cat['value'],
            'color': colors[i % len(colors)],
        }
        for i, cat in enumerate(categories) if cat['category__name']
    ]

    return {
        'title': 'Produits par catégorie',
        'type': 'pie',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_stock_par_entrepot(agences_ids=None):
    """Doughnut : répartition du stock par entrepôt."""
    from inventaire.models import WarehouseStock

    qs = WarehouseStock.objects.all()
    if agences_ids:
        qs = qs.filter(warehouse__agence_id__in=agences_ids)

    warehouses = qs.values('warehouse__name').annotate(
        value=Sum('quantity')
    ).order_by('-value')[:8]

    colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
              '#ec4899', '#14b8a6', '#f97316']

    data = [
        {
            'label': wh['warehouse__name'],
            'value': wh['value'] or 0,
            'color': colors[i % len(colors)],
        }
        for i, wh in enumerate(warehouses) if (wh['value'] or 0) > 0
    ]

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

    labels = {
        'particulier': ('Particulier', '#3b82f6'),
        'entreprise': ('Entreprise', '#10b981'),
        'revendeur': ('Revendeur', '#f59e0b'),
    }
    color_map = {k: v[1] for k, v in labels.items()}

    raw = qs.values('client_type').annotate(
        value=Count('id')).order_by('-value')

    data = [
        {
            'label': labels.get(item['client_type'], (item['client_type'], None))[0],
            'value': item['value'],
            'color': color_map.get(item['client_type'], '#6b7280'),
        }
        for item in raw if item['value'] > 0
    ]

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

    labels = {
        'in': ('Entrée', '#10b981'),
        'out': ('Sortie', '#ef4444'),
        'transfer': ('Transfert', '#3b82f6'),
        'adjustment': ('Ajustement', '#f59e0b'),
        'return': ('Retour', '#8b5cf6'),
        'scrap': ('Rebut', '#6b7280'),
    }
    color_map = {k: v[1] for k, v in labels.items()}

    raw = qs.values('movement_type').annotate(
        value=Count('id')).order_by('-value')

    data = [
        {
            'label': labels.get(item['movement_type'], (item['movement_type'], None))[0],
            'value': item['value'],
            'color': color_map.get(item['movement_type'], '#6b7280'),
        }
        for item in raw if item['value'] > 0
    ]

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
            Q(from_agence_id__in=agences_ids) |
            Q(to_agence_id__in=agences_ids)
        )

    labels = {
        'draft': ('Brouillon', '#94a3b8'),
        'pending_approval': ('En attente', '#f59e0b'),
        'approved': ('Approuvé', '#3b82f6'),
        'in_transit': ('En transit', '#8b5cf6'),
        'partial': ('Partiel', '#f97316'),
        'completed': ('Terminé', '#10b981'),
        'rejected': ('Rejeté', '#ef4444'),
        'cancelled': ('Annulé', '#6b7280'),
    }
    color_map = {k: v[1] for k, v in labels.items()}

    raw = qs.values('status').annotate(value=Count('id')).order_by('-value')

    data = [
        {
            'label': labels.get(item['status'], (item['status'], None))[0],
            'value': item['value'],
            'color': color_map.get(item['status'], '#6b7280'),
        }
        for item in raw if item['value'] > 0
    ]

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

    labels = {
        'draft': ('Brouillon', '#94a3b8'),
        'sent': ('Envoyée', '#3b82f6'),
        'paid': ('Payée', '#10b981'),
        'partially_paid': ('Partielle', '#f59e0b'),
        'overdue': ('En retard', '#ef4444'),
        'cancelled': ('Annulée', '#6b7280'),
    }
    color_map = {k: v[1] for k, v in labels.items()}

    raw = qs.values('status').annotate(value=Count('id')).order_by('-value')

    data = [
        {
            'label': labels.get(item['status'], (item['status'], None))[0],
            'value': item['value'],
            'color': color_map.get(item['status'], '#6b7280'),
        }
        for item in raw if item['value'] > 0
    ]

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

    labels = {
        'draft': ('Brouillon', '#94a3b8'),
        'sent': ('Envoyée', '#3b82f6'),
        'confirmed': ('Confirmée', '#8b5cf6'),
        'in_transit': ('En transit', '#f59e0b'),
        'partially_received': ('Partielle', '#f97316'),
        'received': ('Reçue', '#10b981'),
        'cancelled': ('Annulée', '#6b7280'),
        'rejected': ('Rejetée', '#ef4444'),
    }
    color_map = {k: v[1] for k, v in labels.items()}

    raw = qs.values('status').annotate(value=Count('id')).order_by('-value')

    data = [
        {
            'label': labels.get(item['status'], (item['status'], None))[0],
            'value': item['value'],
            'color': color_map.get(item['status'], '#6b7280'),
        }
        for item in raw if item['value'] > 0
    ]

    return {
        'title': "Commandes d'achat par statut",
        'type': 'doughnut',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_employes_par_departement(agences_ids=None):
    """Camembert : répartition des employés par département."""
    from hr.models import Employee

    qs = Employee.objects.filter(work_status='active')

    departements = qs.values('department__name').annotate(
        value=Count('id')
    ).order_by('-value')[:10]

    colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
              '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#84cc16']

    data = [
        {
            'label': dept['department__name'],
            'value': dept['value'],
            'color': colors[i % len(colors)],
        }
        for i, dept in enumerate(departements) if dept['department__name']
    ]

    return {
        'title': 'Employés par département',
        'type': 'pie',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_utilisateurs_par_role(agences_ids=None):
    """Doughnut : répartition des utilisateurs par rôle."""
    from users.models import CustomUser, RoleAgence

    data = []

    users_stats = CustomUser.objects.aggregate(
        pdg=Count('id', filter=Q(role_global='pdg')),
        drh=Count('id', filter=Q(role_global='drh')),
    )
    if users_stats['pdg'] > 0:
        data.append(
            {'label': 'PDG', 'value': users_stats['pdg'], 'color': '#dc2626'})
    if users_stats['drh'] > 0:
        data.append(
            {'label': 'DRH', 'value': users_stats['drh'], 'color': '#9333ea'})

    roles = RoleAgence.objects.filter(est_actif=True)
    roles_stats = roles.aggregate(
        chefs=Count('user', distinct=True, filter=Q(role='chef_agence')),
        commerciaux=Count('user', distinct=True, filter=Q(role='commercial')),
        gestionnaires=Count('user', distinct=True,
                            filter=Q(role='gestionnaire_stock')),
        comptables=Count('user', distinct=True, filter=Q(role='comptable')),
    )

    if roles_stats['chefs'] > 0:
        data.append({'label': "Chefs d'agence",
                    'value': roles_stats['chefs'], 'color': '#3b82f6'})
    if roles_stats['commerciaux'] > 0:
        data.append({'label': 'Commerciaux',
                    'value': roles_stats['commerciaux'], 'color': '#10b981'})
    if roles_stats['gestionnaires'] > 0:
        data.append({'label': 'Gestionnaires stock',
                    'value': roles_stats['gestionnaires'], 'color': '#f59e0b'})
    if roles_stats['comptables'] > 0:
        data.append({'label': 'Comptables',
                    'value': roles_stats['comptables'], 'color': '#8b5cf6'})

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
        value=Sum('total')
    ).order_by('-value')[:8]

    colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
              '#ec4899', '#14b8a6', '#f97316']

    data = [
        {
            'label': ag['agence__nom'],
            'value': _to_float(ag['value']),
            'color': colors[i % len(colors)],
        }
        for i, ag in enumerate(agences)
        if ag['agence__nom'] and (ag['value'] or 0) > 0
    ]

    return {
        'title': "Chiffre d'affaires par agence",
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

    achats = PurchaseOrder.objects.filter(
        status='received',
        order_date__gte=date_debut,
        order_date__lte=date_fin,
    )
    if agences_ids:
        achats = achats.filter(agence_id__in=agences_ids)
    total_achats = _to_float(
        achats.aggregate(total=Sum('total'))['total']
    )
    if total_achats > 0:
        data.append(
            {'label': 'Achats', 'value': total_achats, 'color': '#ef4444'})

    frais = Frais.objects.filter(
        status='paye',
        date_frais__gte=date_debut,
        date_frais__lte=date_fin,
    )
    if agences_ids:
        frais = frais.filter(agence_id__in=agences_ids)

    frais_par_cat = frais.values('categorie').annotate(
        value=Sum('montant')
    ).order_by('-value')[:6]

    colors = ['#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1']

    for i, f in enumerate(frais_par_cat):
        if f['value']:
            label = dict(Frais.CATEGORIE_FRAIS).get(
                f['categorie'], f['categorie'])
            data.append({
                'label': label,
                'value': _to_float(f['value']),
                'color': colors[i % len(colors)],
            })

    return {
        'title': 'Dépenses par catégorie',
        'type': 'pie',
        'data': data,
        'total': sum(d['value'] for d in data),
    }


def get_repartition_tresorerie(agences_ids=None):
    """Doughnut : répartition caisses vs banques."""
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
        {
            'label': module,
            'value': count,
            'color': colors_map.get(module, '#6b7280'),
        }
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

    labels = {
        'active': ('Actif', '#10b981'),
        'on_leave': ('En congé', '#f59e0b'),
        'sick': ('Maladie', '#ef4444'),
        'remote': ('Télétravail', '#3b82f6'),
        'suspended': ('Suspendu', '#6b7280'),
        'terminated': ('Licencié', '#991b1b'),
    }
    color_map = {k: v[1] for k, v in labels.items()}

    raw = Employee.objects.values('work_status').annotate(
        value=Count('id')
    ).order_by('-value')

    data = [
        {
            'label': labels.get(item['work_status'], (item['work_status'], None))[0],
            'value': item['value'],
            'color': color_map.get(item['work_status'], '#6b7280'),
        }
        for item in raw if item['value'] > 0
    ]

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
        total=Sum('total'),
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

    ventes = Vente.objects.filter(
        status='completed', date_vente__date__gte=debut,
    )
    if agences_ids:
        ventes = ventes.filter(agence_id__in=agences_ids)
    ventes_data = ventes.annotate(
        mois=TruncMonth('date_vente')
    ).values('mois').annotate(total=Sum('total')).order_by('mois')

    achats = PurchaseOrder.objects.filter(
        status='received', order_date__gte=debut,
    )
    if agences_ids:
        achats = achats.filter(agence_id__in=agences_ids)
    achats_data = achats.annotate(
        mois=TruncMonth('order_date')
    ).values('mois').annotate(total=Sum('total')).order_by('mois')

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
        date_mouvement__date__gte=debut,
    )
    if agences_ids:
        qs = qs.filter(agence_id__in=agences_ids)

    mois_fr = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
               'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']

    data = qs.annotate(
        mois=TruncMonth('date_mouvement')
    ).values('mois', 'type_mouvement').annotate(
        total=Sum('montant')
    ).order_by('mois')

    by_month = {}
    for item in data:
        if not item['mois']:
            continue
        key = item['mois']
        if key not in by_month:
            by_month[key] = {'enc': 0, 'dec': 0}
        if item['type_mouvement'] == 'encaissement':
            by_month[key]['enc'] = _to_float(item['total'])
        elif item['type_mouvement'] == 'decaissement':
            by_month[key]['dec'] = _to_float(item['total'])

    labels = []
    enc_vals = []
    dec_vals = []
    solde_vals = []
    solde = 0

    for mois in sorted(by_month.keys()):
        labels.append(f"{mois_fr[mois.month - 1]} {mois.year}")
        enc = by_month[mois]['enc']
        dec = by_month[mois]['dec']
        enc_vals.append(enc)
        dec_vals.append(dec)
        solde += enc - dec
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
# TOUS LES CHARTS (✅ FONCTION MANQUANTE — CAUSE DU BUG)
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
        'utilisateurs_par_role': get_repartition_utilisateurs_par_role(agences_ids),
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
