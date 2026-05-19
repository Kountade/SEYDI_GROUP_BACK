# sales/serializers.py

from rest_framework import serializers
from django.db.models import Sum
from .models import *
from produits.serializers import ProductListSerializer
from users.serializers import UserSerializer, AgenceSimpleSerializer


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at', 'created_by')


class VenteItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(source='product.reference', read_only=True)
    
    class Meta:
        model = VenteItem
        fields = '__all__'
        read_only_fields = ('id', 'total', 'stock_preleve')


class VenteListSerializer(serializers.ModelSerializer):
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    client_nom = serializers.CharField(source='client.nom', read_only=True, allow_null=True)
    vendeur_nom = serializers.CharField(source='vendeur.email', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = Vente
        fields = ('id', 'reference', 'type_vente', 'agence_nom', 'client_nom', 
                  'vendeur_nom', 'status', 'status_display', 'date_vente',
                  'sous_total', 'remise', 'tva', 'total', 'montant_paye', 
                  'montant_du', 'est_paye')


class VenteDetailSerializer(serializers.ModelSerializer):
    agence = AgenceSimpleSerializer(read_only=True)
    client = ClientSerializer(read_only=True)
    vendeur = UserSerializer(read_only=True)
    approved_by = UserSerializer(read_only=True)
    items = VenteItemSerializer(many=True, read_only=True)
    reste_a_payer = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    
    class Meta:
        model = Vente
        fields = '__all__'


class VenteCreateSerializer(serializers.ModelSerializer):
    items = VenteItemSerializer(many=True, write_only=True)
    client_id = serializers.IntegerField(required=False, allow_null=True)
    
    class Meta:
        model = Vente
        fields = ('type_vente', 'agence', 'client_id', 'notes', 'items')
        read_only_fields = ('id', 'reference', 'status', 'vendeur', 'date_vente',
                           'sous_total', 'remise', 'tva', 'total', 'montant_paye', 
                           'montant_du', 'est_paye')
    
    def validate(self, data):
        items_data = data.get('items', [])
        if not items_data:
            raise serializers.ValidationError({"items": "Au moins un article est requis"})
        return data
    
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        client_id = validated_data.pop('client_id', None)
        user = self.context['request'].user
        
        # Calculer les totaux
        sous_total = sum((item.get('prix_unitaire', 0) * item.get('quantity', 0) for item in items_data))
        tva = sous_total * 0.18
        total = sous_total + tva
        
        vente = Vente.objects.create(
            **validated_data,
            client_id=client_id,
            vendeur=user,
            sous_total=sous_total,
            tva=tva,
            total=total,
            montant_du=total
        )
        
        for item_data in items_data:
            VenteItem.objects.create(vente=vente, **item_data)
        
        return vente


class PaiementSerializer(serializers.ModelSerializer):
    encaisse_par_nom = serializers.CharField(source='encaisse_par.email', read_only=True)
    
    class Meta:
        model = Paiement
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'encaisse_par')


class PaiementCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paiement
        fields = ('vente', 'montant', 'methode', 'reference', 'notes')
    
    def create(self, validated_data):
        validated_data['encaisse_par'] = self.context['request'].user
        return super().create(validated_data)


class FactureItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    
    class Meta:
        model = FactureItem
        fields = '__all__'
        read_only_fields = ('id', 'montant_ht', 'montant_tva', 'montant_ttc')


class FactureListSerializer(serializers.ModelSerializer):
    client_nom = serializers.CharField(source='client.nom', read_only=True, allow_null=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    statut_display = serializers.CharField(source='get_statut_display', read_only=True)
    
    class Meta:
        model = Facture
        fields = ('id', 'reference', 'type_facture', 'statut', 'statut_display',
                  'client_nom', 'agence_nom', 'date_facture', 'date_echeance', 
                  'total_ttc', 'montant_paye', 'montant_restant')


class FactureDetailSerializer(serializers.ModelSerializer):
    client = ClientSerializer(read_only=True)
    agence = AgenceSimpleSerializer(read_only=True)
    items = FactureItemSerializer(many=True, read_only=True)
    cree_par = UserSerializer(read_only=True)
    
    class Meta:
        model = Facture
        fields = '__all__'


class FactureCreateSerializer(serializers.ModelSerializer):
    items = FactureItemSerializer(many=True, write_only=True)
    
    class Meta:
        model = Facture
        fields = ('vente', 'client', 'agence', 'type_facture', 'date_echeance',
                  'conditions_paiement', 'notes', 'pied_de_page', 'items')
        read_only_fields = ('id', 'reference', 'statut', 'date_facture', 'cree_par',
                           'sous_total', 'tva', 'total_ttc', 'montant_paye', 'montant_restant')
    
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        user = self.context['request'].user
        
        sous_total = sum((item['prix_unitaire_ht'] * item['quantite'] for item in items_data))
        tva = sum((item['prix_unitaire_ht'] * item['quantite'] * (item.get('tva', 18) / 100) for item in items_data))
        total_ttc = sous_total + tva
        
        facture = Facture.objects.create(
            **validated_data,
            cree_par=user,
            sous_total=sous_total,
            tva=tva,
            total_ttc=total_ttc,
            montant_restant=total_ttc
        )
        
        for item_data in items_data:
            FactureItem.objects.create(facture=facture, **item_data)
        
        return facture


class FacturePaiementSerializer(serializers.Serializer):
    montant = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    methode = serializers.ChoiceField(choices=Paiement.METHODES)
    reference = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)