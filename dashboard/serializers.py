from rest_framework import serializers

class DashboardOverviewSerializer(serializers.Serializer):
    total_agences = serializers.IntegerField()
    total_utilisateurs = serializers.IntegerField()
    total_produits = serializers.IntegerField()
    total_fournisseurs = serializers.IntegerField()
    total_employes = serializers.IntegerField()
    total_ca = serializers.DecimalField(max_digits=15, decimal_places=2)
    ca_jour = serializers.DecimalField(max_digits=15, decimal_places=2)
    ca_mois = serializers.DecimalField(max_digits=15, decimal_places=2)
    ventes_en_attente = serializers.IntegerField()
    impayes = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_achats = serializers.DecimalField(max_digits=15, decimal_places=2)
    commandes_encours = serializers.IntegerField()
    commandes_retard = serializers.IntegerField()
    valeur_stock = serializers.DecimalField(max_digits=15, decimal_places=2)
    alertes_stock = serializers.IntegerField()
    transferts_encours = serializers.IntegerField()
    employes_actifs = serializers.IntegerField()
    conges_en_attente = serializers.IntegerField()
    absences_jour = serializers.IntegerField()
    dernieres_ventes = serializers.ListField()
    derniers_achats = serializers.ListField()
    alertes_recentes = serializers.ListField()

class VentesParMoisSerializer(serializers.Serializer):
    mois = serializers.CharField()
    total = serializers.DecimalField(max_digits=15, decimal_places=2)

class TopProduitsSerializer(serializers.Serializer):
    produit = serializers.CharField()
    quantite = serializers.IntegerField()
    total = serializers.DecimalField(max_digits=15, decimal_places=2)

class AlertesStockSerializer(serializers.Serializer):
    produit = serializers.CharField()
    stock = serializers.IntegerField()
    seuil = serializers.IntegerField()
    agence = serializers.CharField()
    message = serializers.CharField()
    created_at = serializers.DateTimeField()