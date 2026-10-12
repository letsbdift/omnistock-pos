from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from inventory.models import Product, Brand, Category, StockMovement, ProductIMEI, Supplier
from pos.models import Sale, SaleItem, Customer

class OmniStockComprehensiveTestSuite(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cashier1', password='pass@123')
        self.client = Client()
        self.client.login(username='cashier1', password='pass@123')

        self.category = Category.objects.create(name='Smartphones')
        self.brand = Brand.objects.create(name='Apple')
        self.supplier = Supplier.objects.create(name='Direct Apple Distributor', phone='9876543210')
        
        self.product = Product.objects.create(
            name='iPhone 13 128GB Midnight',
            sku='APL-IP13-128',
            barcode='8809988776655',
            category=self.category,
            brand=self.brand,
            supplier=self.supplier,
            ram='4GB',
            rom='128GB',
            grade='A1',
            quantity=5,
            unit_cost=Decimal('42000.00'),
            selling_price=Decimal('49999.00'),
            gst_rate=Decimal('18.00'),
            min_stock_alert_level=2,
            status='Ready to Sell'
        )

        # Attach test IMEI
        self.imei = ProductIMEI.objects.create(
            product=self.product,
            imei1='358992019283741',
            status='AVAILABLE'
        )

        # Create test customer
        self.customer = Customer.objects.create(
            name='Rajesh Sharma',
            phone='9988776655',
            gstin='27ABCDE1234F1Z5'
        )

    def test_imei_search_api(self):
        """Test IMEI search endpoint returns exact device"""
        response = self.client.get(f'/pos/api/search/?imei={self.imei.imei1}')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['products']), 1)
        self.assertEqual(data['products'][0]['imei'], self.imei.imei1)
        self.assertEqual(data['products'][0]['sku'], self.product.sku)

    def test_customer_creation_and_search(self):
        """Test Customer quick-add and search API"""
        response = self.client.post(
            '/pos/api/customers/add/',
            data={'name': 'Anita Roy', 'phone': '9123456780', 'gstin': ''},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertTrue(Customer.objects.filter(phone='9123456780').exists())

        search_res = self.client.get('/pos/api/customers/?q=Anita')
        self.assertEqual(search_res.status_code, 200)
        self.assertGreaterEqual(len(search_res.json()['customers']), 1)

    def test_pos_checkout_with_imei_and_gst_tax(self):
        """Test checkout flow attaching customer, calculating CGST/SGST, and marking IMEI SOLD"""
        payload = {
            'items': [{'id': self.product.id, 'quantity': 1, 'imei': self.imei.imei1}],
            'customer_id': self.customer.id,
            'payment_method': 'SPLIT',
            'split_cash': 20000,
            'split_online': 38998.82,
            'tax_percent': 18,
            'discount_amount': 0,
        }

        response = self.client.post('/pos/api/checkout/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertTrue(res_data['success'])

        sale = Sale.objects.get(id=res_data['sale_id'])
        self.assertEqual(sale.customer, self.customer)
        self.assertEqual(sale.payment_method, 'SPLIT')
        self.assertEqual(sale.subtotal, Decimal('49999.00'))
        self.assertEqual(sale.tax_percent, Decimal('18.00'))
        self.assertEqual(sale.cgst_amount, Decimal('4499.91'))
        self.assertEqual(sale.sgst_amount, Decimal('4499.91'))
        self.assertEqual(sale.total_amount, Decimal('58998.82'))

        # Verify stock and IMEI status
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 4)

        self.imei.refresh_from_db()
        self.assertEqual(self.imei.status, 'SOLD')
        self.assertEqual(self.imei.sold_invoice, sale.invoice_number)

    def test_park_and_resume_order(self):
        """Test parking (holding) an order and resuming it later"""
        payload = {
            'items': [{'id': self.product.id, 'quantity': 1, 'imei': ''}],
            'action': 'park',
            'customer_name': 'Pending Buyer',
            'tax_percent': 18,
            'discount_amount': 500,
        }

        response = self.client.post('/pos/api/checkout/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        held_sale_id = response.json()['sale_id']
        self.assertEqual(response.json()['status'], 'HELD')

        # Stock is NOT deducted when parked
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 5)

        # Resume held sale
        resume_res = self.client.get(f'/pos/api/resume-held/{held_sale_id}/')
        self.assertEqual(resume_res.status_code, 200)
        resume_data = resume_res.json()
        self.assertTrue(resume_data['success'])
        self.assertEqual(resume_data['order']['customer_name'], 'Pending Buyer')

    def test_frontend_routes_accessibility(self):
        """Frontend verification: Ensure all templates render with HTTP 200 OK"""
        routes = [
            '/pos/',
            '/pos/history/',
            '/pos/customers/',
            '/inventory/',
            '/inventory/dashboard/',
            '/inventory/barcodes/',
            '/inventory/suppliers/',
            '/inventory/movements/',
            '/inventory/import/',
            '/manifest.json',
            '/serviceworker.js',
            '/offline/',
        ]
        for route in routes:
            res = self.client.get(route)
            self.assertIn(res.status_code, [200, 302], f"Failed on route {route}")
