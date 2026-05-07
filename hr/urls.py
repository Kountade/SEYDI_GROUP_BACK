from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()

# Enregistrement des ViewSets avec basename
router.register(r'departments', DepartmentViewset, basename='hr-department')
router.register(r'positions', PositionViewset, basename='hr-position')
router.register(r'employees', EmployeeViewset, basename='hr-employee')
router.register(r'leaves', LeaveViewset, basename='hr-leave')
router.register(r'attendance', AttendanceViewset, basename='hr-attendance')
router.register(r'payroll', PayrollViewset, basename='hr-payroll')
router.register(r'recruitments', RecruitmentViewset, basename='hr-recruitment')
router.register(r'candidates', CandidateViewset, basename='hr-candidate')
router.register(r'trainings', TrainingViewset, basename='hr-training')
router.register(r'performance', PerformanceReviewViewset,
                basename='hr-performance')
router.register(r'expenses', ExpenseClaimViewset, basename='hr-expense')
router.register(r'documents', DocumentViewset, basename='hr-document')
router.register(r'stats', HRStatsViewset, basename='hr-stats')

urlpatterns = [
    path('', include(router.urls)),


]
