from django.shortcuts import render
from rest_framework import viewsets, permissions, status, filters
from .serializers import *
from .models import *
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from django.db.models import Q, F, Sum, Count
from django.utils import timezone
import csv
import pandas as pd
from django.http import HttpResponse


class CategoryViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les catégories de produits
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Category.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'parent']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return CategoryDetailSerializer
        return CategorySerializer

    @action(detail=False, methods=['get'])
    def tree(self, request):
        """Retourne l'arborescence complète des catégories"""
        categories = Category.objects.filter(parent__isnull=True)
        serializer = self.get_serializer(categories, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        """Retourne tous les produits d'une catégorie"""
        category = self.get_object()
        products = category.products.filter(is_active=True)
        page = self.paginate_queryset(products)
        if page is not None:
            serializer = ProductListSerializer(
                page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(
            products, many=True, context={'request': request})
        return Response(serializer.data)


class BrandViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les marques
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'description']

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        """Retourne tous les produits d'une marque"""
        brand = self.get_object()
        products = brand.products.filter(is_active=True)
        page = self.paginate_queryset(products)
        if page is not None:
            serializer = ProductListSerializer(
                page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(
            products, many=True, context={'request': request})
        return Response(serializer.data)


class UnitViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les unités de mesure
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer

# products/views.py


class ProductViewset(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'brand', 'is_active', 'product_type']
    search_fields = ['reference', 'barcode', 'name', 'description']
    ordering_fields = ['created_at', 'name', 'sale_price', 'stock_quantity']

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        elif self.action == 'retrieve':
            return ProductDetailSerializer
        return ProductCreateUpdateSerializer

    def get_serializer_context(self):
        """Ajouter le contexte de la requête aux sérialiseurs"""
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        """Retourne les produits avec stock faible"""
        products = self.get_queryset().filter(
            stock_quantity__lte=models.F('minimum_stock'))
        serializer = ProductStockAlertSerializer(products, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def out_of_stock(self, request):
        """Retourne les produits en rupture de stock"""
        products = self.get_queryset().filter(stock_quantity=0)
        serializer = ProductListSerializer(
            products, many=True, context={'request': request})
        return Response(serializer.data)


class ProductVariantViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les variantes de produits
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = ProductVariant.objects.all()
    serializer_class = ProductVariantSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'is_active']
    search_fields = ['sku']
