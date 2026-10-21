# dashboard/apps.py
from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'
    verbose_name = 'Tableau de bord'

    def ready(self):
        """Connecte les signaux d'invalidation du cache."""
        from . import cache_signals
        cache_signals.connect_all_signals()
