from rest_framework import serializers
from django.db.models import Sum
from decimal import Decimal
from django.utils import timezone
from .models import *
from produits.serializers import ProductListSerializer
from users.serializers import UserSerializer, AgenceSimpleSerializer
from inventaire.models import Lot  # <-- AJOUT
# si vous voulez afficher des détails
from inventaire.serializers import LotListSerializer


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at', 'created_by')


# ============================================================
# VENTE ITEM SERIALIZER – avec lot
# ============================================================
class VenteItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)
    price_type_display = serializers.CharField(
        source='get_price_type_display', read_only=True)

    # Champs supplémentaires pour le lot
    lot_number = serializers.CharField(
        source='lot.lot_number', read_only=True, allow_null=True)
    lot_expiry = serializers.DateField(
        source='lot.expiry_date', read_only=True, allow_null=True)
    lot_quantity = serializers.IntegerField(
        source='lot.quantity', read_only=True, allow_null=True)

    class Meta:
        model = VenteItem
        exclude = ('vente',)
        read_only_fields = (
            'id', 'total', 'stock_preleve',
            'product_name', 'product_reference', 'price_type_display',
            'lot_number', 'lot_expiry', 'lot_quantity'
        )
        extra_kwargs = {
            # le champ lot est en écriture (ID)
            'lot': {'required': False, 'allow_null': True}
        }


# ============================================================
# VENTE LIST SERIALIZER (inchangé)
# ============================================================
class VenteListSerializer(serializers.ModelSerializer):
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    client_nom = serializers.CharField(
        source='client.nom', read_only=True, allow_null=True)
    vendeur_nom = serializers.CharField(source='vendeur.email', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = Vente
        fields = (
            'id', 'reference', 'type_vente', 'agence_nom', 'client_nom',
            'vendeur_nom', 'status', 'status_display', 'date_vente',
            'sous_total', 'remise', 'total', 'montant_paye',
            'montant_du', 'est_paye'
        )


# ============================================================
# VENTE DETAIL SERIALIZER (inchangé)
# ============================================================
class VenteDetailSerializer(serializers.ModelSerializer):
    agence = AgenceSimpleSerializer(read_only=True)
    client = ClientSerializer(read_only=True)
    vendeur = UserSerializer(read_only=True)
    approved_by = UserSerializer(read_only=True)
    items = VenteItemSerializer(many=True, read_only=True)
    reste_a_payer = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Vente
        fields = '__all__'


# ============================================================
# VENTE CREATE SERIALIZER – avec gestion des lots
# ============================================================
class VenteCreateSerializer(serializers.ModelSerializer):
    items = VenteItemSerializer(many=True, write_only=True)
    client_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = Vente
        fields = ('type_vente', 'agence', 'client_id', 'notes', 'items')
        read_only_fields = (
            'id', 'reference', 'status', 'vendeur', 'date_vente',
            'sous_total', 'remise', 'total', 'montant_paye',
            'montant_du', 'est_paye'
        )

    def validate(self, data):
        items_data = data.get('items', [])
        if not items_data:
            raise serializers.ValidationError(
                {"items": "Au moins un article est requis"})

        agence = data.get('agence')
        if not agence:
            raise serializers.ValidationError(
                {"agence": "L'agence est obligatoire"})

        # Récupérer l'entrepôt par défaut de l'agence
        from inventaire.models import get_default_warehouse
        warehouse = get_default_warehouse(agence)
        if not warehouse:
            raise serializers.ValidationError(
                {"agence": "Aucun entrepôt configuré pour cette agence"})

        # Valider chaque item
        for idx, item_data in enumerate(items_data):
            product = item_data.get('product')
            quantity = item_data.get('quantity', 0)
            # peut être un ID (int) ou un objet Lot
            lot_id = item_data.get('lot')

            if lot_id:
                try:
                    if isinstance(lot_id, Lot):
                        lot_obj = lot_id
                    else:
                        lot_obj = Lot.objects.get(id=int(lot_id))
                except Lot.DoesNotExist:
                    raise serializers.ValidationError({
                        f"items[{idx}]": f"Lot {lot_id} introuvable"
                    })

                # Vérifications du lot
                if lot_obj.warehouse != warehouse:
                    raise serializers.ValidationError({
                        f"items[{idx}]": f"Le lot {lot_obj.lot_number} n'appartient pas à l'entrepôt de l'agence"
                    })
                if lot_obj.quantity < quantity:
                    raise serializers.ValidationError({
                        f"items[{idx}]": f"Le lot {lot_obj.lot_number} n'a que {lot_obj.quantity} unités disponibles, vous demandez {quantity}"
                    })
                if lot_obj.quality_status != 'good':
                    raise serializers.ValidationError({
                        f"items[{idx}]": f"Le lot {lot_obj.lot_number} n'est pas en bon état (statut: {lot_obj.get_quality_status_display()})"
                    })

                # On remplace l'éventuel objet Lot par son ID pour la création
                item_data['lot'] = lot_obj.id

            # Si pas de lot, on laisse le champ vide (None) – le système fera FIFO à l'approbation

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

        total = sous_total  # Pas de TVA

        vente = Vente.objects.create(
            **validated_data,
            client_id=client_id,
            vendeur=user,
            sous_total=sous_total,
            total=total,
            montant_du=total
        )

        # Création des lignes de vente
        for item_data in items_data:
            # Extraire le lot (qui est un ID ou None)
            lot_id = item_data.pop('lot', None)
            VenteItem.objects.create(vente=vente, lot_id=lot_id, **item_data)

        return vente


class DevisItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)

    class Meta:
        model = DevisItem
        fields = ('id', 'product', 'product_name', 'product_reference', 'variant',
                  'quantity', 'prix_unitaire', 'remise', 'total')
        read_only_fields = ('id', 'total')


class DevisListSerializer(serializers.ModelSerializer):
    client_nom = serializers.CharField(
        source='client.nom', read_only=True, allow_null=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    vendeur_nom = serializers.CharField(source='vendeur.email', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = Devis
        fields = ('id', 'reference', 'client_nom', 'agence_nom', 'vendeur_nom', 'status',
                  'status_display', 'date_creation', 'date_expiration', 'sous_total',
                  'remise', 'total')  # Pas de TVA


class DevisDetailSerializer(serializers.ModelSerializer):
    agence = AgenceSimpleSerializer(read_only=True)
    client = ClientSerializer(read_only=True)
    vendeur = UserSerializer(read_only=True)
    items = DevisItemSerializer(many=True, read_only=True)
    est_valide = serializers.BooleanField(read_only=True)
    jours_restants = serializers.IntegerField(read_only=True)

    class Meta:
        model = Devis
        fields = '__all__'  # Pas de TVA


class DevisCreateSerializer(serializers.ModelSerializer):
    items = DevisItemSerializer(many=True, write_only=True)
    client_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = Devis
        fields = ('agence', 'client_id', 'date_expiration', 'notes', 'conditions',
                  'pied_de_page', 'items')
        read_only_fields = ('id', 'reference', 'status', 'vendeur', 'date_creation',
                            'sous_total', 'remise', 'remise_percentage', 'total')

    def validate(self, data):
        items_data = data.get('items', [])
        if not items_data:
            raise serializers.ValidationError(
                {"items": "Au moins un article est requis"})
        if data.get('date_expiration') and data['date_expiration'] < timezone.now().date():
            raise serializers.ValidationError(
                {"date_expiration": "La date d'expiration ne peut pas être dans le passé"})
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

        total = sous_total  # Pas de TVA

        devis = Devis.objects.create(
            **validated_data,
            client_id=client_id,
            vendeur=user,
            sous_total=sous_total,
            total=total
        )

        for item_data in items_data:
            DevisItem.objects.create(devis=devis, **item_data)

        return devis


class PaiementSerializer(serializers.ModelSerializer):
    """Serializer de lecture pour un paiement (inclut les infos de destination)"""
    encaisse_par_nom = serializers.CharField(
        source='encaisse_par.email', read_only=True)

    facture_ref = serializers.CharField(
        source='facture.reference', read_only=True, default='-')
    facture_date = serializers.DateField(
        source='facture.date_facture', read_only=True, default=None)
    facture_total = serializers.DecimalField(
        source='facture.total_ttc', max_digits=12, decimal_places=2, read_only=True, default=0)
    facture_restant = serializers.DecimalField(
        source='facture.montant_restant', max_digits=12, decimal_places=2, read_only=True, default=0)

    facture_client_nom = serializers.CharField(
        source='facture.client.nom', read_only=True, default='Anonyme')
    facture_client_prenom = serializers.CharField(
        source='facture.client.prenom', read_only=True, default='')
    facture_client_email = serializers.CharField(
        source='facture.client.email', read_only=True, default='')
    facture_client_telephone = serializers.CharField(
        source='facture.client.telephone', read_only=True, default='')
    facture_client_adresse = serializers.CharField(
        source='facture.client.adresse', read_only=True, default='')
    facture_client_raison_sociale = serializers.CharField(
        source='facture.client.raison_sociale', read_only=True, default='')

    client_nom = serializers.CharField(
        source='client.nom', read_only=True, default='Anonyme')
    client_prenom = serializers.CharField(
        source='client.prenom', read_only=True, default='')
    client_email = serializers.CharField(
        source='client.email', read_only=True, default='')
    client_telephone = serializers.CharField(
        source='client.telephone', read_only=True, default='')
    client_adresse = serializers.CharField(
        source='client.adresse', read_only=True, default='')
    client_raison_sociale = serializers.CharField(
        source='client.raison_sociale', read_only=True, default='')

    # ============================================================
    # NOUVEAUX CHAMPS : DESTINATION ET MOUVEMENT ASSOCIÉ
    # ============================================================
    caisse_destination_nom = serializers.CharField(
        source='caisse_destination.nom', read_only=True, default=None)
    compte_destination_nom = serializers.CharField(
        source='compte_destination.nom', read_only=True, default=None)
    mouvement_reference = serializers.CharField(
        source='mouvement_tresorerie.reference', read_only=True, default=None)

    class Meta:
        model = Paiement
        # On peut garder tous les champs (y compris les nouveaux)
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at', 'encaisse_par',
                            'mouvement_tresorerie')  # 'mouvement_tresorerie' en lecture seule


class PaiementCreateSerializer(serializers.ModelSerializer):
    """Serializer de création pour un paiement (inclut les champs de destination)"""

    class Meta:
        model = Paiement
        fields = ('facture', 'montant', 'methode', 'reference_externe', 'notes',
                  'caisse_destination', 'compte_destination')  # ajout des champs de destination

    def validate(self, data):
        # --- Validation du montant par rapport au reste de la facture ---
        facture = data.get('facture')
        if not facture:
            raise serializers.ValidationError(
                {"facture": "La facture est obligatoire."})
        if data['montant'] > facture.montant_restant:
            raise serializers.ValidationError({
                "montant": f"Le montant ({data['montant']}) dépasse le restant dû ({facture.montant_restant} FCFA)."
            })

        # --- Validation des destinations ---
        caisse = data.get('caisse_destination')
        compte = data.get('compte_destination')

        # Un seul des deux doit être renseigné
        if caisse and compte:
            raise serializers.ValidationError(
                "Choisissez une seule destination : caisse ou compte bancaire."
            )

        # Si une destination est renseignée, elle doit appartenir à la même agence que la facture
        if caisse and caisse.agence != facture.agence:
            raise serializers.ValidationError(
                {"caisse_destination": "La caisse doit appartenir à la même agence que la facture."}
            )
        if compte and compte.agence != facture.agence:
            raise serializers.ValidationError(
                {"compte_destination": "Le compte bancaire doit appartenir à la même agence que la facture."}
            )

        # Si aucune destination n'est précisée, on laissera le modèle tenter de prendre la caisse par défaut
        # (la validation ne bloque pas, mais on peut ajouter un avertissement)
        return data

    def create(self, validated_data):
        # L'utilisateur qui encaisse est l'utilisateur connecté
        validated_data['encaisse_par'] = self.context['request'].user

        # Récupérer la facture pour en extraire le client et la vente
        facture = validated_data.get('facture')
        if facture:
            validated_data['client'] = facture.client
            if facture.vente:
                validated_data['vente'] = facture.vente

        # Créer le paiement (le modèle fera le reste : mise à jour facture/vente et création mouvement)
        paiement = super().create(validated_data)
        return paiement


class FactureListSerializer(serializers.ModelSerializer):
    client_nom = serializers.CharField(
        source='client.nom', read_only=True, allow_null=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    statut_display = serializers.CharField(
        source='get_status_display', read_only=True)
    type_display = serializers.CharField(
        source='get_type_facture_display', read_only=True)

    class Meta:
        model = Facture
        fields = ('id', 'reference', 'type_facture', 'type_display', 'status', 'statut_display',
                  'client_nom', 'agence_nom', 'date_facture', 'date_echeance',
                  'total_ttc', 'montant_paye', 'montant_restant', 'currency')


class FactureDetailSerializer(serializers.ModelSerializer):
    client = ClientSerializer(read_only=True)
    agence = AgenceSimpleSerializer(read_only=True)
    cree_par = UserSerializer(read_only=True)
    items = serializers.SerializerMethodField()
    paiements = PaiementSerializer(many=True, read_only=True)

    class Meta:
        model = Facture
        fields = '__all__'  # Pas de champ tva

    def get_items(self, obj):
        if obj.vente:
            return VenteItemSerializer(obj.vente.items.all(), many=True).data
        return []


class FactureCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Facture
        fields = ('vente', 'type_facture', 'date_echeance',
                  'conditions_paiement', 'notes', 'pied_de_page')
        read_only_fields = ('id', 'reference', 'status', 'date_facture', 'cree_par',
                            'sous_total', 'total_ttc', 'montant_paye', 'montant_restant',
                            'client', 'agence', 'currency')  # tva supprimé

    def validate(self, data):
        vente = data.get('vente')
        if not vente:
            raise serializers.ValidationError(
                {"vente": "La vente est obligatoire"})
        if Facture.objects.filter(vente=vente).exists():
            raise serializers.ValidationError(
                {"vente": "Une facture a déjà été générée pour cette vente."})
        if not vente.agence:
            raise serializers.ValidationError(
                {"vente": "La vente sélectionnée n'a pas d'agence associée"})
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
            conditions_paiement=validated_data.get(
                'conditions_paiement', 'Paiement à 30 jours'),
            notes=validated_data.get('notes', ''),
            pied_de_page=validated_data.get('pied_de_page', ''),
            sous_total=vente.sous_total,
            # tva supprimé - pas de champ tva
            total_ttc=vente.total,
            montant_restant=vente.total,
            montant_paye=vente.montant_paye
        )
        return facture


class FacturePaiementSerializer(serializers.Serializer):
    montant = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0.01)
    methode = serializers.ChoiceField(choices=Paiement.METHODES_PAIEMENT)
    reference = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
