from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
import datetime

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name

class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Warehouse(models.Model):
    name = models.CharField(max_length=100, unique=True)
    location = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.name

class Supplier(models.Model):
    name = models.CharField(max_length=150, unique=True)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    gst_status = models.CharField(max_length=20, default='registered', choices=[('registered', 'Registered (Regular)'), ('unregistered', 'Unregistered / Composition')])
    gstin = models.CharField(max_length=30, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    supplier_type = models.CharField(max_length=50, default='General Supplier', choices=[('Liquidation Source', 'Liquidation Source'), ('Parts Supplier', 'Parts Supplier'), ('Brand Partner', 'Brand Partner'), ('General Supplier', 'General Supplier')])
    payment_terms_days = models.IntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class LiquidationLot(models.Model):
    lot_id = models.CharField(max_length=100, unique=True, db_index=True)
    source_manifest_id = models.CharField(max_length=100, blank=True, null=True)
    source_vendor = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='liquidation_lots')
    manifest_date = models.DateField(default=timezone.now)
    total_lot_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    unit_count = models.IntegerField(default=0)
    projected_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    realized_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    status = models.CharField(max_length=30, default='intake', choices=[
        ('intake', 'Intake / Manifested'),
        ('grading', 'Under Device Grading'),
        ('processed', 'Graded & Resale Ready'),
        ('closed', 'Completed & Sold Out')
    ])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.lot_id} ({self.unit_count} units - ₹{self.total_lot_cost})"

class Product(models.Model):
    CONDITION_CHOICES = [
        ('Ready-to-sale', 'Ready-to-sale'),
        ('Needs-repair', 'Needs-repair'),
        ('Parts-missing-or-damaged', 'Parts-missing-or-damaged'),
        ('New', 'New'),
        ('Open Box', 'Open Box'),
        ('Used', 'Used'),
        ('Damaged', 'Damaged'),
        ('Defective', 'Defective'),
    ]

    STATUS_CHOICES = [
        ('Ready to Sell', 'Ready to Sell'),
        ('Under Repair', 'Under Repair'),
        ('Parts Harvest', 'Parts Harvest'),
        ('Out of Stock', 'Out of Stock'),
        ('Damaged', 'Damaged'),
        ('Reserved', 'Reserved'),
    ]

    GRADE_CHOICES = [
        ('N/A', 'N/A'),
        ('A1', 'Grade A1 (Flawless)'),
        ('A2', 'Grade A2 (Very Good)'),
        ('A3', 'Grade A3 (Good)'),
        ('B', 'Grade B (Fair)'),
        ('C', 'Grade C (Defective / Parts)'),
    ]

    GST_SCHEME_CHOICES = [
        ('normal', 'Standard GST (with ITC)'),
        ('margin_scheme', 'Rule 32(5) Margin Scheme (Tax on Margin only)'),
    ]

    name = models.CharField(max_length=255)
    product_code = models.CharField(max_length=100, blank=True, null=True)
    sku = models.CharField(max_length=100, unique=True, db_index=True)
    barcode = models.CharField(max_length=100, db_index=True, blank=True, null=True)
    hsn_code = models.CharField(max_length=30, default='8517', help_text="e.g. 8517 phones, 8471 computers, 9987 repair services")
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    liquidation_lot = models.ForeignKey(LiquidationLot, on_delete=models.SET_NULL, null=True, blank=True, related_name='lot_products')
    
    # Specs & condition
    model_name = models.CharField(max_length=150, blank=True, null=True)
    ram = models.CharField(max_length=50, blank=True, null=True)
    rom = models.CharField(max_length=50, blank=True, null=True)
    color = models.CharField(max_length=50, blank=True, null=True)
    grade = models.CharField(max_length=20, choices=GRADE_CHOICES, default='N/A')
    box_condition = models.CharField(max_length=100, blank=True, null=True)
    tracking_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    wsn_no = models.CharField(max_length=100, blank=True, null=True)
    
    is_spare_part = models.BooleanField(default=False)
    condition = models.CharField(max_length=50, choices=CONDITION_CHOICES, default='New')
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Ready to Sell')
    warehouse_location = models.CharField(max_length=150, default='Mumbai Bandra')
    
    received_date = models.DateField(default=timezone.now, blank=True, null=True)
    quantity = models.IntegerField(default=0)
    stock_unit = models.CharField(max_length=20, default='pcs')
    
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    mrp = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, blank=True, null=True)
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, blank=True, null=True)
    
    gst_scheme = models.CharField(max_length=30, choices=GST_SCHEME_CHOICES, default='normal')
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18.00)
    
    min_stock_alert_level = models.IntegerField(default=5)
    image_url = models.URLField(max_length=500, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        spec = f" [{self.ram}/{self.rom}]" if (self.ram or self.rom) else ""
        return f"{self.name}{spec} ({self.sku})"

    @property
    def stock_age_days(self):
        if self.received_date:
            today = timezone.now().date() if hasattr(timezone.now(), 'date') else datetime.date.today()
            return max(0, (today - self.received_date).days)
        return 0

    @property
    def is_low_stock(self):
        return self.quantity <= self.min_stock_alert_level

    @property
    def unit_profit(self):
        return self.selling_price - self.unit_cost

    @property
    def profit_margin(self):
        if self.selling_price > 0:
            return round(((self.selling_price - self.unit_cost) / self.selling_price) * 100, 2)
        return 0.0

    def adjust_stock(self, delta, movement_type='adjustment', user=None, reference=None, notes=None):
        previous_quantity = self.quantity
        new_quantity = previous_quantity + delta
        if new_quantity < 0:
            raise ValueError(f"Insufficient stock for {self.name}. Available: {previous_quantity}, requested deduction: {abs(delta)}")
        
        self.quantity = new_quantity
        if self.quantity == 0:
            self.status = 'Out of Stock'
        elif self.status == 'Out of Stock' and self.quantity > 0:
            self.status = 'Ready to Sell'
        self.save()

        StockMovement.objects.create(
            product=self,
            movement_type=movement_type,
            quantity=delta,
            previous_quantity=previous_quantity,
            new_quantity=new_quantity,
            reference=reference or '',
            user=user,
            notes=notes or ''
        )

class ProductIMEI(models.Model):
    STATUS_CHOICES = [
        ('AVAILABLE', 'Available In Stock'),
        ('SOLD', 'Sold'),
        ('RETURNED', 'Returned / Defective'),
        ('REPAIRING', 'Under Repair'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='imei_numbers')
    imei1 = models.CharField(max_length=60, unique=True, db_index=True)
    imei2 = models.CharField(max_length=60, blank=True, null=True)
    serial_number = models.CharField(max_length=60, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AVAILABLE')
    sold_invoice = models.CharField(max_length=60, blank=True, null=True)
    location = models.CharField(max_length=150, default='Mumbai Bandra')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.imei1} ({self.product.name}) - {self.status}"

class StockMovement(models.Model):
    MOVEMENT_CHOICES = [
        ('intake', 'Stock Intake'),
        ('sale', 'POS Sale'),
        ('return', 'Customer Return'),
        ('adjustment', 'Manual Adjustment'),
        ('damaged', 'Damaged / Write-off'),
        ('restock', 'Purchase Order Restock'),
        ('shift_dispatch', 'Stock Shift Dispatched'),
        ('shift_received', 'Stock Shift Received'),
        ('repair_consumed', 'Repair Part Consumed'),
        ('parts_salvaged', 'Harvested Salvage Part'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='movements')
    movement_type = models.CharField(max_length=30, choices=MOVEMENT_CHOICES)
    quantity = models.IntegerField(help_text="Positive for additions, negative for deductions")
    previous_quantity = models.IntegerField()
    new_quantity = models.IntegerField()
    reference = models.CharField(max_length=100, blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.product.sku} | {self.movement_type} | {self.quantity} | {self.timestamp:%Y-%m-%d %H:%M}"

class StockShift(models.Model):
    SHIFT_STATUS_CHOICES = [
        ('in_transit', 'Dispatched / In-Transit'),
        ('received', 'Received & Stocked'),
        ('discrepancy', 'Received with Discrepancy / Damage'),
        ('cancelled', 'Cancelled'),
    ]

    shift_number = models.CharField(max_length=50, unique=True, db_index=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='shifts')
    imei_record = models.ForeignKey(ProductIMEI, on_delete=models.SET_NULL, null=True, blank=True)
    from_location = models.CharField(max_length=150, default='Mumbai Bandra')
    to_location = models.CharField(max_length=150, default='Delhi Connaught')
    dispatched_quantity = models.IntegerField(default=1)
    received_quantity = models.IntegerField(default=0)
    dispatched_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='dispatched_shifts')
    received_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_shifts')
    carrier_name = models.CharField(max_length=100, blank=True, null=True)
    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=30, choices=SHIFT_STATUS_CHOICES, default='in_transit')
    discrepancy_notes = models.TextField(blank=True, null=True)
    dispatched_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.shift_number}: {self.product.sku} ({self.from_location} -> {self.to_location}) [{self.status}]"

class PurchaseOrder(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('ORDERED', 'Ordered / Pending Delivery'),
        ('RECEIVED', 'Received & Stocked'),
        ('CANCELLED', 'Cancelled'),
    ]

    po_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchase_orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.po_number} - {self.supplier.name if self.supplier else 'N/A'} ({self.status})"

class PurchaseOrderItem(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"
