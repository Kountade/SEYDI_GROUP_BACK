from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.db import connection

from users.models import Agence, CustomUser
from produits.models import Product
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

# Essayer d'importer ProductPricing si disponible
try:
    from produits.models import ProductPricing
    HAS_PRICING = True
except ImportError:
    HAS_PRICING = False


class DashboardViewSet(viewsets.ViewSet):
    """
    Vue d'ensemble du tableau de bord (KPI généraux, alertes).
    """
    permission_classes = [IsAuthenticated, IsChefAgenceOrAbove]

    def get_agences(self, user):
        if user.est_pdg() or user.est_drh():
            return Agence.objects.filter(est_active=True)
        return user.get_agences()

    @action(detail=False, methods=['get'])
    def overview(self, request):
        """Vue d'ensemble des KPI."""
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

        # Inventaire - calcul de la valeur du stock
        warehouse_stocks = WarehouseStock.objects.filter(
            warehouse__agence__in=agences
        )
        valeur_stock = Decimal('0.00')

        if HAS_PRICING:
            # Utiliser ProductPricing pour obtenir les prix d'achat
            for ws in warehouse_stocks:
                try:
                    pricing = ProductPricing.objects.filter(
                        product=ws.product,
                        warehouse=ws.warehouse,
                        is_current=True
                    ).first()
                    if pricing:
                        valeur_stock += (ws.quantity or 0) * \
                            (pricing.purchase_price or 0)
                except:
                    pass
        else:
            # Sinon, on peut utiliser un prix par défaut (par exemple 0)
            # Ou on peut essayer d'utiliser un champ 'price' si présent dans Product
            # On vérifie si Product a un champ 'price' (par défaut non)
            if hasattr(Product, 'price'):
                for ws in warehouse_stocks:
                    valeur_stock += (ws.quantity or 0) * \
                        (ws.product.price or 0)
            else:
                # En dernier recours, on prend le premier prix de vente disponible
                # Mais pour l'instant on met 0
                valeur_stock = Decimal('0.00')

        alertes_stock = StockAlert.objects.filter(
            warehouse__agence__in=agences, status='active'
        ).count()

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
        """Liste des alertes de stock actives."""
        user = request.user
        agences = self.get_agences(user)
        alertes = StockAlert.objects.filter(
            warehouse__agence__in=agences,
            status='active'
        ).select_related('product', 'warehouse')

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
        """Statistiques RH (réservé PDG/DRH)."""
        if not (request.user.est_pdg() or request.user.est_drh()):
            return Response({"detail": "Accès réservé."}, status=status.HTTP_403_FORBIDDEN)

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
    Statistiques détaillées : ventes mensuelles, top produits, etc.
    """
    permission_classes = [IsAuthenticated, IsChefAgenceOrAbove]

    def get_agences(self, user):
        if user.est_pdg() or user.est_drh():
            return Agence.objects.filter(est_active=True)
        return user.get_agences()

    @action(detail=False, methods=['get'])
    def ventes_mensuelles(self, request):
        """Ventes par mois sur 12 mois."""
        user = request.user
        agences = self.get_agences(user)
        today = timezone.now().date()
        start_date = today - timedelta(days=365)

        # Version compatible SQLite
        # On récupère les ventes et on les groupe par mois en Python (car SQLite n'a pas DATE_TRUNC)
        ventes = Vente.objects.filter(
            agence__in=agences,
            status='completed',
            date_vente__date__gte=start_date
        ).values('date_vente__year', 'date_vente__month').annotate(
            total=Sum('total')
        ).order_by('date_vente__year', 'date_vente__month')

        result = []
        for v in ventes:
            year = v['date_vente__year']
            month = v['date_vente__month']
            mois = f"{year}-{month:02d}"
            result.append({
                'mois': mois,
                'total': v['total']
            })

        # Si aucune donnée, on renvoie un tableau vide
        serializer = VentesParMoisSerializer(result, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def top_produits(self, request):
        """Top 10 produits en quantité vendue."""
        user = request.user
        agences = self.get_agences(user)

        top = VenteItem.objects.filter(
            vente__agence__in=agences,
            vente__status='completed'
        ).values('product__name').annotate(
            quantite=Sum('quantity'),
            total=Sum('total')
        ).order_by('-quantite')[:10]

        # Adapter aux champs attendus par le frontend
        result = [
            {'produit': item['product__name'] or 'Produit inconnu',
             'quantite': item['quantite'],
             'total': item['total']}
            for item in top
        ]
        return Response(result)

    @action(detail=False, methods=['get'])
    def ventes_par_categorie(self, request):
        """CA par catégorie."""
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
    Analyses avancées : tendances, prévisions, marges.
    """
    permission_classes = [IsAuthenticated, IsPDGOrDRH]  # Accès restreint

    @action(detail=False, methods=['get'])
    def tendance_ventes(self, request):
        """Évolution des ventes sur 6 mois (compatible SQLite)."""
        today = timezone.now().date()
        start_date = today - timedelta(days=180)
        ventes = Vente.objects.filter(
            status='completed',
            date_vente__date__gte=start_date
        ).values('date_vente__year', 'date_vente__month').annotate(
            total=Sum('total')
        ).order_by('date_vente__year', 'date_vente__month')

        result = []
        for v in ventes:
            year = v['date_vente__year']
            month = v['date_vente__month']
            mois = f"{year}-{month:02d}"
            result.append({
                'mois': mois,
                'total': float(v['total'])
            })
        return Response(result)

    @action(detail=False, methods=['get'])
    def marge_moyenne(self, request):
        """Marge moyenne par produit."""
        # On vérifie si le champ purchase_price existe dans Product
        if not hasattr(Product, 'purchase_price'):
            return Response({"error": "Le champ purchase_price n'existe pas dans le modèle Product."}, status=status.HTTP_400_BAD_REQUEST)

        from django.db.models import Avg, F
        ventes_items = VenteItem.objects.filter(
            vente__status='completed'
        ).values('product__name').annotate(
            marge_moyenne=Avg(F('prix_unitaire') -
                              F('product__purchase_price'))
        ).order_by('-marge_moyenne')[:20]
        return Response(ventes_items)

    @action(detail=False, methods=['get'])
    def prevision_stock(self, request):
        """Prévision de rupture de stock."""
        from django.db.models import Sum
        today = timezone.now().date()
        start_date = today - timedelta(days=30)

        consommation = VenteItem.objects.filter(
            vente__status='completed',
            vente__date_vente__date__gte=start_date
        ).values('product_id').annotate(
            total_vendu=Sum('quantity')
        )

        stocks = WarehouseStock.objects.filter(quantity__gt=0)
        previsions = []
        for stock in stocks:
            conso = next(
                (c['total_vendu'] for c in consommation if c['product_id'] == stock.product.id), 0)
            if conso > 0:
                jours_restants = stock.quantity / conso * 30
                if jours_restants < 15:
                    previsions.append({
                        'produit': stock.product.name,
                        'stock': stock.quantity,
                        'conso_mensuelle': conso,
                        'jours_restants': round(jours_restants, 1)
                    })
        return Response(previsions)
