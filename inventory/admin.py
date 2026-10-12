from django.contrib import admin
from .models import Category, Brand, Warehouse, Product, StockMovement

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'location')

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'barcode', 'category', 'brand', 'quantity', 'selling_price', 'status')
    list_filter = ('status', 'condition', 'category', 'brand')
    search_fields = ('name', 'sku', 'barcode', 'lot_id')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('product', 'movement_type', 'quantity', 'previous_quantity', 'new_quantity', 'reference', 'timestamp', 'user')
    list_filter = ('movement_type', 'timestamp')
    search_fields = ('product__name', 'product__sku', 'reference')
    readonly_fields = ('timestamp',)
