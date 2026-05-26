# sales/views.py

from django.shortcuts import render
from rest_framework import viewsets, generics, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Q
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from io import BytesIO
from django.http import HttpResponse

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess, IsPDG, IsChefAgence
from inventaire.models import WarehouseStock, StockMovement, Warehouse


class ClientViewSet(viewsets.ModelViewSet):
    serializer_class = ClientSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['client_type', 'est_revendeur', 'is_active']
    search_fields = ['nom', 'prenom', 'email', 'telephone', 'raison_sociale']
    ordering_fields = ['nom', 'created_at']

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Client.objects.none()
        if user.est_pdg() or user.est_drh():
            return Client.objects.all()
        agences = user.get_agences()
        if not agences.exists():
            return Client.objects.none()
        agences_ids = list(agences.values_list('id', flat=True))
        return Client.objects.filter(
            Q(ventes__agence_id__in=agences_ids) | Q(created_by=user)
        ).distinct()

    def list(self, request, *args, **kwargs):
        try:
            queryset = self.filter_queryset(self.get_queryset())
            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_create(self, serializer):
        user = self.request.user
        agence_principale = user.get_agence_principale()
        client = serializer.save(created_by=user)
        if agence_principale and not client.ventes.exists():
            from .models import Vente
            Vente.objects.create(
                agence=agence_principale,
                client=client,
                vendeur=user,
                total=0,
                montant_du=0,
                status='completed',
                notes="Création automatique pour association client-agence"
            )

# sales/views.py - VenteViewSet complet avec méthode sans_facture


class VenteViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des ventes
    """
    permission_classes = [IsAuthenticated, HasAgenceAccess]
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
        if user.est_pdg() or user.est_drh():
            return Vente.objects.all()
        if user.est_chef_agence():
            agences_ids = user.get_agences().values_list('id', flat=True)
            return Vente.objects.filter(agence_id__in=agences_ids)
        return Vente.objects.filter(vendeur=user)

    # ============================================================
    # Ventes éligibles pour facturation (sans facture)
    # ============================================================
    @action(detail=False, methods=['get'])
    def sans_facture(self, request):
        """
        Retourne les ventes approuvées ou complétées qui n'ont pas encore de facture,
        et accessibles à l'utilisateur.
        """
        queryset = self.get_queryset().filter(
            status__in=['approved', 'completed'])
        # Exclure les ventes qui ont déjà une facture
        ventes_avec_facture = Facture.objects.values_list(
            'vente_id', flat=True)
        queryset = queryset.exclude(id__in=ventes_avec_facture)
        # Facultatif : s'assurer que la vente a une agence (nécessaire pour la facture)
        queryset = queryset.filter(agence__isnull=False)
        serializer = VenteListSerializer(
            queryset, many=True, context={'request': request})
        return Response(serializer.data)

    # ============================================================
    # SOUMETTRE UNE VENTE
    # ============================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def submit(self, request, pk=None):
        vente = self.get_object()
        if vente.status != 'draft':
            return Response(
                {'error': f'Seule une vente en brouillon peut être soumise. Statut actuel: {vente.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        warehouse = vente.agence.warehouses.filter(is_default=True).first()
        if not warehouse:
            warehouse = vente.agence.warehouses.filter(is_active=True).first()
        if not warehouse:
            return Response(
                {'error': f'Aucun entrepôt configuré pour l\'agence {vente.agence.nom}.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        stock_insuffisant = []
        for item in vente.items.all():
            stock = WarehouseStock.objects.filter(
                product=item.product, warehouse=warehouse, variant=item.variant
            ).first()
            if not stock:
                stock_insuffisant.append(
                    {'product': item.product.name, 'message': 'Stock non configuré dans cet entrepôt'})
            elif stock.quantity < item.quantity:
                stock_insuffisant.append({
                    'product': item.product.name,
                    'disponible': stock.quantity,
                    'demande': item.quantity,
                    'manquant': item.quantity - stock.quantity
                })
        if stock_insuffisant:
            return Response(
                {'error': 'Stock insuffisant pour soumettre la vente',
                    'details': stock_insuffisant},
                status=status.HTTP_400_BAD_REQUEST
            )
        vente.status = 'pending_approval'
        vente.save()
        return Response({
            'success': True,
            'message': 'Vente soumise avec succès',
            'data': VenteDetailSerializer(vente).data
        })

    # ============================================================
    # APPROUVER UNE VENTE
    # ============================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        vente = self.get_object()
        user = request.user
        if not user.est_chef_agence() and not user.est_pdg():
            return Response(
                {'error': 'Seul le chef d\'agence ou le PDG peut approuver une vente'},
                status=status.HTTP_403_FORBIDDEN
            )
        if not user.est_pdg() and not user.peut_acceder_agence(vente.agence.id):
            return Response(
                {'error': 'Vous n\'avez pas accès à cette agence'},
                status=status.HTTP_403_FORBIDDEN
            )
        if vente.status != 'pending_approval':
            return Response(
                {'error': f'Seule une vente en attente peut être approuvée. Statut actuel: {vente.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        warehouse = vente.agence.warehouses.filter(is_default=True).first()
        if not warehouse:
            warehouse = vente.agence.warehouses.filter(is_active=True).first()
        if not warehouse:
            from inventaire.models import get_default_warehouse
            warehouse = get_default_warehouse(vente.agence)
        if not warehouse:
            return Response(
                {'error': f'Aucun entrepôt configuré pour l\'agence {vente.agence.nom}.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        stock_insuffisant = []
        for item in vente.items.all():
            try:
                stock = WarehouseStock.objects.get(
                    product=item.product, warehouse=warehouse, variant=item.variant
                )
                if stock.quantity < item.quantity:
                    stock_insuffisant.append({
                        'product': item.product.name,
                        'disponible': stock.quantity,
                        'demande': item.quantity,
                        'manquant': item.quantity - stock.quantity
                    })
            except WarehouseStock.DoesNotExist:
                stock_insuffisant.append({
                    'product': item.product.name,
                    'message': 'Produit non trouvé dans l\'entrepôt',
                    'demande': item.quantity
                })
        if stock_insuffisant:
            return Response(
                {'error': 'Stock insuffisant pour approuver la vente',
                    'details': stock_insuffisant},
                status=status.HTTP_400_BAD_REQUEST
            )
        for item in vente.items.all():
            stock = WarehouseStock.objects.get(
                product=item.product, warehouse=warehouse, variant=item.variant
            )
            stock.quantity -= item.quantity
            stock.save()
            item.stock_preleve = True
            item.warehouse_source = warehouse
            item.save()
            StockMovement.objects.create(
                movement_type='out', reference_type='sale', reference_id=vente.id,
                product=item.product, variant=item.variant, quantity=item.quantity,
                from_warehouse=warehouse, unit_price=item.prix_unitaire,
                notes=f"Vente {vente.reference} approuvée", created_by=user
            )
            total_stock = WarehouseStock.objects.filter(product=item.product).aggregate(
                total=Sum('quantity')
            )['total'] or 0
            item.product.stock_quantity = total_stock
            item.product.save()
        vente.status = 'approved'
        vente.approved_by = user
        vente.date_approbation = timezone.now()
        vente.save()
        return Response({
            'success': True,
            'message': 'Vente approuvée avec succès',
            'data': VenteDetailSerializer(vente).data
        })

    # ============================================================
    # REJETER UNE VENTE
    # ============================================================
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        vente = self.get_object()
        if vente.status != 'pending_approval':
            return Response(
                {'error': f'Seule une vente en attente peut être rejetée. Statut actuel: {vente.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        motif = request.data.get('motif')
        if not motif:
            return Response({'error': 'Un motif de rejet est requis'}, status=status.HTTP_400_BAD_REQUEST)
        vente.status = 'rejected'
        vente.motif_rejet = motif
        vente.save()
        return Response({'success': True, 'message': 'Vente rejetée', 'data': VenteDetailSerializer(vente).data})

    # ============================================================
    # COMPLÉTER UNE VENTE
    # ============================================================
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        vente = self.get_object()
        if vente.status != 'approved':
            return Response(
                {'error': f'Seule une vente approuvée peut être complétée. Statut actuel: {vente.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if vente.montant_paye < vente.total:
            reste = vente.total - vente.montant_paye
            return Response(
                {'error': f'Vente non entièrement payée. Reste à payer: {reste} FCFA'},
                status=status.HTTP_400_BAD_REQUEST
            )
        vente.status = 'completed'
        vente.save()
        return Response({'success': True, 'message': 'Vente complétée avec succès', 'data': VenteDetailSerializer(vente).data})

    # ============================================================
    # ANNULER UNE VENTE
    # ============================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, pk=None):
        vente = self.get_object()
        if vente.status in ['completed', 'cancelled']:
            return Response(
                {'error': f'Cette vente ne peut pas être annulée car elle est {vente.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        for item in vente.items.filter(stock_preleve=True):
            if item.warehouse_source:
                try:
                    stock = WarehouseStock.objects.get(
                        product=item.product, warehouse=item.warehouse_source, variant=item.variant
                    )
                    stock.quantity += item.quantity
                    stock.save()
                    StockMovement.objects.create(
                        movement_type='in', reference_type='sale', reference_id=vente.id,
                        product=item.product, variant=item.variant, quantity=item.quantity,
                        to_warehouse=item.warehouse_source, unit_price=item.prix_unitaire,
                        notes=f"Annulation vente {vente.reference}", created_by=request.user
                    )
                    total_stock = WarehouseStock.objects.filter(product=item.product).aggregate(
                        total=Sum('quantity')
                    )['total'] or 0
                    item.product.stock_quantity = total_stock
                    item.product.save()
                except WarehouseStock.DoesNotExist:
                    pass
        vente.status = 'cancelled'
        vente.save()
        return Response({'success': True, 'message': 'Vente annulée avec succès', 'data': VenteDetailSerializer(vente).data})

    # ============================================================
    # STATISTIQUES DES VENTES
    # ============================================================
    @action(detail=False, methods=['get'])
    def stats(self, request):
        user = request.user
        if user.est_pdg() or user.est_drh():
            ventes = Vente.objects.all()
        elif user.est_chef_agence():
            agences_ids = user.get_agences().values_list('id', flat=True)
            ventes = Vente.objects.filter(agence_id__in=agences_ids)
        else:
            ventes = Vente.objects.filter(vendeur=user)
        today = timezone.now().date()
        ventes_today = ventes.filter(date_vente__date=today)
        return Response({
            'total': ventes.count(),
            'total_ca': ventes.filter(status='completed').aggregate(total=Sum('total'))['total'] or 0,
            'ca_today': ventes_today.filter(status='completed').aggregate(total=Sum('total'))['total'] or 0,
            'en_attente': ventes.filter(status='pending_approval').count(),
            'approuvees': ventes.filter(status='approved').count(),
            'completees': ventes.filter(status='completed').count(),
            'rejetees': ventes.filter(status='rejected').count(),
            'annulees': ventes.filter(status='cancelled').count(),
            'impayes': ventes.filter(est_paye=False, status__in=['approved', 'completed']).aggregate(
                total=Sum('montant_du')
            )['total'] or 0
        })


class PaiementViewSet(viewsets.ModelViewSet):
    serializer_class = PaiementSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]
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
        if user.est_pdg() or user.est_drh():
            return Paiement.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return Paiement.objects.filter(
            Q(facture__agence_id__in=agences_ids) |
            Q(vente__agence_id__in=agences_ids) |
            Q(client__ventes__agence_id__in=agences_ids)
        ).distinct()

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        paiement = self.get_object()
        if paiement.statut == 'refunded':
            return Response({'error': 'Ce paiement a déjà été remboursé'}, status=status.HTTP_400_BAD_REQUEST)
        paiement.statut = 'refunded'
        paiement.save()
        # Créer un avoir (montant négatif) – pour éviter la validation, on force l'insertion
        avoir = Paiement.objects.create(
            facture=paiement.facture,
            client=paiement.client,
            vente=paiement.vente,
            montant=-paiement.montant,
            methode=paiement.methode,
            reference_externe=f"Remboursement de {paiement.reference}",
            notes=f"Remboursement suite à l'annulation du paiement {paiement.reference}",
            encaisse_par=request.user,
            statut='completed'
        )
        return Response({
            'success': True,
            'message': 'Paiement annulé avec succès',
            'paiement': PaiementSerializer(paiement).data,
            'avoir': PaiementSerializer(avoir).data
        })

    @action(detail=False, methods=['get'])
    def stats(self, request):
        user = request.user
        if user.est_pdg() or user.est_drh():
            paiements = Paiement.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            paiements = Paiement.objects.filter(
                Q(facture__agence_id__in=agences_ids) | Q(
                    vente__agence_id__in=agences_ids)
            ).distinct()
        today = timezone.now().date()
        stats = {
            'total': paiements.count(),
            'total_montant': paiements.aggregate(total=Sum('montant'))['total'] or 0,
            'montant_jour': paiements.filter(date_paiement=today).aggregate(total=Sum('montant'))['total'] or 0,
            'par_methode': {},
            'par_statut': {}
        }
        for methode, label in Paiement.METHODES_PAIEMENT:
            qs = paiements.filter(methode=methode)
            stats['par_methode'][methode] = {
                'label': label,
                'count': qs.count(),
                'montant': qs.aggregate(total=Sum('montant'))['total'] or 0
            }
        for statut, label in Paiement.STATUT_PAIEMENT:
            qs = paiements.filter(statut=statut)
            stats['par_statut'][statut] = {
                'label': label,
                'count': qs.count(),
                'montant': qs.aggregate(total=Sum('montant'))['total'] or 0
            }
        return Response(stats)

# sales/views.py - FactureViewSet complet et corrigé


class FactureViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des factures
    """
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'type_facture', 'client', 'agence']
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
        if user.est_pdg() or user.est_drh():
            return Facture.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return Facture.objects.filter(agence_id__in=agences_ids)

    # ============================================================
    # ENREGISTRER UN PAIEMENT
    # ============================================================
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
                {'error': f'Le montant dépasse le total de la facture. Reste à payer: {facture.montant_restant} FCFA'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Mettre à jour la facture
        facture.montant_paye = nouveau_montant_paye
        facture.montant_restant = facture.total_ttc - nouveau_montant_paye

        # Mettre à jour le statut
        if facture.montant_paye >= facture.total_ttc:
            facture.status = 'paid'
        elif facture.montant_paye > 0:
            facture.status = 'partially_paid'

        facture.save()

        # Créer le paiement associé
        paiement = Paiement.objects.create(
            facture=facture,
            client=facture.client,
            vente=facture.vente,
            montant=montant,
            methode=serializer.validated_data['methode'],
            reference_externe=serializer.validated_data.get('reference', ''),
            notes=serializer.validated_data.get(
                'notes', f'Paiement du {timezone.now().strftime("%d/%m/%Y")}'),
            encaisse_par=request.user,
            statut='completed'
        )

        return Response({
            'success': True,
            'message': 'Paiement enregistré avec succès',
            'montant_paye': facture.montant_paye,
            'montant_restant': facture.montant_restant,
            'status': facture.status,
            'paiement': {
                'id': paiement.id,
                'reference': paiement.reference,
                'montant': paiement.montant,
                'methode': paiement.methode,
                'date_paiement': paiement.date_paiement
            }
        })

    # ============================================================
    # ANNULER UNE FACTURE
    # ============================================================
    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        facture = self.get_object()

        if facture.status == 'paid':
            return Response(
                {'error': 'Impossible d\'annuler une facture déjà payée'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if facture.status == 'cancelled':
            return Response(
                {'error': 'Cette facture est déjà annulée'},
                status=status.HTTP_400_BAD_REQUEST
            )

        motif = request.data.get('motif', 'Annulation sans motif')

        facture.status = 'cancelled'
        facture.notes = f"{facture.notes or ''}\n\nAnnulée le {timezone.now().strftime('%d/%m/%Y')} - Motif: {motif}"
        facture.save()

        return Response({
            'success': True,
            'message': 'Facture annulée avec succès',
            'status': facture.status
        })

    # ============================================================
    # RELANCER UNE FACTURE (envoyer un rappel)
    # ============================================================
    @action(detail=True, methods=['post'])
    def relancer(self, request, pk=None):
        facture = self.get_object()

        if facture.status == 'paid':
            return Response(
                {'error': 'Cette facture est déjà payée'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if facture.status == 'cancelled':
            return Response(
                {'error': 'Cette facture est annulée'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Ici vous pouvez ajouter l'envoi d'email de relance
        # Par exemple: send_reminder_email(facture)

        return Response({
            'success': True,
            'message': f'Relance envoyée pour la facture {facture.reference}',
            'date_relance': timezone.now().strftime('%d/%m/%Y à %H:%M')
        })

    # ============================================================
    # STATISTIQUES DES FACTURES
    # ============================================================
    @action(detail=False, methods=['get'])
    def stats(self, request):
        user = request.user

        # Récupérer les factures accessibles
        if user.est_pdg() or user.est_drh():
            factures = Facture.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            factures = Facture.objects.filter(agence_id__in=agences_ids)

        today = timezone.now().date()

        # Statistiques globales
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
            'montant_en_retard': 0
        }

        # Statistiques par statut
        for status_code, status_label in Facture.STATUS_CHOICES:
            qs = factures.filter(status=status_code)
            stats['par_statut'][status_code] = {
                'label': status_label,
                'count': qs.count(),
                'montant': qs.aggregate(total=Sum('total_ttc'))['total'] or 0,
                'paye': qs.aggregate(total=Sum('montant_paye'))['total'] or 0
            }

        # Statistiques par type
        for type_code, type_label in Facture.TYPE_FACTURE:
            qs = factures.filter(type_facture=type_code)
            stats['par_type'][type_code] = {
                'label': type_label,
                'count': qs.count(),
                'montant': qs.aggregate(total=Sum('total_ttc'))['total'] or 0
            }

        # Factures impayées (non payées et non annulées)
        factures_impayees = factures.exclude(status__in=['paid', 'cancelled'])
        stats['factures_impayees'] = factures_impayees.count()
        stats['montant_impayes'] = factures_impayees.aggregate(
            total=Sum('montant_restant')
        )['total'] or 0

        # Factures en retard
        factures_retard = factures.filter(
            status='overdue',
            date_echeance__lt=today
        )
        stats['factures_en_retard'] = factures_retard.count()
        stats['montant_en_retard'] = factures_retard.aggregate(
            total=Sum('montant_restant')
        )['total'] or 0

        # Factures du mois
        start_of_month = today.replace(day=1)
        factures_mois = factures.filter(date_facture__gte=start_of_month)
        stats['factures_mois'] = factures_mois.count()
        stats['montant_mois'] = factures_mois.aggregate(
            total=Sum('total_ttc'))['total'] or 0

        return Response(stats)

    # ============================================================
    # GÉNÉRATION DU PDF (CORRIGÉ)
    # ============================================================
    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        """
        Génère un PDF pour la facture
        """
        facture = self.get_object()
        buffer = BytesIO()

        # Configuration du document
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm
        )

        styles = getSampleStyleSheet()
        elements = []

        # Style personnalisé pour le titre
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            alignment=1,  # Centre
            spaceAfter=0.5*cm
        )

        # Style pour les en-têtes de section
        section_style = ParagraphStyle(
            'SectionStyle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#1e40af'),
            spaceAfter=0.3*cm,
            spaceBefore=0.5*cm
        )

        # ============================================================
        # EN-TÊTE avec logo et infos société
        # ============================================================
        # En-tête avec logo (optionnel)
        header_data = [
            ['SEYDI GROUP SARL', f'FACTURE {facture.reference}'],
            ['Solutions Digitales', ''],
            ['Dakar, Sénégal', ''],
            ['Tél: +221 33 123 45 67', ''],
            ['Email: contact@seydigroup.com', '']
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

        # Ligne de séparation
        elements.append(Table([['']], colWidths=[16*cm], style=[
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.grey)
        ]))
        elements.append(Spacer(1, 0.5*cm))

        # ============================================================
        # INFORMATIONS CLIENT ET FACTURE
        # ============================================================
        # Info Client
        client_info = []
        if facture.client:
            client_info = [
                ['INFORMATIONS CLIENT', 'DÉTAILS FACTURE'],
                ['', ''],
            ]

            # Client
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

            # Détails facture
            facture_details = [
                ['Date:', facture.date_facture.strftime('%d/%m/%Y')],
                ['Échéance:', facture.date_echeance.strftime('%d/%m/%Y')],
                ['Type:', facture.get_type_facture_display()],
                ['Statut:', facture.get_status_display()],
                ['Agence:', facture.agence.nom if facture.agence else '-'],
            ]

            # Créer les tableaux
            client_table = Table(client_details, colWidths=[4*cm, 7*cm])
            facture_table = Table(facture_details, colWidths=[4*cm, 7*cm])

            # Styliser
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

            # Tableau à deux colonnes
            two_cols = Table([[client_table, facture_table]],
                             colWidths=[11*cm, 11*cm])
            two_cols.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 11),
            ]))
            elements.append(two_cols)
        else:
            # Pas de client
            elements.append(
                Paragraph("Aucun client associé", styles['Normal']))

        elements.append(Spacer(1, 0.5*cm))

        # ============================================================
        # TABLEAU DES ARTICLES (depuis la vente)
        # ============================================================
        elements.append(Paragraph("ARTICLES", section_style))

        # Récupérer les items depuis la vente associée
        vente_items = facture.vente.items.all() if facture.vente else []

        # Préparer les données du tableau
        table_data = [
            ['Désignation', 'Référence', 'Qté', 'Prix HT', 'Total TTC']
        ]

        for item in vente_items:
            table_data.append([
                item.product.name[:50],
                item.product.reference[:20],
                str(item.quantity),
                f"{item.prix_unitaire:,.0f} FCFA",
                f"{item.total:,.0f} FCFA"
            ])

        if len(table_data) == 1:
            table_data.append(['Aucun article', '-', '-', '-', '-'])

        # Créer le tableau
        col_widths = [6*cm, 3*cm, 1.5*cm, 3*cm, 3*cm]
        table = Table(table_data, colWidths=col_widths, repeatRows=1)

        # Styliser le tableau
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

        # ============================================================
        # TOTAUX
        # ============================================================
        # Cadre des totaux
        totals_data = [
            ['Sous-total HT:', f"{facture.sous_total:,.0f} FCFA"],
            ['TVA (18%):', f"{facture.tva:,.0f} FCFA"],
            ['TOTAL TTC:', f"{facture.total_ttc:,.0f} FCFA"],
            ['Montant payé:', f"{facture.montant_paye:,.0f} FCFA"],
            ['Reste à payer:', f"{facture.montant_restant:,.0f} FCFA"],
        ]

        totals_table = Table(totals_data, colWidths=[8*cm, 6*cm])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 2), (1, 2), 12),
            ('FONTNAME', (0, 2), (1, 2), 'Helvetica-Bold'),
            ('TEXTCOLOR', (1, 4), (1, 4), colors.red),
            ('FONTNAME', (1, 4), (1, 4), 'Helvetica-Bold'),
            ('LINEABOVE', (0, 2), (-1, 2), 0.5, colors.grey),
            ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.grey),
        ]))

        elements.append(totals_table)
        elements.append(Spacer(1, 0.5*cm))

        # ============================================================
        # CONDITIONS DE PAIEMENT
        # ============================================================
        if facture.conditions_paiement:
            elements.append(Paragraph("CONDITIONS DE PAIEMENT", section_style))
            elements.append(
                Paragraph(facture.conditions_paiement, styles['Normal']))
            elements.append(Spacer(1, 0.3*cm))

        # ============================================================
        # NOTES
        # ============================================================
        if facture.notes:
            elements.append(Paragraph("NOTES", section_style))
            elements.append(Paragraph(facture.notes, styles['Normal']))
            elements.append(Spacer(1, 0.3*cm))

        # ============================================================
        # PIED DE PAGE
        # ============================================================
        if facture.pied_de_page:
            elements.append(
                Paragraph("INFORMATIONS COMPLÉMENTAIRES", section_style))
            elements.append(Paragraph(facture.pied_de_page, styles['Normal']))
            elements.append(Spacer(1, 0.5*cm))

        # ============================================================
        # SIGNATURES
        # ============================================================
        signature_data = [
            ['Le Client', 'L\'Entreprise'],
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

        # ============================================================
        # PIED DE PAGE GLOBAL
        # ============================================================
        footer_text = f"""
        <para align="center" fontSize="8" textColor="gray">
        SEYDI GROUP SARL - Capital social: 10 000 000 FCFA - RCCM: SN DKR 2023 B 123<br/>
        Adresse: Dakar, Sénégal - Tél: +221 33 123 45 67 - Email: contact@seydigroup.com<br/>
        Facture générée électroniquement le {timezone.now().strftime('%d/%m/%Y à %H:%M')} - Valide sans signature
        </para>
        """

        elements.append(Paragraph(footer_text, styles['Normal']))

        # Générer le PDF
        doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()

        # Retourner la réponse
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="facture_{facture.reference}.pdf"'
        response['Content-Length'] = len(pdf)

        return response

    # ============================================================
    # ACTION POUR RÉCUPÉRER LES PAIEMENTS D'UNE FACTURE
    # ============================================================
    @action(detail=True, methods=['get'])
    def paiements(self, request, pk=None):
        facture = self.get_object()
        paiements = facture.paiements.all()
        serializer = PaiementSerializer(paiements, many=True)
        return Response(serializer.data)


class DashboardVentesView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, HasAgenceAccess]

    def get(self, request):
        user = request.user
        if user.est_pdg() or user.est_drh():
            ventes = Vente.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            ventes = Vente.objects.filter(agence_id__in=agences_ids)
        today = timezone.now().date()
        ventes_aujourdhui = ventes.filter(date_vente__date=today)
        return Response({
            'total_ventes': ventes.count(),
            'total_ca': ventes.filter(status='completed').aggregate(total=Sum('total'))['total'] or 0,
            'ca_jour': ventes_aujourdhui.filter(status='completed').aggregate(total=Sum('total'))['total'] or 0,
            'ventes_en_attente': ventes.filter(status='pending_approval').count(),
            'impayes': ventes.filter(est_paye=False, status__in=['approved', 'completed']).aggregate(total=Sum('montant_du'))['total'] or 0,
        })
