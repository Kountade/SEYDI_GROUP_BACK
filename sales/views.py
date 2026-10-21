# sales/views.py

import logging
from decimal import Decimal
from io import BytesIO

from django.db import transaction
from django.db.models import Sum, Q, Count, Exists, OuterRef, Prefetch
from django.core.cache import cache
from django.http import HttpResponse
from django.utils import timezone

from rest_framework import viewsets, generics, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from django_filters.rest_framework import DjangoFilterBackend

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

from .models import *
from .serializers import *
from .pagination import (
    ClientPagination, VentePagination, DevisPagination,
    FacturePagination, PaiementPagination,
)
from users.permissions import HasAgenceAccess, IsPDG, IsChefAgence
from inventaire.models import (
    WarehouseStock, StockMovement, Warehouse, Lot, get_default_warehouse
)
from produits.models import Product, ProductPricing


logger = logging.getLogger(__name__)


# ============================================================
# CACHE
# ============================================================
def _purge_sales_cache():
    """Purge le cache sales après mutation."""
    try:
        cache.delete_pattern('sales_stats_*')
        cache.delete_pattern('sales_dashboard_*')
    except Exception:
        cache.clear()


# ============================================================
# CLIENT
# ============================================================
class ClientViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    pagination_class = ClientPagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['client_type', 'est_revendeur', 'is_active']
    search_fields = ['nom', 'prenom', 'email', 'telephone', 'raison_sociale']
    ordering_fields = ['nom', 'created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return ClientListSerializer
        if self.action == 'retrieve':
            return ClientDetailSerializer
        return ClientSerializer

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Client.objects.none()

        base = Client.objects.all()

        if not (user.est_pdg() or user.est_drh()):
            agences = user.get_agences()
            if not agences.exists():
                return Client.objects.none()
            agences_ids = list(agences.values_list('id', flat=True))
            # ✅ Exists(Subquery) → plus rapide que Q(ventes__…)
            base = base.filter(
                Q(created_by=user) |
                Exists(Vente.objects.filter(
                    client=OuterRef('pk'),
                    agence_id__in=agences_ids,
                ))
            )

        if self.action == 'list':
            # ✅ Agrégats SQL → 0 N+1
            base = base.annotate(
                ventes_count=Count('ventes', distinct=True),
                total_achats=Sum('ventes__total'),
                total_paye=Sum('ventes__montant_paye'),
            )

        if self.action == 'retrieve':
            base = base.select_related('created_by').annotate(
                total_ventes=Count('ventes', distinct=True),
                total_factures=Count('ventes__factures', distinct=True),
                total_achats=Sum('ventes__total'),
                total_paye=Sum('ventes__montant_paye'),
            ).prefetch_related(
                Prefetch(
                    'ventes',
                    queryset=Vente.objects
                    .select_related('agence', 'client', 'vendeur')
                    .order_by('-date_vente'),
                    to_attr='_ventes_prefetched',
                ),
            )

        return base.distinct()

    def perform_create(self, serializer):
        user = self.request.user
        agence_principale = user.get_agence_principale()
        client = serializer.save(created_by=user)
        if agence_principale and not client.ventes.exists():
            Vente.objects.create(
                agence=agence_principale,
                client=client,
                vendeur=user,
                total=0,
                montant_du=0,
                status='completed',
                notes="Création automatique pour association client-agence",
            )
        _purge_sales_cache()

    def perform_update(self, serializer):
        serializer.save()
        _purge_sales_cache()

    def perform_destroy(self, instance):
        instance.delete()
        _purge_sales_cache()


# ============================================================
# VENTE
# ============================================================
class VenteViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des ventes - SANS TVA.
    Inclut la fonctionnalité de paiement automatique.
    """
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    pagination_class = VentePagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'agence', 'type_vente', 'est_paye']
    search_fields = ['reference', 'client__nom']
    ordering_fields = ['date_vente', 'total']

    def get_serializer_class(self):
        if self.action == 'list':
            return VenteListSerializer
        if self.action == 'retrieve':
            return VenteDetailSerializer
        return VenteCreateSerializer

    def get_queryset(self):
        user = self.request.user
        base = Vente.objects.select_related(
            'agence', 'client', 'vendeur', 'approved_by'
        )

        if user.est_pdg() or user.est_drh():
            pass
        elif user.est_chef_agence():
            base = base.filter(agence__in=user.get_agences())
        else:
            base = base.filter(vendeur=user)

        if self.action == 'retrieve':
            base = base.prefetch_related(
                Prefetch(
                    'items',
                    queryset=VenteItem.objects
                    .select_related('product', 'variant', 'lot')
                    .order_by('id'),
                ),
                Prefetch(
                    'factures',
                    queryset=Facture.objects
                    .select_related('client', 'agence', 'cree_par'),
                ),
            )

        return base

    def perform_create(self, serializer):
        serializer.save()
        _purge_sales_cache()

    # ============================================================
    # ACTION : VENTES SANS FACTURE
    # ============================================================
    @action(detail=False, methods=['get'])
    def sans_facture(self, request):
        qs = self.get_queryset().filter(
            status__in=['approved', 'completed']
        ).filter(agence__isnull=False)
        # ✅ Exists(Subquery) au lieu de "id__in=liste_de_tous_les_ids"
        qs = qs.filter(~Exists(Facture.objects.filter(vente=OuterRef('pk'))))

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = VenteListSerializer(
                page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = VenteListSerializer(
            qs, many=True, context={'request': request})
        return Response(serializer.data)

    # ============================================================
    # ACTION : PRIX DES PRODUITS
    # ============================================================
    @action(detail=False, methods=['get'])
    def product_prices(self, request):
        product_id = request.query_params.get('product_id')
        warehouse_id = request.query_params.get('warehouse_id')

        if not product_id or not warehouse_id:
            return Response(
                {'error': 'product_id et warehouse_id sont requis'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            pricing = ProductPricing.objects.get(
                product_id=product_id,
                warehouse_id=warehouse_id,
                is_current=True,
            )
            return Response({
                'sale_price': float(pricing.sale_price),
                'wholesale_price': (
                    float(pricing.wholesale_price)
                    if pricing.wholesale_price else None
                ),
                'purchase_price': float(pricing.purchase_price),
                'has_wholesale': (
                    pricing.wholesale_price is not None
                    and pricing.wholesale_price > 0
                ),
            })
        except ProductPricing.DoesNotExist:
            return Response(
                {'error': 'Aucun prix trouvé pour ce produit dans cet entrepôt'},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ============================================================
    # ACTION : SOUMETTRE
    # ============================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def submit(self, request, pk=None):
        vente = self.get_object()

        if vente.status != 'draft':
            return Response(
                {'error': f'Seule une vente en brouillon peut être soumise. Statut actuel: {vente.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        warehouse = (
            vente.agence.warehouses.filter(is_default=True).first()
            or vente.agence.warehouses.filter(is_active=True).first()
            or get_default_warehouse(vente.agence)
        )
        if not warehouse:
            return Response(
                {'error': f"Aucun entrepôt configuré pour l'agence {vente.agence.nom}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        stock_verification = {}
        for item in vente.items.all().select_related('product', 'variant'):
            key = f"{item.product.id}_{item.variant.id if item.variant else 'None'}"
            if key not in stock_verification:
                stock_verification[key] = {
                    'product': item.product,
                    'variant': item.variant,
                    'total_quantity': 0,
                }
            stock_verification[key]['total_quantity'] += item.quantity

        stock_insuffisant = []
        for key, group in stock_verification.items():
            stock = WarehouseStock.objects.filter(
                product=group['product'],
                warehouse=warehouse,
                variant=group['variant'],
            ).first()

            if not stock:
                stock_insuffisant.append({
                    'product': group['product'].name,
                    'variant': group['variant'].name if group['variant'] else 'Sans variante',
                    'message': 'Stock non configuré dans cet entrepôt',
                })
            elif stock.quantity < group['total_quantity']:
                stock_insuffisant.append({
                    'product': group['product'].name,
                    'variant': group['variant'].name if group['variant'] else 'Sans variante',
                    'disponible': stock.quantity,
                    'demande': group['total_quantity'],
                    'manquant': group['total_quantity'] - stock.quantity,
                })

        if stock_insuffisant:
            return Response(
                {'error': 'Stock insuffisant pour soumettre la vente',
                 'details': stock_insuffisant},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vente.status = 'pending_approval'
        vente.save(update_fields=['status', 'updated_at'])
        _purge_sales_cache()

        return Response({
            'success': True,
            'message': 'Vente soumise avec succès',
            'data': VenteDetailSerializer(vente).data,
        })

    # ============================================================
    # ACTION : APPROUVER
    # ============================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        vente = self.get_object()
        user = request.user

        if not (user.est_chef_agence() or user.est_pdg()):
            return Response(
                {'error': "Seul le chef d'agence ou le PDG peut approuver une vente"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not user.est_pdg() and not user.peut_acceder_agence(vente.agence.id):
            return Response(
                {'error': "Vous n'avez pas accès à cette agence"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if vente.status != 'pending_approval':
            return Response(
                {'error': f'Seule une vente en attente peut être approuvée. Statut actuel: {vente.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        warehouse = get_default_warehouse(vente.agence)
        if not warehouse:
            return Response(
                {'error': f"Aucun entrepôt configuré pour l'agence {vente.agence.nom}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        items_to_process = list(
            vente.items.select_related('product', 'variant', 'lot').all()
        )
        stock_insuffisant = []
        mouvements = []

        for item in items_to_process:
            quantity_needed = item.quantity

            warehouse_stock = WarehouseStock.objects.filter(
                product=item.product,
                warehouse=warehouse,
                variant=item.variant,
            ).first()

            if not warehouse_stock or warehouse_stock.quantity < quantity_needed:
                stock_disponible = (
                    warehouse_stock.quantity if warehouse_stock else 0
                )
                stock_insuffisant.append({
                    'product': item.product.name,
                    'variant': item.variant.name if item.variant else 'Sans variante',
                    'disponible': stock_disponible,
                    'demande': quantity_needed,
                    'manquant': quantity_needed - stock_disponible,
                })
                continue

            remaining = quantity_needed

            lots_disponibles = Lot.objects.filter(
                product=item.product,
                warehouse=warehouse,
                quantity__gt=0,
                quality_status='good',
            ).order_by('expiry_date')

            if lots_disponibles.exists():
                for lot in lots_disponibles:
                    if remaining <= 0:
                        break
                    take = min(lot.quantity, remaining)
                    lot.quantity -= take
                    lot.save(update_fields=['quantity', 'updated_at'])
                    remaining -= take
                    mouvements.append({
                        'product': item.product,
                        'variant': item.variant,
                        'quantity': take,
                        'lot': lot,
                        'unit_price': item.prix_unitaire,
                        'source_type': 'lot',
                    })

            if remaining > 0:
                warehouse_stock.quantity -= remaining
                warehouse_stock.save(
                    update_fields=['quantity', 'last_updated'])
                mouvements.append({
                    'product': item.product,
                    'variant': item.variant,
                    'quantity': remaining,
                    'lot': None,
                    'unit_price': item.prix_unitaire,
                    'source_type': 'warehouse_stock',
                })

            item.warehouse_source = warehouse
            item.stock_preleve = True
            item.save(update_fields=[
                'warehouse_source', 'stock_preleve'
            ])

        if stock_insuffisant:
            return Response(
                {'error': 'Stock insuffisant pour approuver la vente',
                 'details': stock_insuffisant},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for mov in mouvements:
            note = (
                f"Vente {vente.reference} - Lot {mov['lot'].lot_number}"
                if mov['source_type'] == 'lot'
                else f"Vente {vente.reference} - Prélèvement depuis stock (sans lot)"
            )
            StockMovement.objects.create(
                movement_type='out',
                reference_type='sale',
                reference_id=vente.id,
                product=mov['product'],
                variant=mov['variant'],
                quantity=mov['quantity'],
                from_warehouse=warehouse,
                unit_price=mov['unit_price'],
                notes=note,
                created_by=user,
            )

        # ✅ Recalcul du stock global produit en SQL (1 requête au lieu de N)
        product_ids = list({item.product_id for item in items_to_process})
        totals = (
            WarehouseStock.objects
            .filter(product_id__in=product_ids)
            .values('product_id')
            .annotate(total=Sum('quantity'))
        )
        for row in totals:
            Product.objects.filter(id=row['product_id']).update(
                stock_quantity=row['total']
            )

        vente.status = 'approved'
        vente.approved_by = user
        vente.date_approbation = timezone.now()
        vente.save(update_fields=[
            'status', 'approved_by', 'date_approbation', 'updated_at'
        ])

        facture_creee = False
        facture_reference = None

        facture_existante = Facture.objects.filter(vente=vente).first()
        if not facture_existante:
            try:
                date_echeance = timezone.now().date() + timezone.timedelta(days=30)
                facture = Facture.objects.create(
                    vente=vente,
                    client=vente.client,
                    agence=vente.agence,
                    cree_par=user,
                    type_facture='finale',
                    date_facture=timezone.now().date(),
                    date_echeance=date_echeance,
                    conditions_paiement='Paiement à 30 jours',
                    notes=f"Facture générée automatiquement à l'approbation de la vente {vente.reference}",
                    sous_total=vente.sous_total,
                    total_ttc=vente.total,
                    montant_paye=vente.montant_paye,
                    montant_restant=vente.total - vente.montant_paye,
                )
                facture_creee = True
                facture_reference = facture.reference
                logger.info(
                    f"✅ Facture {facture.reference} créée pour la vente {vente.reference}")
            except Exception as e:
                logger.error(
                    f"❌ Erreur création facture: {str(e)}")
        else:
            facture_creee = True
            facture_reference = facture_existante.reference

        _purge_sales_cache()

        return Response({
            'success': True,
            'message': 'Vente approuvée avec succès',
            'data': VenteDetailSerializer(vente).data,
            'facture': {
                'creee': facture_creee,
                'reference': facture_reference,
            },
        })

    # ============================================================
    # ACTION : REJETER
    # ============================================================
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        vente = self.get_object()

        if vente.status != 'pending_approval':
            return Response(
                {'error': f'Seule une vente en attente peut être rejetée. Statut actuel: {vente.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        motif = request.data.get('motif')
        if not motif:
            return Response(
                {'error': 'Un motif de rejet est requis'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vente.status = 'rejected'
        vente.motif_rejet = motif
        vente.save(update_fields=['status', 'motif_rejet', 'updated_at'])
        _purge_sales_cache()

        return Response({
            'success': True,
            'message': 'Vente rejetée',
            'data': VenteDetailSerializer(vente).data,
        })

    # ============================================================
    # ACTION : COMPLÉTER
    # ============================================================
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        vente = self.get_object()

        if vente.status != 'approved':
            return Response(
                {'error': f'Seule une vente approuvée peut être complétée. Statut actuel: {vente.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if vente.montant_paye < vente.total:
            reste = vente.total - vente.montant_paye
            return Response(
                {'error': f'Vente non entièrement payée. Reste à payer: {reste} FCFA'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vente.status = 'completed'
        vente.save(update_fields=['status', 'updated_at'])
        _purge_sales_cache()

        return Response({
            'success': True,
            'message': 'Vente complétée avec succès',
            'data': VenteDetailSerializer(vente).data,
        })

    # ============================================================
    # ACTION : ANNULER
    # ============================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, pk=None):
        vente = self.get_object()

        if vente.status in ['completed', 'cancelled']:
            return Response(
                {'error': f'Cette vente ne peut pas être annulée car elle est {vente.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        stock_restauration = {}
        items = vente.items.select_related(
            'product', 'variant', 'lot', 'warehouse_source').all()

        for item in items:
            if not item.stock_preleve:
                continue
            key = f"{item.product.id}_{item.variant.id if item.variant else 'None'}"
            if key not in stock_restauration:
                stock_restauration[key] = {
                    'product': item.product,
                    'variant': item.variant,
                    'total_quantity': 0,
                    'warehouse': item.warehouse_source,
                }
            stock_restauration[key]['total_quantity'] += item.quantity

            if item.lot:
                item.lot.quantity += item.quantity
                item.lot.save(update_fields=['quantity', 'updated_at'])

        for key, group in stock_restauration.items():
            if not group['warehouse']:
                continue

            StockMovement.objects.create(
                movement_type='in',
                reference_type='sale',
                reference_id=vente.id,
                product=group['product'],
                variant=group['variant'],
                quantity=group['total_quantity'],
                to_warehouse=group['warehouse'],
                unit_price=0,
                notes=(
                    f"Annulation vente {vente.reference} - "
                    f"{group['total_quantity']} unités restituées"
                ),
                created_by=request.user,
            )
            stock, _ = WarehouseStock.objects.get_or_create(
                product=group['product'],
                warehouse=group['warehouse'],
                variant=group['variant'],
                defaults={'quantity': 0},
            )
            stock.quantity += group['total_quantity']
            stock.save(update_fields=['quantity', 'last_updated'])

        # ✅ Recalcul SQL
        product_ids = list({item.product_id for item in items})
        totals = (
            WarehouseStock.objects
            .filter(product_id__in=product_ids)
            .values('product_id')
            .annotate(total=Sum('quantity'))
        )
        for row in totals:
            Product.objects.filter(id=row['product_id']).update(
                stock_quantity=row['total']
            )

        facture = Facture.objects.filter(vente=vente).first()
        if facture:
            facture.status = 'cancelled'
            facture.notes = (
                f"{facture.notes or ''}\n\nAnnulée suite à l'annulation de la vente {vente.reference}"
            )
            facture.save(update_fields=['status', 'notes', 'updated_at'])
            logger.info(
                f"📄 Facture {facture.reference} annulée (vente {vente.reference})")

        vente.status = 'cancelled'
        vente.save(update_fields=['status', 'updated_at'])
        _purge_sales_cache()

        return Response({
            'success': True,
            'message': 'Vente annulée avec succès',
            'data': VenteDetailSerializer(vente).data,
        })

    # ============================================================
    # ACTION : MARQUER COMME PAYÉ
    # ============================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def marquer_paye(self, request, pk=None):
        vente = self.get_object()
        user = request.user

        if vente.status not in ['approved', 'completed']:
            return Response(
                {'error': (
                    f'Seule une vente approuvée ou complétée peut être marquée '
                    f'comme payée. Statut actuel: {vente.get_status_display()}'
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if vente.est_paye:
            return Response(
                {'error': 'Cette vente est déjà entièrement payée'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        facture = Facture.objects.filter(vente=vente).first()
        if not facture:
            date_echeance = timezone.now().date() + timezone.timedelta(days=30)
            facture = Facture.objects.create(
                vente=vente,
                client=vente.client,
                agence=vente.agence,
                cree_par=user,
                type_facture='finale',
                date_facture=timezone.now().date(),
                date_echeance=date_echeance,
                conditions_paiement='Paiement immédiat',
                notes=f"Facture créée automatiquement lors du paiement de la vente {vente.reference}",
                sous_total=vente.sous_total,
                total_ttc=vente.total,
                montant_paye=0,
                montant_restant=vente.total,
            )

        montant_restant = facture.montant_restant
        if montant_restant <= 0:
            return Response(
                {'error': 'Cette facture est déjà entièrement payée'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ✅ Utilise le serializer pour valider les destinations/méthode
        payload = {
            'facture': facture.id,
            'montant': montant_restant,
            'methode': request.data.get('methode', 'especes'),
            'reference_externe': request.data.get('reference_externe', ''),
            'notes': request.data.get(
                'notes', f'Paiement automatique - Vente {vente.reference}'),
            'caisse_destination': request.data.get('caisse_destination'),
            'compte_destination': request.data.get('compte_destination'),
        }
        serializer = PaiementCreateSerializer(
            data=payload, context={'request': request})
        serializer.is_valid(raise_exception=True)
        paiement = serializer.save()

        vente.refresh_from_db()
        facture.refresh_from_db()
        paiement.refresh_from_db()
        _purge_sales_cache()

        return Response({
            'success': True,
            'message': f'Vente {vente.reference} marquée comme payée avec succès',
            'paiement': {
                'id': paiement.id,
                'reference': paiement.reference,
                'montant': str(paiement.montant),
                'methode': paiement.methode,
                'methode_display': paiement.methode_display,
                'date_paiement': paiement.date_paiement,
                'statut': paiement.statut,
                'mouvement_tresorerie': (
                    paiement.mouvement_tresorerie.reference
                    if paiement.mouvement_tresorerie else None
                ),
            },
            'facture': {
                'id': facture.id,
                'reference': facture.reference,
                'status': facture.status,
                'status_display': facture.get_status_display(),
                'montant_paye': str(facture.montant_paye),
                'montant_restant': str(facture.montant_restant),
            },
            'vente': {
                'id': vente.id,
                'reference': vente.reference,
                'status': vente.status,
                'est_paye': vente.est_paye,
                'montant_paye': str(vente.montant_paye),
                'montant_du': str(vente.montant_du),
            },
        }, status=status.HTTP_201_CREATED)

    # ============================================================
    # ACTION : STATISTIQUES (avec cache)
    # ============================================================
    @action(detail=False, methods=['get'])
    def stats(self, request):
        user = request.user
        cache_key = f'sales_stats_{user.id}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        if user.est_pdg() or user.est_drh():
            ventes = Vente.objects.all()
        elif user.est_chef_agence():
            ventes = Vente.objects.filter(agence__in=user.get_agences())
        else:
            ventes = Vente.objects.filter(vendeur=user)

        today = timezone.now().date()
        ventes_today = ventes.filter(date_vente__date=today)

        data = {
            'total': ventes.count(),
            'total_ca': ventes.filter(status='completed').aggregate(total=Sum('total'))['total'] or 0,
            'ca_today': ventes_today.filter(status='completed').aggregate(total=Sum('total'))['total'] or 0,
            'en_attente': ventes.filter(status='pending_approval').count(),
            'approuvees': ventes.filter(status='approved').count(),
            'completees': ventes.filter(status='completed').count(),
            'rejetees': ventes.filter(status='rejected').count(),
            'annulees': ventes.filter(status='cancelled').count(),
            'impayes': ventes.filter(est_paye=False, status__in=['approved', 'completed']).aggregate(total=Sum('montant_du'))['total'] or 0,
        }
        cache.set(cache_key, data, 60)
        return Response(data)

    # ============================================================
    # ACTION : DESTINATIONS PAIEMENT
    # ============================================================
    @action(detail=True, methods=['get'])
    def destinations_paiement(self, request, pk=None):
        vente = self.get_object()
        try:
            from tresorerie.models import Caisse, CompteBancaire
            caisses = Caisse.objects.filter(
                agence=vente.agence, is_active=True
            ).values('id', 'nom', 'code', 'type_caisse', 'solde_actuel', 'is_default')
            comptes = CompteBancaire.objects.filter(
                agence=vente.agence, is_active=True
            ).values('id', 'nom', 'numero_compte', 'banque', 'solde_actuel')
            return Response({
                'caisses': list(caisses),
                'comptes_bancaires': list(comptes),
            })
        except ImportError:
            return Response({
                'caisses': [],
                'comptes_bancaires': [],
                'message': 'Module trésorerie non disponible',
            })


# ============================================================
# PAIEMENT
# ============================================================
class PaiementViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    pagination_class = PaiementPagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['facture', 'client', 'vente', 'methode', 'statut']
    search_fields = ['reference', 'reference_externe',
                     'client__nom', 'facture__reference']
    ordering_fields = ['date_paiement', 'montant']

    def get_serializer_class(self):
        if self.action == 'create':
            return PaiementCreateSerializer
        return PaiementSerializer

    def get_queryset(self):
        user = self.request.user
        base = Paiement.objects.select_related(
            'facture__client', 'client', 'encaisse_par',
            'vente', 'caisse_destination', 'compte_destination',
            'mouvement_tresorerie',
        )

        if user.est_pdg() or user.est_drh():
            return base

        agences_ids = user.get_agences().values_list('id', flat=True)
        return base.filter(
            Q(facture__agence_id__in=agences_ids) |
            Q(vente__agence_id__in=agences_ids) |
            Q(client__ventes__agence_id__in=agences_ids)
        ).distinct()

    def perform_create(self, serializer):
        serializer.save()
        _purge_sales_cache()

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        paiement = self.get_object()
        if paiement.statut == 'refunded':
            return Response(
                {'error': 'Ce paiement a déjà été remboursé'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        paiement.statut = 'refunded'
        paiement.save(update_fields=['statut', 'updated_at'])
        avoir = Paiement.objects.create(
            facture=paiement.facture,
            client=paiement.client,
            vente=paiement.vente,
            montant=-paiement.montant,
            methode=paiement.methode,
            reference_externe=f"Remboursement de {paiement.reference}",
            notes=f"Remboursement suite à l'annulation du paiement {paiement.reference}",
            encaisse_par=request.user,
            statut='completed',
        )
        _purge_sales_cache()
        return Response({
            'success': True,
            'message': 'Paiement annulé avec succès',
            'paiement': PaiementSerializer(paiement).data,
            'avoir': PaiementSerializer(avoir).data,
        })

    @action(detail=False, methods=['get'])
    def stats(self, request):
        user = request.user
        cache_key = f'sales_paiement_stats_{user.id}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        if user.est_pdg() or user.est_drh():
            paiements = Paiement.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            paiements = Paiement.objects.filter(
                Q(facture__agence_id__in=agences_ids) |
                Q(vente__agence_id__in=agences_ids)
            ).distinct()

        today = timezone.now().date()
        stats_data = {
            'total': paiements.count(),
            'total_montant': paiements.aggregate(total=Sum('montant'))['total'] or 0,
            'montant_jour': paiements.filter(date_paiement=today).aggregate(total=Sum('montant'))['total'] or 0,
            'par_methode': {},
            'par_statut': {},
        }
        for methode, label in Paiement.METHODES_PAIEMENT:
            qs = paiements.filter(methode=methode)
            stats_data['par_methode'][methode] = {
                'label': label,
                'count': qs.count(),
                'montant': qs.aggregate(total=Sum('montant'))['total'] or 0,
            }
        for statut, label in Paiement.STATUT_PAIEMENT:
            qs = paiements.filter(statut=statut)
            stats_data['par_statut'][statut] = {
                'label': label,
                'count': qs.count(),
                'montant': qs.aggregate(total=Sum('montant'))['total'] or 0,
            }

        cache.set(cache_key, stats_data, 60)
        return Response(stats_data)


# ============================================================
# DEVIS
# ============================================================
class DevisViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    pagination_class = DevisPagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'agence', 'client']
    search_fields = ['reference', 'client__nom', 'client__raison_sociale']
    ordering_fields = ['date_creation', 'date_expiration', 'total']

    def get_serializer_class(self):
        if self.action == 'list':
            return DevisListSerializer
        if self.action == 'retrieve':
            return DevisDetailSerializer
        if self.action == 'create':
            return DevisCreateSerializer
        return DevisDetailSerializer

    def get_queryset(self):
        user = self.request.user
        base = Devis.objects.select_related('agence', 'client', 'vendeur')

        if user.est_pdg() or user.est_drh():
            pass
        else:
            base = base.filter(agence__in=user.get_agences())

        if self.action == 'retrieve':
            base = base.prefetch_related(
                Prefetch(
                    'items',
                    queryset=DevisItem.objects
                    .select_related('product', 'variant')
                    .order_by('id'),
                ),
            )
        return base

    def perform_create(self, serializer):
        serializer.save()
        _purge_sales_cache()

    @action(detail=True, methods=['post'])
    def envoyer(self, request, pk=None):
        devis = self.get_object()
        if devis.status != 'draft':
            return Response(
                {'error': f'Seul un devis brouillon peut être envoyé. Statut actuel : {devis.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        devis.status = 'sent'
        devis.save(update_fields=['status', 'updated_at'])
        _purge_sales_cache()
        return Response({
            'success': True, 'message': 'Devis envoyé avec succès',
            'status': devis.status,
        })

    @action(detail=True, methods=['post'])
    def accepter(self, request, pk=None):
        devis = self.get_object()
        if devis.status != 'sent':
            return Response(
                {'error': f'Seul un devis envoyé peut être accepté. Statut actuel : {devis.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if devis.date_expiration < timezone.now().date():
            devis.status = 'expired'
            devis.save(update_fields=['status', 'updated_at'])
            return Response(
                {'error': 'Ce devis est expiré, il ne peut pas être accepté.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        devis.status = 'accepted'
        devis.save(update_fields=['status', 'updated_at'])
        _purge_sales_cache()
        return Response({
            'success': True, 'message': 'Devis accepté par le client',
            'status': devis.status,
        })

    @action(detail=True, methods=['post'])
    def refuser(self, request, pk=None):
        devis = self.get_object()
        if devis.status not in ('draft', 'sent'):
            return Response(
                {'error': 'Seul un devis en cours peut être refusé.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        motif = request.data.get('motif', '')
        devis.status = 'refused'
        if motif:
            devis.notes = (
                f"{devis.notes or ''}\nRefusé le "
                f"{timezone.now().strftime('%d/%m/%Y')} - Motif: {motif}"
            )
        devis.save(update_fields=['status', 'notes', 'updated_at'])
        _purge_sales_cache()
        return Response({'success': True, 'message': 'Devis refusé'})

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def convertir_en_vente(self, request, pk=None):
        devis = self.get_object()
        if devis.status != 'accepted':
            return Response(
                {'error': f'Seul un devis accepté peut être converti en vente. Statut actuel : {devis.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not devis.client:
            return Response(
                {'error': "Ce devis n'a pas de client associé."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vente = Vente.objects.create(
            agence=devis.agence,
            client=devis.client,
            vendeur=devis.vendeur,
            type_vente='livraison',
            status='draft',
            sous_total=devis.sous_total,
            remise=devis.remise,
            remise_percentage=devis.remise_percentage,
            total=devis.total,
            montant_du=devis.total,
            notes=f"Vente issue du devis {devis.reference}\n{devis.notes or ''}",
        )
        for item in devis.items.select_related('product', 'variant'):
            VenteItem.objects.create(
                vente=vente,
                product=item.product,
                variant=item.variant,
                quantity=item.quantity,
                prix_unitaire=item.prix_unitaire,
                remise=item.remise,
                total=item.total,
            )
        devis.status = 'converted'
        devis.save(update_fields=['status', 'updated_at'])
        _purge_sales_cache()

        serializer = VenteDetailSerializer(vente, context={'request': request})
        return Response({
            'success': True,
            'message': 'Devis converti en vente avec succès',
            'vente': serializer.data,
        })

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        """Génère un PDF du devis - SANS TVA"""
        devis = self.get_object()
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4, rightMargin=2*cm,
            leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm,
        )
        styles = getSampleStyleSheet()
        elements = []

        header_data = [
            ['SEYDI GROUP SARL', f'DEVIS {devis.reference}'],
            ['Solutions Digitales', ''],
            ['Dakar, Sénégal', ''],
            ['Tél: +221 33 123 45 67', ''],
            ['Email: contact@seydigroup.com', ''],
        ]
        header_table = Table(header_data, colWidths=[8*cm, 8*cm])
        header_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (0, 0), 16),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (1, 0), (1, 0), 18),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.5*cm))

        if devis.client:
            denomination = devis.client.raison_sociale or devis.client.nom
            if devis.client.prenom:
                denomination = f"{devis.client.nom} {devis.client.prenom}"
            client_details = [
                ['Client :', denomination],
                ['Adresse :', devis.client.adresse or '-'],
                ['Tél :', devis.client.telephone or '-'],
                ['Email :', devis.client.email or '-'],
            ]
            devis_details = [
                ['Date :', devis.date_creation.strftime('%d/%m/%Y')],
                ['Expiration :', devis.date_expiration.strftime('%d/%m/%Y')],
                ['Statut :', devis.get_status_display()],
                ['Agence :', devis.agence.nom],
            ]
            client_table = Table(client_details, colWidths=[4*cm, 7*cm])
            devis_table = Table(devis_details, colWidths=[4*cm, 7*cm])
            two_cols = Table([[client_table, devis_table]],
                             colWidths=[11*cm, 11*cm])
            elements.append(two_cols)
        else:
            elements.append(
                Paragraph("Aucun client associé", styles['Normal']))
        elements.append(Spacer(1, 0.5*cm))

        elements.append(Paragraph(
            "ARTICLES",
            ParagraphStyle('SectionStyle', parent=styles['Heading2'],
                           fontSize=14, textColor=colors.HexColor('#1e40af'))
        ))
        table_data = [['Désignation', 'Référence',
                       'Qté', 'Prix unitaire', 'Total']]
        for item in devis.items.select_related('product'):
            table_data.append([
                item.product.name[:50],
                item.product.reference[:20],
                str(item.quantity),
                f"{item.prix_unitaire:,.0f} FCFA",
                f"{item.total:,.0f} FCFA",
            ])
        col_widths = [6*cm, 3*cm, 1.5*cm, 3*cm, 3*cm]
        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.5*cm))

        totals_data = [
            ['Sous-total :', f"{devis.sous_total:,.0f} FCFA"],
            ['Remise :', f"{devis.remise:,.0f} FCFA"],
            ['TOTAL TTC :', f"{devis.total:,.0f} FCFA"],
        ]
        totals_table = Table(totals_data, colWidths=[8*cm, 6*cm])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 2), (1, 2), 'Helvetica-Bold'),
            ('LINEABOVE', (0, 2), (-1, 2), 0.5, colors.grey),
        ]))
        elements.append(totals_table)
        elements.append(Spacer(1, 0.5*cm))

        if devis.conditions:
            elements.append(Paragraph(
                "CONDITIONS",
                ParagraphStyle('SectionStyle', parent=styles['Heading2'],
                               fontSize=14, textColor=colors.HexColor('#1e40af'))
            ))
            elements.append(Paragraph(devis.conditions, styles['Normal']))
            elements.append(Spacer(1, 0.3*cm))
        if devis.notes:
            elements.append(Paragraph(
                "NOTES",
                ParagraphStyle('SectionStyle', parent=styles['Heading2'],
                               fontSize=14, textColor=colors.HexColor('#1e40af'))
            ))
            elements.append(Paragraph(devis.notes, styles['Normal']))

        footer_text = (
            f'<para align="center" fontSize="8" textColor="gray">'
            f'Devis valable jusqu\'au {devis.date_expiration.strftime("%d/%m/%Y")}.<br/>'
            f'SEYDI GROUP SARL - RCCM: SN DKR 2023 B 123 - '
            f'Généré le {timezone.now().strftime("%d/%m/%Y à %H:%M")}'
            f'</para>'
        )
        elements.append(Paragraph(footer_text, styles['Normal']))

        doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'inline; filename="devis_{devis.reference}.pdf"'
        )
        return response


# ============================================================
# FACTURE
# ============================================================
class FactureViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    pagination_class = FacturePagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'type_facture', 'client',
                        'agence', 'montant_restant']
    search_fields = ['reference', 'client__nom', 'client__raison_sociale']
    ordering_fields = ['date_facture',
                       'date_echeance', 'total_ttc', 'created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return FactureListSerializer
        if self.action == 'retrieve':
            return FactureDetailSerializer
        if self.action == 'create':
            return FactureCreateSerializer
        return FactureDetailSerializer

    def get_queryset(self):
        user = self.request.user
        base = Facture.objects.select_related(
            'client', 'agence', 'cree_par', 'vente'
        )

        if user.est_pdg() or user.est_drh():
            pass
        else:
            base = base.filter(agence__in=user.get_agences())

        if self.action == 'retrieve':
            base = base.prefetch_related(
                Prefetch(
                    'paiements',
                    queryset=Paiement.objects
                    .select_related('client', 'encaisse_par')
                    .order_by('-date_paiement'),
                ),
            )
        return base

    def perform_create(self, serializer):
        serializer.save()
        _purge_sales_cache()

    @action(detail=True, methods=['post'])
    def enregistrer_paiement(self, request, pk=None):
        facture = self.get_object()
        serializer = FacturePaiementSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        montant = serializer.validated_data['montant']
        nouveau_montant_paye = facture.montant_paye + montant
        if nouveau_montant_paye > facture.total_ttc:
            return Response(
                {'error': (
                    f'Le montant dépasse le total de la facture. '
                    f'Reste à payer: {facture.montant_restant} FCFA'
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Utilise la logique du modèle Paiement (mise à jour auto + trésorerie)
        Paiement.objects.create(
            facture=facture,
            client=facture.client,
            vente=facture.vente,
            montant=montant,
            methode=serializer.validated_data['methode'],
            reference_externe=serializer.validated_data.get('reference', ''),
            notes=serializer.validated_data.get(
                'notes',
                f'Paiement du {timezone.now().strftime("%d/%m/%Y")}',
            ),
            encaisse_par=request.user,
            statut='completed',
        )
        facture.refresh_from_db()
        _purge_sales_cache()

        return Response({
            'success': True,
            'message': 'Paiement enregistré avec succès',
            'montant_paye': facture.montant_paye,
            'montant_restant': facture.montant_restant,
            'status': facture.status,
        })

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        facture = self.get_object()
        if facture.status == 'paid':
            return Response(
                {'error': "Impossible d'annuler une facture déjà payée"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if facture.status == 'cancelled':
            return Response(
                {'error': 'Cette facture est déjà annulée'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        motif = request.data.get('motif', 'Annulation sans motif')
        facture.status = 'cancelled'
        facture.notes = (
            f"{facture.notes or ''}\n\nAnnulée le "
            f"{timezone.now().strftime('%d/%m/%Y')} - Motif: {motif}"
        )
        facture.save(update_fields=['status', 'notes', 'updated_at'])
        _purge_sales_cache()
        return Response({
            'success': True, 'message': 'Facture annulée avec succès',
            'status': facture.status,
        })

    @action(detail=True, methods=['post'])
    def relancer(self, request, pk=None):
        facture = self.get_object()
        if facture.status == 'paid':
            return Response(
                {'error': 'Cette facture est déjà payée'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if facture.status == 'cancelled':
            return Response(
                {'error': 'Cette facture est annulée'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            'success': True,
            'message': f'Relance envoyée pour la facture {facture.reference}',
            'date_relance': timezone.now().strftime('%d/%m/%Y à %H:%M'),
        })

    @action(detail=False, methods=['get'])
    def stats(self, request):
        user = request.user
        cache_key = f'sales_facture_stats_{user.id}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        if user.est_pdg() or user.est_drh():
            factures = Facture.objects.all()
        else:
            factures = Facture.objects.filter(agence__in=user.get_agences())

        today = timezone.now().date()
        stats = {
            'total_factures': factures.count(),
            'total_montant': factures.aggregate(total=Sum('total_ttc'))['total'] or 0,
            'total_paye': factures.aggregate(total=Sum('montant_paye'))['total'] or 0,
            'total_restant': factures.aggregate(total=Sum('montant_restant'))['total'] or 0,
            'par_statut': {},
            'par_type': {},
            'factures_impayees': 0,
            'factures_en_retard': 0,
            'montant_impayes': 0,
            'montant_en_retard': 0,
        }
        for status_code, status_label in Facture.STATUS_CHOICES:
            qs = factures.filter(status=status_code)
            stats['par_statut'][status_code] = {
                'label': status_label,
                'count': qs.count(),
                'montant': qs.aggregate(total=Sum('total_ttc'))['total'] or 0,
                'paye': qs.aggregate(total=Sum('montant_paye'))['total'] or 0,
            }
        for type_code, type_label in Facture.TYPE_FACTURE:
            qs = factures.filter(type_facture=type_code)
            stats['par_type'][type_code] = {
                'label': type_label,
                'count': qs.count(),
                'montant': qs.aggregate(total=Sum('total_ttc'))['total'] or 0,
            }
        factures_impayees = factures.exclude(status__in=['paid', 'cancelled'])
        stats['factures_impayees'] = factures_impayees.count()
        stats['montant_impayes'] = factures_impayees.aggregate(
            total=Sum('montant_restant'))['total'] or 0
        factures_retard = factures.filter(
            status='overdue', date_echeance__lt=today)
        stats['factures_en_retard'] = factures_retard.count()
        stats['montant_en_retard'] = factures_retard.aggregate(
            total=Sum('montant_restant'))['total'] or 0
        start_of_month = today.replace(day=1)
        factures_mois = factures.filter(date_facture__gte=start_of_month)
        stats['factures_mois'] = factures_mois.count()
        stats['montant_mois'] = factures_mois.aggregate(
            total=Sum('total_ttc'))['total'] or 0

        cache.set(cache_key, stats, 60)
        return Response(stats)

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        """Génère un PDF de la facture - SANS TVA"""
        facture = self.get_object()
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4, rightMargin=2*cm,
            leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm,
        )
        styles = getSampleStyleSheet()
        elements = []

        header_data = [
            ['SEYDI GROUP SARL', f'FACTURE {facture.reference}'],
            ['Solutions Digitales', ''],
            ['Dakar, Sénégal', ''],
            ['Tél: +221 33 123 45 67', ''],
            ['Email: contact@seydigroup.com', ''],
        ]
        header_table = Table(header_data, colWidths=[8*cm, 8*cm])
        header_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (0, 0), 16),
            ('FONTSIZE', (0, 1), (0, 2), 10),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (1, 0), (1, 0), 18),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.5*cm))
        elements.append(Table(
            [['']], colWidths=[16*cm],
            style=[('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.grey)]
        ))
        elements.append(Spacer(1, 0.5*cm))

        if facture.client:
            denomination = facture.client.raison_sociale or facture.client.nom
            if facture.client.prenom:
                denomination = f"{facture.client.nom} {facture.client.prenom}"
            client_details = [
                ['Dénomination:', denomination],
                ['Adresse:', facture.client.adresse or '-'],
                ['Téléphone:', facture.client.telephone or '-'],
                ['Email:', facture.client.email or '-'],
            ]
            if facture.client.numero_tva:
                client_details.append(['N° TVA:', facture.client.numero_tva])
            facture_details = [
                ['Date:', facture.date_facture.strftime('%d/%m/%Y')],
                ['Échéance:', facture.date_echeance.strftime('%d/%m/%Y')],
                ['Type:', facture.get_type_facture_display()],
                ['Statut:', facture.get_status_display()],
                ['Agence:', facture.agence.nom if facture.agence else '-'],
            ]
            client_table = Table(client_details, colWidths=[4*cm, 7*cm])
            facture_table = Table(facture_details, colWidths=[4*cm, 7*cm])
            client_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
            ]))
            facture_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
            ]))
            two_cols = Table([[client_table, facture_table]],
                             colWidths=[11*cm, 11*cm])
            two_cols.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 11),
            ]))
            elements.append(two_cols)
        else:
            elements.append(
                Paragraph("Aucun client associé", styles['Normal']))
        elements.append(Spacer(1, 0.5*cm))

        elements.append(Paragraph(
            "ARTICLES",
            ParagraphStyle('SectionStyle', parent=styles['Heading2'],
                           fontSize=14, textColor=colors.HexColor('#1e40af'),
                           spaceAfter=0.3*cm)
        ))
        vente_items = (
            facture.vente.items.select_related('product').all()
            if facture.vente else []
        )
        table_data = [['Désignation', 'Référence',
                       'Qté', 'Prix unitaire', 'Total']]
        for item in vente_items:
            table_data.append([
                item.product.name[:50],
                item.product.reference[:20],
                str(item.quantity),
                f"{item.prix_unitaire:,.0f} FCFA",
                f"{item.total:,.0f} FCFA",
            ])
        if len(table_data) == 1:
            table_data.append(['Aucun article', '-', '-', '-', '-'])
        col_widths = [6*cm, 3*cm, 1.5*cm, 3*cm, 3*cm]
        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.5*cm))

        totals_data = [
            ['Sous-total HT:', f"{facture.sous_total:,.0f} FCFA"],
            ['TOTAL TTC:', f"{facture.total_ttc:,.0f} FCFA"],
            ['Montant payé:', f"{facture.montant_paye:,.0f} FCFA"],
            ['Reste à payer:', f"{facture.montant_restant:,.0f} FCFA"],
        ]
        totals_table = Table(totals_data, colWidths=[8*cm, 6*cm])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (1, 1), 12),
            ('FONTNAME', (0, 1), (1, 1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (1, 3), (1, 3), colors.red),
            ('FONTNAME', (1, 3), (1, 3), 'Helvetica-Bold'),
            ('LINEABOVE', (0, 1), (-1, 1), 0.5, colors.grey),
            ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(totals_table)
        elements.append(Spacer(1, 0.5*cm))

        if facture.conditions_paiement:
            elements.append(Paragraph(
                "CONDITIONS DE PAIEMENT",
                ParagraphStyle('SectionStyle', parent=styles['Heading2'],
                               fontSize=14, textColor=colors.HexColor('#1e40af'))
            ))
            elements.append(Paragraph(
                facture.conditions_paiement, styles['Normal']))
            elements.append(Spacer(1, 0.3*cm))
        if facture.notes:
            elements.append(Paragraph(
                "NOTES",
                ParagraphStyle('SectionStyle', parent=styles['Heading2'],
                               fontSize=14, textColor=colors.HexColor('#1e40af'))
            ))
            elements.append(Paragraph(facture.notes, styles['Normal']))
            elements.append(Spacer(1, 0.3*cm))
        if facture.pied_de_page:
            elements.append(Paragraph(
                "INFORMATIONS COMPLÉMENTAIRES",
                ParagraphStyle('SectionStyle', parent=styles['Heading2'],
                               fontSize=14, textColor=colors.HexColor('#1e40af'))
            ))
            elements.append(Paragraph(facture.pied_de_page, styles['Normal']))
            elements.append(Spacer(1, 0.5*cm))

        signature_data = [
            ['Le Client', "L'Entreprise"],
            ['', ''],
            ['Signature et cachet', 'Signature et cachet'],
        ]
        signature_table = Table(signature_data, colWidths=[8*cm, 8*cm])
        signature_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('FONTSIZE', (0, 2), (-1, 2), 9),
            ('TEXTCOLOR', (0, 2), (-1, 2), colors.grey),
            ('LINEABOVE', (0, 2), (0, 2), 0.5, colors.black),
            ('LINEABOVE', (1, 2), (1, 2), 0.5, colors.black),
        ]))
        elements.append(signature_table)
        elements.append(Spacer(1, 0.5*cm))

        footer_text = (
            f'<para align="center" fontSize="8" textColor="gray">'
            f'SEYDI GROUP SARL - Capital social: 10 000 000 FCFA - '
            f'RCCM: SN DKR 2023 B 123<br/>Adresse: Dakar, Sénégal - '
            f'Tél: +221 33 123 45 67 - Email: contact@seydigroup.com<br/>'
            f'Facture générée électroniquement le '
            f'{timezone.now().strftime("%d/%m/%Y à %H:%M")} - '
            f'Valide sans signature</para>'
        )
        elements.append(Paragraph(footer_text, styles['Normal']))

        doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'inline; filename="facture_{facture.reference}.pdf"'
        )
        return response

    @action(detail=True, methods=['get'])
    def paiements(self, request, pk=None):
        facture = self.get_object()
        qs = facture.paiements.select_related('client', 'encaisse_par').all()
        serializer = PaiementSerializer(qs, many=True)
        return Response(serializer.data)


# ============================================================
# DASHBOARD
# ============================================================
class DashboardVentesView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get(self, request):
        user = request.user
        cache_key = f'sales_dashboard_{user.id}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        if user.est_pdg() or user.est_drh():
            ventes = Vente.objects.all()
        else:
            ventes = Vente.objects.filter(agence__in=user.get_agences())

        today = timezone.now().date()
        ventes_aujourdhui = ventes.filter(date_vente__date=today)

        data = {
            'total_ventes': ventes.count(),
            'total_ca': ventes.filter(status='completed').aggregate(total=Sum('total'))['total'] or 0,
            'ca_jour': ventes_aujourdhui.filter(status='completed').aggregate(total=Sum('total'))['total'] or 0,
            'ventes_en_attente': ventes.filter(status='pending_approval').count(),
            'impayes': ventes.filter(
                est_paye=False, status__in=['approved', 'completed']
            ).aggregate(total=Sum('montant_du'))['total'] or 0,
        }
        cache.set(cache_key, data, 60)
        return Response(data)
