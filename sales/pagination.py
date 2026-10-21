# sales/pagination.py
"""
Pagination pour l'application Sales.

✅ Une classe par modèle, avec des paramètres adaptés à la volumétrie :

| Modèle    | Volumétrie attendue | page_size | max_page_size |
|-----------|---------------------|-----------|---------------|
| Client    | ~5 000 clients      | 30        | 200           |
| Vente     | 10 000+ ventes      | 50        | 200           |
| Devis     | ~1 000 devis        | 30        | 200           |
| Facture   | 10 000+ factures    | 30        | 200           |
| Paiement  | 10 000+ paiements   | 50        | 500           |
"""

from rest_framework.pagination import PageNumberPagination


class ClientPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 200


class VentePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class DevisPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 200


class FacturePagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 200


class PaiementPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500
