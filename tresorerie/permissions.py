from rest_framework import permissions


class IsTresorerieManager(permissions.BasePermission):
    """Vérifie si l'utilisateur est responsable trésorerie"""

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and (
            request.user.est_pdg() or
            request.user.est_drh() or
            request.user.est_comptable() or
            request.user.has_perm('tresorerie.can_manage_tresorerie')
        )


class CanManageCaisse(permissions.BasePermission):
    """Vérifie si l'utilisateur peut gérer une caisse"""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.est_pdg() or request.user.est_drh():
            return True
        return request.user.caisses_gerrees.filter(is_active=True).exists()
