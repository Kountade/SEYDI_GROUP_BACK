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
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from io import BytesIO
from django.http import HttpResponse

from .models import *
from .serializers import *
from users.permissions import HasAgenceAccess, IsPDG, IsChefAgence
from inventaire.models import WarehouseStock, StockMovement

# sales/views.py - ClientViewSet complet

from rest_framework import viewsets, status, filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from .models import Client
from .serializers import ClientSerializer
from users.permissions import HasAgenceAccess

# sales/views.py - ClientViewSet sécurisé

from rest_framework import viewsets, status, filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from .models import Client
from .serializers import ClientSerializer
from users.permissions import HasAgenceAccess

# sales/views.py - ClientViewSet corrigé

from rest_framework import viewsets, status, filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from .models import Client
from .serializers import ClientSerializer
from users.permissions import HasAgenceAccess


class ClientViewSet(viewsets.ModelViewSet):
    serializer_class = ClientSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['client_type', 'est_revendeur', 'is_active']
    search_fields = ['nom', 'prenom', 'email', 'telephone', 'raison_sociale']
    ordering_fields = ['nom', 'created_at']
    
    def get_queryset(self):
        user = self.request.user
        
        # Si l'utilisateur n'est pas authentifié
        if not user or not user.is_authenticated:
            return Client.objects.none()
        
        # PDG et DRH voient TOUS les clients
        if user.est_pdg() or user.est_drh():
            return Client.objects.all()
        
        # Récupérer les agences de l'utilisateur
        agences = user.get_agences()
        
        if not agences.exists():
            return Client.objects.none()
        
        # Récupérer les IDs des agences
        agences_ids = list(agences.values_list('id', flat=True))
        
        # Pour Chef d'agence et Commercial: clients des ventes de leurs agences
        # OU clients créés par eux
        clients = Client.objects.filter(
            Q(ventes__agence_id__in=agences_ids) |  # Clients qui ont des ventes dans leurs agences
            Q(created_by=user)  # Clients créés par l'utilisateur
        ).distinct()
        
        return clients
    
    def list(self, request, *args, **kwargs):
        """Liste des clients"""
        try:
            queryset = self.filter_queryset(self.get_queryset())
            
            # Pagination
            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)
            
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def perform_create(self, serializer):
        """À la création, associer automatiquement l'agence de l'utilisateur"""
        user = self.request.user
        
        # Récupérer l'agence principale de l'utilisateur
        agence_principale = user.get_agence_principale()
        
        # Sauvegarder le client
        client = serializer.save(created_by=user)
        
        # Optionnel: Créer automatiquement une vente pour associer le client à l'agence
        # Si vous voulez que le client soit visible immédiatement
        if agence_principale and not client.ventes.exists():
            # Créer une petite vente de 0 FCFA pour associer le client à l'agence
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
            return Response({'error': 'Seule une vente en brouillon peut être soumise'}, status=400)
        
        warehouse = vente.agence.warehouses.filter(is_default=True).first()
        if not warehouse:
            return Response({'error': f"Entrepôt non configuré"}, status=400)
        
        for item in vente.items.all():
            stock = WarehouseStock.objects.filter(
                product=item.product, warehouse=warehouse, variant=item.variant
            ).first()
            
            if not stock or stock.quantity < item.quantity:
                return Response({
                    'error': f"Stock insuffisant pour {item.product.name}"
                }, status=400)
        
        vente.status = 'pending_approval'
        vente.save()
        
        return Response(VenteDetailSerializer(vente).data)
    
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        vente = self.get_object()
        user = request.user
        
        if not user.est_chef_agence() and not user.est_pdg():
            return Response({'error': 'Seul le chef d\'agence peut approuver'}, status=403)
        
        if not user.est_pdg() and not user.peut_acceder_agence(vente.agence.id):
            return Response({'error': 'Non autorisé'}, status=403)
        
        if vente.status != 'pending_approval':
            return Response({'error': 'Vente non en attente'}, status=400)
        
        warehouse = vente.agence.warehouses.filter(is_default=True).first()
        if not warehouse:
            return Response({'error': 'Entrepôt non configuré'}, status=400)
        
        for item in vente.items.all():
            stock = WarehouseStock.objects.get(
                product=item.product, warehouse=warehouse, variant=item.variant
            )
            
            if stock.quantity < item.quantity:
                return Response({'error': f"Stock insuffisant pour {item.product.name}"}, status=400)
            
            stock.quantity -= item.quantity
            stock.save()
            
            item.stock_preleve = True
            item.warehouse_source = warehouse
            item.save()
            
            StockMovement.objects.create(
                movement_type='out', reference_type='sale', reference_id=vente.id,
                product=item.product, variant=item.variant, quantity=item.quantity,
                from_warehouse=warehouse, unit_price=item.prix_unitaire,
                notes=f"Vente {vente.reference}", created_by=user
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
        
        return Response({'success': True, 'message': 'Vente approuvée'})
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        vente = self.get_object()
        
        if vente.status != 'pending_approval':
            return Response({'error': 'Vente non en attente'}, status=400)
        
        motif = request.data.get('motif')
        if not motif:
            return Response({'error': 'Motif requis'}, status=400)
        
        vente.status = 'rejected'
        vente.motif_rejet = motif
        vente.save()
        
        return Response({'success': True, 'message': 'Vente rejetée'})
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        vente = self.get_object()
        
        if vente.status != 'approved':
            return Response({'error': 'Vente non approuvée'}, status=400)
        
        if vente.montant_paye < vente.total:
            return Response({'error': 'Vente non entièrement payée'}, status=400)
        
        vente.status = 'completed'
        vente.save()
        
        return Response({'success': True, 'message': 'Vente complétée'})


class PaiementViewSet(viewsets.ModelViewSet):
    serializer_class = PaiementSerializer
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['vente', 'methode']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return PaiementCreateSerializer
        return PaiementSerializer
    
    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return Paiement.objects.all()
        agences_ids = user.get_agences().values_list('id', flat=True)
        return Paiement.objects.filter(vente__agence_id__in=agences_ids)
    
    def perform_create(self, serializer):
        paiement = serializer.save()
        vente = paiement.vente
        
        total_paye = vente.paiements.filter(statut='completed').aggregate(
            total=Sum('montant')
        )['total'] or 0
        
        vente.montant_paye = total_paye
        vente.montant_du = vente.total - total_paye
        vente.est_paye = total_paye >= vente.total
        vente.save()


class FactureViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasAgenceAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['statut', 'type_facture', 'client', 'agence']
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
            return Response(serializer.errors, status=400)
        
        montant = serializer.validated_data['montant']
        nouveau_montant_paye = facture.montant_paye + montant
        
        if nouveau_montant_paye > facture.total_ttc:
            return Response({'error': 'Montant dépasse le total'}, status=400)
        
        facture.montant_paye = nouveau_montant_paye
        facture.montant_restant = facture.total_ttc - nouveau_montant_paye
        facture.save()
        
        Paiement.objects.create(
            vente=facture.vente,
            montant=montant,
            methode=serializer.validated_data['methode'],
            reference=serializer.validated_data.get('reference', ''),
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
            ['Statut:', facture.get_statut_display()],
        ]
        
        details_table = Table(details_data, colWidths=[4*cm, 8*cm])
        details_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.5, colors.grey)]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.5*cm))
        
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
            'impayes': ventes.filter(est_paye=False, status__in=['approved', 'completed']).aggregate(
                total=Sum('montant_du')
            )['total'] or 0,
        })