# comptabilite/apps.py
from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ComptabiliteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "comptabilite"
    verbose_name = "Comptabilité et Finance"

    def ready(self):
        """✅ Active les signaux au démarrage de l'application"""
        import comptabilite.signals  # noqa
        print("✅ Signaux comptabilité activés !")

        # ✅ CRÉATION AUTOMATIQUE DES JOURNAUX
        from django.db.models.signals import post_save
        from users.models import Agence
        from django.dispatch import receiver

        # Connecter le signal pour la création d'agences
        @receiver(post_save, sender=Agence)
        def creer_journaux_agence(sender, instance, created, **kwargs):
            """Crée automatiquement les journaux lors de la création d'une agence"""
            if created:
                self._creer_journaux_pour_agence(instance)

        # Créer les journaux pour les agences existantes au démarrage
        self._creer_journaux_pour_agences_existantes()

    def _creer_journaux_pour_agence(self, agence):
        """
        Crée les journaux pour une agence spécifique
        """
        try:
            from comptabilite.models import Journal

            journaux = [
                {'code': 'ACH', 'nom': 'Journal des achats',
                    'type_journal': 'achats'},
                {'code': 'VEN', 'nom': 'Journal des ventes',
                    'type_journal': 'ventes'},
                {'code': 'BAN', 'nom': 'Journal de banque', 'type_journal': 'banque'},
                {'code': 'CAI', 'nom': 'Journal de caisse', 'type_journal': 'caisse'},
                {'code': 'OD', 'nom': 'Opérations diverses', 'type_journal': 'od'},
                {'code': 'PAI', 'nom': 'Journal des paies', 'type_journal': 'paie'},
                {'code': 'INV', 'nom': 'Journal d\'inventaire',
                    'type_journal': 'inventaire'},
                {'code': 'IMM', 'nom': 'Journal des immobilisations',
                    'type_journal': 'immobilisations'},
            ]

            created_count = 0
            for journal_data in journaux:
                # Vérifier si le journal existe déjà
                if not Journal.objects.filter(
                    code=journal_data['code'],
                    agence=agence
                ).exists():
                    Journal.objects.create(
                        agence=agence,
                        code=journal_data['code'],
                        nom=journal_data['nom'],
                        type_journal=journal_data['type_journal'],
                        is_active=True,
                        # OD comme journal par défaut
                        is_default=(journal_data['code'] == 'OD')
                    )
                    created_count += 1

            if created_count > 0:
                print(
                    f"✅ {created_count} journaux créés pour l'agence {agence.nom}")

        except Exception as e:
            print(f"⚠️ Erreur création journaux pour {agence.nom}: {e}")

    def _creer_journaux_pour_agences_existantes(self):
        """
        Crée les journaux pour toutes les agences existantes
        """
        try:
            from users.models import Agence
            from comptabilite.models import Journal

            # Vérifier si la table Journal existe
            from django.db import connection
            if not connection.introspection.table_names():
                return

            for agence in Agence.objects.filter(est_active=True):
                self._creer_journaux_pour_agence(agence)

        except Exception as e:
            print(f"⚠️ Erreur création journaux pour agences existantes: {e}")
