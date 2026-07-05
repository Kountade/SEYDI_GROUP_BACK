"""
Views pour l'application Comptabilité / Finance
"""

from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from datetime import timedelta
from .models import *
from .serializers import *
from .permissions import *
from users.permissions import IsPDG, IsDRH, IsPDGOrDRH, IsChefAgence, IsComptable


# ============================================================
# PLAN COMPTABLE VIEWSET
# ============================================================

class PlanComptableViewset(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion du plan comptable
    """
    permission_classes = [permissions.IsAuthenticated, IsPDGOrDRH | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code', 'nom', 'description']
    ordering_fields = ['code', 'nom', 'type_compte', 'niveau']

    def get_serializer_class(self):
        if self.action == 'create':
            return PlanComptableCreateSerializer
        return PlanComptableSerializer

    def get_queryset(self):
        queryset = PlanComptable.objects.filter(is_active=True)
        
        # Filtrer par type
        type_compte = self.request.query_params.get('type_compte')
        if type_compte:
            queryset = queryset.filter(type_compte=type_compte)
        
        # Filtrer par niveau
        niveau = self.request.query_params.get('niveau')
        if niveau:
            queryset = queryset.filter(niveau=niveau)
        
        # Filtrer par classe
        classe = self.request.query_params.get('classe')
        if classe:
            queryset = queryset.filter(classe=classe)
        
        return queryset

    @action(detail=True, methods=['get'])
    def soldes(self, request, pk=None):
        """Récupère les soldes d'un compte"""
        compte = self.get_object()
        
        # Récupérer les soldes pour cette agence
        agence_id = request.query_params.get('agence_id')
        if not agence_id:
            return Response(
                {"error": "agence_id est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        soldes = SoldeCompte.objects.filter(
            compte=compte,
            agence_id=agence_id
        ).order_by('-date_solde')
        
        serializer = SoldeCompteSerializer(soldes, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def lignes_ecritures(self, request, pk=None):
        """Récupère toutes les lignes d'écriture d'un compte"""
        compte = self.get_object()
        
        agence_id = request.query_params.get('agence_id')
        if not agence_id:
            return Response(
                {"error": "agence_id est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        lignes = LigneEcriture.objects.filter(
            compte=compte,
            ecriture__agence_id=agence_id,
            ecriture__status='valide'
        ).select_related('ecriture').order_by('-ecriture__date_ecriture')
        
        serializer = LigneEcritureSerializer(lignes, many=True)
        return Response(serializer.data)


# ============================================================
# JOURNAL VIEWSET
# ============================================================

class JournalViewset(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des journaux
    """
    permission_classes = [permissions.IsAuthenticated, IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code', 'nom', 'description']
    ordering_fields = ['code', 'nom', 'type_journal']

    def get_serializer_class(self):
        if self.action == 'create':
            return JournalCreateSerializer
        return JournalSerializer

    def get_queryset(self):
        user = self.request.user
        
        if user.est_pdg() or user.est_drh():
            return Journal.objects.filter(is_active=True)
        
        # Filtrer par agences accessibles
        agences_ids = user.get_agences().values_list('id', flat=True)
        return Journal.objects.filter(agence_id__in=agences_ids, is_active=True)

    @action(detail=True, methods=['get'])
    def ecritures(self, request, pk=None):
        """Récupère les écritures d'un journal"""
        journal = self.get_object()
        
        status_filter = request.query_params.get('status')
        date_debut = request.query_params.get('date_debut')
        date_fin = request.query_params.get('date_fin')
        
        ecritures = journal.ecritures.all()
        
        if status_filter:
            ecritures = ecritures.filter(status=status_filter)
        
        if date_debut:
            ecritures = ecritures.filter(date_ecriture__gte=date_debut)
        
        if date_fin:
            ecritures = ecritures.filter(date_ecriture__lte=date_fin)
        
        serializer = EcritureSerializer(ecritures, many=True)
        return Response(serializer.data)


# ============================================================
# ÉCRITURES VIEWSET
# ============================================================

class EcritureViewset(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des écritures comptables
    """
    permission_classes = [permissions.IsAuthenticated, IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference', 'libelle', 'piece_justificative']
    ordering_fields = ['date_ecriture', 'date_comptable', 'created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return EcritureCreateSerializer
        return EcritureSerializer

    def get_queryset(self):
        user = self.request.user
        
        if user.est_pdg() or user.est_drh():
            queryset = Ecriture.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = Ecriture.objects.filter(agence_id__in=agences_ids)
        
        # Filtres
        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        journal_id = self.request.query_params.get('journal_id')
        if journal_id:
            queryset = queryset.filter(journal_id=journal_id)
        
        date_debut = self.request.query_params.get('date_debut')
        if date_debut:
            queryset = queryset.filter(date_ecriture__gte=date_debut)
        
        date_fin = self.request.query_params.get('date_fin')
        if date_fin:
            queryset = queryset.filter(date_ecriture__lte=date_fin)
        
        return queryset.select_related('journal', 'agence', 'created_by')

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        """Valide une écriture"""
        ecriture = self.get_object()
        
        if ecriture.status == 'valide':
            return Response(
                {"error": "Cette écriture est déjà validée"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not ecriture.est_equilibree:
            return Response(
                {"error": "L'écriture n'est pas équilibrée"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        ecriture.valider(request.user)
        
        # Mettre à jour les soldes
        self._mettre_a_jour_soldes(ecriture)
        
        serializer = self.get_serializer(ecriture)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        """Annule une écriture"""
        ecriture = self.get_object()
        
        if ecriture.status == 'annulee':
            return Response(
                {"error": "Cette écriture est déjà annulée"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if ecriture.status == 'cloturee':
            return Response(
                {"error": "Cette écriture est clôturée et ne peut pas être annulée"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        ecriture.status = 'annulee'
        ecriture.save()
        
        serializer = self.get_serializer(ecriture)
        return Response(serializer.data)

    def _mettre_a_jour_soldes(self, ecriture):
        """Met à jour les soldes des comptes après validation"""
        for ligne in ecriture.lignes.all():
            # Mettre à jour ou créer le solde pour la date
            solde, created = SoldeCompte.objects.get_or_create(
                compte=ligne.compte,
                agence=ecriture.agence,
                date_solde=ecriture.date_comptable,
                defaults={
                    'debit': ligne.debit,
                    'credit': ligne.credit,
                    'solde': ligne.debit - ligne.credit,
                    'debit_periode': ligne.debit,
                    'credit_periode': ligne.credit
                }
            )
            
            if not created:
                solde.debit += ligne.debit
                solde.credit += ligne.credit
                solde.solde = solde.debit - solde.credit
                solde.debit_periode += ligne.debit
                solde.credit_periode += ligne.credit
                solde.save()


# ============================================================
# BALANCE VIEWSET
# ============================================================

class BalanceViewset(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des balances
    """
    permission_classes = [permissions.IsAuthenticated, IsPDGOrDRH | IsChefAgence | IsComptable]

    def get_serializer_class(self):
        if self.action == 'create':
            return BalanceCreateSerializer
        return BalanceSerializer

    def get_queryset(self):
        user = self.request.user
        
        if user.est_pdg() or user.est_drh():
            queryset = Balance.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = Balance.objects.filter(agence_id__in=agences_ids)
        
        # Filtres
        type_balance = self.request.query_params.get('type_balance')
        if type_balance:
            queryset = queryset.filter(type_balance=type_balance)
        
        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.select_related('agence', 'created_by')

    def create(self, request, *args, **kwargs):
        """Génère une balance à partir des écritures"""
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            balance = serializer.save(created_by=request.user)
            
            # Générer les lignes de balance
            self._generer_lignes_balance(balance)
            
            return Response(BalanceSerializer(balance).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def _generer_lignes_balance(self, balance):
        """Génère les lignes de la balance"""
        # Récupérer tous les comptes actifs de l'agence
        comptes = PlanComptable.objects.filter(is_active=True)
        
        for compte in comptes:
            # Solde initial (avant date_debut)
            solde_initial = self._calculer_solde_initial(
                compte, balance.agence, balance.date_debut
            )
            
            # Mouvements de la période
            mouvements = self._calculer_mouvements_periode(
                compte, balance.agence, balance.date_debut, balance.date_fin
            )
            
            LigneBalance.objects.create(
                balance=balance,
                compte=compte,
                solde_initial_debit=solde_initial['debit'],
                solde_initial_credit=solde_initial['credit'],
                mouvement_debit=mouvements['debit'],
                mouvement_credit=mouvements['credit'],
                solde_final_debit=solde_initial['debit'] + mouvements['debit'],
                solde_final_credit=solde_initial['credit'] + mouvements['credit']
            )

    def _calculer_solde_initial(self, compte, agence, date_debut):
        """Calcule le solde initial d'un compte"""
        # Récupérer le dernier solde avant la date_debut
        solde = SoldeCompte.objects.filter(
            compte=compte,
            agence=agence,
            date_solde__lt=date_debut
        ).order_by('-date_solde').first()
        
        if solde:
            return {'debit': solde.debit, 'credit': solde.credit}
        return {'debit': 0, 'credit': 0}

    def _calculer_mouvements_periode(self, compte, agence, date_debut, date_fin):
        """Calcule les mouvements d'une période"""
        # Récupérer les soldes de la période
        soldes = SoldeCompte.objects.filter(
            compte=compte,
            agence=agence,
            date_solde__gte=date_debut,
            date_solde__lte=date_fin
        )
        
        total_debit = soldes.aggregate(total=Sum('debit_periode'))['total'] or 0
        total_credit = soldes.aggregate(total=Sum('credit_periode'))['total'] or 0
        
        return {'debit': total_debit, 'credit': total_credit}


# ============================================================
# FACTURES COMPTABLES VIEWSET
# ============================================================

class FactureComptableViewset(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des factures comptables
    """
    permission_classes = [permissions.IsAuthenticated, IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference', 'client__nom', 'fournisseur__company_name']
    ordering_fields = ['date_facture', 'date_echeance', 'montant_ttc']

    def get_serializer_class(self):
        if self.action == 'create':
            return FactureComptableCreateSerializer
        return FactureComptableSerializer

    def get_queryset(self):
        user = self.request.user
        
        if user.est_pdg() or user.est_drh():
            queryset = FactureComptable.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = FactureComptable.objects.filter(agence_id__in=agences_ids)
        
        # Filtres
        type_facture = self.request.query_params.get('type_facture')
        if type_facture:
            queryset = queryset.filter(type_facture=type_facture)
        
        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        client_id = self.request.query_params.get('client_id')
        if client_id:
            queryset = queryset.filter(client_id=client_id)
        
        fournisseur_id = self.request.query_params.get('fournisseur_id')
        if fournisseur_id:
            queryset = queryset.filter(fournisseur_id=fournisseur_id)
        
        return queryset.select_related('agence', 'client', 'fournisseur', 'created_by')


# ============================================================
# RÈGLEMENTS VIEWSET
# ============================================================

class ReglementViewset(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des règlements
    """
    permission_classes = [permissions.IsAuthenticated, IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['reference', 'client__nom', 'fournisseur__company_name', 'reference_externe']
    ordering_fields = ['date_reglement', 'montant']

    def get_serializer_class(self):
        if self.action == 'create':
            return ReglementCreateSerializer
        return ReglementSerializer

    def get_queryset(self):
        user = self.request.user
        
        if user.est_pdg() or user.est_drh():
            queryset = Reglement.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = Reglement.objects.filter(agence_id__in=agences_ids)
        
        # Filtres
        type_reglement = self.request.query_params.get('type_reglement')
        if type_reglement:
            queryset = queryset.filter(type_reglement=type_reglement)
        
        mode_reglement = self.request.query_params.get('mode_reglement')
        if mode_reglement:
            queryset = queryset.filter(mode_reglement=mode_reglement)
        
        client_id = self.request.query_params.get('client_id')
        if client_id:
            queryset = queryset.filter(client_id=client_id)
        
        fournisseur_id = self.request.query_params.get('fournisseur_id')
        if fournisseur_id:
            queryset = queryset.filter(fournisseur_id=fournisseur_id)
        
        return queryset.select_related('agence', 'client', 'fournisseur', 'facture', 'created_by')

    def create(self, request, *args, **kwargs):
        """Crée un règlement et met à jour la facture associée"""
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            reglement = serializer.save(created_by=request.user)
            
            # Mettre à jour la facture
            if reglement.facture:
                self._mettre_a_jour_facture(reglement.facture)
            
            return Response(ReglementSerializer(reglement).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def _mettre_a_jour_facture(self, facture):
        """Met à jour le statut de la facture après un règlement"""
        total_paye = facture.reglements.aggregate(
            total=Sum('montant')
        )['total'] or 0
        
        facture.montant_paye = total_paye
        facture.montant_restant = facture.montant_ttc - total_paye
        
        if total_paye >= facture.montant_ttc:
            facture.status = 'payee'
        elif total_paye > 0:
            facture.status = 'partielle'
        elif facture.date_echeance < timezone.now().date():
            facture.status = 'impayee'
        
        facture.save()


# ============================================================
# INDICATEURS VIEWSET
# ============================================================

class IndicateurViewset(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des indicateurs financiers
    """
    permission_classes = [permissions.IsAuthenticated, IsPDGOrDRH | IsChefAgence | IsComptable]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nom', 'code', 'description']
    ordering_fields = ['valeur', 'date_calcul']

    def get_serializer_class(self):
        if self.action == 'create':
            return IndicateurCreateSerializer
        return IndicateurFinancierSerializer

    def get_queryset(self):
        user = self.request.user
        
        if user.est_pdg() or user.est_drh():
            queryset = IndicateurFinancier.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = IndicateurFinancier.objects.filter(agence_id__in=agences_ids)
        
        # Filtres
        type_indicateur = self.request.query_params.get('type_indicateur')
        if type_indicateur:
            queryset = queryset.filter(type_indicateur=type_indicateur)
        
        date = self.request.query_params.get('date')
        if date:
            queryset = queryset.filter(date_calcul=date)
        
        return queryset.select_related('agence')


# ============================================================
# CLÔTURE VIEWSET
# ============================================================

class ClotureViewset(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des clôtures comptables
    """
    permission_classes = [permissions.IsAuthenticated, IsPDGOrDRH | IsComptable]

    def get_serializer_class(self):
        if self.action == 'create':
            return ClotureCreateSerializer
        return ClotureComptableSerializer

    def get_queryset(self):
        user = self.request.user
        
        if user.est_pdg() or user.est_drh():
            queryset = ClotureComptable.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = ClotureComptable.objects.filter(agence_id__in=agences_ids)
        
        # Filtres
        type_cloture = self.request.query_params.get('type_cloture')
        if type_cloture:
            queryset = queryset.filter(type_cloture=type_cloture)
        
        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.select_related('agence', 'created_by', 'closed_by')


# ============================================================
# ANALYSE VIEWSET
# ============================================================

class AnalyseViewset(viewsets.ModelViewSet):
    """
    ViewSet pour la gestion des analyses financières
    """
    permission_classes = [permissions.IsAuthenticated, IsPDGOrDRH | IsChefAgence | IsComptable]

    def get_serializer_class(self):
        if self.action == 'create':
            return AnalyseCreateSerializer
        return AnalyseFinanciereSerializer

    def get_queryset(self):
        user = self.request.user
        
        if user.est_pdg() or user.est_drh():
            queryset = AnalyseFinanciere.objects.all()
        else:
            agences_ids = user.get_agences().values_list('id', flat=True)
            queryset = AnalyseFinanciere.objects.filter(agence_id__in=agences_ids)
        
        # Filtres
        type_analyse = self.request.query_params.get('type_analyse')
        if type_analyse:
            queryset = queryset.filter(type_analyse=type_analyse)
        
        return queryset.select_related('agence', 'created_by')


# ============================================================
# RAPPORTS ET TABLEAUX DE BORD
# ============================================================

from rest_framework.views import APIView


class DashboardView(APIView):
    """
    Vue pour le tableau de bord financier
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')
        if not agence_id:
            return Response(
                {"error": "agence_id est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            agence = Agence.objects.get(id=agence_id)
        except Agence.DoesNotExist:
            return Response(
                {"error": "Agence non trouvée"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Vérifier les permissions
        if not request.user.peut_acceder_agence(agence_id):
            return Response(
                {"error": "Permission denied"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Date actuelle
        now = timezone.now().date()
        debut_mois = now.replace(day=1)
        
        # 1. Chiffre d'affaires du mois
        ca_mois = FactureComptable.objects.filter(
            agence=agence,
            type_facture='client',
            date_facture__gte=debut_mois,
            date_facture__lte=now,
            status__in=['payee', 'partielle']
        ).aggregate(total=Sum('montant_ttc'))['total'] or 0
        
        # 2. CA mois précédent
        mois_precedent = debut_mois - timedelta(days=1)
        debut_mois_precedent = mois_precedent.replace(day=1)
        ca_mois_precedent = FactureComptable.objects.filter(
            agence=agence,
            type_facture='client',
            date_facture__gte=debut_mois_precedent,
            date_facture__lte=mois_precedent,
            status__in=['payee', 'partielle']
        ).aggregate(total=Sum('montant_ttc'))['total'] or 0
        
        # 3. Achats du mois
        achats_mois = FactureComptable.objects.filter(
            agence=agence,
            type_facture='fournisseur',
            date_facture__gte=debut_mois,
            date_facture__lte=now
        ).aggregate(total=Sum('montant_ttc'))['total'] or 0
        
        # 4. Trésorerie
        encaissements = Reglement.objects.filter(
            agence=agence,
            type_reglement='client',
            date_reglement__lte=now
        ).aggregate(total=Sum('montant'))['total'] or 0
        
        decaissements = Reglement.objects.filter(
            agence=agence,
            type_reglement='fournisseur',
            date_reglement__lte=now
        ).aggregate(total=Sum('montant'))['total'] or 0
        
        tresorerie = encaissements - decaissements
        
        # 5. Alertes
        alertes = []
        
        # Factures impayées
        factures_impayees = FactureComptable.objects.filter(
            agence=agence,
            status='impayee'
        ).count()
        if factures_impayees > 0:
            alertes.append({
                'type': 'warning',
                'message': f'{factures_impayees} factures impayées',
                'count': factures_impayees
            })
        
        # Dettes fournisseurs
        dettes_fournisseurs = FactureComptable.objects.filter(
            agence=agence,
            type_facture='fournisseur',
            status__in=['impayee', 'partielle']
        ).aggregate(total=Sum('montant_restant'))['total'] or 0
        
        if dettes_fournisseurs > 0:
            alertes.append({
                'type': 'info',
                'message': f'Dettes fournisseurs: {dettes_fournisseurs:,.0f} FCFA',
                'montant': dettes_fournisseurs
            })
        
        # Trésorerie basse
        if tresorerie < 0:
            alertes.append({
                'type': 'error',
                'message': 'Trésorerie négative',
                'montant': tresorerie
            })
        
        data = {
            'periode': now.strftime('%B %Y'),
            'agence_id': agence.id,
            'ca_total': ca_mois,
            'ca_evolution': ca_mois - ca_mois_precedent,
            'ca_evolution_pourcentage': ((ca_mois - ca_mois_precedent) / ca_mois_precedent * 100) if ca_mois_precedent > 0 else 0,
            'marge_brute': ca_mois - achats_mois,
            'marge_pourcentage': ((ca_mois - achats_mois) / ca_mois * 100) if ca_mois > 0 else 0,
            'tresorerie': tresorerie,
            'ventes_mois': ca_mois,
            'achats_mois': achats_mois,
            'charges_mois': 0,  # À calculer selon les besoins
            'alertes': alertes
        }
        
        return Response(data)


class CompteResultatView(APIView):
    """
    Vue pour le compte de résultat
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')
        date_debut = request.query_params.get('date_debut')
        date_fin = request.query_params.get('date_fin')
        
        if not all([agence_id, date_debut, date_fin]):
            return Response(
                {"error": "agence_id, date_debut et date_fin sont requis"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            agence = Agence.objects.get(id=agence_id)
        except Agence.DoesNotExist:
            return Response(
                {"error": "Agence non trouvée"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Vérifier les permissions
        if not request.user.peut_acceder_agence(agence_id):
            return Response(
                {"error": "Permission denied"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Calculer les produits
        produits = self._calculer_produits(agence, date_debut, date_fin)
        
        # Calculer les charges
        charges = self._calculer_charges(agence, date_debut, date_fin)
        
        # Résultat
        total_produits = sum(produits.values())
        total_charges = sum(charges.values())
        resultat = total_produits - total_charges
        
        data = {
            'periode': f"{date_debut} au {date_fin}",
            'agence_id': agence.id,
            'produits': produits,
            'total_produits': total_produits,
            'charges': charges,
            'total_charges': total_charges,
            'resultat': resultat,
            'type_resultat': 'Bénéfice' if resultat > 0 else 'Perte'
        }
        
        return Response(data)

    def _calculer_produits(self, agence, date_debut, date_fin):
        """Calcule les produits de la période"""
        produits = {}
        
        # Ventes (compte 701)
        ventes = FactureComptable.objects.filter(
            agence=agence,
            type_facture='client',
            date_facture__gte=date_debut,
            date_facture__lte=date_fin,
            status__in=['payee', 'partielle']
        ).aggregate(total=Sum('montant_ttc'))['total'] or 0
        produits['ventes'] = ventes
        
        # Autres produits à ajouter selon les besoins
        
        return produits

    def _calculer_charges(self, agence, date_debut, date_fin):
        """Calcule les charges de la période"""
        charges = {}
        
        # Achats (compte 601)
        achats = FactureComptable.objects.filter(
            agence=agence,
            type_facture='fournisseur',
            date_facture__gte=date_debut,
            date_facture__lte=date_fin
        ).aggregate(total=Sum('montant_ttc'))['total'] or 0
        charges['achats'] = achats
        
        # Autres charges à ajouter selon les besoins
        
        return charges


class BilanView(APIView):
    """
    Vue pour le bilan comptable
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')
        date_cloture = request.query_params.get('date_cloture')
        
        if not all([agence_id, date_cloture]):
            return Response(
                {"error": "agence_id et date_cloture sont requis"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            agence = Agence.objects.get(id=agence_id)
        except Agence.DoesNotExist:
            return Response(
                {"error": "Agence non trouvée"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Vérifier les permissions
        if not request.user.peut_acceder_agence(agence_id):
            return Response(
                {"error": "Permission denied"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Calculer l'actif
        actif = self._calculer_actif(agence, date_cloture)
        
        # Calculer le passif
        passif = self._calculer_passif(agence, date_cloture)
        
        total_actif = sum(actif.values())
        total_passif = sum(passif.values())
        
        data = {
            'date': date_cloture,
            'agence_id': agence.id,
            'actif': actif,
            'total_actif': total_actif,
            'passif': passif,
            'total_passif': total_passif,
            'est_equilibre': total_actif == total_passif
        }
        
        return Response(data)

    def _calculer_actif(self, agence, date):
        """Calcule l'actif du bilan"""
        actif = {}
        
        # Trésorerie (compte 5)
        encaissements = Reglement.objects.filter(
            agence=agence,
            type_reglement='client',
            date_reglement__lte=date
        ).aggregate(total=Sum('montant'))['total'] or 0
        
        decaissements = Reglement.objects.filter(
            agence=agence,
            type_reglement='fournisseur',
            date_reglement__lte=date
        ).aggregate(total=Sum('montant'))['total'] or 0
        
        actif['tresorerie'] = encaissements - decaissements
        
        # Créances clients
        creances = FactureComptable.objects.filter(
            agence=agence,
            type_facture='client',
            date_facture__lte=date,
            status__in=['impayee', 'partielle', 'envoyee']
        ).aggregate(total=Sum('montant_restant'))['total'] or 0
        actif['creances'] = creances
        
        # Autres actifs à ajouter selon les besoins
        
        return actif

    def _calculer_passif(self, agence, date):
        """Calcule le passif du bilan"""
        passif = {}
        
        # Dettes fournisseurs
        dettes = FactureComptable.objects.filter(
            agence=agence,
            type_facture='fournisseur',
            date_facture__lte=date,
            status__in=['impayee', 'partielle', 'recue']
        ).aggregate(total=Sum('montant_restant'))['total'] or 0
        passif['dettes_fournisseurs'] = dettes
        
        # Autres passifs à ajouter selon les besoins
        
        return passif


class TresorerieView(APIView):
    """
    Vue pour le suivi de trésorerie
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agence_id = request.query_params.get('agence_id')
        date_debut = request.query_params.get('date_debut')
        date_fin = request.query_params.get('date_fin')
        
        if not all([agence_id, date_debut, date_fin]):
            return Response(
                {"error": "agence_id, date_debut et date_fin sont requis"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            agence = Agence.objects.get(id=agence_id)
        except Agence.DoesNotExist:
            return Response(
                {"error": "Agence non trouvée"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Vérifier les permissions
        if not request.user.peut_acceder_agence(agence_id):
            return Response(
                {"error": "Permission denied"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Solde initial
        solde_initial = Reglement.objects.filter(
            agence=agence,
            date_reglement__lt=date_debut
        ).aggregate(
            encaissements=Sum('montant', filter=Q(type_reglement='client')),
            decaissements=Sum('montant', filter=Q(type_reglement='fournisseur'))
        )
        
        solde_init = (solde_initial['encaissements'] or 0) - (solde_initial['decaissements'] or 0)
        
        # Encaissements de la période
        encaissements = Reglement.objects.filter(
            agence=agence,
            type_reglement='client',
            date_reglement__gte=date_debut,
            date_reglement__lte=date_fin
        ).select_related('client')
        
        # Décaissements de la période
        decaissements = Reglement.objects.filter(
            agence=agence,
            type_reglement='fournisseur',
            date_reglement__gte=date_debut,
            date_reglement__lte=date_fin
        ).select_related('fournisseur')
        
        total_encaissements = encaissements.aggregate(total=Sum('montant'))['total'] or 0
        total_decaissements = decaissements.aggregate(total=Sum('montant'))['total'] or 0
        
        data = {
            'agence_id': agence.id,
            'date_debut': date_debut,
            'date_fin': date_fin,
            'solde_initial': solde_init,
            'encaissements': total_encaissements,
            'decaissements': total_decaissements,
            'solde_final': solde_init + total_encaissements - total_decaissements,
            'details_encaissements': ReglementSerializer(encaissements, many=True).data,
            'details_decaissements': ReglementSerializer(decaissements, many=True).data
        }
        
        return Response(data)