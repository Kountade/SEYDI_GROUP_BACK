# comptabilite/pagination.py
"""
Pagination pour l'application Comptabilité / Finance.

✅ Une classe par modèle, avec des paramètres adaptés à la volumétrie réelle :

| Modèle              | Volumétrie attendue | page_size | max_page_size |
|---------------------|---------------------|-----------|---------------|
| PlanComptable       | ~500 comptes        | 50        | 200           |
| Journal             | ~20 journaux        | 30        | 100           |
| Ecriture            | 10 000+ écritures   | 100       | 500           |
| LigneEcriture       | 100 000+ lignes     | 100       | 1000          |
| Balance             | ~100 balances       | 30        | 100           |
| LigneBalance        | 50 000+ lignes      | 100       | 500           |
| FactureComptable    | 10 000+ factures    | 100       | 500           |
| Reglement           | 10 000+ règlements  | 100       | 500           |
| IndicateurFinancier | ~50 indicateurs     | 30        | 100           |
| ClotureComptable    | ~30 clôtures        | 30        | 100           |
| AnalyseFinanciere   | ~100 analyses       | 30        | 100           |

✅ Compatible avec le frontend :
- `?page=N` pour la page
- `?page_size=N` pour personnaliser la taille (borné par max_page_size)
- Réponse : {count, next, previous, results}
"""

from rest_framework.pagination import PageNumberPagination


# ============================================================
# PLAN COMPTABLE
# ============================================================
class PlanComptablePagination(PageNumberPagination):
    """Pagination pour le plan comptable (~500 comptes)."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


# ============================================================
# JOURNAL
# ============================================================
class JournalPagination(PageNumberPagination):
    """Pagination pour les journaux (~20 journaux)."""
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================
# ÉCRITURE (grosse volumétrie)
# ============================================================
class EcriturePagination(PageNumberPagination):
    """Pagination pour les écritures (10 000+)."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


# ============================================================
# LIGNE ÉCRITURE (très grosse volumétrie)
# ============================================================
class LigneEcriturePagination(PageNumberPagination):
    """Pagination pour les lignes d'écriture (100 000+)."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000


# ============================================================
# BALANCE
# ============================================================
class BalancePagination(PageNumberPagination):
    """Pagination pour les balances (~100)."""
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================
# LIGNE BALANCE
# ============================================================
class LigneBalancePagination(PageNumberPagination):
    """Pagination pour les lignes de balance (50 000+)."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


# ============================================================
# FACTURE COMPTABLE (grosse volumétrie)
# ============================================================
class FactureComptablePagination(PageNumberPagination):
    """Pagination pour les factures comptables (10 000+)."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


# ============================================================
# RÈGLEMENT (grosse volumétrie)
# ============================================================
class ReglementPagination(PageNumberPagination):
    """Pagination pour les règlements (10 000+)."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


# ============================================================
# INDICATEUR FINANCIER
# ============================================================
class IndicateurPagination(PageNumberPagination):
    """Pagination pour les indicateurs financiers (~50)."""
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================
# CLÔTURE COMPTABLE
# ============================================================
class CloturePagination(PageNumberPagination):
    """Pagination pour les clôtures comptables (~30)."""
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================
# ANALYSE FINANCIÈRE
# ============================================================
class AnalysePagination(PageNumberPagination):
    """Pagination pour les analyses financières (~100)."""
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100
