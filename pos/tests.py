from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from accounts.models import UserProfile
from inventory.models import Product, Brand, Category, StockMovement, ProductIMEI, Supplier, StockShift, LiquidationLot
from pos.models import Sale, SaleItem, Customer, DiscountOverride, CustomerReturn, CashRegister, CashDepositRequest
from repair.models import RepairTicket, RepairConsumedPart
from finance.models import CustomerInvoiceAR, VendorBillAP, GSTCompliancePeriod, ImmutableAuditLog, RewardProduct

class OmniStockEnterpriseTestSuite(TestCase):
    def setUp(self):
        # 1. Setup Super Admin
        self.super_admin_user = User.objects.create_user(username='user_admin_arif', password='pass@123', is_staff=True, is_superuser=True)
        # Profile is created via signal
        self.super_admin_profile = self.super_admin_user.profile
        self.super_admin_profile.role = 'super_admin'
        self.super_admin_profile.employee_id = 'EMP-ADM-001'
        self.super_admin_profile.save()

        # 2. Setup Cash Handler
        self.cash_handler_user = User.objects.create_user(username='cash_custodian', password='pass@123')
        self.cash_handler_profile = self.cash_handler_user.profile
        self.cash_handler_profile.role = 'admin'
        self.cash_handler_profile.is_cash_handler = True
        self.cash_handler_profile.save()

        # 3. Setup Sales Staff
        self.cashier_user = User.objects.create_user(username='cashier_mumbai', password='pass@123')
        self.cashier_profile = self.cashier_user.profile
        self.cashier_profile.role = 'user'
        self.cashier_profile.assigned_branch = 'Mumbai Bandra'
        self.cashier_profile.save()

        self.client = Client()
        self.client.login(username='cashier_mumbai', password='pass@123')

        # Core inventory setup
        self.category = Category.objects.create(name='Smartphones')
        self.brand = Brand.objects.create(name='Apple')
        self.supplier = Supplier.objects.create(name='Apple Distributor', gstin='27ABCDE1234F1Z5', supplier_type='Brand Partner')

        # Normal GST product
        self.product_normal = Product.objects.create(
            name='iPhone 13 128GB',
            sku='APL-IP13',
            category=self.category,
            brand=self.brand,
            supplier=self.supplier,
            quantity=10,
            unit_cost=Decimal('40000.00'),
            selling_price=Decimal('50000.00'),
            wholesale_price=Decimal('46000.00'),
            gst_scheme='normal',
            gst_rate=Decimal('18.00'),
            status='Ready to Sell'
        )

        # Margin Scheme product (Rule 32(5) Valuation: Second-hand refurbished)
        self.product_margin = Product.objects.create(
            name='Refurb iPhone 12 64GB',
            sku='REF-IP12',
            category=self.category,
            brand=self.brand,
            supplier=self.supplier,
            quantity=5,
            unit_cost=Decimal('25000.00'),
            selling_price=Decimal('30000.00'),
            gst_scheme='margin_scheme',
            gst_rate=Decimal('18.00'),
            status='Ready to Sell'
        )

        self.imei = ProductIMEI.objects.create(
            product=self.product_normal,
            imei1='358992019283741',
            status='AVAILABLE'
        )

        # Customer profiles
        self.retail_customer = Customer.objects.create(
            name='Ramesh Kumar',
            phone='9876543210',
            customer_type='RETAIL'
        )
        self.wholesale_customer = Customer.objects.create(
            name='Apex Mobile Wholesale',
            phone='9811223344',
            gstin='27ABCDE9999Z1Z5',
            customer_type='WHOLESALE',
            credit_limit=Decimal('100000.00'),
            outstanding_balance=Decimal('0.00'),
            credit_terms_days=30
        )

    def test_single_super_admin_invariant(self):
        """Invariant 1: Exactly ONE user can have role 'super_admin'"""
        another_user = User.objects.create_user(username='hacker_admin', password='pass@123')
        profile = another_user.profile
        profile.role = 'super_admin'
        with self.assertRaises(ValidationError):
            profile.clean()

    def test_single_cash_handler_invariant(self):
        """Invariant 2: Exactly ONE user can have 'is_cash_handler=True'"""
        another_user = User.objects.create_user(username='cash_handler_2', password='pass@123')
        profile = another_user.profile
        profile.is_cash_handler = True
        with self.assertRaises(ValidationError):
            profile.clean()

    def test_cost_price_concealment_invariant(self):
        """Invariant 3: Sales staff cannot view cost price in API responses"""
        # Logged in as cashier (role 'user')
        res = self.client.get(f'/pos/api/search/?q={self.product_normal.name}')
        self.assertEqual(res.status_code, 200)
        item = res.json()['products'][0]
        self.assertNotIn('cost_price', item)

        # Logged in as Admin / Cash Handler
        self.client.login(username='user_admin_arif', password='pass@123')
        res_admin = self.client.get(f'/pos/api/search/?q={self.product_normal.name}')
        self.assertEqual(res_admin.status_code, 200)
        item_admin = res_admin.json()['products'][0]
        self.assertIn('cost_price', item_admin)
        self.assertEqual(item_admin['cost_price'], float(self.product_normal.unit_cost))

    def test_dual_gst_margin_scheme_rule_32_5(self):
        """Feature 1 & 2: Rule 32(5) Valuation: Tax calculated solely on positive margin"""
        self.client.login(username='cashier_mumbai', password='pass@123')
        # Selling price: 30000, Cost: 25000 -> Margin = 5000. Taxable = 5000 / 1.18 = 4237.29, Tax = 762.71
        payload = {
            'items': [{'id': self.product_margin.id, 'quantity': 1, 'imei': ''}],
            'customer_id': self.retail_customer.id,
            'payment_method': 'CASH',
        }
        res = self.client.post('/pos/api/checkout/', data=payload, content_type='application/json')
        self.assertEqual(res.status_code, 200)
        sale = Sale.objects.get(id=res.json()['sale_id'])
        self.assertEqual(sale.subtotal, Decimal('30000.00'))
        self.assertEqual(sale.tax_amount, Decimal('762.71'))
        self.assertEqual(sale.total_amount, Decimal('30762.71'))

    def test_discount_override_pipeline(self):
        """Feature 3: Cashier requests override, Admin reviews and issues one-time OVR-XXXXXX code"""
        self.client.login(username='cashier_mumbai', password='pass@123')
        req_res = self.client.post('/pos/api/override/request/', data={
            'product_id': self.product_normal.id,
            'requested_price': 45000,
            'reason': 'Customer comparing with online price'
        }, content_type='application/json')
        self.assertEqual(req_res.status_code, 200)
        self.assertTrue(req_res.json()['success'])

        override = DiscountOverride.objects.get(request_number=req_res.json()['request_number'])
        self.assertEqual(override.status, 'pending')
        self.assertEqual(override.surrendered_profit, Decimal('5000.00'))

        # Admin approves override
        self.client.login(username='user_admin_arif', password='pass@123')
        action_res = self.client.post(f'/pos/overrides/{override.id}/action/', data={'action': 'approve'})
        self.assertEqual(action_res.status_code, 302)
        override.refresh_from_db()
        self.assertEqual(override.status, 'approved')
        self.assertTrue(override.authorization_code.startswith('OVR-'))

    def test_repair_desk_and_parts_consumption(self):
        """Feature 4: Repair device ticketing and inventory parts deduction"""
        spare_screen = Product.objects.create(
            name='iPhone 13 Replacement OLED Screen',
            sku='PART-IP13-SCR',
            quantity=4,
            unit_cost=Decimal('5000.00'),
            selling_price=Decimal('8500.00'),
            is_spare_part=True,
            status='Ready to Sell'
        )

        ticket = RepairTicket.objects.create(
            ticket_number='REP-20261013-0001',
            customer_name='Vikas Khanna',
            customer_phone='9898989898',
            device_type='Smartphone',
            brand_name='Apple',
            model_name='iPhone 13',
            imei_or_serial='358992019999999',
            reported_issue='Cracked front screen',
            warranty_type='out_of_warranty',
            labor_charge=Decimal('1500.00')
        )

        self.client.login(username='user_admin_arif', password='pass@123')
        res = self.client.post(f'/repair/{ticket.id}/part/add/', data={
            'part_product_id': spare_screen.id,
            'quantity': 1
        })
        self.assertEqual(res.status_code, 302)

        ticket.refresh_from_db()
        spare_screen.refresh_from_db()
        # Part deducted from stock
        self.assertEqual(spare_screen.quantity, 3)
        # Total billed: Labor (1500) + Part (8500) = 10000
        self.assertEqual(ticket.total_billed, Decimal('10000.00'))

    def test_customer_return_two_phase_restock(self):
        """Feature 5: Customer return logged and admin authorizes restock disposition"""
        # Create a completed sale
        sale = Sale.objects.create(
            invoice_number='REC-TEST-001',
            cashier=self.cashier_user,
            customer=self.retail_customer,
            total_amount=Decimal('50000.00'),
            status='COMPLETED'
        )

        self.client.login(username='cashier_mumbai', password='pass@123')
        res = self.client.post('/pos/returns/log/', data={
            'invoice_number': sale.invoice_number,
            'product_id': self.product_normal.id,
            'refund_amount': 50000,
            'refund_method': 'Cash',
            'staff_recommended_routing': 'route_to_repair',
            'customer_reason': 'Mic not working'
        })
        self.assertEqual(res.status_code, 302)

        return_obj = CustomerReturn.objects.first()
        self.assertEqual(return_obj.status, 'restock_pending')

        # Admin approves restock routing
        self.client.login(username='user_admin_arif', password='pass@123')
        approve_res = self.client.post(f'/pos/returns/{return_obj.id}/approve/', data={
            'admin_approved_routing': 'route_to_repair'
        })
        self.assertEqual(approve_res.status_code, 302)
        return_obj.refresh_from_db()
        self.assertEqual(return_obj.status, 'restocked')
        self.assertEqual(return_obj.admin_approved_routing, 'route_to_repair')

    def test_multi_location_stock_shift(self):
        """Feature 7: Dispatch stock shift (in-transit) and receiving verification"""
        self.client.login(username='user_admin_arif', password='pass@123')
        dispatch_res = self.client.post('/inventory/shifts/dispatch/', data={
            'product_id': self.product_normal.id,
            'from_location': 'Mumbai Bandra',
            'to_location': 'Delhi Connaught',
            'quantity': 2,
            'carrier_name': 'BlueDart',
            'tracking_number': 'BD99887766'
        })
        self.assertEqual(dispatch_res.status_code, 302)

        shift = StockShift.objects.first()
        self.assertEqual(shift.status, 'in_transit')
        self.assertEqual(shift.dispatched_quantity, 2)
        self.product_normal.refresh_from_db()
        self.assertEqual(self.product_normal.quantity, 8) # 10 - 2

        # Receiving branch receives shipment
        receive_res = self.client.post(f'/inventory/shifts/{shift.id}/receive/', data={
            'received_quantity': 2,
            'discrepancy_notes': ''
        })
        self.assertEqual(receive_res.status_code, 302)
        shift.refresh_from_db()
        self.assertEqual(shift.status, 'received')
        self.product_normal.refresh_from_db()
        self.assertEqual(self.product_normal.quantity, 10) # 8 + 2

    def test_cash_register_and_custody_handover(self):
        """Feature 8: Seller registers cash, requests handover, Designated Cash Handler confirms"""
        register, _ = CashRegister.objects.get_or_create(user=self.cashier_user, defaults={'branch': 'Mumbai Bandra'})
        register.cash_sales = Decimal('25000.00')
        register.save()

        # Cashier requests deposit
        self.client.login(username='cashier_mumbai', password='pass@123')
        dep_res = self.client.post('/pos/register/deposit/request/', data={'claimed_amount': 25000})
        self.assertEqual(dep_res.status_code, 302)

        deposit = CashDepositRequest.objects.first()
        self.assertEqual(deposit.status, 'pending')

        # Designated Cash Handler physically counts and confirms
        self.client.login(username='cash_custodian', password='pass@123')
        confirm_res = self.client.post(f'/pos/register/deposit/{deposit.id}/confirm/', data={
            'counted_amount': 25000,
            'discrepancy_notes': 'Verified exact note count'
        })
        self.assertEqual(confirm_res.status_code, 302)

        deposit.refresh_from_db()
        self.assertEqual(deposit.status, 'confirmed')
        register.refresh_from_db()
        self.assertEqual(register.cash_in_hand, Decimal('0.00')) # 25000 - 25000

    def test_wholesale_credit_sale_and_ar_invoice(self):
        """Feature 9: B2B wholesale credit sale creates AR invoice and updates outstanding balance"""
        self.client.login(username='cashier_mumbai', password='pass@123')
        payload = {
            'items': [{'id': self.product_normal.id, 'quantity': 1, 'imei': ''}],
            'customer_id': self.wholesale_customer.id,
            'payment_method': 'CREDIT',
        }
        res = self.client.post('/pos/api/checkout/', data=payload, content_type='application/json')
        self.assertEqual(res.status_code, 200)

        self.wholesale_customer.refresh_from_db()
        self.assertGreater(self.wholesale_customer.outstanding_balance, Decimal('0.00'))
        self.assertTrue(CustomerInvoiceAR.objects.filter(customer=self.wholesale_customer).exists())

    def test_gst_compliance_period_lock(self):
        """Feature 11: Lock monthly tax period with government ARN"""
        self.client.login(username='user_admin_arif', password='pass@123')
        res = self.client.post('/finance/gst/lock/', data={
            'period_name': 'October 2026',
            'arn_number': 'AA2709260018921',
            'amendment_notes': 'GSTR-1 and GSTR-3B filed successfully'
        })
        self.assertEqual(res.status_code, 302)
        period = GSTCompliancePeriod.objects.get(period_name='October 2026')
        self.assertEqual(period.status, 'locked_and_filed')
        self.assertEqual(period.arn_number, 'AA2709260018921')

    def test_immutable_audit_log_invariant(self):
        """Invariant 5: Audit log is strictly append-only; mutations or deletions raise error"""
        log = ImmutableAuditLog.objects.create(
            user=self.super_admin_user,
            user_identifier=self.super_admin_user.username,
            action="System Config Changed",
            module="Core",
            severity="info"
        )
        with self.assertRaises(ValueError):
            log.action = "Mutated Action"
            log.save()

        with self.assertRaises(ValueError):
            log.delete()

    def test_all_enterprise_frontend_routes(self):
        """Frontend route testing: Ensure all enterprise portal routes render with HTTP 200 OK"""
        self.client.login(username='user_admin_arif', password='pass@123')
        routes = [
            '/pos/',
            '/pos/register/',
            '/pos/overrides/',
            '/pos/returns/',
            '/pos/history/',
            '/pos/customers/',
            '/inventory/',
            '/inventory/dashboard/',
            '/inventory/lots/',
            '/inventory/shifts/',
            '/inventory/barcodes/',
            '/repair/',
            '/finance/pl/',
            '/finance/ar/',
            '/finance/ap/',
            '/finance/gst/',
            '/finance/audit/',
            '/finance/rewards/',
            '/finance/backup/',
            '/manifest.json',
            '/serviceworker.js',
            '/offline/',
        ]
        for route in routes:
            res = self.client.get(route)
            self.assertEqual(res.status_code, 200, f"Route {route} failed with status {res.status_code}")
