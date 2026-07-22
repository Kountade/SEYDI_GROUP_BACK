import os
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth import get_user_model
from rest_framework import serializers
from django.utils import timezone
from .models import *
from users.serializers import UserSerializer
from users.models import CustomUser


class DepartmentSerializer(serializers.ModelSerializer):
    manager_name = serializers.CharField(
        source='manager.user.get_full_name', read_only=True)
    employees_count = serializers.IntegerField(
        source='employees.count', read_only=True)
    parent_department_name = serializers.CharField(
        source='parent_department.name', read_only=True)

    class Meta:
        model = Department
        fields = '__all__'


class PositionSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(
        source='department.name', read_only=True)
    employees_count = serializers.IntegerField(
        source='employees.count', read_only=True)

    class Meta:
        model = Position
        fields = '__all__'


class EmployeeListSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField(source='user.email', read_only=True)
    phone = serializers.CharField(source='user.phone', read_only=True)
    department_name = serializers.CharField(
        source='department.name', read_only=True)
    position_title = serializers.CharField(
        source='position.title', read_only=True)
    manager_name = serializers.SerializerMethodField()
    work_status_display = serializers.CharField(
        source='get_work_status_display', read_only=True)
    contract_type_display = serializers.CharField(
        source='get_contract_type_display', read_only=True)
    remaining_leave_days = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = ('id', 'employee_number', 'full_name', 'email', 'phone', 'department_name',
                  'position_title', 'manager_name', 'hire_date', 'contract_type', 'contract_type_display',
                  'work_status', 'work_status_display', 'base_salary', 'qr_code', 'remaining_leave_days')

    def get_full_name(self, obj):
        return obj.full_name

    def get_manager_name(self, obj):
        # Correction: vérifier si manager existe
        if obj.manager:
            return obj.manager.full_name
        return None

    def get_remaining_leave_days(self, obj):
        return obj.remaining_leave_days


class EmployeeDetailSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    department = DepartmentSerializer(read_only=True)
    position = PositionSerializer(read_only=True)
    manager = EmployeeListSerializer(read_only=True)
    work_status_display = serializers.CharField(
        source='get_work_status_display', read_only=True)
    contract_type_display = serializers.CharField(
        source='get_contract_type_display', read_only=True)
    gender_display = serializers.CharField(
        source='get_gender_display', read_only=True)
    marital_status_display = serializers.CharField(
        source='get_marital_status_display', read_only=True)
    subordinates_count = serializers.IntegerField(
        source='subordinates.count', read_only=True)
    leaves_taken = serializers.SerializerMethodField()
    total_absences = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = '__all__'

    def get_leaves_taken(self, obj):
        current_year = timezone.now().year
        return obj.leaves.filter(
            status='approved',
            start_date__year=current_year,
            leave_type='annual'
        ).aggregate(total=models.Sum('duration_days'))['total'] or 0

    def get_total_absences(self, obj):
        return obj.attendances.filter(is_absent=True).count()


class EmployeeCreateUpdateSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(write_only=True)
    first_name = serializers.CharField(write_only=True)
    last_name = serializers.CharField(write_only=True)
    phone = serializers.CharField(
        write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Employee
        fields = '__all__'
        read_only_fields = ('employee_number', 'qr_code',
                            'qr_code_token', 'created_at', 'updated_at')

    def create(self, validated_data):
        email = validated_data.pop('email')
        first_name = validated_data.pop('first_name')
        last_name = validated_data.pop('last_name')
        phone = validated_data.pop('phone', '')

        # Créer ou récupérer l'utilisateur
        user, created = CustomUser.objects.get_or_create(
            email=email,
            defaults={
                'username': email,
                'first_name': first_name,
                'last_name': last_name,
                'phone': phone
            }
        )

        employee = Employee.objects.create(user=user, **validated_data)
        return employee

    def update(self, instance, validated_data):
        # Mettre à jour l'utilisateur associé
        user_data = {}
        if 'email' in validated_data:
            user_data['email'] = validated_data.pop('email')
        if 'first_name' in validated_data:
            user_data['first_name'] = validated_data.pop('first_name')
        if 'last_name' in validated_data:
            user_data['last_name'] = validated_data.pop('last_name')
        if 'phone' in validated_data:
            user_data['phone'] = validated_data.pop('phone')

        for attr, value in user_data.items():
            setattr(instance.user, attr, value)
        instance.user.save()

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance


class LeaveSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source='employee.full_name', read_only=True)
    leave_type_display = serializers.CharField(
        source='get_leave_type_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    approved_by_name = serializers.CharField(
        source='approved_by.full_name', read_only=True)

    class Meta:
        model = Leave
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class LeaveCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Leave
        fields = ('employee', 'leave_type', 'start_date',
                  'end_date', 'reason', 'attachment')
        read_only_fields = ('duration_days', 'status',
                            'approved_by', 'approval_date', 'approval_comments')

    def validate(self, data):
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError(
                "La date de début doit être antérieure à la date de fin")

        if start_date and end_date:
            duration = (end_date - start_date).days + 1
            data['duration_days'] = duration

        return data


class AttendanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source='employee.full_name', read_only=True)
    check_in_method_display = serializers.CharField(
        source='get_check_in_method_display', read_only=True)
    check_out_method_display = serializers.CharField(
        source='get_check_out_method_display', read_only=True)

    class Meta:
        model = Attendance
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class AttendanceCheckinSerializer(serializers.Serializer):
    qr_token = serializers.CharField(required=False, allow_blank=True)
    employee_id = serializers.IntegerField(required=False)
    method = serializers.ChoiceField(
        choices=['qr', 'manual', 'face'], default='manual')


class PayrollSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source='employee.full_name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    payment_method_display = serializers.CharField(
        source='get_payment_method_display', read_only=True)

    class Meta:
        model = Payroll
        fields = '__all__'
        read_only_fields = ('payroll_number', 'gross_salary',
                            'net_salary', 'created_at', 'updated_at')


class PayrollCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payroll
        fields = '__all__'
        read_only_fields = ('payroll_number', 'gross_salary',
                            'net_salary', 'created_at', 'updated_at')


class RecruitmentSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(
        source='department.name', read_only=True)
    position_title = serializers.CharField(
        source='position.title', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    contract_type_display = serializers.CharField(
        source='get_contract_type_display', read_only=True)
    candidates_count = serializers.IntegerField(
        source='candidates.count', read_only=True)

    class Meta:
        model = Recruitment
        fields = '__all__'
        read_only_fields = ('posted_date', 'created_at', 'updated_at')


class CandidateSerializer(serializers.ModelSerializer):
    recruitment_title = serializers.CharField(
        source='recruitment.title', read_only=True)
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = Candidate
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class TrainingSerializer(serializers.ModelSerializer):
    participants_count = serializers.IntegerField(
        source='participants.count', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = Training
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class TrainingParticipantSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source='employee.full_name', read_only=True)
    training_title = serializers.CharField(
        source='training.title', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = TrainingParticipant
        fields = '__all__'


class PerformanceReviewSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source='employee.full_name', read_only=True)
    reviewer_name = serializers.CharField(
        source='reviewer.full_name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = PerformanceReview
        fields = '__all__'
        read_only_fields = ('overall_rating', 'created_at', 'updated_at')

# hr/serializers.py - ExpenseClaimSerializer CORRIGÉ
# hr/serializers.py - ExpenseClaimSerializer (sans employee)


# hr/serializers.py - ExpenseClaimSerializer SANS employee

class ExpenseClaimSerializer(serializers.ModelSerializer):
    """
    Serializer pour les notes de frais
    """

    expense_type_display = serializers.CharField(
        source='get_expense_type_display',
        read_only=True
    )

    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )

    validated_by_name = serializers.CharField(
        source='validated_by.full_name',
        read_only=True
    )

    paid_by_name = serializers.CharField(
        source='paid_by.full_name',
        read_only=True
    )

    amount_formatted = serializers.SerializerMethodField()
    receipt_url = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseClaim
        fields = '__all__'
        read_only_fields = (
            'created_at',
            'updated_at',
            'validation_date',
            'payment_date',
            'expense_type_display',
            'status_display',
            'validated_by_name',
            'paid_by_name',
            'amount_formatted',
            'receipt_url',
        )

    def get_amount_formatted(self, obj):
        if obj.amount:
            return f"{int(obj.amount):,}".replace(',', ' ') + ' GNF'
        return '0 GNF'

    def get_receipt_url(self, obj):
        if obj.receipt and hasattr(obj.receipt, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.receipt.url)
            return obj.receipt.url
        return None

    def validate(self, data):
        errors = {}

        if data.get('date') and data['date'] > timezone.now().date():
            errors['date'] = "La date ne peut pas être dans le futur"

        if data.get('amount'):
            if data['amount'] <= 0:
                errors['amount'] = "Le montant doit être supérieur à 0"
            elif data['amount'] > 999999999:
                errors['amount'] = "Le montant ne peut pas dépasser 999 999 999 GNF"

        if data.get('description'):
            description = data['description'].strip()
            if len(description) < 3:
                errors['description'] = "La description doit contenir au moins 3 caractères"

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def validate_receipt(self, value):
        if not value:
            return value

        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError(
                "Le fichier ne doit pas dépasser 5MB")

        valid_extensions = ['.pdf', '.jpg', '.jpeg', '.png', '.doc', '.docx']
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in valid_extensions:
            raise serializers.ValidationError(
                f"Format non supporté. Utilisez: {', '.join(valid_extensions)}"
            )

        return value

# ============================================
# 📊 SERIALIZER POUR LA CRÉATION UNIQUEMENT
# ============================================


class ExpenseClaimCreateSerializer(ExpenseClaimSerializer):
    """
    Serializer simplifié pour la création
    Champs requis minimaux
    """

    class Meta(ExpenseClaimSerializer.Meta):
        read_only_fields = ExpenseClaimSerializer.Meta.read_only_fields + (
            'status',
        )

    def validate(self, data):
        """
        Validation minimale pour la création
        """
        # ✅ Vérifier que l'employee est présent
        if not data.get('employee'):
            raise serializers.ValidationError(
                "L'employé est requis pour créer une note de frais"
            )

        # ✅ Vérifier que le montant est présent
        if not data.get('amount'):
            raise serializers.ValidationError(
                "Le montant est requis"
            )

        return super().validate(data)


# ============================================
# 📊 SERIALIZER POUR L'APPROBATION
# ============================================

class ExpenseClaimApproveSerializer(serializers.Serializer):
    """
    Serializer pour l'approbation/rejet
    """
    comments = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Commentaires sur l'approbation"
    )

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Motif du rejet"
    )

    def validate_comments(self, value):
        if value and len(value) > 500:
            raise serializers.ValidationError(
                "Les commentaires ne peuvent pas dépasser 500 caractères"
            )
        return value

    def validate_reason(self, value):
        if value and len(value) > 500:
            raise serializers.ValidationError(
                "Le motif ne peut pas dépasser 500 caractères"
            )
        return value


class DocumentSerializer(serializers.ModelSerializer):
    document_type_display = serializers.CharField(
        source='get_document_type_display', read_only=True)
    uploaded_by_name = serializers.CharField(
        source='uploaded_by.get_full_name', read_only=True)

    class Meta:
        model = Document
        fields = '__all__'
        read_only_fields = ('uploaded_at', 'updated_at')


class HRStatsSerializer(serializers.Serializer):
    total_employees = serializers.IntegerField()
    active_employees = serializers.IntegerField()
    on_leave = serializers.IntegerField()
    pending_leaves = serializers.IntegerField()
    present_today = serializers.IntegerField()
    absent_today = serializers.IntegerField()
    monthly_payroll = serializers.DecimalField(max_digits=15, decimal_places=2)
    new_hires_this_month = serializers.IntegerField()
    turnover_rate = serializers.FloatField()
    average_salary = serializers.DecimalField(max_digits=12, decimal_places=2)
    gender_distribution = serializers.DictField()
    department_distribution = serializers.ListField()
    leave_balance_alert = serializers.ListField()
