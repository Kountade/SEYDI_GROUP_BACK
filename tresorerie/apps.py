from django.apps import AppConfig

class TresorerieConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tresorerie'
    verbose_name = 'Gestion de Trésorerie'

    def ready(self):
        import tresorerie.signals