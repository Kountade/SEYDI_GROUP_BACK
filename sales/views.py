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
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
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


class VenteViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
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
    
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def submit(self, request, pk=None):
        vente = self.get_object()
        if vente.status != 'draft':
            return Response({'error': f'Seule une vente en brouillon peut être soumise. Statut actuel: {vente.status}'}, 
                            status=status.HTTP_400_BAD_REQUEST)
        warehouse = vente.agence.warehouses.filter(is_default=True).first()
        if not warehouse:
            warehouse = vente.agence.warehouses.filter(is_active=True).first()
        if not warehouse:
            return Response({'error': f'Aucun entrepôt configuré pour l\'agence {vente.agence.nom}.'},
                            status=status.HTTP_400_BAD_REQUEST)
        stock_insuffisant = []
        for item in vente.items.all():
            stock = WarehouseStock.objects.filter(product=item.product, warehouse=warehouse, variant=item.variant).first()
            if not stock:
                stock_insuffisant.append({'product': item.product.name, 'message': 'Stock non configuré dans cet entrepôt'})
            elif stock.quantity < item.quantity:
                stock_insuffisant.append({'product': item.product.name, 'disponible': stock.quantity,
                                          'demande': item.quantity, 'manquant': item.quantity - stock.quantity})
        if stock_insuffisant:
            return Response({'error': 'Stock insuffisant pour soumettre la vente', 'details': stock_insuffisant},
                            status=status.HTTP_400_BAD_REQUEST)
        vente.status = 'pending_approval'
        vente.save()
        return Response({'success': True, 'message': 'Vente soumise avec succès', 'data': VenteDetailSerializer(vente).data})
    
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        vente = self.get_object()
        user = request.user
        if not user.est_chef_agence() and not user.est_pdg():
            return Response({'error': 'Seul le chef d\'agence ou le PDG peut approuver une vente'},
                            status=status.HTTP_403_FORBIDDEN)
        if not user.est_pdg() and not user.peut_acceder_agence(vente.agence.id):
            return Response({'error': 'Vous n\'avez pas accès à cette agence'}, status=status.HTTP_403_FORBIDDEN)
        if vente.status != 'pending_approval':
            return Response({'error': f'Seule une vente en attente peut être approuvée. Statut actuel: {vente.status}'},
                            status=status.HTTP_400_BAD_REQUEST)
        warehouse = vente.agence.warehouses.filter(is_default=True).first()
        if not warehouse:
            warehouse = vente.agence.warehouses.filter(is_active=True).first()
        if not warehouse:
            from inventaire.models import get_default_warehouse
            warehouse = get_default_warehouse(vente.agence)
        if not warehouse:
            return Response({'error': f'Aucun entrepôt configuré pour l\'agence {vente.agence.nom}.'},
                            status=status.HTTP_400_BAD_REQUEST)
        stock_insuffisant = []
        for item in vente.items.all():
            try:
                stock = WarehouseStock.objects.get(product=item.product, warehouse=warehouse, variant=item.variant)
                if stock.quantity < item.quantity:
                    stock_insuffisant.append({'product': item.product.name, 'disponible': stock.quantity,
                                              'demande': item.quantity, 'manquant': item.quantity - stock.quantity})
            except WarehouseStock.DoesNotExist:
                stock_insuffisant.append({'product': item.product.name, 'message': 'Produit non trouvé dans l\'entrepôt',
                                          'demande': item.quantity})
        if stock_insuffisant:
            return Response({'error': 'Stock insuffisant pour approuver la vente', 'details': stock_insuffisant},
                            status=status.HTTP_400_BAD_REQUEST)
        for item in vente.items.all():
            stock = WarehouseStock.objects.get(product=item.product, warehouse=warehouse, variant=item.variant)
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
            total_stock = WarehouseStock.objects.filter(product=item.product).aggregate(total=Sum('quantity'))['total'] or 0
            item.product.stock_quantity = total_stock
            item.product.save()
        vente.status = 'approved'
        vente.approved_by = user
        vente.date_approbation = timezone.now()
        vente.save()
        return Response({'success': True, 'message': 'Vente approuvée avec succès', 'data': VenteDetailSerializer(vente).data})
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        vente = self.get_object()
        if vente.status != 'pending_approval':
            return Response({'error': f'Seule une vente en attente peut être rejetée. Statut actuel: {vente.status}'},
                            status=status.HTTP_400_BAD_REQUEST)
        motif = request.data.get('motif')
        if not motif:
            return Response({'error': 'Un motif de rejet est requis'}, status=status.HTTP_400_BAD_REQUEST)
        vente.status = 'rejected'
        vente.motif_rejet = motif
        vente.save()
        return Response({'success': True, 'message': 'Vente rejetée', 'data': VenteDetailSerializer(vente).data})
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        vente = self.get_object()
        if vente.status != 'approved':
            return Response({'error': f'Seule une vente approuvée peut être complétée. Statut actuel: {vente.status}'},
                            status=status.HTTP_400_BAD_REQUEST)
        if vente.montant_paye < vente.total:
            reste = vente.total - vente.montant_paye
            return Response({'error': f'Vente non entièrement payée. Reste à payer: {reste} FCFA'},
                            status=status.HTTP_400_BAD_REQUEST)
        vente.status = 'completed'
        vente.save()
        return Response({'success': True, 'message': 'Vente complétée avec succès', 'data': VenteDetailSerializer(vente).data})
    
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, pk=None):
        vente = self.get_object()
        if vente.status in ['completed', 'cancelled']:
            return Response({'error': f'Cette vente ne peut pas être annulée car elle est {vente.status}'},
                            status=status.HTTP_400_BAD_REQUEST)
        for item in vente.items.filter(stock_preleve=True):
            if item.warehouse_source:
                try:
                    stock = WarehouseStock.objects.get(product=item.product, warehouse=item.warehouse_source, variant=item.variant)
                    stock.quantity += item.quantity
                    stock.save()
                    StockMovement.objects.create(
                        movement_type='in', reference_type='sale', reference_id=vente.id,
                        product=item.product, variant=item.variant, quantity=item.quantity,
                        to_warehouse=item.warehouse_source, unit_price=item.prix_unitaire,
                        notes=f"Annulation vente {vente.reference}", created_by=request.user
                    )
                    total_stock = WarehouseStock.objects.filter(product=item.product).aggregate(total=Sum('quantity'))['total'] or 0
                    item.product.stock_quantity = total_stock
                    item.product.save()
                except WarehouseStock.DoesNotExist:
                    pass
        vente.status = 'cancelled'
        vente.save()
        return Response({'success': True, 'message': 'Vente annulée avec succès', 'data': VenteDetailSerializer(vente).data})
    
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
            'impayes': ventes.filter(est_paye=False, status__in=['approved', 'completed']).aggregate(total=Sum('montant_du'))['total'] or 0
        })


class PaiementViewSet(viewsets.ModelViewSet):
    serializer_class = PaiementSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['facture', 'client', 'vente', 'methode', 'statut']
    search_fields = ['reference', 'reference_externe', 'client__nom', 'facture__reference']
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
                Q(facture__agence_id__in=agences_ids) | Q(vente__agence_id__in=agences_ids)
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


class FactureViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['status', 'type_facture', 'client', 'agence']
    search_fields = ['reference', 'client__nom']
    
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
    
    @action(detail=True, methods=['post'])
    def enregistrer_paiement(self, request, pk=None):
        facture = self.get_object()
        serializer = FacturePaiementSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        montant = serializer.validated_data['montant']
        nouveau_montant_paye = facture.montant_paye + montant
        if nouveau_montant_paye > facture.total_ttc:
            return Response({'error': 'Montant dépasse le total'}, status=status.HTTP_400_BAD_REQUEST)
        facture.montant_paye = nouveau_montant_paye
        facture.montant_restant = facture.total_ttc - nouveau_montant_paye
        facture.save()
        # Créer le paiement associé
        Paiement.objects.create(
            facture=facture,
            client=facture.client,
            vente=facture.vente,
            montant=montant,
            methode=serializer.validated_data['methode'],
            reference_externe=serializer.validated_data.get('reference', ''),
            notes=serializer.validated_data.get('notes', ''),
            encaisse_par=request.user,
            statut='completed'
        )
        return Response({
            'success': True,
            'montant_paye': facture.montant_paye,
            'montant_restant': facture.montant_restant
        })
    
    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        facture = self.get_object()
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = []
        title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=24, alignment=1)
        elements.append(Paragraph(f"FACTURE {facture.reference}", title_style))
        elements.append(Spacer(1, 0.5*cm))
        if facture.client:
            elements.append(Paragraph(f"Client: {facture.client.nom}", styles['Heading4']))
        details_data = [
            ['Date:', facture.date_facture.strftime('%d/%m/%Y')],
            ['Échéance:', facture.date_echeance.strftime('%d/%m/%Y')],
            ['Statut:', facture.get_status_display()],
        ]
        details_table = Table(details_data, colWidths=[4*cm, 8*cm])
        details_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.5, colors.grey)]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.5*cm))
        # Tableau des articles
        table_data = [['Description', 'Qté', 'Prix HT', 'Total TTC']]
        for item in facture.items.all():
            table_data.append([
                item.description[:50], str(item.quantite),
                f"{item.prix_unitaire_ht:,.0f} FCFA",
                f"{item.montant_ttc:,.0f} FCFA"
            ])
        table = Table(table_data, colWidths=[6*cm, 2*cm, 3*cm, 3*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.5*cm))
        totals_data = [
            ['Sous-total:', f"{facture.sous_total:,.0f} FCFA"],
            ['TVA:', f"{facture.tva:,.0f} FCFA"],
            ['TOTAL:', f"{facture.total_ttc:,.0f} FCFA"],
            ['Payé:', f"{facture.montant_paye:,.0f} FCFA"],
            ['Reste:', f"{facture.montant_restant:,.0f} FCFA"],
        ]
        totals_table = Table(totals_data, colWidths=[6*cm, 6*cm])
        elements.append(totals_table)
        doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="facture_{facture.reference}.pdf"'
        return response


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