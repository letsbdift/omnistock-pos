import uuid
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from inventory.models import Product, ProductIMEI

class Customer(models.Model):
    CUSTOMER_TYPE_CHOICES = [
        ('RETAIL', 'Retail Walk-In Customer'),
        ('WHOLESALE', 'Wholesale / B2B Reseller'),
    ]

    customer_type = models.CharField(max_length=20, choices=CUSTOMER_TYPE_CHOICES, default='RETAIL')
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, unique=True, db_index=True)
    email = models.EmailField(blank=True, null=True)
    gstin = models.CharField(max_length=30, blank=True, null=True, help_text="Customer GSTIN for B2B billing")
    address = models.TextField(blank=True, null=True)
    
    # Wholesale / B2B AR Fields
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    credit_terms_days = models.IntegerField(default=30, help_text="Payment terms: 15, 30, 60 days")
    outstanding_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    wholesale_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    loyalty_points = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        b2b_tag = " [B2B Wholesale]" if self.customer_type == 'WHOLESALE' else ""
        return f"{self.name}{b2b_tag} ({self.phone})"

    @property
    def total_purchases(self):
        return self.sales.filter(status='COMPLETED').count()

    @property
    def total_spent(self):
        return sum((s.total_amount for s in self.sales.filter(status='COMPLETED')), Decimal('0.00'))

    @property
    def available_credit(self):
        return max(Decimal('0.00'), self.credit_limit - self.outstanding_balance)

class DiscountOverride(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('countered', 'Counter-Offer Made'),
        ('declined', 'Declined'),
        ('used', 'Redeemed & Used'),
    ]

    request_number = models.CharField(max_length=50, unique=True, db_index=True)
    cashier = models.ForeignKey(User, on_delete=models.CASCADE, related_name='override_requests')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    standard_price = models.DecimalField(max_digits=12, decimal_places=2)
    requested_price = models.DecimalField(max_digits=12, decimal_places=2)
    approved_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)
    operational_notes = models.TextField(blank=True, null=True)
    
    authorization_code = models.CharField(max_length=30, blank=True, null=True, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_overrides')
    decline_reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    @property
    def is_loss_making(self):
        target = self.approved_price if self.approved_price is not None else self.requested_price
        return target < self.cost_price

    @property
    def surrendered_profit(self):
        target = self.approved_price if self.approved_price is not None else self.requested_price
        return max(Decimal('0.00'), self.standard_price - target)

    def __str__(self):
        return f"{self.request_number} - {self.product.name} (Req: ₹{self.requested_price}) [{self.status}]"

class Sale(models.Model):
    PAYMENT_CHOICES = [
        ('CASH', 'Cash'),
        ('CARD', 'Credit / Debit Card'),
        ('UPI', 'UPI / QR Code'),
        ('CREDIT', 'Wholesale Credit (AR)'),
        ('SPLIT', 'Split Payment (Cash + UPI/Card)'),
    ]

    STATUS_CHOICES = [
        ('COMPLETED', 'Completed'),
        ('HELD', 'Held / Parked'),
        ('VOIDED', 'Voided / Refunded'),
    ]

    invoice_number = models.CharField(max_length=50, unique=True, db_index=True)
    cashier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')
    branch_location = models.CharField(max_length=150, default='Mumbai Bandra')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')
    customer_name = models.CharField(max_length=150, blank=True, default='Walk-in Customer')
    customer_phone = models.CharField(max_length=30, blank=True, null=True)
    customer_gstin = models.CharField(max_length=30, blank=True, null=True)
    
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    gross_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    staff_points_earned = models.IntegerField(default=0, help_text="10 pts per ₹100 net profit")
    
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='CASH')
    split_cash_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    split_online_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED')
    notes = models.TextField(blank=True, null=True)
    is_offline_sync = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.invoice_number} - ₹{self.total_amount} ({self.created_at:%Y-%m-%d %H:%M})"

    @classmethod
    def generate_invoice_number(cls):
        return f"REC-{uuid.uuid4().hex[:8].upper()}"

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, related_name='sale_items')
    product_name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100)
    imei = models.CharField(max_length=60, blank=True, null=True)
    hsn_code = models.CharField(max_length=30, default='8517')
    gst_scheme = models.CharField(max_length=30, default='normal')
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.IntegerField(default=1)
    taxable_margin = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product_name} x {self.quantity} (₹{self.line_total})"

class CustomerReturn(models.Model):
    RETURN_STATUS = [
        ('logged', 'Return Logged & Inspected'),
        ('restock_pending', 'Restock Proposal Pending Admin Approval'),
        ('restocked', 'Restock Routing Approved & Completed'),
        ('refund_issued', 'Refund Issued to Customer'),
    ]

    ROUTING_DESTINATION = [
        ('return_to_resale', 'Return to Resale Inventory'),
        ('route_to_repair', 'Route to Technical Repair Desk'),
        ('spare_parts_harvest', 'Teardown for Spare Parts Salvage'),
        ('write_off_unsellable', 'Write-off / Financial Loss Ledger'),
    ]

    return_number = models.CharField(max_length=50, unique=True, db_index=True)
    original_sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='returns')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    imei = models.CharField(max_length=60, blank=True, null=True)
    condition_assessment = models.CharField(max_length=50, choices=[
        ('Ready-to-resell', 'Ready to Resell'),
        ('Needs-repair', 'Needs Repair'),
        ('Parts-missing-or-damaged', 'Parts Missing / Damaged'),
        ('Damaged', 'Damaged / Beyond Repair')
    ], default='Ready-to-resell')
    customer_reason = models.TextField()
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)
    refund_method = models.CharField(max_length=30, default='Cash', choices=[
        ('Cash', 'Cash'),
        ('UPI', 'UPI'),
        ('Card', 'Card'),
        ('Store Credit', 'Store Credit'),
        ('Replacement', 'Replacement Unit')
    ])
    
    # 2-Phase Restock Authorization
    staff_recommended_routing = models.CharField(max_length=50, choices=ROUTING_DESTINATION, default='return_to_resale')
    admin_approved_routing = models.CharField(max_length=50, choices=ROUTING_DESTINATION, blank=True, null=True)
    status = models.CharField(max_length=30, choices=RETURN_STATUS, default='restock_pending')
    processed_by_staff = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='processed_returns')
    approved_by_admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_returns')
    admin_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.return_number}: {self.product.name} (Refund: ₹{self.refund_amount}) [{self.status}]"

class CashRegister(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cash_register')
    branch = models.CharField(max_length=150, default='Mumbai Bandra')
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    cash_sales = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    incurred_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    confirmed_deposits = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    last_reset_at = models.DateTimeField(auto_now_add=True)

    @property
    def cash_in_hand(self):
        return (self.opening_balance + self.cash_sales) - (self.incurred_expenses + self.confirmed_deposits)

    def __str__(self):
        return f"Register: {self.user.username} | Cash in Hand: ₹{self.cash_in_hand}"

class PettyCashExpense(models.Model):
    register = models.ForeignKey(CashRegister, on_delete=models.CASCADE, related_name='expenses')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    category = models.CharField(max_length=100, choices=[
        ('Tea & Refreshments', 'Tea & Refreshments'),
        ('Packaging & Supplies', 'Packaging & Supplies'),
        ('Store Maintenance', 'Store Maintenance'),
        ('Courier & Logistics', 'Courier & Logistics'),
        ('Other Petty Cash', 'Other Petty Cash'),
    ])
    receipt_note = models.TextField()
    incurred_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Expense: ₹{self.amount} - {self.category} ({self.incurred_by})"

class CashDepositRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Physical Verification & Handover'),
        ('confirmed', 'Confirmed & Register Reset'),
        ('vault_deposited', 'Deposited to Corporate Vault'),
    ]

    deposit_number = models.CharField(max_length=50, unique=True, db_index=True)
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='deposit_requests')
    branch = models.CharField(max_length=150, default='Mumbai Bandra')
    claimed_amount = models.DecimalField(max_digits=12, decimal_places=2)
    counted_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    discrepancy_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discrepancy_notes = models.TextField(blank=True, null=True)
    
    cash_handler = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='confirmed_cash_deposits')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.deposit_number}: Claimed ₹{self.claimed_amount} by {self.seller.username} [{self.status}]"
