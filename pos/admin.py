from django.contrib import admin
from .models import Sale, SaleItem

class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    readonly_fields = ('product_name', 'sku', 'unit_price', 'quantity', 'line_total')

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'cashier', 'customer_name', 'total_amount', 'payment_method', 'status', 'created_at')
    list_filter = ('status', 'payment_method', 'created_at')
    search_fields = ('invoice_number', 'customer_name', 'customer_phone')
    inlines = [SaleItemInline]
    readonly_fields = ('created_at',)
