# dashboard/permissions.py
from rest_framework.permissions import BasePermission


class IsPDGOrDRH(BasePermission):
    """
    Permission pour les utilisateurs ayant le rôle global PDG ou DRH.
    Utilisé pour les endpoints sensibles (analyses avancées, etc.)
    """

    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.est_pdg() or request.user.est_drh()
        )


class IsChefAgenceOrAbove(BasePermission):
    """
    Permission pour les chefs d'agence, DRH ou PDG.
    Utilisé pour la plupart des endpoints du tableau de bord.
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # ✅ En production, utilisez cette ligne (décommentez) :
        # return (
        #     request.user.est_pdg() or
        #     request.user.est_drh() or
        #     request.user.est_chef_agence()
        # )

        # ⚠️ Pour le développement, vous pouvez autoriser tous les utilisateurs authentifiés :
        return True   # ← COMMENTEZ CETTE LIGNE EN PRODUCTION
