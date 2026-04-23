from django.shortcuts import render

# Create your views here.
# users/views.py
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from django.contrib.auth import get_user_model, authenticate
from knox.models import AuthToken
from rest_framework.decorators import action
from django.db.models import Q
from .serializers import *
from .models import Agence, RoleAgence, CustomUser

User = get_user_model()


class LoginViewset(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer

    def create(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            password = serializer.validated_data['password']
            user = authenticate(request, email=email, password=password)
            if user:
                if not user.is_active:
                    return Response({"error": "Compte désactivé"}, status=401)
                _, token = AuthToken.objects.create(user)
                user_data = UserSerializer(user).data
                return Response({"user": user_data, "token": token})
            return Response({"error": "Email ou mot de passe incorrect"}, status=401)
        return Response(serializer.errors, status=400)


class RegisterViewset(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({"user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=400)

# users/views.py - UserViewset complet

class UserViewset(viewsets.ViewSet):
    """
    ViewSet pour la gestion des utilisateurs
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Retourne la liste des utilisateurs accessibles selon le rôle
        """
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return User.objects.all()
        # Autres utilisateurs : uniquement ceux de leurs agences
        agences_ids = user.roles_agence.filter(
            est_actif=True).values_list('agence_id', flat=True)
        return User.objects.filter(
            Q(roles_agence__agence_id__in=agences_ids,
              roles_agence__est_actif=True) | Q(id=user.id)
        ).distinct()

    def list(self, request):
        """
        Liste des utilisateurs avec filtres
        """
        queryset = self.get_queryset()
        role_global = request.query_params.get('role_global')
        if role_global:
            queryset = queryset.filter(role_global=role_global)
        agence_id = request.query_params.get('agence_id')
        if agence_id:
            queryset = queryset.filter(
                roles_agence__agence_id=agence_id, roles_agence__est_actif=True)
        serializer = UserSerializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """
        Détails d'un utilisateur
        """
        try:
            user = User.objects.get(pk=pk)
            # Vérification des droits
            if not (request.user.est_pdg() or request.user.est_drh()):
                if request.user.id != user.id:
                    user_agences = user.roles_agence.filter(
                        est_actif=True).values_list('agence_id', flat=True)
                    current_agences = request.user.roles_agence.filter(
                        est_actif=True).values_list('agence_id', flat=True)
                    if not set(user_agences) & set(current_agences):
                        return Response({"error": "Permission denied"}, status=403)
            serializer = UserDetailSerializer(user)
            return Response(serializer.data)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)

    def create(self, request):
        """
        Création d'un utilisateur (via RegisterViewset généralement)
        """
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        """
        Mise à jour complète d'un utilisateur
        """
        if not (request.user.est_pdg() or request.user.est_drh()):
            if request.user.id != int(pk):
                return Response({"error": "Permission denied"}, status=403)
        
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)
        
        serializer = UserDetailSerializer(user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def partial_update(self, request, pk=None):
        """
        Mise à jour partielle d'un utilisateur (pour activation/désactivation)
        """
        # Vérification des droits
        if not (request.user.est_pdg() or request.user.est_drh()):
            if request.user.id != int(pk):
                return Response({"error": "Permission denied. Seul le PDG ou DRH peut modifier les utilisateurs"}, status=403)
        
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)
        
        serializer = UserDetailSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        """
        Suppression d'un utilisateur
        """
        if not (request.user.est_pdg() or request.user.est_drh()):
            return Response({"error": "Permission denied. Seul le PDG ou DRH peut supprimer des utilisateurs"}, status=403)
        
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)
        
        # Ne pas supprimer son propre compte
        if request.user.id == user.id:
            return Response({"error": "Vous ne pouvez pas supprimer votre propre compte"}, status=400)
        
        user.delete()
        return Response({"message": "Utilisateur supprimé avec succès"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'])
    def toggle_active(self, request, pk=None):
        """
        Active ou désactive un utilisateur
        """
        # Vérification des droits
        if not (request.user.est_pdg() or request.user.est_drh()):
            if request.user.id != int(pk):
                return Response({"error": "Permission denied. Seul le PDG ou DRH peut modifier le statut des utilisateurs"}, status=403)
        
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)
        
        # Ne pas désactiver son propre compte
        if request.user.id == user.id and user.is_active:
            return Response({"error": "Vous ne pouvez pas désactiver votre propre compte"}, status=400)
        
        # Inverser le statut
        user.is_active = not user.is_active
        user.save()
        
        status_text = "activé" if user.is_active else "désactivé"
        return Response({
            "id": user.id,
            "is_active": user.is_active,
            "message": f"Utilisateur {user.email} {status_text} avec succès"
        })

    @action(detail=True, methods=['post'])
    def assign_role(self, request, pk=None):
        """
        Assigner un rôle à un utilisateur dans une agence
        """
        if not (request.user.est_pdg() or request.user.est_drh()):
            return Response({"error": "Permission denied"}, status=403)
        
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=404)
        
        serializer = AssignRoleSerializer(data=request.data)
        if serializer.is_valid():
            role = RoleAgence.objects.create(
                user=user,
                agence_id=serializer.validated_data['agence_id'],
                role=serializer.validated_data['role'],
                est_actif=True
            )
            return Response(RoleAgenceSerializer(role).data, status=201)
        return Response(serializer.errors, status=400)

    @action(detail=True, methods=['delete'])
    def remove_role(self, request, pk=None):
        """
        Retirer un rôle d'un utilisateur
        """
        if not (request.user.est_pdg() or request.user.est_drh()):
            return Response({"error": "Permission denied"}, status=403)
        
        role_id = request.data.get('role_id')
        if not role_id:
            return Response({"error": "role_id required"}, status=400)
        
        try:
            role = RoleAgence.objects.get(id=role_id, user_id=pk)
            role.est_actif = False
            role.save()
            return Response({"message": "Rôle retiré avec succès"})
        except RoleAgence.DoesNotExist:
            return Response({"error": "Rôle non trouvé"}, status=404)

    @action(detail=False, methods=['get'])
    def me(self, request):
        """
        Retourne le profil de l'utilisateur connecté
        """
        serializer = UserDetailSerializer(request.user)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        Statistiques des utilisateurs
        """
        if not (request.user.est_pdg() or request.user.est_drh()):
            return Response({"error": "Permission denied"}, status=403)
        
        users = self.get_queryset()
        stats = {
            "total": users.count(),
            "active": users.filter(is_active=True).count(),
            "inactive": users.filter(is_active=False).count(),
            "pdg": users.filter(role_global='pdg').count(),
            "drh": users.filter(role_global='drh').count(),
            "autre": users.filter(role_global='autre').count(),
            "by_agence": {}
        }
        
        # Statistiques par agence
        for agence in Agence.objects.filter(est_active=True):
            count = users.filter(roles_agence__agence_id=agence.id, roles_agence__est_actif=True).count()
            if count > 0:
                stats["by_agence"][agence.nom] = count
        
        return Response(stats)


class ProfileViewset(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserDetailSerializer

    def retrieve(self, request):
        serializer = self.serializer_class(request.user)
        return Response(serializer.data)

    def update(self, request):
        serializer = self.serializer_class(
            request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    @action(detail=False, methods=['get'])
    def agences(self, request):
        agences = request.user.get_agences()
        serializer = AgenceSerializer(agences, many=True)
        return Response(serializer.data)


class AgenceViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AgenceSerializer

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg():
            return Agence.objects.all()
        elif user.est_drh():
            return Agence.objects.filter(est_active=True)
        else:
            agences_ids = user.roles_agence.filter(
                est_actif=True).values_list('agence_id', flat=True)
            return Agence.objects.filter(id__in=agences_ids, est_active=True)

    def get_serializer_class(self):
        if self.action == 'create':
            return AgenceCreateSerializer
        return AgenceSerializer

    def create(self, request, *args, **kwargs):
        if not request.user.est_pdg():
            return Response({"error": "Seul le PDG peut créer des agences"}, status=403)
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            agence = serializer.save(created_by=request.user)
            return Response(AgenceSerializer(agence).data, status=201)
        return Response(serializer.errors, status=400)

    @action(detail=True, methods=['get'])
    def utilisateurs(self, request, pk=None):
        agence = self.get_object()
        if not (request.user.est_pdg() or request.user.est_drh() or request.user.peut_acceder_agence(agence.id)):
            return Response({"error": "Permission denied"}, status=403)
        roles = agence.roles.filter(est_actif=True).select_related('user')
        utilisateurs = [{'user': UserSerializer(
            r.user).data, 'role': r.role, 'role_display': r.get_role_display()} for r in roles]
        return Response(utilisateurs)

    @action(detail=True, methods=['get'])
    def roles_disponibles(self, request, pk=None):
        agence = self.get_object()
        roles = [{'value': r[0], 'label': r[1]}
                 for r in agence.get_roles_disponibles()]
        return Response({'type_agence': agence.type_agence, 'type_display': agence.get_type_agence_display(), 'roles': roles})


class RoleAgenceViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RoleAgenceSerializer
    queryset = RoleAgence.objects.all()

    def get_queryset(self):
        user = self.request.user
        if user.est_pdg() or user.est_drh():
            return RoleAgence.objects.filter(est_actif=True)
        agences_ids = user.roles_agence.filter(
            est_actif=True).values_list('agence_id', flat=True)
        return RoleAgence.objects.filter(agence_id__in=agences_ids, est_actif=True)

    def create(self, request, *args, **kwargs):
        if not (request.user.est_pdg() or request.user.est_drh()):
            return Response({"error": "Permission denied. Seul PDG ou DRH peut assigner des rôles"}, status=403)
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


class AgencesPubliquesViewset(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    def list(self, request):
        agences = Agence.objects.filter(est_active=True)
        serializer = AgenceSerializer(agences, many=True)
        return Response(serializer.data)
