from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register('register', RegisterViewset, basename='register')
router.register('login', LoginViewset, basename='login')
router.register('users', UserViewset, basename='users')
router.register('profile', ProfileViewset, basename='profile')
router.register('agences', AgenceViewset, basename='agences')
router.register('roles', RoleAgenceViewset, basename='roles')

urlpatterns = [
    path('', include(router.urls)),
]
