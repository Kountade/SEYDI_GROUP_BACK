from rest_framework.permissions import BasePermission


class IsPDGOrDRH(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.est_pdg() or request.user.est_drh()
        )


class IsChefAgenceOrAbove(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return (
            request.user.est_pdg() or
            request.user.est_drh() or
            request.user.est_chef_agence()
        )
