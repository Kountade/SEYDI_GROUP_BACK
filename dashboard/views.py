# dashboard/views.py
"""
Vues du tableau de bord général.
Consolide les statistiques de TOUS les modules de l'application.

✅ CORRECTIONS :
- Logging complet pour debug (logger.info / logger.exception)
- Fallback chart-par-chart si get_all_charts plante
- Message d'erreur réel retourné au frontend
- Cache Django (5 min global, 2 min stats, 1 h RH)
- Parallélisation ThreadPoolExecutor
- Try/except sur chaque module
"""

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor

from django.core.cache import cache

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from users.permissions import HasAgenceAccess
from . import utils
from . import charts


logger = logging.getLogger(__name__)


# ============================================================
# CACHE — Constantes
# ============================================================
CACHE_TTL_GLOBAL = 60 * 5
CACHE_TTL_CHARTS = 60 * 5
CACHE_TTL_STATS = 60 * 2
CACHE_TTL_MODULES = 60 * 5
CACHE_TTL_ALERTES = 60 * 2
CACHE_TTL_RH = 60 * 60


# ============================================================
# HELPERS CACHE
# ============================================================
def _build_cache_key(prefix, agences_ids, periode='mois', extra=''):
    if agences_ids is None:
        agences_key = 'none'
    elif len(agences_ids) == 0:
        agences_key = 'empty'
    else:
        agences_key = ','.join(str(a) for a in sorted(agences_ids))
    return f'dashboard:{prefix}:{agences_key}:{periode}:{extra}'


def _purge_dashboard_cache():
    try:
        cache.delete_pattern('dashboard:*')
    except AttributeError:
        try:
            cache.clear()
        except Exception as e:
            logger.warning(f"Impossible de purger le cache : {e}")
    except Exception as e:
        logger.warning(f"Erreur purge cache : {e}")


# ============================================================
# DASHBOARD VIEWSET
# ============================================================
class DashboardViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    # ---------- HELPERS ----------
    def _get_agences_ids(self, request):
        """Retourne les IDs des agences accessibles (None si accès interdit)."""
        user = request.user
        agence_id = request.query_params.get('agence_id')

        if agence_id:
            try:
                agence_id_int = int(agence_id)
            except (ValueError, TypeError):
                return None
            if not user.peut_acceder_agence(agence_id_int):
                return None
            return [agence_id_int]

        agences_ids = utils.get_agences_ids(user)
        if not agences_ids and not (user.est_pdg() or user.est_drh()):
            return []
        return agences_ids

    def _error_response(self, message, code=status.HTTP_403_FORBIDDEN):
        return Response({'error': message}, status=code)

    def _build_stats_globales(self, agences_ids, periode):
        """8 modules en parallèle."""
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {
                'produits': ex.submit(utils.get_stats_produits, agences_ids),
                'inventaire': ex.submit(utils.get_stats_inventaire, agences_ids),
                'ventes': ex.submit(utils.get_stats_ventes, agences_ids, periode),
                'achats': ex.submit(utils.get_stats_achats, agences_ids, periode),
                'tresorerie': ex.submit(utils.get_stats_tresorerie, agences_ids, periode),
                'comptabilite': ex.submit(utils.get_stats_comptabilite, agences_ids, periode),
                'rh': ex.submit(utils.get_stats_rh),
                'utilisateurs': ex.submit(utils.get_stats_utilisateurs),
            }
            result = {}
            for name, fut in futures.items():
                try:
                    result[name] = fut.result()
                except Exception as e:
                    logger.exception(f"Erreur stats {name}: {e}")
                    result[name] = {}
            return result

    # ============================================================
    # GET /dashboard/global/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='global')
    def global_view(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return self._error_response('Accès non autorisé à cette agence')

        periode = request.query_params.get('periode', 'mois')
        try:
            limit = int(request.query_params.get('limit', 10))
        except (ValueError, TypeError):
            limit = 10

        cache_key = _build_cache_key(
            'global', agences_ids, periode, extra=f'limit:{limit}'
        )
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug(f"global_view cache HIT")
            return Response(cached)

        try:
            logger.info(
                f"global_view CALC: agences={agences_ids}, periode={periode}"
            )

            with ThreadPoolExecutor(max_workers=8) as ex:
                f_stats = ex.submit(
                    self._build_stats_globales, agences_ids, periode)
                f_recettes = ex.submit(
                    utils.get_recettes_par_mois, agences_ids)
                f_depenses = ex.submit(
                    utils.get_depenses_par_mois, agences_ids)
                f_top_produits = ex.submit(
                    utils.get_top_produits_vendus, agences_ids, limit)
                f_top_clients = ex.submit(
                    utils.get_top_clients, agences_ids, limit)
                f_top_fournisseurs = ex.submit(
                    utils.get_top_fournisseurs, agences_ids, limit)
                f_activites = ex.submit(
                    utils.get_dernieres_activites, agences_ids, limit)
                f_alertes = ex.submit(utils.get_alertes_globales, agences_ids)

                # ✅ CHART : calcul avec fallback
                try:
                    charts_data = charts.get_all_charts(agences_ids, periode)
                    logger.info(
                        f"charts.get_all_charts OK: {len(charts_data)} clés")
                except Exception as e:
                    logger.exception(f"ERREUR charts.get_all_charts: {e}")
                    # Fallback : chart-par-chart
                    charts_data = self._compute_all_charts_safe(
                        agences_ids, periode)

                data = {
                    'periode': periode,
                    'agences_ids': agences_ids,
                    'stats_globales': f_stats.result(),
                    'recettes_par_mois': f_recettes.result(),
                    'depenses_par_mois': f_depenses.result(),
                    'charts': charts_data,
                    'top_produits': f_top_produits.result(),
                    'top_clients': f_top_clients.result(),
                    'top_fournisseurs': f_top_fournisseurs.result(),
                    'dernieres_activites': f_activites.result(),
                    'alertes': f_alertes.result(),
                }

            cache.set(cache_key, data, CACHE_TTL_GLOBAL)
            logger.info(f"global_view OK")
            return Response(data)

        except Exception as e:
            logger.exception(f"ERREUR global_view: {e}")
            return Response(
                {'error': f'Erreur lors du calcul du tableau de bord: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _compute_all_charts_safe(self, agences_ids, periode):
        """
        ✅ Fallback : calcule chaque chart individuellement.
        Si un chart plante, on continue avec les autres.
        """
        result = {}

        chart_defs = [
            ('ventes_par_statut',
             lambda: charts.get_repartition_ventes_par_statut(agences_ids)),
            ('produits_par_categorie',
             lambda: charts.get_repartition_produits_par_categorie(agences_ids)),
            ('stock_par_entrepot',
             lambda: charts.get_repartition_stock_par_entrepot(agences_ids)),
            ('clients_par_type',
             lambda: charts.get_repartition_clients_par_type(agences_ids)),
            ('mouvements_par_type',
             lambda: charts.get_repartition_mouvements_par_type(agences_ids)),
            ('transferts_par_statut',
             lambda: charts.get_repartition_transferts_par_statut(agences_ids)),
            ('factures_par_statut',
             lambda: charts.get_repartition_factures_par_statut(agences_ids)),
            ('achats_par_statut',
             lambda: charts.get_repartition_achats_par_statut(agences_ids)),
            ('employes_par_departement',
             lambda: charts.get_repartition_employes_par_departement(agences_ids)),
            ('utilisateurs_par_role',
             lambda: charts.get_repartition_utilisateurs_par_role(agences_ids)),
            ('ca_par_agence', lambda: charts.get_repartition_ca_par_agence(agences_ids)),
            ('depenses_par_categorie', lambda: charts.get_repartition_depenses_par_categorie(
                agences_ids, periode)),
            ('tresorerie', lambda: charts.get_repartition_tresorerie(agences_ids)),
            ('alertes', lambda: charts.get_repartition_alertes(agences_ids)),
            ('rh_par_statut', lambda: charts.get_repartition_rh(agences_ids)),
            ('top_produits_bar', lambda: charts.get_top_produits_bar(agences_ids)),
            ('ventes_vs_achats', lambda: charts.get_ventes_vs_achats_bar(agences_ids)),
            ('evolution_tresorerie',
             lambda: charts.get_evolution_tresorerie(agences_ids)),
        ]

        for name, fn in chart_defs:
            try:
                result[name] = fn()
            except Exception as e:
                logger.exception(f"Erreur chart '{name}': {e}")
                result[name] = {
                    'title': name.replace('_', ' ').title(),
                    'type': 'error',
                    'data': [],
                    'total': 0,
                    'error': str(e),
                }

        return result

    # ============================================================
    # GET /dashboard/stats/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return self._error_response('Accès non autorisé')

        cache_key = _build_cache_key('stats', agences_ids, 'jour')
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            with ThreadPoolExecutor(max_workers=5) as ex:
                f_produits = ex.submit(utils.get_stats_produits, agences_ids)
                f_ventes = ex.submit(
                    utils.get_stats_ventes, agences_ids, 'jour')
                f_achats = ex.submit(
                    utils.get_stats_achats, agences_ids, 'jour')
                f_tresorerie = ex.submit(
                    utils.get_stats_tresorerie, agences_ids, 'jour')
                f_alertes = ex.submit(utils.get_alertes_globales, agences_ids)

                data = {
                    'produits': f_produits.result(),
                    'ventes': f_ventes.result(),
                    'achats': f_achats.result(),
                    'tresorerie': f_tresorerie.result(),
                    'alertes_count': len(f_alertes.result()),
                }
            cache.set(cache_key, data, CACHE_TTL_STATS)
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR stats: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ============================================================
    # GET /dashboard/charts/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='charts')
    def charts(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return self._error_response('Accès non autorisé')

        chart_type = request.query_params.get('type', 'all')
        try:
            nb_mois = int(request.query_params.get('nb_mois', 12))
        except (ValueError, TypeError):
            nb_mois = 12
        periode = request.query_params.get('periode', 'mois')

        cache_key = _build_cache_key(
            'charts', agences_ids, periode, extra=f'{chart_type}:{nb_mois}'
        )
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug(f"charts cache HIT")
            return Response(cached)

        try:
            logger.info(
                f"charts CALC: type={chart_type}, agences={agences_ids}, "
                f"periode={periode}"
            )

            data = self._compute_chart(
                chart_type, agences_ids, periode, nb_mois)

            if data is None:
                return Response(
                    {'error': f'Type de graphique inconnu: {chart_type}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            cache.set(cache_key, data, CACHE_TTL_CHARTS)
            logger.info(f"charts OK")
            return Response(data)

        except Exception as e:
            logger.exception(f"ERREUR charts({chart_type}): {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _compute_chart(self, chart_type, agences_ids, periode, nb_mois):
        """Calcule un chart selon son type."""

        # ===== ALL =====
        if chart_type == 'all':
            try:
                return charts.get_all_charts(agences_ids, periode)
            except Exception as e:
                logger.exception(f"ERREUR get_all_charts: {e}")
                return self._compute_all_charts_safe(agences_ids, periode)

        # ===== TEMPORELS =====
        if chart_type == 'recettes':
            return utils.get_recettes_par_mois(agences_ids, nb_mois)
        if chart_type == 'depenses':
            return utils.get_depenses_par_mois(agences_ids, nb_mois)
        if chart_type == 'evolution_tresorerie':
            return charts.get_evolution_tresorerie(agences_ids)

        # ===== CIRCULAIRES =====
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
            return chart_functions[chart_type](agences_ids)

        if chart_type == 'depenses_par_categorie':
            return charts.get_repartition_depenses_par_categorie(agences_ids, periode)

        # ===== BARRES =====
        if chart_type == 'top_produits_bar':
            return charts.get_top_produits_bar(agences_ids)
        if chart_type == 'ventes_vs_achats':
            return charts.get_ventes_vs_achats_bar(agences_ids)

        # ===== FALLBACK =====
        if chart_type == 'top_produits':
            return utils.get_top_produits_vendus(agences_ids)
        if chart_type == 'top_clients':
            return utils.get_top_clients(agences_ids)
        if chart_type == 'top_fournisseurs':
            return utils.get_top_fournisseurs(agences_ids)

        return None

    # ============================================================
    # GET /dashboard/charts-circulaires/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='charts-circulaires')
    def charts_circulaires(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return self._error_response('Accès non autorisé')

        periode = request.query_params.get('periode', 'mois')
        cache_key = _build_cache_key('charts_circ', agences_ids, periode)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            logger.info(f"charts_circulaires CALC: agences={agences_ids}")
            with ThreadPoolExecutor(max_workers=15) as ex:
                futures = {
                    'ventes_par_statut': ex.submit(charts.get_repartition_ventes_par_statut, agences_ids),
                    'produits_par_categorie': ex.submit(charts.get_repartition_produits_par_categorie, agences_ids),
                    'stock_par_entrepot': ex.submit(charts.get_repartition_stock_par_entrepot, agences_ids),
                    'clients_par_type': ex.submit(charts.get_repartition_clients_par_type, agences_ids),
                    'mouvements_par_type': ex.submit(charts.get_repartition_mouvements_par_type, agences_ids),
                    'transferts_par_statut': ex.submit(charts.get_repartition_transferts_par_statut, agences_ids),
                    'factures_par_statut': ex.submit(charts.get_repartition_factures_par_statut, agences_ids),
                    'achats_par_statut': ex.submit(charts.get_repartition_achats_par_statut, agences_ids),
                    'employes_par_departement': ex.submit(charts.get_repartition_employes_par_departement, agences_ids),
                    'utilisateurs_par_role': ex.submit(charts.get_repartition_utilisateurs_par_role, agences_ids),
                    'ca_par_agence': ex.submit(charts.get_repartition_ca_par_agence, agences_ids),
                    'depenses_par_categorie': ex.submit(charts.get_repartition_depenses_par_categorie, agences_ids, periode),
                    'tresorerie': ex.submit(charts.get_repartition_tresorerie, agences_ids),
                    'alertes': ex.submit(charts.get_repartition_alertes, agences_ids),
                    'rh_par_statut': ex.submit(charts.get_repartition_rh, agences_ids),
                }
                data = {}
                for name, fut in futures.items():
                    try:
                        data[name] = fut.result()
                    except Exception as e:
                        logger.exception(
                            f"Erreur chart circulaire {name}: {e}")
                        data[name] = {
                            'title': name.replace('_', ' ').title(),
                            'type': 'error',
                            'data': [],
                            'total': 0,
                            'error': str(e),
                        }
            cache.set(cache_key, data, CACHE_TTL_CHARTS)
            logger.info(f"charts_circulaires OK: {len(data)} charts")
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR charts_circulaires: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ============================================================
    # GET /dashboard/charts-barres/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='charts-barres')
    def charts_barres(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return self._error_response('Accès non autorisé')

        cache_key = _build_cache_key('charts_bar', agences_ids)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            with ThreadPoolExecutor(max_workers=2) as ex:
                f1 = ex.submit(charts.get_top_produits_bar, agences_ids)
                f2 = ex.submit(charts.get_ventes_vs_achats_bar, agences_ids)
                data = {
                    'top_produits_bar': f1.result(),
                    'ventes_vs_achats': f2.result(),
                }
            cache.set(cache_key, data, CACHE_TTL_CHARTS)
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR charts_barres: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ============================================================
    # GET /dashboard/charts-lignes/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='charts-lignes')
    def charts_lignes(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return self._error_response('Accès non autorisé')

        cache_key = _build_cache_key('charts_line', agences_ids)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            data = {
                'evolution_tresorerie': charts.get_evolution_tresorerie(agences_ids)}
            cache.set(cache_key, data, CACHE_TTL_CHARTS)
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR charts_lignes: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ============================================================
    # GET /dashboard/alertes/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='alertes')
    def alertes(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return self._error_response('Accès non autorisé')

        cache_key = _build_cache_key('alertes', agences_ids)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            alertes = utils.get_alertes_globales(agences_ids)
            data = {'total': len(alertes), 'alertes': alertes}
            cache.set(cache_key, data, CACHE_TTL_ALERTES)
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR alertes: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ============================================================
    # GET /dashboard/modules/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='modules')
    def modules(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return self._error_response('Accès non autorisé')

        periode = request.query_params.get('periode', 'mois')
        cache_key = _build_cache_key('modules', agences_ids, periode)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            with ThreadPoolExecutor(max_workers=8) as ex:
                f_produits = ex.submit(utils.get_stats_produits, agences_ids)
                f_inventaire = ex.submit(
                    utils.get_stats_inventaire, agences_ids)
                f_ventes = ex.submit(
                    utils.get_stats_ventes, agences_ids, periode)
                f_achats = ex.submit(
                    utils.get_stats_achats, agences_ids, periode)
                f_tresorerie = ex.submit(
                    utils.get_stats_tresorerie, agences_ids, periode)
                f_comptabilite = ex.submit(
                    utils.get_stats_comptabilite, agences_ids, periode)
                f_rh = ex.submit(utils.get_stats_rh)
                f_users = ex.submit(utils.get_stats_utilisateurs)

                produits = f_produits.result()
                inventaire = f_inventaire.result()
                ventes = f_ventes.result()
                achats = f_achats.result()
                tresorerie = f_tresorerie.result()
                comptabilite = f_comptabilite.result()
                rh = f_rh.result()
                utilisateurs = f_users.result()

            data = {
                'produits': {
                    'total': produits.get('total', 0),
                    'actifs': produits.get('actifs', 0),
                    'stock_faible': produits.get('stock_faible', 0),
                    'rupture': produits.get('rupture', 0),
                    'icone': 'Package', 'route': '/produits',
                },
                'inventaire': {
                    'entrepots': inventaire.get('entrepots', 0),
                    'transferts_en_attente': inventaire.get('transferts_en_attente', 0),
                    'alertes': inventaire.get('alertes_actives', 0),
                    'lots_expirant': inventaire.get('lots_expirant_bientot', 0),
                    'icone': 'Warehouse', 'route': '/inventaire',
                },
                'ventes': {
                    'total': ventes.get('ventes_total', 0),
                    'ca': float(ventes.get('ca_total', 0) or 0),
                    'en_attente': ventes.get('ventes_en_attente', 0),
                    'impayes': float(ventes.get('impayes', 0) or 0),
                    'icone': 'ShoppingCart', 'route': '/ventes',
                },
                'achats': {
                    'total': achats.get('commandes_total', 0),
                    'montant': float(achats.get('montant_total_achats', 0) or 0),
                    'en_attente': achats.get('commandes_en_attente', 0),
                    'en_retard': achats.get('commandes_en_retard', 0),
                    'icone': 'Truck', 'route': '/achats',
                },
                'tresorerie': {
                    'solde': float(tresorerie.get('solde_global', 0) or 0),
                    'caisses': tresorerie.get('nb_caisses', 0),
                    'comptes': tresorerie.get('nb_comptes', 0),
                    'alertes': tresorerie.get('caisses_sous_seuil', 0),
                    'icone': 'Wallet', 'route': '/tresorerie',
                },
                'comptabilite': {
                    'ecritures': comptabilite.get('ecritures_total', 0),
                    'factures_clients': comptabilite.get('factures_clients', 0),
                    'factures_fournisseurs': comptabilite.get('factures_fournisseurs', 0),
                    'impayes': float(comptabilite.get('montant_clients_impayes', 0) or 0),
                    'icone': 'Calculator', 'route': '/comptabilite',
                },
                'rh': {
                    'employes': rh.get('employes_total', 0),
                    'actifs': rh.get('employes_actifs', 0),
                    'conges_en_attente': rh.get('conges_en_attente', 0),
                    'paie_mois': float(rh.get('paie_mois', 0) or 0),
                    'icone': 'Users', 'route': '/rh',
                },
                'utilisateurs': {
                    'total': utilisateurs.get('utilisateurs_total', 0),
                    'actifs': utilisateurs.get('utilisateurs_actifs', 0),
                    'agences': utilisateurs.get('agences_total', 0),
                    'icone': 'UserCog', 'route': '/utilisateurs',
                },
            }
            cache.set(cache_key, data, CACHE_TTL_MODULES)
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR modules: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ============================================================
    # GET /dashboard/export/
    # ============================================================
    @action(detail=False, methods=['get'], url_path='export')
    def export(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return self._error_response('Accès non autorisé')

        periode = request.query_params.get('periode', 'mois')
        try:
            limit = int(request.query_params.get('limit', 50))
        except (ValueError, TypeError):
            limit = 50

        try:
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_global = ex.submit(
                    self._compute_global_for_export, agences_ids, periode, limit
                )
                f_charts = ex.submit(charts.get_all_charts,
                                     agences_ids, periode)
                data = {
                    **f_global.result(),
                    'charts': f_charts.result(),
                }
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR export: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _compute_global_for_export(self, agences_ids, periode, limit):
        return {
            'periode': periode,
            'agences_ids': agences_ids,
            'stats_globales': self._build_stats_globales(agences_ids, periode),
            'recettes_par_mois': utils.get_recettes_par_mois(agences_ids),
            'depenses_par_mois': utils.get_depenses_par_mois(agences_ids),
            'top_produits': utils.get_top_produits_vendus(agences_ids, limit),
            'top_clients': utils.get_top_clients(agences_ids, limit),
            'top_fournisseurs': utils.get_top_fournisseurs(agences_ids, limit),
            'dernieres_activites': utils.get_dernieres_activites(agences_ids, limit),
            'alertes': utils.get_alertes_globales(agences_ids),
        }


# ============================================================
# STATISTIQUES VIEWSET
# ============================================================
class StatistiquesViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def _get_agences_ids(self, request):
        user = request.user
        agence_id = request.query_params.get('agence_id')
        if agence_id:
            try:
                agence_id_int = int(agence_id)
            except (ValueError, TypeError):
                return None
            if not user.peut_acceder_agence(agence_id_int):
                return None
            return [agence_id_int]
        agences_ids = utils.get_agences_ids(user)
        if not agences_ids and not (user.est_pdg() or user.est_drh()):
            return []
        return agences_ids

    def _cached_stats(self, request, prefix, ttl, fn):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        periode = request.query_params.get('periode', 'mois')
        cache_key = _build_cache_key(prefix, agences_ids, periode)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        try:
            data = fn(agences_ids, periode)
            cache.set(cache_key, data, ttl)
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR {prefix}: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=['get'], url_path='produits')
    def produits(self, request):
        return self._cached_stats(
            request, 'stat_produits', CACHE_TTL_STATS,
            lambda a, p: utils.get_stats_produits(a),
        )

    @action(detail=False, methods=['get'], url_path='inventaire')
    def inventaire(self, request):
        return self._cached_stats(
            request, 'stat_inventaire', CACHE_TTL_STATS,
            lambda a, p: utils.get_stats_inventaire(a),
        )

    @action(detail=False, methods=['get'], url_path='ventes')
    def ventes(self, request):
        return self._cached_stats(
            request, 'stat_ventes', CACHE_TTL_STATS,
            lambda a, p: utils.get_stats_ventes(a, p),
        )

    @action(detail=False, methods=['get'], url_path='achats')
    def achats(self, request):
        return self._cached_stats(
            request, 'stat_achats', CACHE_TTL_STATS,
            lambda a, p: utils.get_stats_achats(a, p),
        )

    @action(detail=False, methods=['get'], url_path='tresorerie')
    def tresorerie(self, request):
        return self._cached_stats(
            request, 'stat_tresorerie', CACHE_TTL_STATS,
            lambda a, p: utils.get_stats_tresorerie(a, p),
        )

    @action(detail=False, methods=['get'], url_path='comptabilite')
    def comptabilite(self, request):
        return self._cached_stats(
            request, 'stat_comptabilite', CACHE_TTL_STATS,
            lambda a, p: utils.get_stats_comptabilite(a, p),
        )

    @action(detail=False, methods=['get'], url_path='rh')
    def rh(self, request):
        cache_key = 'dashboard:stat_rh:global'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        try:
            data = utils.get_stats_rh()
            cache.set(cache_key, data, CACHE_TTL_RH)
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR rh: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=['get'], url_path='utilisateurs')
    def utilisateurs(self, request):
        cache_key = 'dashboard:stat_users:global'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        try:
            data = utils.get_stats_utilisateurs()
            cache.set(cache_key, data, CACHE_TTL_RH)
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR utilisateurs: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ============================================================
# ANALYSES VIEWSET
# ============================================================
class AnalysesViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def _get_agences_ids(self, request):
        user = request.user
        agence_id = request.query_params.get('agence_id')
        if agence_id:
            try:
                agence_id_int = int(agence_id)
            except (ValueError, TypeError):
                return None
            if not user.peut_acceder_agence(agence_id_int):
                return None
            return [agence_id_int]
        agences_ids = utils.get_agences_ids(user)
        if not agences_ids and not (user.est_pdg() or user.est_drh()):
            return []
        return agences_ids

    def _cached(self, request, prefix, ttl, fn):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)
        try:
            limit = int(request.query_params.get('limit', 10))
        except (ValueError, TypeError):
            limit = 10
        cache_key = _build_cache_key(
            prefix, agences_ids, extra=f'limit:{limit}')
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        try:
            data = fn(agences_ids, limit)
            cache.set(cache_key, data, ttl)
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR {prefix}: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=['get'], url_path='top-produits')
    def top_produits(self, request):
        return self._cached(
            request, 'top_produits', CACHE_TTL_STATS,
            lambda a, l: utils.get_top_produits_vendus(a, l),
        )

    @action(detail=False, methods=['get'], url_path='top-clients')
    def top_clients(self, request):
        return self._cached(
            request, 'top_clients', CACHE_TTL_STATS,
            lambda a, l: utils.get_top_clients(a, l),
        )

    @action(detail=False, methods=['get'], url_path='top-fournisseurs')
    def top_fournisseurs(self, request):
        return self._cached(
            request, 'top_fournisseurs', CACHE_TTL_STATS,
            lambda a, l: utils.get_top_fournisseurs(a, l),
        )

    @action(detail=False, methods=['get'], url_path='activites')
    def activites(self, request):
        return self._cached(
            request, 'activites', CACHE_TTL_STATS,
            lambda a, l: utils.get_dernieres_activites(a, l),
        )

    @action(detail=False, methods=['get'], url_path='comparaison')
    def comparaison(self, request):
        agences_ids = self._get_agences_ids(request)
        if agences_ids is None:
            return Response({'error': 'Accès non autorisé'}, status=403)

        cache_key = _build_cache_key('comparaison', agences_ids)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_recettes = ex.submit(
                    utils.get_recettes_par_mois, agences_ids)
                f_depenses = ex.submit(
                    utils.get_depenses_par_mois, agences_ids)
                data = {
                    'recettes': f_recettes.result(),
                    'depenses': f_depenses.result(),
                }
            cache.set(cache_key, data, CACHE_TTL_STATS)
            return Response(data)
        except Exception as e:
            logger.exception(f"ERREUR comparaison: {e}")
            return Response(
                {'error': f'Erreur: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
