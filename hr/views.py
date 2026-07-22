from django.contrib.auth import get_user_model
import logging
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Q, Sum, Count, Avg
from datetime import datetime, timedelta
from .models import *
from .serializers import *
from django.core.files.base import ContentFile
import qrcode
from io import BytesIO
import json


class DepartmentViewset(viewsets.ModelViewSet):
    """Viewset pour les départements"""
    permission_classes = [permissions.IsAuthenticated]
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code', 'description']
    filterset_fields = ['is_active', 'parent_department']
    ordering_fields = ['name', 'created_at']


class PositionViewset(viewsets.ModelViewSet):
    """Viewset pour les postes"""
    permission_classes = [permissions.IsAuthenticated]
    queryset = Position.objects.all()
    serializer_class = PositionSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description']
    filterset_fields = ['department', 'is_active']


class EmployeeViewset(viewsets.ModelViewSet):
    """Viewset pour les employés"""
    permission_classes = [permissions.IsAuthenticated]
    queryset = Employee.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['employee_number', 'user__first_name',
                     'user__last_name', 'user__email']
    filterset_fields = ['department', 'position',
                        'work_status', 'contract_type']
    ordering_fields = ['employee_number', 'hire_date', 'base_salary']

    def get_serializer_class(self):
        if self.action == 'list':
            return EmployeeListSerializer
        elif self.action == 'retrieve':
            return EmployeeDetailSerializer
        return EmployeeCreateUpdateSerializer

    @action(detail=True, methods=['get'])
    def qr_code(self, request, pk=None):
        """Récupère le QR code de l'employé (URL absolue pour le frontend)"""
        employee = self.get_object()
        if not employee.qr_code:
            employee.generate_qr_code()
            employee.save()

        # Construire l'URL absolue
        qr_absolute_url = None
        if employee.qr_code and employee.qr_code.url:
            qr_absolute_url = request.build_absolute_uri(employee.qr_code.url)

        qr_data = {
            'qr_code_url': qr_absolute_url,
            'employee_number': employee.employee_number,
            'full_name': employee.full_name,
            'token': employee.qr_code_token
        }
        return Response(qr_data)

    @action(detail=True, methods=['post'])
    def regenerate_qr(self, request, pk=None):
        """Régénère le QR code de l'employé"""
        employee = self.get_object()
        employee.generate_qr_code()
        employee.save()
        return Response({'message': 'QR code régénéré avec succès'})

    @action(detail=False, methods=['get'])
    def by_department(self, request):
        """Récupère les employés par département"""
        department_id = request.query_params.get('department')
        if department_id:
            employees = self.queryset.filter(department_id=department_id)
        else:
            employees = self.queryset
        serializer = EmployeeListSerializer(employees, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_manager(self, request):
        """Récupère les employés sous un manager"""
        manager_id = request.query_params.get('manager')
        if manager_id:
            employees = self.queryset.filter(manager_id=manager_id)
            serializer = EmployeeListSerializer(employees, many=True)
            return Response(serializer.data)
        return Response([])


class LeaveViewset(viewsets.ModelViewSet):
    """Viewset pour les congés"""
    permission_classes = [permissions.IsAuthenticated]
    queryset = Leave.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['employee__user__first_name',
                     'employee__user__last_name', 'reason']
    filterset_fields = ['leave_type', 'status', 'employee']
    ordering_fields = ['start_date', 'created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return LeaveCreateSerializer
        return LeaveSerializer

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approuver une demande de congé"""
        leave = self.get_object()
        if leave.status != 'pending':
            return Response({'error': 'Cette demande a déjà été traitée'}, status=status.HTTP_400_BAD_REQUEST)

        leave.status = 'approved'
        leave.approved_by = Employee.objects.get(user=request.user)
        leave.approval_date = timezone.now()
        leave.approval_comments = request.data.get('comments', '')
        leave.save()

        return Response({'message': 'Demande approuvée avec succès'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Rejeter une demande de congé"""
        leave = self.get_object()
        if leave.status != 'pending':
            return Response({'error': 'Cette demande a déjà été traitée'}, status=status.HTTP_400_BAD_REQUEST)

        leave.status = 'rejected'
        leave.approved_by = Employee.objects.get(user=request.user)
        leave.approval_date = timezone.now()
        leave.approval_comments = request.data.get('comments', '')
        leave.save()

        return Response({'message': 'Demande rejetée'})

    @action(detail=False, methods=['get'])
    def pending(self, request):
        """Récupère les demandes en attente"""
        leaves = self.queryset.filter(status='pending')
        serializer = self.get_serializer(leaves, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def my_leaves(self, request):
        """Récupère les congés de l'employé connecté"""
        try:
            employee = Employee.objects.get(user=request.user)
            leaves = self.queryset.filter(employee=employee)
            serializer = self.get_serializer(leaves, many=True)
            return Response(serializer.data)
        except Employee.DoesNotExist:
            return Response([])


class AttendanceViewset(viewsets.ModelViewSet):
    """Viewset pour les présences"""
    permission_classes = [permissions.IsAuthenticated]
    queryset = Attendance.objects.all()
    serializer_class = AttendanceSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['employee', 'date', 'is_absent']
    search_fields = ['employee__user__first_name', 'employee__user__last_name']
    ordering_fields = ['date', 'check_in_time']

    @action(detail=False, methods=['post'])
    def checkin(self, request):
        """Pointage d'arrivée"""
        serializer = AttendanceCheckinSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        qr_token = data.get('qr_token')
        employee_id = data.get('employee_id')
        method = data.get('method', 'manual')

        # Récupérer l'employé
        if qr_token:
            employee = Employee.objects.filter(qr_code_token=qr_token).first()
        elif employee_id:
            employee = Employee.objects.filter(id=employee_id).first()
        else:
            return Response({'error': 'QR code ou ID employé requis'}, status=status.HTTP_400_BAD_REQUEST)

        if not employee:
            return Response({'error': 'Employé non trouvé'}, status=status.HTTP_404_NOT_FOUND)

        today = timezone.now().date()
        attendance, created = Attendance.objects.get_or_create(
            employee=employee,
            date=today,
            defaults={'check_in_method': method}
        )

        if attendance.check_in_time and not created:
            return Response({'error': 'Check-in déjà effectué aujourd\'hui'}, status=status.HTTP_400_BAD_REQUEST)

        attendance.check_in_time = timezone.now()
        attendance.check_in_method = method
        attendance.save()

        return Response({
            'message': 'Check-in effectué avec succès',
            'employee': employee.full_name,
            'check_in_time': attendance.check_in_time
        })

    @action(detail=False, methods=['post'])
    def checkout(self, request):
        """Pointage de départ"""
        serializer = AttendanceCheckinSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        qr_token = data.get('qr_token')
        employee_id = data.get('employee_id')

        if qr_token:
            employee = Employee.objects.filter(qr_code_token=qr_token).first()
        elif employee_id:
            employee = Employee.objects.filter(id=employee_id).first()
        else:
            return Response({'error': 'QR code ou ID employé requis'}, status=status.HTTP_400_BAD_REQUEST)

        if not employee:
            return Response({'error': 'Employé non trouvé'}, status=status.HTTP_404_NOT_FOUND)

        today = timezone.now().date()
        try:
            attendance = Attendance.objects.get(employee=employee, date=today)
        except Attendance.DoesNotExist:
            return Response({'error': 'Aucun check-in trouvé pour aujourd\'hui'}, status=status.HTTP_400_BAD_REQUEST)

        if attendance.check_out_time:
            return Response({'error': 'Check-out déjà effectué'}, status=status.HTTP_400_BAD_REQUEST)

        attendance.check_out_time = timezone.now()
        attendance.check_out_method = data.get('method', 'manual')
        attendance.save()

        return Response({
            'message': 'Check-out effectué avec succès',
            'employee': employee.full_name,
            'check_out_time': attendance.check_out_time,
            'hours_worked': attendance.hours_worked
        })

    @action(detail=False, methods=['get'])
    def today(self, request):
        """Présences du jour"""
        today = timezone.now().date()
        attendances = self.queryset.filter(date=today)
        serializer = self.get_serializer(attendances, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def report(self, request):
        """Rapport de présence"""
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        employee_id = request.query_params.get('employee_id')

        queryset = self.queryset
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)

        stats = queryset.aggregate(
            total_days=Count('id'),
            total_hours=Sum('hours_worked'),
            total_overtime=Sum('overtime_hours'),
            total_late=Sum('late_minutes')
        )

        return Response(stats)


class PayrollViewset(viewsets.ModelViewSet):
    """Viewset pour les paies"""
    permission_classes = [permissions.IsAuthenticated]
    queryset = Payroll.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['employee', 'month', 'year', 'status']
    search_fields = ['employee__user__first_name',
                     'employee__user__last_name', 'payroll_number']
    ordering_fields = ['year', 'month', 'created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return PayrollCreateSerializer
        return PayrollSerializer

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approuver une fiche de paie"""
        payroll = self.get_object()
        payroll.status = 'approved'
        payroll.save()
        return Response({'message': 'Fiche de paie approuvée'})

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """Marquer comme payée"""
        payroll = self.get_object()
        payroll.status = 'paid'
        payroll.payment_date = timezone.now().date()
        payroll.bank_reference = request.data.get('bank_reference', '')
        payroll.save()
        return Response({'message': 'Paiement enregistré'})

    @action(detail=False, methods=['get'])
    def current_month(self, request):
        """Paie du mois en cours"""
        now = timezone.now()
        payrolls = self.queryset.filter(month=now.month, year=now.year)
        serializer = self.get_serializer(payrolls, many=True)
        return Response(serializer.data)


class RecruitmentViewset(viewsets.ModelViewSet):
    """Viewset pour les recrutements"""
    permission_classes = [permissions.IsAuthenticated]
    queryset = Recruitment.objects.all()
    serializer_class = RecruitmentSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description', 'requirements']
    filterset_fields = ['department', 'contract_type', 'status']


class CandidateViewset(viewsets.ModelViewSet):
    """Viewset pour les candidats"""
    permission_classes = [permissions.IsAuthenticated]
    queryset = Candidate.objects.all()
    serializer_class = CandidateSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['first_name', 'last_name', 'email']
    filterset_fields = ['recruitment', 'status']

    @action(detail=True, methods=['post'])
    def schedule_interview(self, request, pk=None):
        """Planifier un entretien"""
        candidate = self.get_object()
        candidate.interview_date = request.data.get('interview_date')
        candidate.status = 'interview_scheduled'
        candidate.save()
        return Response({'message': 'Entretien planifié'})

    @action(detail=True, methods=['post'])
    def hire(self, request, pk=None):
        """Embaucher un candidat"""
        candidate = self.get_object()
        candidate.status = 'hired'
        candidate.save()
        return Response({'message': 'Candidat embauché'})


class TrainingViewset(viewsets.ModelViewSet):
    """Viewset pour les formations"""
    permission_classes = [permissions.IsAuthenticated]
    queryset = Training.objects.all()
    serializer_class = TrainingSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description', 'provider']
    filterset_fields = ['status']

    @action(detail=True, methods=['post'])
    def register(self, request, pk=None):
        """Inscrire un employé à une formation"""
        training = self.get_object()
        employee_id = request.data.get('employee_id')
        try:
            employee = Employee.objects.get(id=employee_id)
            TrainingParticipant.objects.get_or_create(
                training=training, employee=employee)
            return Response({'message': 'Inscription réussie'})
        except Employee.DoesNotExist:
            return Response({'error': 'Employé non trouvé'}, status=status.HTTP_404_NOT_FOUND)


class PerformanceReviewViewset(viewsets.ModelViewSet):
    """Viewset pour les évaluations"""
    permission_classes = [permissions.IsAuthenticated]
    queryset = PerformanceReview.objects.all()
    serializer_class = PerformanceReviewSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['employee', 'reviewer', 'status']
    ordering_fields = ['review_date']


# views.py - ExpenseClaimViewset COMPLET


logger = logging.getLogger(__name__)

# hr/views.py - ExpenseClaimViewset (sans employee)
# hr/views.py - ExpenseClaimViewset SANS employee

# hr/views.py - ExpenseClaimViewset avec création automatique


CustomUser = get_user_model()
logger = logging.getLogger(__name__)


class ExpenseClaimViewset(viewsets.ModelViewSet):
    """
    Viewset pour les notes de frais
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = ExpenseClaim.objects.all()
    serializer_class = ExpenseClaimSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['description']
    filterset_fields = ['expense_type', 'status', 'date']
    ordering_fields = ['date', 'created_at', 'amount']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user

        if user.role_global in ['pdg', 'drh']:
            return super().get_queryset()

        if self._is_comptable(user):
            return super().get_queryset()

        return super().get_queryset()

    def perform_create(self, serializer):
        serializer.save()

    # ============================================
    # 🔧 FONCTION UTILITAIRE - Récupérer ou créer un Employee
    # ============================================

    def _get_or_create_employee(self, user):
        """
        Récupère ou crée un profil Employee pour l'utilisateur
        """
        try:
            # Essayer de récupérer l'Employee existant
            employee = Employee.objects.get(user=user)
            logger.info(
                f"✅ Employee trouvé: {employee.employee_number} - {user.email}")
            return employee
        except Employee.DoesNotExist:
            # Créer un Employee automatiquement
            logger.info(
                f"⚠️ Création automatique d'un Employee pour {user.email}")

            employee = Employee.objects.create(
                user=user,
                employee_number=f"EMP{user.id:06d}",
                hire_date=timezone.now().date(),
                contract_type='cdi',
                base_salary=0,
                emergency_contact_name=user.get_full_name() or user.email or 'À définir',
                emergency_contact_phone='À définir',
                emergency_contact_relation='À définir',
            )

            logger.info(
                f"✅ Employee créé: {employee.employee_number} - {user.email}")
            return employee

    # ============================================
    # 🔥 VALIDATION RH
    # ============================================

    @action(detail=True, methods=['post'])
    def validate(self, request, pk=None):
        """RH/Manager valide la note"""
        expense = self.get_object()
        user = request.user

        if not self._can_validate(user):
            return Response(
                {'error': 'Seul le RH, DRH ou PDG peut valider'},
                status=status.HTTP_403_FORBIDDEN
            )

        if expense.status != 'pending':
            return Response(
                {'error': f'Statut actuel: {expense.get_status_display()}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ✅ Récupérer ou créer l'Employee pour l'utilisateur connecté
        try:
            employee = self._get_or_create_employee(user)
        except Exception as e:
            logger.error(
                f"❌ Erreur lors de la récupération/création de l'Employee: {e}")
            return Response(
                {'error': 'Impossible de trouver ou créer votre profil employé. Contactez le RH.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        expense.status = 'approved'
        expense.validated_by = employee
        expense.validation_date = timezone.now()
        expense.validation_comments = request.data.get('comments', '')
        expense.save()

        return Response({
            'message': '✅ Note validée avec succès',
            'expense': ExpenseClaimSerializer(expense).data
        })

    # ============================================
    # 🔥 PAIEMENT COMPTABLE
    # ============================================

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        """Comptable approuve le paiement"""
        expense = self.get_object()
        user = request.user

        if not self._can_pay(user):
            return Response(
                {'error': 'Seul un comptable, DRH ou PDG peut payer'},
                status=status.HTTP_403_FORBIDDEN
            )

        if expense.status != 'approved':
            return Response(
                {'error': 'La note doit être validée avant le paiement'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ✅ Récupérer ou créer l'Employee pour l'utilisateur connecté
        try:
            employee = self._get_or_create_employee(user)
        except Exception as e:
            logger.error(
                f"❌ Erreur lors de la récupération/création de l'Employee: {e}")
            return Response(
                {'error': 'Impossible de trouver ou créer votre profil employé. Contactez le RH.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        expense.status = 'paid'
        expense.paid_by = employee
        expense.payment_date = timezone.now()
        expense.payment_reference = request.data.get('payment_reference', '')
        expense.save()

        return Response({
            'message': '✅ Paiement approuvé avec succès',
            'expense': ExpenseClaimSerializer(expense).data
        })

    # ============================================
    # 🔥 REJET
    # ============================================

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """RH/Manager rejette la note"""
        expense = self.get_object()
        user = request.user

        if not self._can_validate(user):
            return Response(
                {'error': 'Seul le RH, DRH ou PDG peut rejeter'},
                status=status.HTTP_403_FORBIDDEN
            )

        if expense.status != 'pending':
            return Response(
                {'error': f'Statut actuel: {expense.get_status_display()}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ✅ Récupérer ou créer l'Employee pour l'utilisateur connecté
        try:
            employee = self._get_or_create_employee(user)
        except Exception as e:
            logger.error(
                f"❌ Erreur lors de la récupération/création de l'Employee: {e}")
            return Response(
                {'error': 'Impossible de trouver ou créer votre profil employé. Contactez le RH.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        expense.status = 'rejected'
        expense.validated_by = employee
        expense.validation_date = timezone.now()
        expense.rejection_reason = request.data.get('reason', 'Aucun motif')
        expense.save()

        return Response({
            'message': '❌ Note rejetée',
            'expense': ExpenseClaimSerializer(expense).data
        })

    # ============================================
    # 🔥 ANNULATION
    # ============================================

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Annuler une note"""
        expense = self.get_object()

        if expense.status != 'pending':
            return Response(
                {'error': 'Seules les notes en attente peuvent être annulées'},
                status=status.HTTP_400_BAD_REQUEST
            )

        expense.status = 'cancelled'
        expense.save()

        return Response({
            'message': '✅ Note annulée avec succès',
            'expense': ExpenseClaimSerializer(expense).data
        })

    # ============================================
    # 🔒 FONCTIONS DE PERMISSION
    # ============================================

    def _is_comptable(self, user):
        """Vérifie si l'utilisateur est comptable"""
        try:
            employee = Employee.objects.get(user=user)
            if hasattr(employee, 'roles_agence'):
                return employee.roles_agence.filter(
                    role='comptable',
                    est_actif=True
                ).exists()
        except Employee.DoesNotExist:
            pass
        return False

    def _can_validate(self, user):
        """Vérifie si l'utilisateur peut valider"""
        return user.role_global in ['pdg', 'drh']

    def _can_pay(self, user):
        """Vérifie si l'utilisateur peut payer"""
        if user.role_global in ['pdg', 'drh']:
            return True
        return self._is_comptable(user)
# ============================================


class ExpenseClaimSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source='employee.full_name', read_only=True)
    expense_type_display = serializers.CharField(
        source='get_expense_type_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    approved_by_name = serializers.CharField(
        source='approved_by.full_name', read_only=True)
    amount_formatted = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseClaim
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at',
                            'approval_date', 'payment_date')

    def get_amount_formatted(self, obj):
        """Formatage du montant avec séparateur d'espace"""
        if obj.amount:
            return f"{int(obj.amount):,}".replace(',', ' ') + ' GNF'
        return '0 GNF'

    def validate(self, data):
        """Validation personnalisée"""
        # Vérifier que la date n'est pas dans le futur
        if data.get('date') and data['date'] > timezone.now().date():
            raise serializers.ValidationError(
                "La date de la dépense ne peut pas être dans le futur"
            )

        # Vérifier que le montant est positif
        if data.get('amount') and data['amount'] <= 0:
            raise serializers.ValidationError(
                "Le montant doit être supérieur à 0"
            )

        return data


# ============================================


@action(detail=False, methods=['get'])
def dashboard_stats(self, request):
    """Statistiques avancées pour le dashboard"""
    user = request.user
    queryset = self.get_queryset()

    # Filtrer par année
    year = request.query_params.get('year', timezone.now().year)
    try:
        year = int(year)
        queryset = queryset.filter(date__year=year)
    except ValueError:
        pass

    # Statistiques mensuelles
    monthly_stats = queryset.extra(
        select={'month': "EXTRACT(month FROM date)"}
    ).values('month').annotate(
        total_amount=Sum('amount'),
        count=Count('id')
    ).order_by('month')

    # Top des types de dépenses
    top_expenses = queryset.values('expense_type').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')[:5]

    # Délai moyen de traitement (approuvées)
    approved_expenses = queryset.filter(
        status='approved',
        approval_date__isnull=False
    )
    avg_processing_time = approved_expenses.aggregate(
        avg_days=Avg(
            models.ExpressionWrapper(
                models.F('approval_date') - models.F('created_at'),
                output_field=models.DurationField()
            )
        )
    )

    stats = {
        'year': year,
        'total_expenses': queryset.count(),
        'total_amount': queryset.aggregate(total=Sum('amount'))['total'] or 0,
        'monthly': list(monthly_stats),
        'top_expense_types': list(top_expenses),
        'avg_processing_days': avg_processing_time['avg_days'].days if avg_processing_time['avg_days'] else 0,
        'pending_count': queryset.filter(status='pending').count(),
        'pending_amount': queryset.filter(status='pending').aggregate(total=Sum('amount'))['total'] or 0,
    }

    return Response(stats)


class DocumentViewset(viewsets.ModelViewSet):
    """Viewset pour les documents"""
    permission_classes = [permissions.IsAuthenticated]
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description']
    filterset_fields = ['document_type', 'department']

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


class HRStatsViewset(viewsets.GenericViewSet):
    """Viewset pour les statistiques RH"""
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Statistiques du tableau de bord RH"""

        # Statistiques employés
        total_employees = Employee.objects.count()
        active_employees = Employee.objects.filter(
            work_status='active').count()
        on_leave = Employee.objects.filter(work_status='on_leave').count()

        # Congés en attente
        pending_leaves = Leave.objects.filter(status='pending').count()

        # Présences aujourd'hui
        today = timezone.now().date()
        present_today = Attendance.objects.filter(
            date=today, check_in_time__isnull=False).count()
        absent_today = Attendance.objects.filter(
            date=today, is_absent=True).count()

        # Paie du mois
        now = timezone.now()
        monthly_payroll = Payroll.objects.filter(
            month=now.month,
            year=now.year,
            status='approved'
        ).aggregate(total=Sum('net_salary'))['total'] or 0

        # Nouveaux embauches ce mois
        first_day_of_month = datetime(now.year, now.month, 1).date()
        new_hires = Employee.objects.filter(
            hire_date__gte=first_day_of_month).count()

        # Turnover rate
        # (Calcul simplifié)
        turnover_rate = 0.0

        # Salaire moyen
        avg_salary = Employee.objects.filter(work_status='active').aggregate(
            avg=Avg('base_salary'))['avg'] or 0

        # Distribution par genre
        gender_dist = Employee.objects.values(
            'gender').annotate(count=Count('id'))
        gender_distribution = {item['gender']: item['count'] for item in gender_dist}

        # Distribution par département
        dept_dist = Department.objects.annotate(
            employee_count=Count('employees')
        ).values('name', 'employee_count')

        # Alertes solde congés
        leave_alerts = []
        for employee in Employee.objects.filter(work_status='active'):
            if employee.remaining_leave_days < 5:
                leave_alerts.append({
                    'employee_id': employee.id,
                    'employee_name': employee.full_name,
                    'remaining_days': employee.remaining_leave_days
                })

        stats = {
            'total_employees': total_employees,
            'active_employees': active_employees,
            'on_leave': on_leave,
            'pending_leaves': pending_leaves,
            'present_today': present_today,
            'absent_today': absent_today,
            'monthly_payroll': monthly_payroll,
            'new_hires_this_month': new_hires,
            'turnover_rate': turnover_rate,
            'average_salary': avg_salary,
            'gender_distribution': gender_distribution,
            'department_distribution': list(dept_dist),
            'leave_balance_alert': leave_alerts
        }

        serializer = HRStatsSerializer(stats)
        return Response(serializer.data)
