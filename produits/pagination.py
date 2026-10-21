# products/pagination.py

from rest_framework.pagination import PageNumberPagination


class ProductPagination(PageNumberPagination):
    """Pagination standard pour les produits."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class OptimizedPagination(PageNumberPagination):
    """Pagination pour les listes volumineuses (prices, mouvements, etc.)."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


class SmallPagination(PageNumberPagination):
    """Pagination pour les catégories, marques, unités (petites listes)."""
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100
