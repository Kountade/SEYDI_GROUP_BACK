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


class ExpenseClaimSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source='employee.full_name', read_only=True)
    expense_type_display = serializers.CharField(
        source='get_expense_type_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    approved_by_name = serializers.CharField(
        source='approved_by.full_name', read_only=True)

    class Meta:
        model = ExpenseClaim
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


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
