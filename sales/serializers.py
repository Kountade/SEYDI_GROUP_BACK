# sales/serializers.py

from rest_framework import serializers
from django.db.models import Sum
from decimal import Decimal
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
        exclude = ('vente',)
        read_only_fields = ('id', 'total', 'stock_preleve', 'product_name', 'product_reference')


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
        
        sous_total = Decimal('0')
        for item in items_data:
            prix = Decimal(str(item.get('prix_unitaire', 0)))
            qte = Decimal(str(item.get('quantity', 0)))
            sous_total += prix * qte
        
        tva = sous_total * Decimal('0.18')
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
        fields = ('vente', 'montant', 'methode', 'reference_externe', 'notes')
    
    def create(self, validated_data):
        validated_data['encaisse_par'] = self.context['request'].user
        return super().create(validated_data)


# ----------------------------------------------------------------------
# Facture : pas de FactureItem, les détails sont dans la vente associée
# ----------------------------------------------------------------------

class FactureListSerializer(serializers.ModelSerializer):
    client_nom = serializers.CharField(source='client.nom', read_only=True, allow_null=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    statut_display = serializers.CharField(source='get_status_display', read_only=True)
    type_display = serializers.CharField(source='get_type_facture_display', read_only=True)
    
    class Meta:
        model = Facture
        fields = ('id', 'reference', 'type_facture', 'type_display', 'status', 'statut_display',
                  'client_nom', 'agence_nom', 'date_facture', 'date_echeance', 
                  'total_ttc', 'montant_paye', 'montant_restant', 'currency')


class FactureDetailSerializer(serializers.ModelSerializer):
    client = ClientSerializer(read_only=True)
    agence = AgenceSimpleSerializer(read_only=True)
    cree_par = UserSerializer(read_only=True)
    # Récupère les items depuis la vente associée
    items = serializers.SerializerMethodField()
    
    class Meta:
        model = Facture
        fields = '__all__'
    
    def get_items(self, obj):
        """Retourne les items de la vente associée à la facture"""
        if obj.vente:
            return VenteItemSerializer(obj.vente.items.all(), many=True).data
        return []

# sales/serializers.py
class FactureCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Facture
        fields = ('vente', 'type_facture', 'date_echeance', 'conditions_paiement', 'notes', 'pied_de_page')
        read_only_fields = ('id', 'reference', 'status', 'date_facture', 'cree_par',
                           'sous_total', 'tva', 'total_ttc', 'montant_paye', 'montant_restant',
                           'client', 'agence', 'currency')
    
    def validate(self, data):
        vente = data.get('vente')
        if not vente:
            raise serializers.ValidationError({"vente": "La vente est obligatoire"})
        # Vérifier si une facture existe déjà pour cette vente
        if Facture.objects.filter(vente=vente).exists():
            raise serializers.ValidationError({"vente": "Une facture a déjà été générée pour cette vente."})
        if not vente.agence:
            raise serializers.ValidationError({"vente": "La vente sélectionnée n'a pas d'agence associée"})
        return data
    
    def create(self, validated_data):
        vente = validated_data['vente']
        user = self.context['request'].user
        
        facture = Facture.objects.create(
            vente=vente,
            client=vente.client,
            agence=vente.agence,
            cree_par=user,
            type_facture=validated_data.get('type_facture', 'finale'),
            date_echeance=validated_data.get('date_echeance'),
            conditions_paiement=validated_data.get('conditions_paiement', 'Paiement à 30 jours'),
            notes=validated_data.get('notes', ''),
            pied_de_page=validated_data.get('pied_de_page', ''),
            sous_total=vente.sous_total,
            tva=vente.tva,
            total_ttc=vente.total,
            montant_restant=vente.total,
            montant_paye=vente.montant_paye
        )
        return facture


# Serializer pour l'enregistrement d'un paiement sur facture
class FacturePaiementSerializer(serializers.Serializer):
    montant = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    methode = serializers.ChoiceField(choices=Paiement.METHODES_PAIEMENT)
    reference = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)