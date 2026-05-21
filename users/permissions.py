# users/permissions.py
"""
Permissions personnalisées pour l'application users
Gestion des accès basés sur les rôles et les agences
"""

from rest_framework.permissions import BasePermission


class HasAgenceAccess(BasePermission):
    """
    Permission pour vérifier que l'utilisateur a accès à l'agence
    - PDG et DRH ont accès à tout
    - Les autres utilisateurs n'ont accès qu'à leurs agences
    - CORRECTION : Pour les transferts, on autorise si l'utilisateur a accès
      à l'agence source OU à l'agence destination
    """

    def has_permission(self, request, view):
        """Vérifie la permission au niveau de la requête"""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Les superutilisateurs et staff ont tout accès
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # PDG et DRH ont accès à tout
        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True
        
        # Pour le TransferViewSet, toujours autoriser car la validation se fait dans le serializer
        view_name = view.__class__.__name__
        if view_name == 'TransferViewSet':
            return True
        
        return True

    def has_object_permission(self, request, view, obj):
        """Vérifie la permission au niveau de l'objet"""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Les superutilisateurs et staff ont tout accès
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # PDG et DRH ont accès à tout
        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        if hasattr(request.user, 'est_drh') and request.user.est_drh():
            return True
        
        # Pour les objets Transfer, vérifier l'accès à l'agence source OU destination
        # Import différé pour éviter l'import circulaire
        from inventaire.models import Transfer
        
        if isinstance(obj, Transfer):
            has_from_access = request.user.peut_acceder_agence(obj.from_agence_id)
            has_to_access = request.user.peut_acceder_agence(obj.to_agence_id)
            return has_from_access or has_to_access
        
        # Vérifier si l'objet a un champ 'agence'
        if hasattr(obj, 'agence') and obj.agence:
            return request.user.peut_acceder_agence(obj.agence.id)
        
        # Vérifier si l'objet a un champ 'warehouse' avec une agence
        if hasattr(obj, 'warehouse') and obj.warehouse:
            if hasattr(obj.warehouse, 'agence') and obj.warehouse.agence:
                return request.user.peut_acceder_agence(obj.warehouse.agence.id)
        
        # Vérifier si l'objet a un champ 'from_warehouse' ou 'to_warehouse'
        if hasattr(obj, 'from_warehouse') and obj.from_warehouse:
            if hasattr(obj.from_warehouse, 'agence') and obj.from_warehouse.agence:
                return request.user.peut_acceder_agence(obj.from_warehouse.agence.id)
        
        if hasattr(obj, 'to_warehouse') and obj.to_warehouse:
            if hasattr(obj.to_warehouse, 'agence') and obj.to_warehouse.agence:
                return request.user.peut_acceder_agence(obj.to_warehouse.agence.id)
        
        # Si l'objet est une agence directement
        if hasattr(obj, 'est_active'):  # Si c'est une instance d'Agence
            return request.user.peut_acceder_agence(obj.id)
        
        # Par défaut, refuser l'accès par sécurité
        return False


class IsPDG(BasePermission):
    """Permission pour les PDG uniquement"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return hasattr(request.user, 'est_pdg') and request.user.est_pdg()


class IsDRH(BasePermission):
    """Permission pour les DRH uniquement"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return hasattr(request.user, 'est_drh') and request.user.est_drh()


class IsPDGOrDRH(BasePermission):
    """Permission pour les PDG ou DRH"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (hasattr(request.user, 'est_pdg') and request.user.est_pdg()) or \
               (hasattr(request.user, 'est_drh') and request.user.est_drh())


class IsCommercial(BasePermission):
    """Permission pour les commerciaux (ou supérieur)"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if (hasattr(request.user, 'est_pdg') and request.user.est_pdg()) or \
           (hasattr(request.user, 'est_drh') and request.user.est_drh()):
            return True
        
        if hasattr(request.user, 'a_role_dans_agence'):
            agences = request.user.get_agences()
            for agence in agences:
                if request.user.a_role_dans_agence(agence.id, 'commercial'):
                    return True
        
        return False


class IsGestionnaireStock(BasePermission):
    """Permission pour les gestionnaires de stock (ou supérieur)"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if (hasattr(request.user, 'est_pdg') and request.user.est_pdg()) or \
           (hasattr(request.user, 'est_drh') and request.user.est_drh()):
            return True
        
        if hasattr(request.user, 'a_role_dans_agence'):
            agences = request.user.get_agences()
            for agence in agences:
                if request.user.a_role_dans_agence(agence.id, 'gestionnaire_stock'):
                    return True
        
        return False


class IsChefAgence(BasePermission):
    """Permission pour les chefs d'agence (ou supérieur)"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if (hasattr(request.user, 'est_pdg') and request.user.est_pdg()) or \
           (hasattr(request.user, 'est_drh') and request.user.est_drh()):
            return True
        
        if hasattr(request.user, 'a_role_dans_agence'):
            agences = request.user.get_agences()
            for agence in agences:
                if request.user.a_role_dans_agence(agence.id, 'chef_agence'):
                    return True
        
        return False


class HasSpecificAgenceAccess(BasePermission):
    """
    Permission pour vérifier l'accès à une agence spécifique
    Utiliser avec l'URL qui contient un paramètre 'agence_id'
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        if (hasattr(request.user, 'est_pdg') and request.user.est_pdg()) or \
           (hasattr(request.user, 'est_drh') and request.user.est_drh()):
            return True
        
        agence_id = view.kwargs.get('agence_id') or view.kwargs.get('pk')
        
        if agence_id and hasattr(request.user, 'peut_acceder_agence'):
            return request.user.peut_acceder_agence(int(agence_id))
        
        return True


class CanManageInventory(BasePermission):
    """Permission pour la gestion d'inventaire"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        if (hasattr(request.user, 'est_pdg') and request.user.est_pdg()) or \
           (hasattr(request.user, 'est_drh') and request.user.est_drh()):
            return True
        
        if request.user.has_perm('inventory.can_manage_inventory'):
            return True
        
        if hasattr(request.user, 'a_role_dans_agence'):
            agences = request.user.get_agences()
            for agence in agences:
                if request.user.a_role_dans_agence(agence.id, 'gestionnaire_stock') or \
                   request.user.a_role_dans_agence(agence.id, 'chef_agence'):
                    return True
        
        return False


class CanManagePurchases(BasePermission):
    """Permission pour la gestion des achats"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        if (hasattr(request.user, 'est_pdg') and request.user.est_pdg()) or \
           (hasattr(request.user, 'est_drh') and request.user.est_drh()):
            return True
        
        if request.user.has_perm('purchases.can_manage_purchases'):
            return True
        
        if hasattr(request.user, 'a_role_dans_agence'):
            agences = request.user.get_agences()
            for agence in agences:
                if request.user.a_role_dans_agence(agence.id, 'chef_agence'):
                    return True
        
        return False


class CanValidateOrders(BasePermission):
    """Permission pour la validation des commandes"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        if (hasattr(request.user, 'est_pdg') and request.user.est_pdg()) or \
           (hasattr(request.user, 'est_drh') and request.user.est_drh()):
            return True
        
        if request.user.has_perm('users.can_validate_orders'):
            return True
        
        if hasattr(request.user, 'a_role_dans_agence'):
            agences = request.user.get_agences()
            for agence in agences:
                if request.user.a_role_dans_agence(agence.id, 'chef_agence'):
                    return True
        
        return False


class IsPDGOrChefAgence(BasePermission):
    """
    Permission combinée pour PDG ou Chef d'agence
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        
        if hasattr(request.user, 'est_chef_agence') and request.user.est_chef_agence():
            return True
        
        return False
    
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if hasattr(request.user, 'est_pdg') and request.user.est_pdg():
            return True
        
        if hasattr(request.user, 'est_chef_agence') and request.user.est_chef_agence():
            # Vérification spécifique pour un objet avec entrepôt
            if hasattr(obj, 'warehouse') and obj.warehouse:
                if hasattr(obj.warehouse, 'agence'):
                    return request.user.peut_acceder_agence(obj.warehouse.agence.id)
            if hasattr(obj, 'product'):
                # Pour les prix, on autorise si l'utilisateur a un rôle de chef dans l'agence du produit
                return True
        return False