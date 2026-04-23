from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Agence, RoleAgence


# ================================
# ROLE AGENCE INLINE
# ================================
class RoleAgenceInline(admin.TabularInline):
    model = RoleAgence
    extra = 1


# ================================
# CUSTOM USER ADMIN
# ================================
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):

    model = CustomUser

    list_display = (
        'email',
        'get_full_name_display',
        'role_global',
        'agence_principale',
        'is_active',
        'is_staff'
    )

    list_filter = ('role_global', 'is_active', 'is_staff')

    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)

    inlines = [RoleAgenceInline]

    fieldsets = (
        ("Connexion", {
            'fields': ('email', 'password')
        }),

        ("Informations personnelles", {
            'fields': (
                'first_name',
                'last_name',
                'birthday',
                'phone',
                'address',
                'city',
                'postal_code',
                'country',
                'profile_picture'
            )
        }),

        ("Informations professionnelles", {
            'fields': (
                'employee_id',
                'hire_date',
                'contract_type',
                'salary',
                'agence_principale',
                'role_global'
            )
        }),

        ("Permissions", {
            'fields': (
                'is_active',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions'
            )
        }),

        ("Dates", {
            'fields': ('last_login', 'created_at', 'updated_at')
        }),
    )

    readonly_fields = ('created_at', 'updated_at', 'last_login')


# ================================
# AGENCE ADMIN
# ================================
@admin.register(Agence)
class AgenceAdmin(admin.ModelAdmin):

    list_display = (
        'nom',
        'code',
        'type_agence',
        'ville',
        'est_active'
    )

    list_filter = ('type_agence', 'est_active', 'ville')
    search_fields = ('nom', 'code', 'ville')

    readonly_fields = ('code', 'date_creation', 'date_modification')

    fieldsets = (
        ("Informations générales", {
            'fields': ('nom', 'type_agence', 'code')
        }),

        ("Contact", {
            'fields': ('telephone', 'email')
        }),

        ("Adresse", {
            'fields': ('adresse', 'ville', 'code_postal', 'pays')
        }),

        ("Meta", {
            'fields': ('est_active', 'created_by', 'date_creation', 'date_modification')
        }),
    )


# ================================
# ROLE AGENCE ADMIN
# ================================
@admin.register(RoleAgence)
class RoleAgenceAdmin(admin.ModelAdmin):

    list_display = (
        'user',
        'agence',
        'role',
        'est_actif',
        'date_attribution'
    )

    list_filter = ('role', 'est_actif', 'agence')
    search_fields = ('user__email', 'agence__nom')

    autocomplete_fields = ('user', 'agence')