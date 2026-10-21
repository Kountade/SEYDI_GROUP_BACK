# sales/serializers.py

from rest_framework import serializers
from django.db.models import Sum
from decimal import Decimal
from django.utils import timezone

from .models import *
from produits.serializers import ProductListSerializer
from users.serializers import UserSerializer, AgenceSimpleSerializer

# ✅ SUPPRIMÉ : import au niveau module qui causait le cycle
# from inventaire.models import Lot
# from inventaire.serializers import LotListSerializer
#
# ✅ Ces imports sont maintenant faits LOCALEMENT dans les méthodes
#    qui en ont besoin (voir VenteItemSerializer, VenteCreateSerializer)


# ============================================================
# HELPERS
# ============================================================
def _dec_or_zero(value):
    """Retourne Decimal(0) si la valeur est None."""
    return value if value is not None else Decimal('0')


# ============================================================
# CLIENT
# ============================================================
class ClientSerializer(serializers.ModelSerializer):
    """Serializer de base (création / mise à jour)."""
    class Meta:
        model = Client
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at', 'created_by')


class ClientListSerializer(serializers.ModelSerializer):
    """
    ✅ Serializer allégé pour la liste.
    Utilise les annotations `ventes_count`, `total_achats`, `total_paye`
    injectées par le ViewSet → 0 N+1.
    """
    ventes_count = serializers.IntegerField(read_only=True, default=0)
    total_achats = serializers.SerializerMethodField()
    total_paye = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = (
            'id', 'client_type', 'nom', 'prenom', 'email', 'telephone',
            'adresse', 'raison_sociale', 'numero_tva', 'est_revendeur',
            'is_active', 'created_at', 'updated_at',
            'ventes_count', 'total_achats', 'total_paye',
        )

    def get_total_achats(self, obj):
        value = getattr(obj, 'total_achats', None)
        return _dec_or_zero(value)

    def get_total_paye(self, obj):
        value = getattr(obj, 'total_paye', None)
        return _dec_or_zero(value)


class ClientDetailSerializer(serializers.ModelSerializer):
    """
    ✅ Serializer de détail.
    - Utilise les annotations du ViewSet (`total_ventes`, `total_achats`, etc.)
    - Utilise le Prefetch `_ventes_prefetched` si présent
    - Fallback : requête ciblée (jamais `obj.ventes.all()` en boucle)
    """
    ventes = serializers.SerializerMethodField()
    factures = serializers.SerializerMethodField()
    total_ventes = serializers.SerializerMethodField()
    total_factures = serializers.SerializerMethodField()
    total_achats = serializers.SerializerMethodField()
    total_paye = serializers.SerializerMethodField()
    reste_a_payer = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source='created_by.email', read_only=True, default='')

    class Meta:
        model = Client
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at', 'created_by')

    # ---------- relations ----------
    def get_ventes(self, obj):
        qs = getattr(obj, '_ventes_prefetched', None)
        if qs is None:
            qs = (obj.ventes
                  .select_related('agence', 'client', 'vendeur')
                  .order_by('-date_vente')[:20])
        return VenteListSerializer(qs, many=True, context=self.context).data

    def get_factures(self, obj):
        qs = getattr(obj, '_factures_prefetched', None)
        if qs is None:
            qs = (Facture.objects
                  .filter(client=obj)
                  .select_related('agence', 'client')
                  .order_by('-date_facture')[:20])
        return FactureListSerializer(qs, many=True, context=self.context).data

    # ---------- stats ----------
    def get_total_ventes(self, obj):
        v = getattr(obj, 'total_ventes', None)
        if v is not None:
            return v
        return obj.ventes.count()

    def get_total_factures(self, obj):
        v = getattr(obj, 'total_factures', None)
        if v is not None:
            return v
        return Facture.objects.filter(client=obj).count()

    def get_total_achats(self, obj):
        v = getattr(obj, 'total_achats', None)
        if v is not None:
            return _dec_or_zero(v)
        return _dec_or_zero(obj.ventes.aggregate(t=Sum('total'))['t'])

    def get_total_paye(self, obj):
        v = getattr(obj, 'total_paye', None)
        if v is not None:
            return _dec_or_zero(v)
        return _dec_or_zero(obj.ventes.aggregate(t=Sum('montant_paye'))['t'])

    def get_reste_a_payer(self, obj):
        achats = self.get_total_achats(obj)
        paye = self.get_total_paye(obj)
        return _dec_or_zero(achats) - _dec_or_zero(paye)


# ============================================================
# VENTE ITEM
# ============================================================
class VenteItemSerializer(serializers.ModelSerializer):
    """
    Serializer pour les lignes de vente.

    ✅ IMPORT LOCAL : `Lot` et `LotListSerializer` sont importés
       dans les méthodes pour éviter le cycle `inventaire` ↔ `sales`.
    """
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)
    price_type_display = serializers.CharField(
        source='get_price_type_display', read_only=True)

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
            'lot': {'required': False, 'allow_null': True}
        }


# ============================================================
# VENTE LIST
# ============================================================
class VenteListSerializer(serializers.ModelSerializer):
    agence_id = serializers.IntegerField(source='agence.id', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    client_id = serializers.IntegerField(
        source='client.id', read_only=True, allow_null=True)
    client_nom = serializers.CharField(
        source='client.nom', read_only=True, allow_null=True)
    vendeur_nom = serializers.CharField(source='vendeur.email', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = Vente
        fields = (
            'id', 'reference', 'type_vente',
            'agence_id', 'agence_nom',
            'client_id', 'client_nom',
            'vendeur_nom', 'status', 'status_display', 'date_vente',
            'sous_total', 'remise', 'total', 'montant_paye',
            'montant_du', 'est_paye',
        )


# ============================================================
# VENTE DETAIL
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
# VENTE CREATE (avec gestion des lots)
# ============================================================
class VenteCreateSerializer(serializers.ModelSerializer):
    """
    Serializer pour la création d'une vente.

    ✅ IMPORT LOCAL : `Lot` importé dans `validate()` et `create()`.
    """
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

        # ✅ Import local pour éviter le cycle
        from inventaire.models import get_default_warehouse, Lot

        warehouse = get_default_warehouse(agence)
        if not warehouse:
            raise serializers.ValidationError(
                {"agence": "Aucun entrepôt configuré pour cette agence"})

        for idx, item_data in enumerate(items_data):
            quantity = item_data.get('quantity', 0)
            lot_id = item_data.get('lot')

            if lot_id:
                try:
                    if isinstance(lot_id, Lot):
                        lot_obj = lot_id
                    else:
                        lot_obj = Lot.objects.get(id=int(lot_id))
                except Lot.DoesNotExist:
                    raise serializers.ValidationError({
                        f"items[{idx}]": f"Lot {lot_id} introuvable"})

                if lot_obj.warehouse != warehouse:
                    raise serializers.ValidationError({
                        f"items[{idx}]": (
                            f"Le lot {lot_obj.lot_number} n'appartient pas "
                            f"à l'entrepôt de l'agence"
                        )})
                if lot_obj.quantity < quantity:
                    raise serializers.ValidationError({
                        f"items[{idx}]": (
                            f"Le lot {lot_obj.lot_number} n'a que "
                            f"{lot_obj.quantity} unités disponibles, "
                            f"vous demandez {quantity}"
                        )})
                if lot_obj.quality_status != 'good':
                    raise serializers.ValidationError({
                        f"items[{idx}]": (
                            f"Le lot {lot_obj.lot_number} n'est pas en bon "
                            f"état (statut: {lot_obj.get_quality_status_display()})"
                        )})

                item_data['lot'] = lot_obj.id

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
            montant_du=total,
        )

        for item_data in items_data:
            lot_id = item_data.pop('lot', None)
            VenteItem.objects.create(vente=vente, lot_id=lot_id, **item_data)

        return vente


# ============================================================
# DEVIS
# ============================================================
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
    client_id = serializers.IntegerField(
        source='client.id', read_only=True, allow_null=True)
    client_nom = serializers.CharField(
        source='client.nom', read_only=True, allow_null=True)
    agence_id = serializers.IntegerField(source='agence.id', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    vendeur_nom = serializers.CharField(source='vendeur.email', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = Devis
        fields = (
            'id', 'reference',
            'client_id', 'client_nom',
            'agence_id', 'agence_nom',
            'vendeur_nom', 'status', 'status_display',
            'date_creation', 'date_expiration',
            'sous_total', 'remise', 'total',
        )


class DevisDetailSerializer(serializers.ModelSerializer):
    agence = AgenceSimpleSerializer(read_only=True)
    client = ClientSerializer(read_only=True)
    vendeur = UserSerializer(read_only=True)
    items = DevisItemSerializer(many=True, read_only=True)
    est_valide = serializers.BooleanField(read_only=True)
    jours_restants = serializers.IntegerField(read_only=True)

    class Meta:
        model = Devis
        fields = '__all__'


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

        total = sous_total

        devis = Devis.objects.create(
            **validated_data,
            client_id=client_id,
            vendeur=user,
            sous_total=sous_total,
            total=total,
        )

        for item_data in items_data:
            DevisItem.objects.create(devis=devis, **item_data)

        return devis


# ============================================================
# PAIEMENT
# ============================================================
class PaiementSerializer(serializers.ModelSerializer):
    """Lecture d'un paiement + infos facture + destination."""
    encaisse_par_nom = serializers.CharField(
        source='encaisse_par.email', read_only=True)

    facture_ref = serializers.CharField(
        source='facture.reference', read_only=True, default='-')
    facture_date = serializers.DateField(
        source='facture.date_facture', read_only=True, default=None)
    facture_total = serializers.DecimalField(
        source='facture.total_ttc',
        max_digits=12, decimal_places=2, read_only=True, default=0)
    facture_restant = serializers.DecimalField(
        source='facture.montant_restant',
        max_digits=12, decimal_places=2, read_only=True, default=0)

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

    caisse_destination_nom = serializers.CharField(
        source='caisse_destination.nom', read_only=True, default=None)
    compte_destination_nom = serializers.CharField(
        source='compte_destination.nom', read_only=True, default=None)
    mouvement_reference = serializers.CharField(
        source='mouvement_tresorerie.reference', read_only=True, default=None)

    class Meta:
        model = Paiement
        fields = '__all__'
        read_only_fields = (
            'id', 'created_at', 'updated_at',
            'encaisse_par', 'mouvement_tresorerie',
        )


class PaiementCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paiement
        fields = (
            'facture', 'montant', 'methode', 'reference_externe', 'notes',
            'caisse_destination', 'compte_destination',
        )

    def validate(self, data):
        facture = data.get('facture')
        if not facture:
            raise serializers.ValidationError(
                {"facture": "La facture est obligatoire."})
        if data['montant'] > facture.montant_restant:
            raise serializers.ValidationError({
                "montant": (
                    f"Le montant ({data['montant']}) dépasse le restant dû "
                    f"({facture.montant_restant} FCFA)."
                )
            })

        caisse = data.get('caisse_destination')
        compte = data.get('compte_destination')

        if caisse and compte:
            raise serializers.ValidationError(
                "Choisissez une seule destination : caisse ou compte bancaire.")

        if caisse and caisse.agence != facture.agence:
            raise serializers.ValidationError({
                "caisse_destination":
                "La caisse doit appartenir à la même agence que la facture."})

        if compte and compte.agence != facture.agence:
            raise serializers.ValidationError({
                "compte_destination":
                "Le compte bancaire doit appartenir à la même agence que la facture."})

        return data

    def create(self, validated_data):
        validated_data['encaisse_par'] = self.context['request'].user

        facture = validated_data.get('facture')
        if facture:
            validated_data['client'] = facture.client
            if facture.vente:
                validated_data['vente'] = facture.vente

        return super().create(validated_data)


# ============================================================
# FACTURE
# ============================================================
class FactureListSerializer(serializers.ModelSerializer):
    client_id = serializers.IntegerField(
        source='client.id', read_only=True, allow_null=True)
    client_nom = serializers.CharField(
        source='client.nom', read_only=True, allow_null=True)
    agence_id = serializers.IntegerField(source='agence.id', read_only=True)
    agence_nom = serializers.CharField(source='agence.nom', read_only=True)
    statut_display = serializers.CharField(
        source='get_status_display', read_only=True)
    type_display = serializers.CharField(
        source='get_type_facture_display', read_only=True)

    class Meta:
        model = Facture
        fields = (
            'id', 'reference', 'type_facture', 'type_display',
            'status', 'statut_display',
            'client_id', 'client_nom',
            'agence_id', 'agence_nom',
            'date_facture', 'date_echeance',
            'total_ttc', 'montant_paye', 'montant_restant', 'currency',
        )


class FactureDetailSerializer(serializers.ModelSerializer):
    client = ClientSerializer(read_only=True)
    agence = AgenceSimpleSerializer(read_only=True)
    cree_par = UserSerializer(read_only=True)
    items = serializers.SerializerMethodField()
    paiements = PaiementSerializer(many=True, read_only=True)

    class Meta:
        model = Facture
        fields = '__all__'

    def get_items(self, obj):
        if obj.vente:
            return VenteItemSerializer(
                obj.vente.items.all(), many=True, context=self.context
            ).data
        return []


class FactureCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Facture
        fields = ('vente', 'type_facture', 'date_echeance',
                  'conditions_paiement', 'notes', 'pied_de_page')
        read_only_fields = (
            'id', 'reference', 'status', 'date_facture', 'cree_par',
            'sous_total', 'total_ttc', 'montant_paye', 'montant_restant',
            'client', 'agence', 'currency',
        )

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
            total_ttc=vente.total,
            montant_restant=vente.total,
            montant_paye=vente.montant_paye,
        )
        return facture


class FacturePaiementSerializer(serializers.Serializer):
    montant = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0.01)
    methode = serializers.ChoiceField(choices=Paiement.METHODES_PAIEMENT)
    reference = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
