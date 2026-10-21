# dashboard/cache_signals.py
"""
Signaux d'invalidation du cache dashboard.

✅ Couvre TOUS les modèles métier des apps :
- hr (employees, leaves, payroll, expenses, etc.)
- produits (products, categories, brands, pricing)
- inventaire (warehouses, transfers, inventory counts, alerts, lots)
- comptabilite (ecritures, factures, reglements, clotures)
- tresorerie (caisses, comptes, mouvements, frais, previsions, rapprochements)
- sales (ventes, devis, factures, paiements, clients)
- users (custom users, agences)

❌ N'invalide PAS pour des changements mineurs (login, last_seen, etc.)
✅ N'invalide QUE pour les changements métier impactant le dashboard.
"""

import logging
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete

logger = logging.getLogger(__name__)


# ============================================================
# PURGE DU CACHE DASHBOARD
# ============================================================
def purge_dashboard_cache():
    """
    Supprime tout le cache dashboard.
    Utilise delete_pattern si Redis, sinon fallback.
    """
    try:
        # ✅ Redis/django-redis : suppression par pattern
        cache.delete_pattern('dashboard:*')
        logger.debug("✅ Cache dashboard purgé (pattern)")
    except AttributeError:
        # Fallback : LocMemCache ne supporte pas delete_pattern
        try:
            cache.clear()
            logger.debug("✅ Cache dashboard purgé (clear complet)")
        except Exception as e:
            logger.warning(f"⚠️ Impossible de purger le cache dashboard : {e}")
    except Exception as e:
        logger.warning(f"⚠️ Erreur purge cache : {e}")


def _safe_purge(reason: str):
    """
    Wrapper qui purge + log la raison (utile en debug).
    """
    try:
        purge_dashboard_cache()
    except Exception as e:
        logger.exception(f"Erreur purge cache (raison: {reason}) : {e}")


# ============================================================
# SIGNAL HANDLERS (un par module)
# ============================================================

# ---------- HR ----------
def _handle_hr_save(sender, instance, created, **kwargs):
    _safe_purge(f"hr.{sender.__name__}.save")


def _handle_hr_delete(sender, instance, **kwargs):
    _safe_purge(f"hr.{sender.__name__}.delete")


# ---------- PRODUITS ----------
def _handle_produits_save(sender, instance, created, **kwargs):
    _safe_purge(f"produits.{sender.__name__}.save")


def _handle_produits_delete(sender, instance, **kwargs):
    _safe_purge(f"produits.{sender.__name__}.delete")


# ---------- INVENTAIRE ----------
def _handle_inventaire_save(sender, instance, created, **kwargs):
    _safe_purge(f"inventaire.{sender.__name__}.save")


def _handle_inventaire_delete(sender, instance, **kwargs):
    _safe_purge(f"inventaire.{sender.__name__}.delete")


# ---------- COMPTABILITE ----------
def _handle_comptabilite_save(sender, instance, created, **kwargs):
    _safe_purge(f"comptabilite.{sender.__name__}.save")


def _handle_comptabilite_delete(sender, instance, **kwargs):
    _safe_purge(f"comptabilite.{sender.__name__}.delete")


# ---------- TRESORERIE ----------
def _handle_tresorerie_save(sender, instance, created, **kwargs):
    _safe_purge(f"tresorerie.{sender.__name__}.save")


def _handle_tresorerie_delete(sender, instance, **kwargs):
    _safe_purge(f"tresorerie.{sender.__name__}.delete")


# ---------- SALES ----------
def _handle_sales_save(sender, instance, created, **kwargs):
    _safe_purge(f"sales.{sender.__name__}.save")


def _handle_sales_delete(sender, instance, **kwargs):
    _safe_purge(f"sales.{sender.__name__}.delete")


# ============================================================
# CONNEXION DES SIGNAUX
# ============================================================
def connect_all_signals():
    """
    Connecte tous les signaux d'invalidation du cache dashboard.
    À appeler UNE SEULE FOIS dans apps.py → ready().
    """
    connected = []

    # ============================================================
    # HR
    # ============================================================
    try:
        from hr.models import (
            Employee, Leave, Attendance, Payroll,
            Recruitment, Candidate, Training, TrainingParticipant,
            PerformanceReview, ExpenseClaim, Document,
            Department, Position,
        )
        hr_models = [
            Employee, Leave, Attendance, Payroll,
            Recruitment, Candidate, Training, TrainingParticipant,
            PerformanceReview, ExpenseClaim, Document,
            Department, Position,
        ]
        for model in hr_models:
            post_save.connect(_handle_hr_save, sender=model, weak=False)
            post_delete.connect(_handle_hr_delete, sender=model, weak=False)
        connected.append(f'hr ({len(hr_models)} modèles)')
    except ImportError as e:
        logger.debug(f"⚠️ hr non disponible : {e}")

    # ============================================================
    # PRODUITS
    # ============================================================
    try:
        from produits.models import (
            Category, Brand, Unit,
            Product, ProductImage, ProductVariant, ProductPricing,
        )
        produits_models = [
            Category, Brand, Unit,
            Product, ProductImage, ProductVariant, ProductPricing,
        ]
        for model in produits_models:
            post_save.connect(_handle_produits_save, sender=model, weak=False)
            post_delete.connect(_handle_produits_delete,
                                sender=model, weak=False)
        connected.append(f'produits ({len(produits_models)} modèles)')
    except ImportError as e:
        logger.debug(f"⚠️ produits non disponible : {e}")

    # ============================================================
    # INVENTAIRE
    # ============================================================
    try:
        from inventaire.models import (
            Warehouse, Location, StockMovement,
            Transfer, TransferItem,
            InventoryCount, InventoryCountItem,
            StockAlert, WarehouseStock, Lot, QualityControl,
        )
        inventaire_models = [
            Warehouse, Location, StockMovement,
            Transfer, TransferItem,
            InventoryCount, InventoryCountItem,
            StockAlert, WarehouseStock, Lot, QualityControl,
        ]
        for model in inventaire_models:
            post_save.connect(_handle_inventaire_save,
                              sender=model, weak=False)
            post_delete.connect(_handle_inventaire_delete,
                                sender=model, weak=False)
        connected.append(f'inventaire ({len(inventaire_models)} modèles)')
    except ImportError as e:
        logger.debug(f"⚠️ inventaire non disponible : {e}")

    # ============================================================
    # COMPTABILITE
    # ============================================================
    try:
        from comptabilite.models import (
            PlanComptable, Journal, Ecriture, LigneEcriture,
            SoldeCompte, Balance, LigneBalance,
            FactureComptable, Reglement,
            IndicateurFinancier, ClotureComptable, AnalyseFinanciere,
        )
        compta_models = [
            PlanComptable, Journal, Ecriture, LigneEcriture,
            SoldeCompte, Balance, LigneBalance,
            FactureComptable, Reglement,
            IndicateurFinancier, ClotureComptable, AnalyseFinanciere,
        ]
        for model in compta_models:
            post_save.connect(_handle_comptabilite_save,
                              sender=model, weak=False)
            post_delete.connect(_handle_comptabilite_delete,
                                sender=model, weak=False)
        connected.append(f'comptabilite ({len(compta_models)} modèles)')
    except ImportError as e:
        logger.debug(f"⚠️ comptabilite non disponible : {e}")

    # ============================================================
    # TRESORERIE
    # ============================================================
    try:
        from tresorerie.models import (
            Caisse, CompteBancaire, MouvementTresorerie,
            Frais, PrevisionTresorerie, RapprochementBancaire,
            TresorerieJournaliere,
        )
        tresorerie_models = [
            Caisse, CompteBancaire, MouvementTresorerie,
            Frais, PrevisionTresorerie, RapprochementBancaire,
            TresorerieJournaliere,
        ]
        for model in tresorerie_models:
            post_save.connect(_handle_tresorerie_save,
                              sender=model, weak=False)
            post_delete.connect(_handle_tresorerie_delete,
                                sender=model, weak=False)
        connected.append(f'tresorerie ({len(tresorerie_models)} modèles)')
    except ImportError as e:
        logger.debug(f"⚠️ tresorerie non disponible : {e}")

    # ============================================================
    # SALES
    # ============================================================
    try:
        from sales.models import (
            Client, Vente, VenteItem,
            Devis, DevisItem, Facture, Paiement,
        )
        sales_models = [
            Client, Vente, VenteItem,
            Devis, DevisItem, Facture, Paiement,
        ]
        for model in sales_models:
            post_save.connect(_handle_sales_save, sender=model, weak=False)
            post_delete.connect(_handle_sales_delete, sender=model, weak=False)
        connected.append(f'sales ({len(sales_models)} modèles)')
    except ImportError as e:
        logger.debug(f"⚠️ sales non disponible : {e}")

    # ============================================================
    # USERS (agences impactent le dashboard)
    # ============================================================
    try:
        from users.models import Agence
        post_save.connect(_handle_sales_save, sender=Agence, weak=False)
        post_delete.connect(_handle_sales_delete, sender=Agence, weak=False)
        connected.append('users.Agence')
    except ImportError as e:
        logger.debug(f"⚠️ users.Agence non disponible : {e}")

    # ============================================================
    # LOG FINAL
    # ============================================================
    if connected:
        logger.info(
            f"✅ Signaux d'invalidation dashboard connectés : "
            f"{', '.join(connected)}"
        )
    else:
        logger.warning(
            "⚠️ Aucun signal d'invalidation dashboard connecté. "
            "Vérifie les noms d'apps dans INSTALLED_APPS."
        )
