# dashboard/views.py
"""
Vues du tableau de bord général.
Consolide les statistiques de TOUS les modules de l'application.
Utilise des ViewSets pour être compatible avec le router Django REST.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from users.permissions import HasAgenceAccess
from . import utils
from . import charts  # ✅ NOUVEAU : module de graphiques


class DashboardViewSet(viewsets.ViewSet):
    """
    ViewSet principal du tableau de bord.

    Endpoints disponibles :
    - GET /dashboard/global/     → Toutes les statistiques + graphiques consolidés
    - GET /dashboard/stats/      → Statistiques rapides
    - GET /dashboard/charts/     → Données pour graphiques
    - GET /dashboard/alertes/    → Alertes de tous les modules
    - GET /dashboard/modules/    → Statut de chaque module
    - GET /dashboard/export/     → Export complet JSON
    """
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def _get_agences_ids(self, request):
        """Retourne les IDs des agences accessibles à l'utilisateur."""
        user = request.user
        agence_id = request.query_params.get('agence_id')

        if agence_id:
            if not user.peut_acceder_agence(int(agence_id)):
                return None
            return [int(agence_id)]

        agences_ids = utils.get_agences_ids(user)
        if not agences_ids and not (user.est_pdg() or user.est_drh()):
            return []
        return agences_ids

    # ============================================================
    # GET /dashboard/global/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='global')
    def global_view(self, request):
        """
        Vue complète du tableau de bord.
        Retourne TOUTES les statistiques ET TOUS les graphiques
        de TOUS les modules.

        Query params:
        - periode: 'jour', 'semaine', 'mois', 'trimestre', 'annee'
        - agence_id: ID d'une agence spécifique (optionnel)
        """
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response(
                {'error': 'Accès non autorisé à cette agence'},
                status=status.HTTP_403_FORBIDDEN
            )

        periode = request.query_params.get('periode', 'mois')

        data = {
            'periode': periode,
            'agences_ids': agences_ids,

            # ===== STATS GLOBALES PAR MODULE =====
            'stats_globales': {
                'produits': utils.get_stats_produits(agences_ids),
                'inventaire': utils.get_stats_inventaire(agences_ids),
                'ventes': utils.get_stats_ventes(agences_ids, periode),
                'achats': utils.get_stats_achats(agences_ids, periode),
                'tresorerie': utils.get_stats_tresorerie(agences_ids, periode),
                'comptabilite': utils.get_stats_comptabilite(agences_ids, periode),
                'rh': utils.get_stats_rh(),
                'utilisateurs': utils.get_stats_utilisateurs(),
            },

            # ===== DONNÉES GRAPHIQUES TEMPORELLES =====
            'recettes_par_mois': utils.get_recettes_par_mois(agences_ids),
            'depenses_par_mois': utils.get_depenses_par_mois(agences_ids),

            # ===== ✅ TOUS LES GRAPHIQUES CIRCULAIRES, BARRES ET LIGNES =====
            'charts': charts.get_all_charts(agences_ids, periode),

            # ===== TOP / CLASSEMENTS =====
            'top_produits': utils.get_top_produits_vendus(agences_ids),
            'top_clients': utils.get_top_clients(agences_ids),
            'top_fournisseurs': utils.get_top_fournisseurs(agences_ids),

            # ===== ACTIVITÉS RÉCENTES =====
            'dernieres_activites': utils.get_dernieres_activites(agences_ids),

            # ===== ALERTES =====
            'alertes': utils.get_alertes_globales(agences_ids),
        }

        return Response(data)

    # ============================================================
    # GET /dashboard/stats/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        """
        Statistiques rapides (sans les données lourdes).
        """
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response(
                {'error': 'Accès non autorisé'},
                status=status.HTTP_403_FORBIDDEN
            )

        return Response({
            'produits': utils.get_stats_produits(agences_ids),
            'ventes': utils.get_stats_ventes(agences_ids, 'jour'),
            'achats': utils.get_stats_achats(agences_ids, 'jour'),
            'tresorerie': utils.get_stats_tresorerie(agences_ids, 'jour'),
            'alertes_count': len(utils.get_alertes_globales(agences_ids)),
        })

    # ============================================================
    # GET /dashboard/charts/?type=recettes&nb_mois=12
    # ============================================================
    @action(detail=False, methods=['get'], url_path='charts')
    def charts(self, request):
        """
        Données pour les graphiques.

        Query params:
        - type: 
            TEMPOREL: 'recettes', 'depenses', 'evolution_tresorerie'
            CIRCULAIRE: 'ventes_par_statut', 'produits_par_categorie',
                        'stock_par_entrepot', 'clients_par_type',
                        'mouvements_par_type', 'transferts_par_statut',
                        'factures_par_statut', 'achats_par_statut',
                        'employes_par_departement', 'utilisateurs_par_role',
                        'ca_par_agence', 'depenses_par_categorie',
                        'tresorerie', 'alertes', 'rh_par_statut'
            BARRES: 'top_produits_bar', 'ventes_vs_achats'
            TOUS: 'all' (défaut)
        - nb_mois: nombre de mois (défaut: 12)
        - periode: 'jour', 'semaine', 'mois', 'trimestre', 'annee'
        """
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response(
                {'error': 'Accès non autorisé'},
                status=status.HTTP_403_FORBIDDEN
            )

        chart_type = request.query_params.get('type', 'all')
        nb_mois = int(request.query_params.get('nb_mois', 12))
        periode = request.query_params.get('periode', 'mois')

        # ✅ TOUS les graphiques en un seul appel
        if chart_type == 'all':
            return Response(charts.get_all_charts(agences_ids, periode))

        # ===== Graphiques temporels =====
        if chart_type == 'recettes':
            return Response(utils.get_recettes_par_mois(agences_ids, nb_mois))
        if chart_type == 'depenses':
            return Response(utils.get_depenses_par_mois(agences_ids, nb_mois))
        if chart_type == 'evolution_tresorerie':
            return Response(charts.get_evolution_tresorerie(agences_ids))

        # ===== Graphiques circulaires =====
        chart_functions = {
            'ventes_par_statut': charts.get_repartition_ventes_par_statut,
            'produits_par_categorie': charts.get_repartition_produits_par_categorie,
            'stock_par_entrepot': charts.get_repartition_stock_par_entrepot,
            'clients_par_type': charts.get_repartition_clients_par_type,
            'mouvements_par_type': charts.get_repartition_mouvements_par_type,
            'transferts_par_statut': charts.get_repartition_transferts_par_statut,
            'factures_par_statut': charts.get_repartition_factures_par_statut,
            'achats_par_statut': charts.get_repartition_achats_par_statut,
            'employes_par_departement': charts.get_repartition_employes_par_departement,
            'utilisateurs_par_role': charts.get_repartition_utilisateurs_par_role,
            'ca_par_agence': charts.get_repartition_ca_par_agence,
            'tresorerie': charts.get_repartition_tresorerie,
            'alertes': charts.get_repartition_alertes,
            'rh_par_statut': charts.get_repartition_rh,
        }

        if chart_type in chart_functions:
            return Response(chart_functions[chart_type](agences_ids))

        # Graphiques avec période
        if chart_type == 'depenses_par_categorie':
            return Response(
                charts.get_repartition_depenses_par_categorie(
                    agences_ids, periode)
            )

        # ===== Graphiques à barres =====
        if chart_type == 'top_produits_bar':
            return Response(charts.get_top_produits_bar(agences_ids))
        if chart_type == 'ventes_vs_achats':
            return Response(charts.get_ventes_vs_achats_bar(agences_ids))

        # ===== Fallback : anciens types =====
        if chart_type == 'top_produits':
            return Response(utils.get_top_produits_vendus(agences_ids))
        if chart_type == 'top_clients':
            return Response(utils.get_top_clients(agences_ids))
        if chart_type == 'top_fournisseurs':
            return Response(utils.get_top_fournisseurs(agences_ids))

        return Response(
            {'error': f'Type de graphique inconnu: {chart_type}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ============================================================
    # GET /dashboard/charts-circulaires/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='charts-circulaires')
    def charts_circulaires(self, request):
        """
        Retourne UNIQUEMENT les graphiques circulaires (Pie / Doughnut).
        Idéal pour un rendu rapide sans les autres données.
        """
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response(
                {'error': 'Accès non autorisé'},
                status=status.HTTP_403_FORBIDDEN
            )

        periode = request.query_params.get('periode', 'mois')

        return Response({
            'ventes_par_statut': charts.get_repartition_ventes_par_statut(agences_ids),
            'produits_par_categorie': charts.get_repartition_produits_par_categorie(agences_ids),
            'stock_par_entrepot': charts.get_repartition_stock_par_entrepot(agences_ids),
            'clients_par_type': charts.get_repartition_clients_par_type(agences_ids),
            'mouvements_par_type': charts.get_repartition_mouvements_par_type(agences_ids),
            'transferts_par_statut': charts.get_repartition_transferts_par_statut(agences_ids),
            'factures_par_statut': charts.get_repartition_factures_par_statut(agences_ids),
            'achats_par_statut': charts.get_repartition_achats_par_statut(agences_ids),
            'employes_par_departement': charts.get_repartition_employes_par_departement(agences_ids),
            'utilisateurs_par_role': charts.get_repartition_utilisateurs_par_role(),
            'ca_par_agence': charts.get_repartition_ca_par_agence(agences_ids),
            'depenses_par_categorie': charts.get_repartition_depenses_par_categorie(agences_ids, periode),
            'tresorerie': charts.get_repartition_tresorerie(agences_ids),
            'alertes': charts.get_repartition_alertes(agences_ids),
            'rh_par_statut': charts.get_repartition_rh(agences_ids),
        })

    # ============================================================
    # GET /dashboard/charts-barres/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='charts-barres')
    def charts_barres(self, request):
        """
        Retourne UNIQUEMENT les graphiques à barres.
        """
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response(
                {'error': 'Accès non autorisé'},
                status=status.HTTP_403_FORBIDDEN
            )

        return Response({
            'top_produits_bar': charts.get_top_produits_bar(agences_ids),
            'ventes_vs_achats': charts.get_ventes_vs_achats_bar(agences_ids),
        })

    # ============================================================
    # GET /dashboard/charts-lignes/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='charts-lignes')
    def charts_lignes(self, request):
        """
        Retourne UNIQUEMENT les graphiques en ligne.
        """
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response(
                {'error': 'Accès non autorisé'},
                status=status.HTTP_403_FORBIDDEN
            )

        return Response({
            'evolution_tresorerie': charts.get_evolution_tresorerie(agences_ids),
        })

    # ============================================================
    # GET /dashboard/alertes/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='alertes')
    def alertes(self, request):
        """Alertes uniquement."""
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response(
                {'error': 'Accès non autorisé'},
                status=status.HTTP_403_FORBIDDEN
            )

        alertes = utils.get_alertes_globales(agences_ids)
        return Response({
            'total': len(alertes),
            'alertes': alertes,
        })

    # ============================================================
    # GET /dashboard/modules/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='modules')
    def modules(self, request):
        """
        Statut de chaque module pour affichage rapide.
        """
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response(
                {'error': 'Accès non autorisé'},
                status=status.HTTP_403_FORBIDDEN
            )

        periode = request.query_params.get('periode', 'mois')

        produits = utils.get_stats_produits(agences_ids)
        inventaire = utils.get_stats_inventaire(agences_ids)
        ventes = utils.get_stats_ventes(agences_ids, periode)
        achats = utils.get_stats_achats(agences_ids, periode)
        tresorerie = utils.get_stats_tresorerie(agences_ids, periode)
        comptabilite = utils.get_stats_comptabilite(agences_ids, periode)
        rh = utils.get_stats_rh()
        utilisateurs = utils.get_stats_utilisateurs()

        return Response({
            'produits': {
                'total': produits['total'],
                'actifs': produits['actifs'],
                'stock_faible': produits['stock_faible'],
                'rupture': produits['rupture'],
                'icone': 'Package',
                'route': '/produits',
            },
            'inventaire': {
                'entrepots': inventaire['entrepots'],
                'transferts_en_attente': inventaire['transferts_en_attente'],
                'alertes': inventaire['alertes_actives'],
                'lots_expirant': inventaire['lots_expirant_bientot'],
                'icone': 'Warehouse',
                'route': '/inventaire',
            },
            'ventes': {
                'total': ventes['ventes_total'],
                'ca': float(ventes['ca_total']),
                'en_attente': ventes['ventes_en_attente'],
                'impayes': float(ventes['impayes']),
                'icone': 'ShoppingCart',
                'route': '/ventes',
            },
            'achats': {
                'total': achats['commandes_total'],
                'montant': float(achats['montant_total_achats']),
                'en_attente': achats['commandes_en_attente'],
                'en_retard': achats['commandes_en_retard'],
                'icone': 'Truck',
                'route': '/achats',
            },
            'tresorerie': {
                'solde': float(tresorerie['solde_global']),
                'caisses': tresorerie['nb_caisses'],
                'comptes': tresorerie['nb_comptes'],
                'alertes': tresorerie['caisses_sous_seuil'],
                'icone': 'Wallet',
                'route': '/tresorerie',
            },
            'comptabilite': {
                'ecritures': comptabilite['ecritures_total'],
                'factures_clients': comptabilite['factures_clients'],
                'factures_fournisseurs': comptabilite['factures_fournisseurs'],
                'impayes': float(comptabilite['montant_clients_impayes']),
                'icone': 'Calculator',
                'route': '/comptabilite',
            },
            'rh': {
                'employes': rh['employes_total'],
                'actifs': rh['employes_actifs'],
                'conges_en_attente': rh['conges_en_attente'],
                'paie_mois': float(rh['paie_mois']),
                'icone': 'Users',
                'route': '/rh',
            },
            'utilisateurs': {
                'total': utilisateurs['utilisateurs_total'],
                'actifs': utilisateurs['utilisateurs_actifs'],
                'agences': utilisateurs['agences_total'],
                'icone': 'UserCog',
                'route': '/utilisateurs',
            },
        })

    # ============================================================
    # GET /dashboard/export/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='export')
    def export(self, request):
        """Export complet du dashboard."""
        return self.global_view(request)


class StatistiquesViewSet(viewsets.ViewSet):
    """
    ViewSet pour les statistiques par module.

    Endpoints :
    - GET /statistiques/produits/
    - GET /statistiques/inventaire/
    - GET /statistiques/ventes/
    - GET /statistiques/achats/
    - GET /statistiques/tresorerie/
    - GET /statistiques/comptabilite/
    - GET /statistiques/rh/
    - GET /statistiques/utilisateurs/
    """
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def _get_agences_ids(self, request):
        user = request.user
        agence_id = request.query_params.get('agence_id')

        if agence_id:
            if not user.peut_acceder_agence(int(agence_id)):
                return None
            return [int(agence_id)]

        agences_ids = utils.get_agences_ids(user)
        if not agences_ids and not (user.est_pdg() or user.est_drh()):
            return []
        return agences_ids

    @action(detail=False, methods=['get'], url_path='produits')
    def produits(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        return Response(utils.get_stats_produits(agences_ids))

    @action(detail=False, methods=['get'], url_path='inventaire')
    def inventaire(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        return Response(utils.get_stats_inventaire(agences_ids))

    @action(detail=False, methods=['get'], url_path='ventes')
    def ventes(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        periode = request.query_params.get('periode', 'mois')
        return Response(utils.get_stats_ventes(agences_ids, periode))

    @action(detail=False, methods=['get'], url_path='achats')
    def achats(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        periode = request.query_params.get('periode', 'mois')
        return Response(utils.get_stats_achats(agences_ids, periode))

    @action(detail=False, methods=['get'], url_path='tresorerie')
    def tresorerie(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        periode = request.query_params.get('periode', 'mois')
        return Response(utils.get_stats_tresorerie(agences_ids, periode))

    @action(detail=False, methods=['get'], url_path='comptabilite')
    def comptabilite(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        periode = request.query_params.get('periode', 'mois')
        return Response(utils.get_stats_comptabilite(agences_ids, periode))

    @action(detail=False, methods=['get'], url_path='rh')
    def rh(self, request):
        return Response(utils.get_stats_rh())

    @action(detail=False, methods=['get'], url_path='utilisateurs')
    def utilisateurs(self, request):
        return Response(utils.get_stats_utilisateurs())


class AnalysesViewSet(viewsets.ViewSet):
    """
    ViewSet pour les analyses et rapports.

    Endpoints :
    - GET /analyses/top-produits/
    - GET /analyses/top-clients/
    - GET /analyses/top-fournisseurs/
    - GET /analyses/activites/
    - GET /analyses/comparaison/
    """
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def _get_agences_ids(self, request):
        user = request.user
        agence_id = request.query_params.get('agence_id')

        if agence_id:
            if not user.peut_acceder_agence(int(agence_id)):
                return None
            return [int(agence_id)]

        agences_ids = utils.get_agences_ids(user)
        if not agences_ids and not (user.est_pdg() or user.est_drh()):
            return []
        return agences_ids

    @action(detail=False, methods=['get'], url_path='top-produits')
    def top_produits(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        limit = int(request.query_params.get('limit', 10))
        return Response(utils.get_top_produits_vendus(agences_ids, limit))

    @action(detail=False, methods=['get'], url_path='top-clients')
    def top_clients(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        limit = int(request.query_params.get('limit', 10))
        return Response(utils.get_top_clients(agences_ids, limit))

    @action(detail=False, methods=['get'], url_path='top-fournisseurs')
    def top_fournisseurs(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        limit = int(request.query_params.get('limit', 10))
        return Response(utils.get_top_fournisseurs(agences_ids, limit))

    @action(detail=False, methods=['get'], url_path='activites')
    def activites(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        limit = int(request.query_params.get('limit', 10))
        return Response(utils.get_dernieres_activites(agences_ids, limit))

    @action(detail=False, methods=['get'], url_path='comparaison')
    def comparaison(self, request):
        """Comparaison CA vs Dépenses sur la période."""
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)

        recettes = utils.get_recettes_par_mois(agences_ids)
        depenses = utils.get_depenses_par_mois(agences_ids)

        return Response({
            'recettes': recettes,
            'depenses': depenses,
        })
