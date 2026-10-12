import uuid
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from inventory.models import Product, ProductIMEI

class Customer(models.Model):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, unique=True, db_index=True)
    email = models.EmailField(blank=True, null=True)
    gstin = models.CharField(max_length=30, blank=True, null=True, help_text="Customer GSTIN for B2B billing")
    address = models.TextField(blank=True, null=True)
    loyalty_points = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.phone})"

    @property
    def total_purchases(self):
        return self.sales.filter(status='COMPLETED').count()

    @property
    def total_spent(self):
        return sum((s.total_amount for s in self.sales.filter(status='COMPLETED')), Decimal('0.00'))

class Sale(models.Model):
    PAYMENT_CHOICES = [
        ('CASH', 'Cash'),
        ('CARD', 'Credit / Debit Card'),
        ('UPI', 'UPI / QR Code'),
        ('BANK', 'Bank Transfer'),
        ('SPLIT', 'Split Payment (Cash + UPI/Card)'),
    ]

    STATUS_CHOICES = [
        ('COMPLETED', 'Completed'),
        ('HELD', 'Held / Parked'),
        ('VOIDED', 'Voided / Refunded'),
    ]

    invoice_number = models.CharField(max_length=50, unique=True, db_index=True)
    cashier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')
    customer_name = models.CharField(max_length=150, blank=True, default='Walk-in Customer')
    customer_phone = models.CharField(max_length=30, blank=True, null=True)
    customer_gstin = models.CharField(max_length=30, blank=True, null=True)
    
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='CASH')
    split_cash_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    split_online_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.invoice_number} - ₹{self.total_amount} ({self.created_at:%Y-%m-%d %H:%M})"

    @classmethod
    def generate_invoice_number(cls):
        return f"INV-{uuid.uuid4().hex[:8].upper()}"

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, related_name='sale_items')
    product_name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100)
    imei = models.CharField(max_length=60, blank=True, null=True, help_text="Specific device IMEI sold")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.IntegerField(default=1)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product_name} x {self.quantity} (₹{self.line_total})"
