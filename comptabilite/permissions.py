# comptabilite/permissions.py
"""
Permissions personnalisées pour l'application Comptabilité
Gestion des accès basés sur les rôles et les agences
"""

from rest_framework.permissions import BasePermission


class HasAccountingAccess(BasePermission):
    """
    Permission de base pour l'accès à la comptabilité
    - PDG et DRH ont accès à tout
    - Comptables ont accès à leur agence
    - Chefs d'agence ont accès à leur agence (lecture)
    - Les autres utilisateurs n'ont pas accès
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Superutilisateurs
        if request.user.is_superuser or request.user.is_staff:
            return True

        # PDG et DRH
        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True

        # Comptable ou chef d'agence
        if hasattr(request.user, 'est_comptable') and request.user.est_comptable():
            return True
        if hasattr(request.user, 'est_chef_agence') and request.user.est_chef_agence():
            return True

        return False

    def has_object_permission(self, request, view, obj):
        """Vérification au niveau de l'objet"""
        if not request.user or not request.user.is_authenticated:
            return False

        # Superutilisateurs
        if request.user.is_superuser or request.user.is_staff:
            return True

        # PDG et DRH
        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True

        # Vérifier l'accès à l'agence de l'objet
        agence_id = self._get_agence_id(obj)
        if agence_id:
            if hasattr(request.user, 'peut_acceder_agence'):
                return request.user.peut_acceder_agence(agence_id)
            # Fallback: vérifier les rôles
            if hasattr(request.user, 'a_role_dans_agence'):
                return (request.user.a_role_dans_agence(agence_id, 'comptable') or
                        request.user.a_role_dans_agence(agence_id, 'chef_agence'))

        return False

    def _get_agence_id(self, obj):
        """Extrait l'agence_id de l'objet"""
        if hasattr(obj, 'agence') and obj.agence:
            return obj.agence.id if hasattr(obj.agence, 'id') else obj.agence
        if hasattr(obj, 'agence_id'):
            return obj.agence_id
        return None


class IsComptableOrSuperior(BasePermission):
    """
    Permission pour les comptables et supérieurs (PDG, DRH)
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True
        if hasattr(request.user, 'est_comptable') and request.user.est_comptable():
            return True

        return False

    def has_object_permission(self, request, view, obj):
        """Vérification au niveau de l'objet"""
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True

        # Vérifier que le comptable a accès à l'agence
        agence_id = self._get_agence_id(obj)
        if agence_id and hasattr(request.user, 'peut_acceder_agence'):
            return request.user.peut_acceder_agence(agence_id)

        return False

    def _get_agence_id(self, obj):
        """Extrait l'agence_id de l'objet"""
        if hasattr(obj, 'agence') and obj.agence:
            return obj.agence.id if hasattr(obj.agence, 'id') else obj.agence
        if hasattr(obj, 'agence_id'):
            return obj.agence_id
        return None


class CanManagePlanComptable(BasePermission):
    """
    Permission pour gérer le plan comptable
    - Seul PDG, DRH ou comptable peuvent gérer le plan comptable
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True
        if hasattr(request.user, 'est_comptable') and request.user.est_comptable():
            return True

        return False


class CanManageEcritures(BasePermission):
    """
    Permission pour gérer les écritures comptables
    - PDG, DRH, comptable: création/modification
    - Chef d'agence: lecture seule
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True
        if hasattr(request.user, 'est_comptable') and request.user.est_comptable():
            return True

        # Lecture seule pour les chefs d'agence
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            if hasattr(request.user, 'est_chef_agence') and request.user.est_chef_agence():
                return True

        return False

    def has_object_permission(self, request, view, obj):
        """Vérification au niveau de l'objet"""
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True

        agence_id = self._get_agence_id(obj)
        if agence_id:
            if hasattr(request.user, 'peut_acceder_agence'):
                return request.user.peut_acceder_agence(agence_id)

        return False

    def _get_agence_id(self, obj):
        """Extrait l'agence_id de l'objet"""
        if hasattr(obj, 'agence') and obj.agence:
            return obj.agence.id if hasattr(obj.agence, 'id') else obj.agence
        if hasattr(obj, 'agence_id'):
            return obj.agence_id
        return None


class CanValidateEcritures(BasePermission):
    """
    Permission pour valider les écritures comptables
    - PDG, DRH, comptable peuvent valider
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True
        if hasattr(request.user, 'est_comptable') and request.user.est_comptable():
            return True

        return False

    def has_object_permission(self, request, view, obj):
        """Vérification au niveau de l'objet"""
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True

        # Vérifier que le comptable a accès à l'agence
        agence_id = self._get_agence_id(obj)
        if agence_id and hasattr(request.user, 'peut_acceder_agence'):
            return request.user.peut_acceder_agence(agence_id)

        return False

    def _get_agence_id(self, obj):
        """Extrait l'agence_id de l'objet"""
        if hasattr(obj, 'agence') and obj.agence:
            return obj.agence.id if hasattr(obj.agence, 'id') else obj.agence
        if hasattr(obj, 'agence_id'):
            return obj.agence_id
        return None


class CanManageFacturesComptables(BasePermission):
    """
    Permission pour gérer les factures comptables
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True
        if hasattr(request.user, 'est_comptable') and request.user.est_comptable():
            return True

        # Lecture seule pour les chefs d'agence
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            if hasattr(request.user, 'est_chef_agence') and request.user.est_chef_agence():
                return True

        return False

    def has_object_permission(self, request, view, obj):
        """Vérification au niveau de l'objet"""
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True

        agence_id = self._get_agence_id(obj)
        if agence_id and hasattr(request.user, 'peut_acceder_agence'):
            return request.user.peut_acceder_agence(agence_id)

        return False

    def _get_agence_id(self, obj):
        """Extrait l'agence_id de l'objet"""
        if hasattr(obj, 'agence') and obj.agence:
            return obj.agence.id if hasattr(obj.agence, 'id') else obj.agence
        if hasattr(obj, 'agence_id'):
            return obj.agence_id
        return None


class CanManageReglements(BasePermission):
    """
    Permission pour gérer les règlements
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True
        if hasattr(request.user, 'est_comptable') and request.user.est_comptable():
            return True

        # Lecture seule pour les chefs d'agence
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            if hasattr(request.user, 'est_chef_agence') and request.user.est_chef_agence():
                return True

        return False

    def has_object_permission(self, request, view, obj):
        """Vérification au niveau de l'objet"""
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True

        agence_id = self._get_agence_id(obj)
        if agence_id and hasattr(request.user, 'peut_acceder_agence'):
            return request.user.peut_acceder_agence(agence_id)

        return False

    def _get_agence_id(self, obj):
        """Extrait l'agence_id de l'objet"""
        if hasattr(obj, 'agence') and obj.agence:
            return obj.agence.id if hasattr(obj.agence, 'id') else obj.agence
        if hasattr(obj, 'agence_id'):
            return obj.agence_id
        return None


class CanViewReports(BasePermission):
    """
    Permission pour consulter les rapports comptables
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True
        if hasattr(request.user, 'est_comptable') and request.user.est_comptable():
            return True
        if hasattr(request.user, 'est_chef_agence') and request.user.est_chef_agence():
            return True

        return False


class CanManageCloture(BasePermission):
    """
    Permission pour gérer les clôtures comptables
    - PDG, DRH, comptable uniquement
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True
        if hasattr(request.user, 'est_comptable') and request.user.est_comptable():
            return True

        return False

    def has_object_permission(self, request, view, obj):
        """Vérification au niveau de l'objet"""
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True

        agence_id = self._get_agence_id(obj)
        if agence_id and hasattr(request.user, 'peut_acceder_agence'):
            return request.user.peut_acceder_agence(agence_id)

        return False

    def _get_agence_id(self, obj):
        """Extrait l'agence_id de l'objet"""
        if hasattr(obj, 'agence') and obj.agence:
            return obj.agence.id if hasattr(obj.agence, 'id') else obj.agence
        if hasattr(obj, 'agence_id'):
            return obj.agence_id
        return None


class CanManageAnalyses(BasePermission):
    """
    Permission pour gérer les analyses financières
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True
        if hasattr(request.user, 'est_comptable') and request.user.est_comptable():
            return True

        return False

    def has_object_permission(self, request, view, obj):
        """Vérification au niveau de l'objet"""
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser or request.user.is_staff:
            return True

        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True

        agence_id = self._get_agence_id(obj)
        if agence_id and hasattr(request.user, 'peut_acceder_agence'):
            return request.user.peut_acceder_agence(agence_id)

        return False

    def _get_agence_id(self, obj):
        """Extrait l'agence_id de l'objet"""
        if hasattr(obj, 'agence') and obj.agence:
            return obj.agence.id if hasattr(obj.agence, 'id') else obj.agence
        if hasattr(obj, 'agence_id'):
            return obj.agence_id
        return None
