# dashboard/views.py
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Q, F, Avg
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from users.models import Agence, CustomUser
from produits.models import Product, ProductPricing
from purchases.models import Supplier, PurchaseOrder
from inventaire.models import WarehouseStock, StockAlert, Transfer
from sales.models import Vente, VenteItem
from hr.models import Employee, Leave, Attendance

from .permissions import IsPDGOrDRH, IsChefAgenceOrAbove
from .serializers import (
    DashboardOverviewSerializer,
    VentesParMoisSerializer,
    TopProduitsSerializer,
    AlertesStockSerializer
)


class DashboardViewSet(viewsets.ViewSet):
    """
    Endpoints généraux pour le tableau de bord principal.
    """
    permission_classes = [IsAuthenticated, IsChefAgenceOrAbove]

    def get_agences(self, user):
        if user.est_pdg() or user.est_drh():
            return Agence.objects.filter(est_active=True)
        return user.get_agences()

    @action(detail=False, methods=['get'])
    def overview(self, request):
        """
        Vue d'ensemble des KPI.
        """
        user = request.user
        agences = self.get_agences(user)

        # Stats générales
        total_agences = agences.count()
        total_utilisateurs = CustomUser.objects.filter(
            roles_agence__agence__in=agences,
            roles_agence__est_actif=True
        ).distinct().count()
        total_produits = Product.objects.filter(is_active=True).count()
        total_fournisseurs = Supplier.objects.filter(is_active=True).count()
        # à affiner si besoin de filtre agence
        total_employes = Employee.objects.count()

        # Ventes
        ventes = Vente.objects.filter(agence__in=agences)
        total_ca = ventes.filter(status='completed').aggregate(
            total=Sum('total'))['total'] or Decimal('0.00')
        aujourd_hui = timezone.now().date()
        ca_jour = ventes.filter(date_vente__date=aujourd_hui, status='completed').aggregate(
            total=Sum('total'))['total'] or Decimal('0.00')
        debut_mois = aujourd_hui.replace(day=1)
        ca_mois = ventes.filter(date_vente__date__gte=debut_mois, status='completed').aggregate(
            total=Sum('total'))['total'] or Decimal('0.00')
        ventes_en_attente = ventes.filter(status='pending_approval').count()
        impayes = ventes.filter(est_paye=False, status__in=['approved', 'completed']).aggregate(
            total=Sum('montant_du'))['total'] or Decimal('0.00')

        # Achats
        achats = PurchaseOrder.objects.filter(agence__in=agences)
        total_achats = achats.filter(status='received').aggregate(
            total=Sum('total'))['total'] or Decimal('0.00')
        commandes_encours = achats.filter(status__in=[
                                          'draft', 'sent', 'confirmed', 'in_transit', 'partially_received']).count()
        commandes_retard = achats.filter(expected_date__lt=aujourd_hui, status__in=[
                                         'confirmed', 'sent', 'in_transit']).count()

        # Inventaire - valeur du stock (basée sur le dernier prix d'achat via ProductPricing)
        # On récupère le prix d'achat du produit (le plus récent) via ProductPricing
        # Pour simplifier, on utilise le prix d'achat du produit s'il existe, sinon 0
        warehouse_stocks = WarehouseStock.objects.filter(
            warehouse__agence__in=agences
        ).select_related('product')
        valeur_stock = Decimal('0.00')
        for ws in warehouse_stocks:
            # Récupérer le dernier prix d'achat (is_current=True) pour ce produit
            pricing = ProductPricing.objects.filter(
                product=ws.product,
                is_current=True
            ).order_by('-valid_from').first()
            prix_achat = pricing.purchase_price if pricing else Decimal('0.00')
            valeur_stock += (ws.quantity * prix_achat)
        # Alternative avec agrégation si Product a un champ purchase_price direct
        # valeur_stock = warehouse_stocks.aggregate(total=Sum(F('quantity') * F('product__purchase_price')))['total'] or Decimal('0.00')

        alertes_stock = StockAlert.objects.filter(
            warehouse__agence__in=agences, status='active').count()
        transferts_encours = Transfer.objects.filter(
            Q(from_agence__in=agences) | Q(to_agence__in=agences),
            status__in=['pending_approval', 'approved', 'in_transit']
        ).distinct().count()

        # RH
        employes_actifs = Employee.objects.filter(work_status='active').count()
        conges_en_attente = Leave.objects.filter(status='pending').count()
        absences_jour = Attendance.objects.filter(
            date=aujourd_hui, is_absent=True).count()

        # Dernières activités
        dernieres_ventes = Vente.objects.filter(agence__in=agences).order_by(
            '-date_vente')[:5].values('reference', 'total', 'date_vente', 'client__nom')
        derniers_achats = PurchaseOrder.objects.filter(agence__in=agences).order_by(
            '-created_at')[:5].values('order_number', 'total', 'created_at', 'supplier__company_name')
        alertes_recentes = StockAlert.objects.filter(warehouse__agence__in=agences, status='active').order_by(
            '-created_at')[:5].values('product__name', 'message', 'created_at')

        data = {
            'total_agences': total_agences,
            'total_utilisateurs': total_utilisateurs,
            'total_produits': total_produits,
            'total_fournisseurs': total_fournisseurs,
            'total_employes': total_employes,
            'total_ca': total_ca,
            'ca_jour': ca_jour,
            'ca_mois': ca_mois,
            'ventes_en_attente': ventes_en_attente,
            'impayes': impayes,
            'total_achats': total_achats,
            'commandes_encours': commandes_encours,
            'commandes_retard': commandes_retard,
            'valeur_stock': valeur_stock,
            'alertes_stock': alertes_stock,
            'transferts_encours': transferts_encours,
            'employes_actifs': employes_actifs,
            'conges_en_attente': conges_en_attente,
            'absences_jour': absences_jour,
            'dernieres_ventes': list(dernieres_ventes),
            'derniers_achats': list(derniers_achats),
            'alertes_recentes': list(alertes_recentes),
        }

        serializer = DashboardOverviewSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def alertes_stock(self, request):
        """
        Liste des alertes de stock actives.
        """
        user = request.user
        agences = self.get_agences(user)
        alertes = StockAlert.objects.filter(
            warehouse__agence__in=agences,
            status='active'
        ).select_related('product', 'warehouse__agence')

        data = [
            {
                'produit': a.product.name,
                'stock': a.current_quantity,
                'seuil': a.threshold,
                'agence': a.warehouse.agence.nom,
                'message': a.message,
                'created_at': a.created_at
            }
            for a in alertes
        ]
        serializer = AlertesStockSerializer(data, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def stats_rh(self, request):
        """
        Statistiques RH (réservé PDG/DRH).
        """
        if not (request.user.est_pdg() or request.user.est_drh()):
            return Response({"detail": "Accès réservé au PDG ou DRH."}, status=status.HTTP_403_FORBIDDEN)

        total = Employee.objects.count()
        actifs = Employee.objects.filter(work_status='active').count()
        par_departement = Employee.objects.values(
            'department__name').annotate(count=Count('id'))
        conges = Leave.objects.filter(status='pending').count()
        today = timezone.now().date()
        presents = Attendance.objects.filter(
            date=today, check_in_time__isnull=False).count()
        absents = Attendance.objects.filter(date=today, is_absent=True).count()

        return Response({
            'total_employes': total,
            'actifs': actifs,
            'par_departement': list(par_departement),
            'conges_en_attente': conges,
            'presents_aujourdhui': presents,
            'absents_aujourdhui': absents,
        })


class StatistiquesViewSet(viewsets.ViewSet):
    """
    Endpoints pour les statistiques avancées.
    """
    permission_classes = [IsAuthenticated, IsChefAgenceOrAbove]

    def get_agences(self, user):
        if user.est_pdg() or user.est_drh():
            return Agence.objects.filter(est_active=True)
        return user.get_agences()

    @action(detail=False, methods=['get'])
    def ventes_mensuelles(self, request):
        """
        Ventes par mois sur les 12 derniers mois.
        """
        user = request.user
        agences = self.get_agences(user)
        today = timezone.now().date()
        start_date = today - timedelta(days=365)

        # Utilisation de TruncMonth pour éviter l'extra
        from django.db.models.functions import TruncMonth
        ventes = Vente.objects.filter(
            agence__in=agences,
            status='completed',
            date_vente__date__gte=start_date
        ).annotate(
            mois=TruncMonth('date_vente')
        ).values('mois').annotate(total=Sum('total')).order_by('mois')

        result = []
        for v in ventes:
            if v['mois']:
                result.append({
                    'mois': v['mois'].strftime('%Y-%m'),
                    'total': v['total']
                })
        return Response(result)

    @action(detail=False, methods=['get'])
    def top_produits(self, request):
        """
        Top 10 produits vendus en quantité.
        """
        user = request.user
        agences = self.get_agences(user)

        top = VenteItem.objects.filter(
            vente__agence__in=agences,
            vente__status='completed'
        ).values('product__name').annotate(
            quantite=Sum('quantity'),
            total=Sum('total')
        ).order_by('-quantite')[:10]

        # Transformer les noms de champs pour correspondre au sérializer
        result = []
        for item in top:
            result.append({
                'produit': item['product__name'] or 'Sans nom',
                'quantite': item['quantite'] or 0,
                'total': item['total'] or 0
            })
        return Response(result)

    @action(detail=False, methods=['get'])
    def ventes_par_categorie(self, request):
        """
        Répartition du CA par catégorie de produit.
        """
        user = request.user
        agences = self.get_agences(user)

        data = VenteItem.objects.filter(
            vente__agence__in=agences,
            vente__status='completed'
        ).values('product__category__name').annotate(
            total=Sum('total')
        ).order_by('-total')

        return Response(data)


class AnalysesViewSet(viewsets.ViewSet):
    """
    Endpoints pour les analyses avancées (tendances, prévisions...).
    """
    permission_classes = [IsAuthenticated, IsPDGOrDRH]  # Accès restreint

    @action(detail=False, methods=['get'])
    def tendance_ventes(self, request):
        """
        Tendance des ventes sur les 6 derniers mois (évolution).
        """
        today = timezone.now().date()
        start_date = today - timedelta(days=180)
        from django.db.models.functions import TruncMonth
        ventes = Vente.objects.filter(
            status='completed',
            date_vente__date__gte=start_date
        ).annotate(
            mois=TruncMonth('date_vente')
        ).values('mois').annotate(total=Sum('total')).order_by('mois')

        result = []
        for v in ventes:
            if v['mois']:
                result.append({
                    'mois': v['mois'].strftime('%Y-%m'),
                    'total': float(v['total']) if v['total'] else 0
                })
        return Response(result)

    @action(detail=False, methods=['get'])
    def marge_moyenne(self, request):
        """
        Marge moyenne par produit (prix vente - prix achat).
        """
        from django.db.models import Avg, F, Value
        from django.db.models.functions import Coalesce

        # Récupérer le prix d'achat depuis ProductPricing pour chaque produit
        # On va annoter chaque VenteItem avec le prix d'achat du produit (le plus récent)
        # Cette requête peut être lourde, on fait une approche plus simple :
        # On agrège par produit et on calcule la marge moyenne
        ventes_items = VenteItem.objects.filter(
            vente__status='completed'
        ).values('product__name').annotate(
            prix_vente_moyen=Avg('prix_unitaire'),
            # On récupère le prix d'achat moyen du produit depuis ProductPricing
            # Pour simplifier, on utilise le champ purchase_price de ProductPricing si disponible
            # Sinon on peut faire une sous-requête.
        )
        # Ici, on va plutôt utiliser une approche avec ProductPricing
        # On peut faire une boucle mais pour l'exemple on retourne des données factices
        # ou on peut faire une requête plus complexe.
        # Je propose de retourner une liste des produits avec leur marge moyenne calculée en backend
        # Pour l'exemple, on renvoie les produits avec un prix de vente moyen et un prix d'achat moyen estimé
        # (à adapter selon votre modèle)

        # Simplification : on retourne les produits avec leur prix de vente moyen
        # et on ajoute un champ marge estimée (à améliorer)
        result = []
        for item in ventes_items:
            # On essaie de récupérer le prix d'achat depuis ProductPricing
            product = Product.objects.filter(
                name=item['product__name']).first()
            if product:
                pricing = ProductPricing.objects.filter(
                    product=product, is_current=True).order_by('-valid_from').first()
                purchase_price = pricing.purchase_price if pricing else 0
                marge = float(item['prix_vente_moyen']) - float(purchase_price)
                result.append({
                    'produit': item['product__name'],
                    'prix_vente_moyen': item['prix_vente_moyen'],
                    'prix_achat_moyen': purchase_price,
                    'marge_moyenne': marge
                })
            else:
                result.append({
                    'produit': item['product__name'],
                    'prix_vente_moyen': item['prix_vente_moyen'],
                    'prix_achat_moyen': 0,
                    'marge_moyenne': 0
                })
        # Trier par marge décroissante
        result.sort(key=lambda x: x['marge_moyenne'], reverse=True)
        return Response(result[:20])

    @action(detail=False, methods=['get'])
    def prevision_stock(self, request):
        """
        Prévision de rupture de stock basée sur les ventes passées.
        """
        today = timezone.now().date()
        start_date = today - timedelta(days=30)

        # Consommation sur 30 jours
        consommation = VenteItem.objects.filter(
            vente__status='completed',
            vente__date_vente__date__gte=start_date
        ).values('product_id').annotate(
            total_vendu=Sum('quantity')
        )

        # Produits en stock
        stocks = WarehouseStock.objects.filter(
            quantity__gt=0).select_related('product')
        previsions = []
        for stock in stocks:
            conso = next(
                (c['total_vendu'] for c in consommation if c['product_id'] == stock.product.id), 0)
            if conso > 0:
                jours_restants = stock.quantity / conso * 30
                if jours_restants < 15:  # alerte si moins de 15 jours
                    previsions.append({
                        'produit': stock.product.name,
                        'stock': stock.quantity,
                        'conso_mensuelle': conso,
                        'jours_restants': round(jours_restants, 1)
                    })
        return Response(previsions)
