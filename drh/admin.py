from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import (
    Departement, Poste, Employe, Contrat,
    TypeConge, DemandeConge, Pointage, Absence,
    Formation, ParticipationFormation
)


# ============================================================
# DÉPARTEMENT
# ============================================================

@admin.register(Departement)
class DepartementAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code', 'agence', 'est_actif', 'date_creation']
    list_filter = ['agence', 'est_actif']
    search_fields = ['nom', 'code']


# ============================================================
# POSTE
# ============================================================

@admin.register(Poste)
class PosteAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code', 'departement', 'niveau',
                    'salaire_min', 'salaire_max', 'est_actif']
    list_filter = ['departement', 'niveau', 'est_actif']
    search_fields = ['nom', 'code']


# ============================================================
# EMPLOYÉ
# ============================================================

@admin.register(Employe)
class EmployeAdmin(admin.ModelAdmin):
    list_display = ['matricule', 'nom', 'prenom', 'email', 'poste',
                    'departement', 'agence', 'est_actif', 'date_embauche']
    list_filter = ['agence', 'departement', 'poste', 'sexe', 'est_actif']
    search_fields = ['matricule', 'nom', 'prenom', 'email']
    readonly_fields = ['matricule']

    actions = ['activer_employes', 'desactiver_employes']

    def activer_employes(self, request, queryset):
        queryset.update(est_actif=True)
        self.message_user(request, 'Employés activés')
    activer_employes.short_description = "Activer"

    def desactiver_employes(self, request, queryset):
        queryset.update(est_actif=False)
        self.message_user(request, 'Employés désactivés')
    desactiver_employes.short_description = "Désactiver"


# ============================================================
# CONTRAT
# ============================================================

@admin.register(Contrat)
class ContratAdmin(admin.ModelAdmin):
    list_display = ['reference', 'employe', 'type_contrat',
                    'statut', 'date_debut', 'date_fin', 'salaire_brut']
    list_filter = ['type_contrat', 'statut']
    search_fields = ['reference', 'employe__nom', 'employe__prenom']
    readonly_fields = ['reference']

    actions = ['signer_contrats']

    def signer_contrats(self, request, queryset):
        from datetime import date
        queryset.filter(statut='brouillon').update(
            statut='signe', date_signature=date.today())
        self.message_user(request, 'Contrats signés')
    signer_contrats.short_description = "Signer"


# ============================================================
# TYPE DE CONGÉ
# ============================================================

@admin.register(TypeConge)
class TypeCongeAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code',
                    'nombre_jours_par_an', 'est_paye', 'est_actif']
    list_filter = ['est_paye', 'est_actif']
    search_fields = ['nom', 'code']


# ============================================================
# DEMANDE DE CONGÉ
# ============================================================

@admin.register(DemandeConge)
class DemandeCongeAdmin(admin.ModelAdmin):
    list_display = ['employe', 'type_conge', 'date_debut',
                    'date_fin', 'nombre_jours', 'statut', 'date_demande']
    list_filter = ['type_conge', 'statut']
    search_fields = ['employe__nom', 'employe__prenom', 'motif']

    actions = ['valider_demandes', 'refuser_demandes']

    def valider_demandes(self, request, queryset):
        from datetime import datetime
        queryset.filter(statut='en_attente').update(
            statut='validee', date_validation=datetime.now(), valide_par=request.user)
        self.message_user(request, 'Demandes validées')
    valider_demandes.short_description = "Valider"

    def refuser_demandes(self, request, queryset):
        queryset.filter(statut='en_attente').update(statut='refusee')
        self.message_user(request, 'Demandes refusées')
    refuser_demandes.short_description = "Refuser"


# ============================================================
# POINTAGE
# ============================================================

@admin.register(Pointage)
class PointageAdmin(admin.ModelAdmin):
    list_display = ['employe', 'type_pointage', 'date_heure', 'est_valide']
    list_filter = ['type_pointage', 'est_valide']
    search_fields = ['employe__nom', 'employe__prenom']


# ============================================================
# ABSENCE
# ============================================================

@admin.register(Absence)
class AbsenceAdmin(admin.ModelAdmin):
    list_display = ['employe', 'type_absence', 'date_debut',
                    'date_fin', 'justifiee', 'est_validee']
    list_filter = ['type_absence', 'justifiee', 'est_validee']
    search_fields = ['employe__nom', 'employe__prenom']


# ============================================================
# FORMATION
# ============================================================

@admin.register(Formation)
class FormationAdmin(admin.ModelAdmin):
    list_display = ['titre', 'code', 'date_debut',
                    'date_fin', 'formateur', 'organisme', 'statut']
    list_filter = ['statut', 'organisme']
    search_fields = ['titre', 'code', 'formateur', 'organisme']


# ============================================================
# PARTICIPATION FORMATION
# ============================================================

@admin.register(ParticipationFormation)
class ParticipationFormationAdmin(admin.ModelAdmin):
    list_display = ['employe', 'formation', 'resultat', 'date_inscription']
    list_filter = ['formation', 'resultat']
    search_fields = ['employe__nom', 'employe__prenom', 'formation__titre']
