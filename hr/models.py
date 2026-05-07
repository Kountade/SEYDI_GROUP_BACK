from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from users.models import CustomUser
import qrcode
from io import BytesIO
from django.core.files.base import ContentFile
import uuid
from datetime import date, timedelta
from django.db import models  # import local pour éviter circular import

class Department(models.Model):
    """Département de l'entreprise"""
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True, null=True)
    manager = models.ForeignKey('Employee', on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='managed_departments')
    parent_department = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='sub_departments')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

    class Meta:
        ordering = ['code']


class Position(models.Model):
    """Poste / Fonction"""
    title = models.CharField(max_length=200)
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name='positions')
    description = models.TextField(blank=True, null=True)
    requirements = models.TextField(blank=True, null=True)
    min_salary = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True)
    max_salary = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title} - {self.department.name}"

import uuid
import json
import qrcode
from io import BytesIO
from datetime import date
from django.db import models
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model

CustomUser = get_user_model()

class Employee(models.Model):
    """Employé (peut ne pas avoir de compte utilisateur associé)"""
    
    CONTRACT_TYPES = (
        ('cdi', 'CDI'),
        ('cdd', 'CDD'),
        ('internship', 'Stage'),
        ('freelance', 'Freelance'),
        ('temporary', 'Intérim'),
        ('apprentice', 'Alternant'),
    )

    WORK_STATUS = (
        ('active', 'Actif'),
        ('inactive', 'Inactif'),
        ('on_leave', 'En congé'),
        ('sick', 'Maladie'),
        ('remote', 'Télétravail'),
        ('suspended', 'Suspendu'),
        ('terminated', 'Licencié'),
    )

    GENDER = (
        ('M', 'Masculin'),
        ('F', 'Féminin'),
        ('other', 'Autre'),
    )

    MARITAL_STATUS = (
        ('single', 'Célibataire'),
        ('married', 'Marié(e)'),
        ('divorced', 'Divorcé(e)'),
        ('widowed', 'Veuf/Veuve'),
    )

    # Relation optionnelle avec CustomUser
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='employee_profile',
        null=True,
        blank=True
    )
    employee_number = models.CharField(max_length=50, unique=True)

    # QR Code
    qr_code = models.ImageField(upload_to='hr/qrcodes/', null=True, blank=True)
    qr_code_token = models.CharField(
        max_length=100, unique=True, null=True, blank=True)

    # Informations personnelles
    photo = models.ImageField(upload_to='hr/photos/', null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    birth_place = models.CharField(max_length=200, null=True, blank=True)
    nationality = models.CharField(max_length=100, default='Sénégalaise')
    gender = models.CharField(
        max_length=10, choices=GENDER, null=True, blank=True)
    marital_status = models.CharField(
        max_length=20, choices=MARITAL_STATUS, null=True, blank=True)
    social_security_number = models.CharField(
        max_length=15, unique=True, null=True, blank=True)

    # Adresse
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, default='Sénégal')

    # Informations professionnelles
    hire_date = models.DateField()
    contract_type = models.CharField(max_length=20, choices=CONTRACT_TYPES)
    contract_end_date = models.DateField(null=True, blank=True)
    probation_end_date = models.DateField(null=True, blank=True)
    work_status = models.CharField(
        max_length=20, choices=WORK_STATUS, default='active')

    # Poste et département
    position = models.ForeignKey(
        'Position', on_delete=models.SET_NULL, null=True, related_name='employees')
    department = models.ForeignKey(
        'Department', on_delete=models.SET_NULL, null=True, related_name='employees')
    manager = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='subordinates')

    # Rémunération
    base_salary = models.DecimalField(max_digits=12, decimal_places=2)
    hourly_rate = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True)
    bank_account = models.CharField(
        max_length=34, null=True, blank=True)  # IBAN
    bank_name = models.CharField(max_length=200, blank=True, null=True)

    # Avantages
    meal_vouchers = models.BooleanField(default=False)
    health_insurance = models.BooleanField(default=False)
    company_car = models.BooleanField(default=False)
    phone_allowance = models.DecimalField(
        max_digits=8, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(
        max_digits=8, decimal_places=2, default=0)

    # Coordonnées d'urgence
    emergency_contact_name = models.CharField(max_length=200)
    emergency_contact_phone = models.CharField(max_length=20)
    emergency_contact_relation = models.CharField(max_length=100)
    emergency_contact_email = models.EmailField(blank=True, null=True)

    # Documents
    resume = models.FileField(upload_to='hr/resumes/', null=True, blank=True)
    contract = models.FileField(
        upload_to='hr/contracts/', null=True, blank=True)
    id_card = models.FileField(upload_to='hr/id_cards/', null=True, blank=True)
    medical_certificate = models.FileField(
        upload_to='hr/medical/', null=True, blank=True)

    # Métadonnées
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_employees')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['employee_number']

    def __str__(self):
        if self.user:
            return f"{self.employee_number} - {self.user.get_full_name()}"
        return f"{self.employee_number} - (Sans compte)"

    def save(self, *args, **kwargs):
        if not self.employee_number:
            last_employee = Employee.objects.order_by('-id').first()
            if last_employee:
                last_num = int(
                    last_employee.employee_number.replace('EMP', ''))
                self.employee_number = f"EMP{str(last_num + 1).zfill(6)}"
            else:
                self.employee_number = "EMP000001"

        # Générer le QR code (si besoin)
        if not self.qr_code_token:
            self.qr_code_token = str(uuid.uuid4())
            self.generate_qr_code()

        super().save(*args, **kwargs)

    def generate_qr_code(self):
        """Génère le QR code de l'employé, gère les cas sans user"""
        # Récupérer les infos depuis user si disponible
        if self.user:
            name = self.user.get_full_name()
            email = self.user.email
        else:
            name = f"Employé {self.employee_number}"
            email = ""

        qr_data = {
            'id': self.id,
            'employee_number': self.employee_number,
            'name': name,
            'email': email,
            'position': self.position.title if self.position else '',
            'department': self.department.name if self.department else '',
            'token': self.qr_code_token
        }

        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(json.dumps(qr_data, default=str))
        qr.make(fit=True)

        img = qr.make_image(fill_color="#003C3f", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        self.qr_code.save(f'qr_{self.employee_number}.png',
                          ContentFile(buffer.read()), save=False)

    # Propriétés
    @property
    def full_name(self):
        if self.user:
            return self.user.get_full_name()
        return f"Employé {self.employee_number}"

    @property
    def email(self):
        if self.user:
            return self.user.email
        return ""

    @property
    def phone(self):
        if self.user and hasattr(self.user, 'phone'):
            return self.user.phone
        return ""

    @property
    def age(self):
        if self.birth_date:
            today = date.today()
            return today.year - self.birth_date.year - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        return None

    @property
    def remaining_leave_days(self):
        """Calcule les jours de congé restants (nécessite la relation 'leaves')"""
      
        taken = self.leaves.filter(
            leave_type='annual',
            status='approved',
            start_date__year=date.today().year
        ).aggregate(total=models.Sum('duration_days'))['total'] or 0
        return 25 - taken  # 25 jours de congés par an

class Leave(models.Model):
    """Demande de congé"""
    LEAVE_TYPES = (
        ('annual', 'Congés payés'),
        ('sick', 'Congé maladie'),
        ('maternity', 'Congé maternité'),
        ('paternity', 'Congé paternité'),
        ('unpaid', 'Congé sans solde'),
        ('training', 'Formation'),
        ('family', 'Événement familial'),
        ('other', 'Autre'),
    )

    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
        ('cancelled', 'Annulé'),
    )

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='leaves')
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPES)
    start_date = models.DateField()
    end_date = models.DateField()
    duration_days = models.DecimalField(max_digits=5, decimal_places=1)
    reason = models.TextField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending')
    attachment = models.FileField(
        upload_to='hr/leave_attachments/', null=True, blank=True)
    approved_by = models.ForeignKey(
        Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_leaves')
    approval_date = models.DateTimeField(null=True, blank=True)
    approval_comments = models.TextField(blank=True, null=True)
    comments = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee} - {self.get_leave_type_display()} - {self.start_date}"

    class Meta:
        ordering = ['-created_at']


class Attendance(models.Model):
    """Pointage / Présence"""
    CHECK_TYPES = (
        ('check_in', 'Arrivée'),
        ('check_out', 'Départ'),
        ('break_start', 'Début pause'),
        ('break_end', 'Fin pause'),
    )

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='attendances')
    date = models.DateField()
    check_in_time = models.DateTimeField(null=True, blank=True)
    check_out_time = models.DateTimeField(null=True, blank=True)
    check_in_method = models.CharField(max_length=20, choices=[(
        'qr', 'QR Code'), ('manual', 'Manuel'), ('face', 'Reconnaissance faciale')], default='manual')
    check_out_method = models.CharField(max_length=20, choices=[(
        'qr', 'QR Code'), ('manual', 'Manuel'), ('face', 'Reconnaissance faciale')], default='manual')
    hours_worked = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True)
    overtime_hours = models.DecimalField(
        max_digits=5, decimal_places=2, default=0)
    late_minutes = models.IntegerField(default=0)
    early_departure_minutes = models.IntegerField(default=0)
    is_absent = models.BooleanField(default=False)
    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['employee', 'date']
        ordering = ['-date', '-created_at']

    def save(self, *args, **kwargs):
        if self.check_in_time and self.check_out_time:
            delta = self.check_out_time - self.check_in_time
            self.hours_worked = round(delta.total_seconds() / 3600, 2)

            # Calculer les heures supplémentaires (après 8h)
            if self.hours_worked > 8:
                self.overtime_hours = round(self.hours_worked - 8, 2)
            else:
                self.overtime_hours = 0

            # Calculer les minutes de retard (arrivée après 9h)
            expected_check_in = self.check_in_time.replace(
                hour=9, minute=0, second=0)
            if self.check_in_time > expected_check_in:
                self.late_minutes = int(
                    (self.check_in_time - expected_check_in).total_seconds() / 60)

            # Calculer les minutes de départ anticipé (départ avant 18h)
            expected_check_out = self.check_out_time.replace(
                hour=18, minute=0, second=0)
            if self.check_out_time < expected_check_out:
                self.early_departure_minutes = int(
                    (expected_check_out - self.check_out_time).total_seconds() / 60)

        super().save(*args, **kwargs)


class Payroll(models.Model):
    """Fiche de paie"""
    PAYROLL_STATUS = (
        ('draft', 'Brouillon'),
        ('calculated', 'Calculée'),
        ('approved', 'Approuvée'),
        ('paid', 'Payée'),
        ('cancelled', 'Annulée'),
    )

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='payrolls')
    month = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)])
    year = models.IntegerField()
    payroll_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(
        max_length=20, choices=PAYROLL_STATUS, default='draft')

    # Salaire de base
    base_salary = models.DecimalField(max_digits=12, decimal_places=2)

    # Primes et avantages
    performance_bonus = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    seniority_bonus = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    overtime_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    transport_bonus = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    phone_bonus = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    other_bonus = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)

    # Déductions
    social_security = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    income_tax = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    pension_fund = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    health_insurance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    unpaid_leave = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    other_deductions = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)

    # Totaux
    gross_salary = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False)
    net_salary = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False)

    # Paiement
    payment_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=20, choices=[(
        'bank', 'Virement'), ('cash', 'Espèces'), ('check', 'Chèque')], default='bank')
    bank_reference = models.CharField(max_length=100, blank=True, null=True)

    # Documents
    pdf_file = models.FileField(
        upload_to='hr/payrolls/', null=True, blank=True)

    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_payrolls')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['employee', 'month', 'year']
        ordering = ['-year', '-month']

    def save(self, *args, **kwargs):
        if not self.payroll_number:
            last = Payroll.objects.order_by('-id').first()
            if last:
                last_num = int(last.payroll_number.replace('PAY', ''))
                self.payroll_number = f"PAY{str(last_num + 1).zfill(6)}"
            else:
                self.payroll_number = "PAY000001"

        # Calculer les totaux
        self.gross_salary = (
            self.base_salary + self.performance_bonus + self.seniority_bonus +
            self.overtime_amount + self.transport_bonus + self.phone_bonus + self.other_bonus
        )

        total_deductions = (
            self.social_security + self.income_tax + self.pension_fund +
            self.health_insurance + self.unpaid_leave + self.other_deductions
        )

        self.net_salary = self.gross_salary - total_deductions

        super().save(*args, **kwargs)


class Recruitment(models.Model):
    """Recrutement"""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('published', 'Publié'),
        ('in_progress', 'En cours'),
        ('closed', 'Clôturé'),
        ('cancelled', 'Annulé'),
    )

    title = models.CharField(max_length=200)
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, related_name='recruitments')
    position = models.ForeignKey(
        Position, on_delete=models.SET_NULL, null=True, related_name='recruitments')

    description = models.TextField()
    requirements = models.TextField()
    location = models.CharField(max_length=200)
    contract_type = models.CharField(
        max_length=20, choices=Employee.CONTRACT_TYPES)
    experience_required = models.IntegerField(
        help_text="Années d'expérience requises", default=0)

    posted_date = models.DateField(auto_now_add=True)
    deadline = models.DateField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')

    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_recruitments')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} - {self.department.name if self.department else ''}"


class Candidate(models.Model):
    """Candidat"""
    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('reviewed', 'Examiné'),
        ('interview_scheduled', 'Entretien programmé'),
        ('interviewed', 'Entretien effectué'),
        ('rejected', 'Rejeté'),
        ('accepted', 'Accepté'),
        ('hired', 'Embauché'),
    )

    recruitment = models.ForeignKey(
        Recruitment, on_delete=models.CASCADE, related_name='candidates')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)

    cv = models.FileField(upload_to='hr/cvs/', null=True, blank=True)
    cover_letter = models.FileField(
        upload_to='hr/cover_letters/', null=True, blank=True)

    experience_years = models.IntegerField(default=0)
    current_salary = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    expected_salary = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)

    status = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True, null=True)

    interview_date = models.DateTimeField(null=True, blank=True)
    interview_notes = models.TextField(blank=True, null=True)

    hired_employee = models.OneToOneField(
        Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='candidate')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.recruitment.title}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Training(models.Model):
    """Formation"""
    STATUS_CHOICES = (
        ('planned', 'Planifiée'),
        ('in_progress', 'En cours'),
        ('completed', 'Terminée'),
        ('cancelled', 'Annulée'),
    )

    title = models.CharField(max_length=200)
    description = models.TextField()
    provider = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    duration_hours = models.IntegerField()
    location = models.CharField(max_length=200)
    max_participants = models.IntegerField(default=20)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='planned')

    participants = models.ManyToManyField(
        Employee, through='TrainingParticipant', related_name='trainings')

    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_trainings')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class TrainingParticipant(models.Model):
    """Participant à une formation"""
    training = models.ForeignKey(
        Training, on_delete=models.CASCADE, related_name='training_participants')
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='training_participations')

    status = models.CharField(max_length=20, choices=[
        ('registered', 'Inscrit'),
        ('confirmed', 'Confirmé'),
        ('completed', 'Terminé'),
        ('dropped', 'Abandonné'),
    ], default='registered')

    completion_date = models.DateField(null=True, blank=True)
    certificate = models.FileField(
        upload_to='hr/certificates/', null=True, blank=True)
    evaluation_score = models.IntegerField(null=True, blank=True, validators=[
                                           MinValueValidator(0), MaxValueValidator(100)])
    feedback = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['training', 'employee']


class PerformanceReview(models.Model):
    """Évaluation de performance"""
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='performance_reviews')
    reviewer = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='given_reviews')
    review_date = models.DateField()
    review_period_start = models.DateField()
    review_period_end = models.DateField()

    # Compétences notées sur 5
    work_quality = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)])
    productivity = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)])
    teamwork = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)])
    communication = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)])
    initiative = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)])
    punctuality = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)])

    strengths = models.TextField()
    weaknesses = models.TextField()
    achievements = models.TextField()
    goals = models.TextField()
    training_needs = models.TextField()

    overall_rating = models.DecimalField(
        max_digits=3, decimal_places=2, editable=False)

    employee_comments = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=20, choices=[
        ('draft', 'Brouillon'),
        ('submitted', 'Soumis'),
        ('acknowledged', 'Reconnu'),
        ('completed', 'Terminé'),
    ], default='draft')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.overall_rating = (
            self.work_quality + self.productivity + self.teamwork +
            self.communication + self.initiative + self.punctuality
        ) / 6
        super().save(*args, **kwargs)


class ExpenseClaim(models.Model):
    """Note de frais"""
    EXPENSE_TYPES = (
        ('transport', 'Transport'),
        ('meal', 'Repas'),
        ('accommodation', 'Hébergement'),
        ('supplies', 'Fournitures'),
        ('client', 'Client'),
        ('other', 'Autre'),
    )

    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
        ('paid', 'Remboursé'),
    )

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='expenses')
    expense_type = models.CharField(max_length=20, choices=EXPENSE_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    description = models.TextField()
    receipt = models.FileField(upload_to='hr/expenses/', null=True, blank=True)

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(
        Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_expenses')
    approval_date = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)

    payment_date = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee} - {self.get_expense_type_display()} - {self.amount}"


class Document(models.Model):
    """Documents RH"""
    DOCUMENT_TYPES = (
        ('contract', 'Contrat'),
        ('attestation', 'Attestation'),
        ('certificate', 'Certificat'),
        ('procedure', 'Procédure'),
        ('policy', 'Politique'),
        ('other', 'Autre'),
    )

    title = models.CharField(max_length=200)
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES)
    file = models.FileField(upload_to='hr/documents/')
    version = models.CharField(max_length=20, default='1.0')
    description = models.TextField(blank=True, null=True)

    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    is_public = models.BooleanField(default=False)

    uploaded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='uploaded_documents')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} v{self.version}"
