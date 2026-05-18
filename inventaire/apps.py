# inventaire/apps.py

from django.apps import AppConfig


class InventaireConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventaire'

    def ready(self):
        import inventaire.signals  # noqa