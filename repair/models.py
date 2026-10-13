from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from inventory.models import Product, ProductIMEI
from pos.models import Customer

class RepairTicket(models.Model):
    WARRANTY_TYPE_CHOICES = [
        ('brand_authorized', 'Brand Authorized (In-Warranty, Free to Customer)'),
        ('out_of_warranty', 'Out-of-Warranty (Paid Service & Parts)'),
        ('store_warranty', 'OmniStock Store Warranty (Free internal guarantee)'),
    ]

    STAGE_CHOICES = [
        ('received', 'Received & Logged'),
        ('diagnosed', 'Diagnosed by Technician'),
        ('repairing', 'Repair in Progress'),
        ('ready', 'Repair Completed & Ready for Pickup'),
        ('delivered', 'Delivered & Billed'),
        ('unrepairable', 'Unrepairable / Returned to Customer'),
    ]

    ticket_number = models.CharField(max_length=50, unique=True, db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='repair_tickets')
    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=30)
    
    device_type = models.CharField(max_length=100, default='Smartphone')
    brand_name = models.CharField(max_length=100)
    model_name = models.CharField(max_length=150)
    imei_or_serial = models.CharField(max_length=100, db_index=True)
    lock_passcode = models.CharField(max_length=50, blank=True, null=True)
    
    reported_issue = models.TextField()
    technician_diagnostic_notes = models.TextField(blank=True, null=True)
    warranty_type = models.CharField(max_length=40, choices=WARRANTY_TYPE_CHOICES, default='out_of_warranty')
    intake_branch = models.CharField(max_length=150, default='Mumbai Bandra')
    
    labor_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    parts_total = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_billed = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    brand_reimbursement_claim = models.CharField(max_length=100, blank=True, null=True, help_text="Claim ref for brand warranty")
    stage = models.CharField(max_length=30, choices=STAGE_CHOICES, default='received')
    assigned_technician = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_repairs')
    intake_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='intake_repairs')
    
    created_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)

    def calculate_total(self):
        parts_sum = sum((p.line_total for p in self.consumed_parts.all()), 0)
        self.parts_total = parts_sum
        if self.warranty_type in ['brand_authorized', 'store_warranty']:
            self.total_billed = 0.00
        else:
            self.total_billed = self.labor_charge + self.parts_total
        self.save()

    def __str__(self):
        return f"{self.ticket_number}: {self.brand_name} {self.model_name} ({self.stage})"

class RepairConsumedPart(models.Model):
    ticket = models.ForeignKey(RepairTicket, on_delete=models.CASCADE, related_name='consumed_parts')
    part_product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    consumed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.ticket.ticket_number} - {self.part_product.name} x {self.quantity}"
