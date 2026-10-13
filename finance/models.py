from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
from pos.models import Customer, Sale
from inventory.models import Supplier, PurchaseOrder

class CustomerInvoiceAR(models.Model):
    STATUS_CHOICES = [
        ('unpaid', 'Unpaid / Overdue'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid in Full'),
    ]

    invoice_number = models.CharField(max_length=50, unique=True, db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='ar_invoices')
    sale = models.ForeignKey(Sale, on_delete=models.SET_NULL, null=True, blank=True)
    invoice_date = models.DateField(default=timezone.now)
    due_date = models.DateField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='unpaid')
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def aging_bucket(self):
        today = timezone.now().date()
        days_overdue = (today - self.due_date).days
        if days_overdue <= 0:
            return 'Current (0-30 days)'
        elif days_overdue <= 60:
            return '31-60 days'
        elif days_overdue <= 90:
            return '61-90 days'
        else:
            return '90+ days overdue'

    def record_payment(self, amount, payment_reference=None):
        self.paid_amount += Decimal(str(amount))
        self.balance_due = max(Decimal('0.00'), self.total_amount - self.paid_amount)
        if self.balance_due == 0:
            self.status = 'paid'
        else:
            self.status = 'partially_paid'
        self.save()
        # Update customer balance
        self.customer.outstanding_balance = max(Decimal('0.00'), self.customer.outstanding_balance - Decimal(str(amount)))
        self.customer.save()

    def __str__(self):
        return f"{self.invoice_number}: {self.customer.name} (Due: ₹{self.balance_due}) [{self.status}]"

class VendorBillAP(models.Model):
    STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid'),
    ]

    bill_number = models.CharField(max_length=50, unique=True, db_index=True)
    vendor = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='ap_bills')
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True)
    bill_date = models.DateField(default=timezone.now)
    due_date = models.DateField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2)
    is_itc_eligible = models.BooleanField(default=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='unpaid')
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def aging_bucket(self):
        today = timezone.now().date()
        days_overdue = (today - self.due_date).days
        if days_overdue <= 0:
            return 'Current (0-30 days)'
        elif days_overdue <= 60:
            return '31-60 days'
        elif days_overdue <= 90:
            return '61-90 days'
        else:
            return '90+ days overdue'

    def __str__(self):
        return f"{self.bill_number}: {self.vendor.name} (Due: ₹{self.balance_due}) [{self.status}]"

class GSTCompliancePeriod(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open / Active Accrual'),
        ('reviewed', 'Reconciled & Ready to File'),
        ('locked_and_filed', 'Locked with Portal ARN'),
    ]

    period_name = models.CharField(max_length=50, unique=True, help_text="e.g. September 2026")
    start_date = models.DateField()
    end_date = models.DateField()
    
    # GSTR-1 Aggregates
    b2b_taxable_value = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    b2b_tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    b2c_taxable_value = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    b2c_tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    credit_notes_adjustment = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    
    # GSTR-3B Aggregates
    gross_tax_liability = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    eligible_itc_claimed = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    ineligible_itc_excluded = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    net_cash_tax_payable = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    
    # Filing lock
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='open')
    arn_number = models.CharField(max_length=50, blank=True, null=True, help_text="Government ARN e.g. AA2709260018921")
    locked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    locked_at = models.DateTimeField(blank=True, null=True)
    amendment_notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"GST Period: {self.period_name} [{self.status}] (ARN: {self.arn_number or 'Not Filed'})"

class OperatingExpense(models.Model):
    EXPENSE_CATEGORY = [
        ('Rent', 'Store & Warehouse Rent'),
        ('Salaries', 'Staff Salaries & Wages'),
        ('Logistics', 'Logistics & Courier Delivery'),
        ('Utilities', 'Utilities & Electricity'),
        ('Marketing', 'Marketing & Digital Ads'),
        ('General Overheads', 'General Overheads & Maintenance'),
    ]

    expense_date = models.DateField(default=timezone.now)
    category = models.CharField(max_length=50, choices=EXPENSE_CATEGORY)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField()
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.category}: ₹{self.amount} ({self.expense_date})"

class ImmutableAuditLog(models.Model):
    SEVERITY_CHOICES = [
        ('info', 'Information'),
        ('warning', 'Operational Warning'),
        ('critical', 'Critical Security / Financial Event'),
    ]

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    user_identifier = models.CharField(max_length=100, default='SYSTEM')
    action = models.CharField(max_length=200)
    module = models.CharField(max_length=100)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='info')
    before_state = models.TextField(blank=True, null=True)
    after_state = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']

    def save(self, *args, **kwargs):
        # Audit Trail Immutability Invariant: Strictly append-only
        if self.pk:
            raise ValueError("Audit Trail Immutability Violation: Existing audit records cannot be mutated or updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit Trail Immutability Violation: Audit records cannot be deleted.")

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M:%S}] [{self.severity.upper()}] {self.module} - {self.action} by {self.user_identifier}"

class RewardProduct(models.Model):
    name = models.CharField(max_length=200)
    points_required = models.IntegerField(default=100)
    description = models.TextField(blank=True, null=True)
    image_url = models.URLField(max_length=500, blank=True, null=True)
    available_stock = models.IntegerField(default=10)

    def __str__(self):
        return f"{self.name} ({self.points_required} Points)"

class StaffRewardRedemption(models.Model):
    redemption_code = models.CharField(max_length=50, unique=True, db_index=True)
    staff = models.ForeignKey(User, on_delete=models.CASCADE, related_name='redemptions')
    reward = models.ForeignKey(RewardProduct, on_delete=models.CASCADE)
    points_spent = models.IntegerField()
    status = models.CharField(max_length=30, default='approved')
    claimed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.redemption_code}: {self.staff.username} claimed {self.reward.name}"

class SystemIDSequence(models.Model):
    entity_key = models.CharField(max_length=50, unique=True, help_text="e.g. SKU, REC, PO, REP, SHIFT, DEP, RST, RTN, REQ, ARN")
    prefix = models.CharField(max_length=20, default='REC-')
    include_date = models.BooleanField(default=True)
    next_number = models.IntegerField(default=1)

    def generate_next_id(self):
        today_str = timezone.now().strftime('%Y%m%d') if self.include_date else ''
        id_str = f"{self.prefix}{today_str}-{self.next_number:04d}" if today_str else f"{self.prefix}{self.next_number:04d}"
        self.next_number += 1
        self.save()
        return id_str

    def __str__(self):
        return f"{self.entity_key}: Prefix={self.prefix}, Next={self.next_number}"
