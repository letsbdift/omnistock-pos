import json
import uuid
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Q
from django.contrib import messages
from django.utils import timezone
from inventory.models import Product, StockMovement, ProductIMEI
from .models import (
    Sale, SaleItem, Customer, DiscountOverride, CustomerReturn,
    CashRegister, PettyCashExpense, CashDepositRequest
)
from finance.models import CustomerInvoiceAR, ImmutableAuditLog

@login_required
def terminal_view(request):
    profile = getattr(request.user, 'profile', None)
    branch = profile.assigned_branch if profile else 'Mumbai Bandra'
    products = Product.objects.filter(quantity__gt=0, status='Ready to Sell').select_related('brand', 'category')
    customers = Customer.objects.all().order_by('name')[:50]
    held_sales = Sale.objects.filter(status='HELD').order_by('-created_at')[:10]
    
    # Active register for current cashier
    register, _ = CashRegister.objects.get_or_create(user=request.user, defaults={'branch': branch})
    
    return render(request, 'pos/terminal.html', {
        'products': products,
        'customers': customers,
        'held_sales': held_sales,
        'cash_in_hand': register.cash_in_hand,
        'user_branch': branch,
        'can_view_cost': profile.can_view_cost_and_profit if profile else False,
    })

@login_required
def product_search_api(request):
    query = request.GET.get('q', '').strip()
    barcode = request.GET.get('barcode', '').strip()
    imei = request.GET.get('imei', '').strip()
    profile = getattr(request.user, 'profile', None)
    can_view_cost = profile.can_view_cost_and_profit if profile else False

    if imei:
        imei_obj = ProductIMEI.objects.filter(imei1__iexact=imei, status='AVAILABLE').select_related('product').first()
        if imei_obj:
            p = imei_obj.product
            res = {
                'id': p.id,
                'name': f"{p.name} (IMEI: {imei_obj.imei1})",
                'sku': p.sku,
                'barcode': p.barcode or '',
                'imei': imei_obj.imei1,
                'price': float(p.selling_price),
                'mrp': float(p.mrp) if p.mrp else float(p.selling_price),
                'wholesale_price': float(p.wholesale_price) if p.wholesale_price else float(p.selling_price),
                'gst_scheme': p.gst_scheme,
                'gst_rate': float(p.gst_rate),
                'stock': p.quantity,
                'category': p.category.name if p.category else '',
                'image_url': p.image_url or '',
            }
            if can_view_cost:
                res['cost_price'] = float(p.unit_cost)
            return JsonResponse({'products': [res]})

    products = Product.objects.filter(status='Ready to Sell')
    if barcode:
        products = products.filter(Q(barcode=barcode) | Q(sku=barcode))
    elif query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(sku__icontains=query) |
            Q(barcode__icontains=query) |
            Q(model_name__icontains=query) |
            Q(ram__icontains=query) |
            Q(rom__icontains=query) |
            Q(imei_numbers__imei1__icontains=query)
        ).distinct()

    results = []
    for p in products[:25]:
        item_data = {
            'id': p.id,
            'name': p.name,
            'sku': p.sku,
            'barcode': p.barcode or '',
            'price': float(p.selling_price),
            'mrp': float(p.mrp) if p.mrp else float(p.selling_price),
            'wholesale_price': float(p.wholesale_price) if p.wholesale_price else float(p.selling_price),
            'gst_scheme': p.gst_scheme,
            'gst_rate': float(p.gst_rate),
            'stock': p.quantity,
            'ram': p.ram or '',
            'rom': p.rom or '',
            'grade': p.grade if p.grade != 'N/A' else '',
            'category': p.category.name if p.category else '',
            'image_url': p.image_url or '',
        }
        # Strict Cost Price Concealment Invariant: Only Admin / Cash Handler can see cost
        if can_view_cost:
            item_data['cost_price'] = float(p.unit_cost)
        results.append(item_data)

    return JsonResponse({'products': results})

@login_required
def customer_search_api(request):
    q = request.GET.get('q', '').strip()
    customers = Customer.objects.all()
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(phone__icontains=q))[:15]
    else:
        customers = customers[:15]

    data = [{
        'id': c.id, 
        'name': c.name, 
        'phone': c.phone, 
        'gstin': c.gstin or '',
        'type': c.customer_type,
        'credit_limit': float(c.credit_limit),
        'available_credit': float(c.available_credit),
        'outstanding_balance': float(c.outstanding_balance),
        'wholesale_discount_percent': float(c.wholesale_discount_percent)
    } for c in customers]
    return JsonResponse({'customers': data})

@login_required
@require_POST
def add_customer_api(request):
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        gstin = data.get('gstin', '').strip()
        customer_type = data.get('customer_type', 'RETAIL')
        credit_limit = Decimal(str(data.get('credit_limit', 0)))
        if not name or not phone:
            return JsonResponse({'success': False, 'error': 'Name and Phone are required'}, status=400)
        
        customer, created = Customer.objects.get_or_create(
            phone=phone,
            defaults={
                'name': name, 
                'gstin': gstin,
                'customer_type': customer_type,
                'credit_limit': credit_limit
            }
        )
        if not created and name:
            customer.name = name
            if gstin: customer.gstin = gstin
            customer.customer_type = customer_type
            if credit_limit > 0: customer.credit_limit = credit_limit
            customer.save()

        return JsonResponse({
            'success': True, 
            'customer': {
                'id': customer.id, 
                'name': customer.name, 
                'phone': customer.phone, 
                'gstin': customer.gstin or '',
                'type': customer.customer_type,
                'available_credit': float(customer.available_credit)
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@require_POST
def checkout_api(request):
    try:
        data = json.loads(request.body)
        items = data.get('items', [])
        action = data.get('action', 'checkout') # 'checkout' or 'park'
        if not items:
            return JsonResponse({'success': False, 'error': 'Cart is empty'}, status=400)

        customer_id = data.get('customer_id')
        customer_name = data.get('customer_name', 'Walk-in Customer')
        customer_phone = data.get('customer_phone', '')
        customer_gstin = data.get('customer_gstin', '')
        payment_method = data.get('payment_method', 'CASH')
        split_cash = Decimal(str(data.get('split_cash', 0)))
        split_online = Decimal(str(data.get('split_online', 0)))
        override_code = data.get('override_code', '').strip()
        discount_amount = Decimal(str(data.get('discount_amount', 0)))
        notes = data.get('notes', '')
        is_offline = data.get('is_offline', False)

        profile = getattr(request.user, 'profile', None)
        branch = profile.assigned_branch if profile else 'Mumbai Bandra'

        customer = None
        if customer_id:
            customer = Customer.objects.filter(id=customer_id).first()
        elif customer_phone:
            customer, _ = Customer.objects.get_or_create(phone=customer_phone, defaults={'name': customer_name, 'gstin': customer_gstin})

        with transaction.atomic():
            subtotal = Decimal('0.00')
            total_cost = Decimal('0.00')
            total_tax = Decimal('0.00')
            total_taxable_margin = Decimal('0.00')
            validated_items = []

            for item in items:
                p_id = item.get('id')
                qty = int(item.get('quantity', 1))
                item_imei = item.get('imei', '').strip()
                item_price = Decimal(str(item.get('price', 0)))
                if qty <= 0:
                    continue

                product = Product.objects.select_for_update().get(id=p_id)
                if action == 'checkout' and product.quantity < qty:
                    return JsonResponse({
                        'success': False,
                        'error': f"Insufficient stock for '{product.name}'. In stock: {product.quantity}, requested: {qty}"
                    }, status=400)

                # Pricing calculation: Wholesale tier check or override
                unit_price = item_price if item_price > 0 else product.selling_price
                if customer and customer.customer_type == 'WHOLESALE' and product.wholesale_price and product.wholesale_price > 0:
                    unit_price = product.wholesale_price

                line_total = (unit_price * qty).quantize(Decimal('0.01'))
                line_cost = (product.unit_cost * qty).quantize(Decimal('0.01'))
                subtotal += line_total
                total_cost += line_cost

                # DUAL GST TAX ENGINE: Rule 32(5) Margin Scheme vs Normal GST
                item_tax = Decimal('0.00')
                taxable_margin = Decimal('0.00')
                if product.gst_scheme == 'margin_scheme':
                    # Section 32(5): Tax only on positive margin (Selling - Cost)
                    margin = line_total - line_cost
                    if margin > 0:
                        tax_factor = product.gst_rate / Decimal('100.00')
                        taxable_margin = (margin / (Decimal('1.00') + tax_factor)).quantize(Decimal('0.01'))
                        item_tax = (margin - taxable_margin).quantize(Decimal('0.01'))
                    else:
                        taxable_margin = Decimal('0.00')
                        item_tax = Decimal('0.00')
                else:
                    # Normal GST
                    tax_rate = product.gst_rate / Decimal('100.00')
                    item_tax = (line_total * tax_rate).quantize(Decimal('0.01'))

                total_tax += item_tax
                total_taxable_margin += taxable_margin
                validated_items.append((product, qty, unit_price, line_total, line_cost, item_imei, item_tax, taxable_margin))

            # Credit payment limit guard (Feature 9)
            final_total = max(Decimal('0.00'), subtotal + total_tax - discount_amount)
            if action == 'checkout' and payment_method == 'CREDIT':
                if not customer:
                    return JsonResponse({'success': False, 'error': 'Wholesale credit sale requires a customer profile'}, status=400)
                if customer.available_credit < final_total:
                    return JsonResponse({
                        'success': False, 
                        'error': f"Credit Limit Exceeded! Available: ₹{customer.available_credit}, Sale Amount: ₹{final_total}"
                    }, status=400)

            # Split CGST and SGST (or IGST if out of state)
            cgst_amount = (total_tax / Decimal('2.00')).quantize(Decimal('0.01'))
            sgst_amount = total_tax - cgst_amount
            gross_profit = max(Decimal('0.00'), subtotal - total_cost)

            # Staff Profit-Linked Incentive Points (Feature 13): 10 points per ₹100 net profit
            points_earned = int((gross_profit / Decimal('100.00')) * 10) if gross_profit > 0 else 0

            sale_status = 'HELD' if action == 'park' else 'COMPLETED'
            sale = Sale.objects.create(
                invoice_number=Sale.generate_invoice_number(),
                cashier=request.user,
                branch_location=branch,
                customer=customer,
                customer_name=customer.name if customer else customer_name,
                customer_phone=customer.phone if customer else customer_phone,
                customer_gstin=customer.gstin if customer and customer.gstin else customer_gstin,
                subtotal=subtotal,
                tax_percent=Decimal('18.00'),
                cgst_amount=cgst_amount,
                sgst_amount=sgst_amount,
                tax_amount=total_tax,
                discount_amount=discount_amount,
                total_amount=final_total,
                total_cost=total_cost,
                gross_profit=gross_profit,
                staff_points_earned=points_earned,
                payment_method=payment_method,
                split_cash_amount=split_cash,
                split_online_amount=split_online,
                status=sale_status,
                notes=notes,
                is_offline_sync=is_offline
            )

            # Award staff points
            if action == 'checkout' and points_earned > 0 and profile:
                profile.reward_points += points_earned
                profile.save()

            # Create sale items and deduct stock
            for product, qty, unit_price, line_total, line_cost, item_imei, item_tax, taxable_margin in validated_items:
                SaleItem.objects.create(
                    sale=sale,
                    product=product,
                    product_name=product.name,
                    sku=product.sku,
                    imei=item_imei,
                    hsn_code=product.hsn_code,
                    gst_scheme=product.gst_scheme,
                    unit_cost=product.unit_cost,
                    unit_price=unit_price,
                    quantity=qty,
                    taxable_margin=taxable_margin,
                    line_total=line_total
                )
                if action == 'checkout':
                    product.adjust_stock(
                        delta=-qty,
                        movement_type='sale',
                        user=request.user,
                        reference=sale.invoice_number,
                        notes=f"POS Sale #{sale.invoice_number}" + (f" (IMEI: {item_imei})" if item_imei else "")
                    )
                    if item_imei:
                        ProductIMEI.objects.filter(imei1=item_imei).update(status='SOLD', sold_invoice=sale.invoice_number)

            # Cash Register update (Feature 8)
            if action == 'checkout':
                register, _ = CashRegister.objects.get_or_create(user=request.user, defaults={'branch': branch})
                if payment_method == 'CASH':
                    register.cash_sales = Decimal(str(register.cash_sales)) + Decimal(str(final_total))
                elif payment_method == 'SPLIT' and split_cash > 0:
                    register.cash_sales = Decimal(str(register.cash_sales)) + Decimal(str(split_cash))
                register.save()

                # Wholesale Credit AR Invoice creation (Feature 9)
                if payment_method == 'CREDIT' and customer:
                    CustomerInvoiceAR.objects.create(
                        invoice_number=f"INV-{sale.invoice_number}",
                        customer=customer,
                        sale=sale,
                        due_date=timezone.now().date() + timezone.timedelta(days=customer.credit_terms_days),
                        total_amount=final_total,
                        balance_due=final_total,
                        status='unpaid'
                    )
                    customer.outstanding_balance += final_total
                    customer.save()

                # Immutable Audit Trail
                ImmutableAuditLog.objects.create(
                    user=request.user,
                    user_identifier=request.user.username,
                    action=f"Completed POS Sale {sale.invoice_number} (₹{final_total})",
                    module="POS Engine",
                    severity="info",
                    after_state=f"Payment: {payment_method}, Profit: ₹{gross_profit}, Items: {len(validated_items)}"
                )

        return JsonResponse({
            'success': True,
            'invoice_number': sale.invoice_number,
            'sale_id': sale.id,
            'status': sale.status,
            'points_earned': points_earned,
            'receipt_url': f"/pos/receipt/{sale.id}/"
        })

    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'One or more products were not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@require_POST
def request_override_api(request):
    """Feature 3: Request Special Discount / Price Override"""
    try:
        data = json.loads(request.body)
        product_id = data.get('product_id')
        requested_price = Decimal(str(data.get('requested_price', 0)))
        reason = data.get('reason', '').strip()
        notes = data.get('notes', '').strip()

        product = get_object_or_404(Product, id=product_id)
        req_num = f"REQ-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"

        override = DiscountOverride.objects.create(
            request_number=req_num,
            cashier=request.user,
            product=product,
            standard_price=product.selling_price,
            requested_price=requested_price,
            cost_price=product.unit_cost,
            reason=reason or 'Customer price negotiation',
            operational_notes=notes,
            status='pending'
        )

        return JsonResponse({
            'success': True,
            'request_number': override.request_number,
            'message': 'Discount override request submitted to Admin for approval.'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def override_requests_view(request):
    """Feature 3: Admin Review Dashboard for Discount Overrides"""
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Permission denied: Only Administrators can review discount overrides.")
        return redirect('pos:terminal')

    requests_qs = DiscountOverride.objects.all().order_by('-created_at')
    return render(request, 'pos/override_requests.html', {'requests': requests_qs})

@login_required
@require_POST
def handle_override_action(request, pk):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    override = get_object_or_404(DiscountOverride, pk=pk)
    action = request.POST.get('action') # 'approve', 'counter', 'decline'

    if action == 'approve':
        override.status = 'approved'
        override.approved_price = override.requested_price
        override.authorization_code = f"OVR-{uuid.uuid4().hex[:6].upper()}"
        override.reviewed_by = request.user
        override.reviewed_at = timezone.now()
        override.save()
        messages.success(request, f"Approved {override.request_number} with code {override.authorization_code}")
    elif action == 'counter':
        counter_price = Decimal(str(request.POST.get('counter_price', override.requested_price)))
        override.status = 'countered'
        override.approved_price = counter_price
        override.authorization_code = f"OVR-{uuid.uuid4().hex[:6].upper()}"
        override.reviewed_by = request.user
        override.reviewed_at = timezone.now()
        override.save()
        messages.info(request, f"Counter-offer set to ₹{counter_price} for {override.request_number}")
    elif action == 'decline':
        override.status = 'declined'
        override.decline_reason = request.POST.get('decline_reason', 'Below minimum margin threshold')
        override.reviewed_by = request.user
        override.reviewed_at = timezone.now()
        override.save()
        messages.warning(request, f"Declined {override.request_number}")

    return redirect('pos:override_requests')

# Feature 8: Cash Register & Physical Cash Custody Views
@login_required
def cash_register_view(request):
    profile = getattr(request.user, 'profile', None)
    branch = profile.assigned_branch if profile else 'Mumbai Bandra'
    register, _ = CashRegister.objects.get_or_create(user=request.user, defaults={'branch': branch})
    expenses = register.expenses.all().order_by('-created_at')[:20]
    deposits = register.user.deposit_requests.all().order_by('-created_at')[:20]
    
    # Designated Cash Handler View
    is_cash_handler = profile.is_cash_handler if profile else False
    all_pending_deposits = None
    if is_cash_handler or request.user.is_superuser or (profile and profile.is_admin):
        all_pending_deposits = CashDepositRequest.objects.filter(status='pending').order_by('-created_at')

    return render(request, 'pos/cash_register.html', {
        'register': register,
        'expenses': expenses,
        'deposits': deposits,
        'is_cash_handler': is_cash_handler,
        'all_pending_deposits': all_pending_deposits,
    })

@login_required
@require_POST
def add_petty_expense(request):
    amount = Decimal(str(request.POST.get('amount', 0)))
    category = request.POST.get('category', 'Other Petty Cash')
    receipt_note = request.POST.get('receipt_note', '').strip()
    
    register, _ = CashRegister.objects.get_or_create(user=request.user)
    if amount > register.cash_in_hand:
        messages.error(request, f"Expense ₹{amount} exceeds cash in hand (₹{register.cash_in_hand}).")
        return redirect('pos:cash_register')

    PettyCashExpense.objects.create(
        register=register,
        amount=amount,
        category=category,
        receipt_note=receipt_note,
        incurred_by=request.user
    )
    register.incurred_expenses += amount
    register.save()
    messages.success(request, f"Logged expense of ₹{amount} for {category}.")
    return redirect('pos:cash_register')

@login_required
@require_POST
def request_cash_deposit(request):
    claimed_amount = Decimal(str(request.POST.get('claimed_amount', 0)))
    register, _ = CashRegister.objects.get_or_create(user=request.user)
    
    if claimed_amount <= 0 or claimed_amount > register.cash_in_hand:
        messages.error(request, f"Invalid deposit amount. Cash in hand is ₹{register.cash_in_hand}.")
        return redirect('pos:cash_register')

    dep_num = f"DEP-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    CashDepositRequest.objects.create(
        deposit_number=dep_num,
        seller=request.user,
        branch=register.branch,
        claimed_amount=claimed_amount,
        status='pending'
    )
    messages.success(request, f"Deposit request {dep_num} submitted to Designated Cash Handler.")
    return redirect('pos:cash_register')

@login_required
@require_POST
def confirm_cash_deposit(request, pk):
    """Designated Cash Handler confirms deposit, counts cash, logs discrepancies, and resets seller register"""
    profile = getattr(request.user, 'profile', None)
    can_confirm = (profile and profile.is_cash_handler) or request.user.is_superuser
    if not can_confirm:
        messages.error(request, "Permission denied: Only the Designated Cash Handler can confirm deposits.")
        return redirect('pos:cash_register')

    deposit = get_object_or_404(CashDepositRequest, pk=pk)
    counted_amount = Decimal(str(request.POST.get('counted_amount', deposit.claimed_amount)))
    discrepancy_notes = request.POST.get('discrepancy_notes', '')

    with transaction.atomic():
        discrepancy = counted_amount - deposit.claimed_amount
        deposit.counted_amount = counted_amount
        deposit.discrepancy_amount = discrepancy
        deposit.discrepancy_notes = discrepancy_notes
        deposit.cash_handler = request.user
        deposit.status = 'confirmed'
        deposit.confirmed_at = timezone.now()
        deposit.save()

        # Update seller register
        seller_register, _ = CashRegister.objects.get_or_create(user=deposit.seller)
        seller_register.confirmed_deposits += counted_amount
        seller_register.save()

        # Append to audit trail
        ImmutableAuditLog.objects.create(
            user=request.user,
            user_identifier=request.user.username,
            action=f"Confirmed Cash Deposit {deposit.deposit_number} from {deposit.seller.username}",
            module="Cash Custody",
            severity="warning" if discrepancy != 0 else "info",
            after_state=f"Claimed: ₹{deposit.claimed_amount}, Counted: ₹{counted_amount}, Discrepancy: ₹{discrepancy}"
        )

    messages.success(request, f"Deposit {deposit.deposit_number} confirmed successfully. Seller register updated.")
    return redirect('pos:cash_register')

# Feature 5: Customer Returns & 2-Phase Restock Workflow Views
@login_required
def returns_list_view(request):
    returns_qs = CustomerReturn.objects.all().order_by('-created_at')
    profile = getattr(request.user, 'profile', None)
    is_admin = request.user.is_superuser or (profile and profile.is_admin)
    return render(request, 'pos/returns_list.html', {
        'returns': returns_qs,
        'is_admin': is_admin,
    })

@login_required
@require_POST
def log_customer_return(request):
    invoice_number = request.POST.get('invoice_number', '').strip()
    sale = get_object_or_404(Sale, invoice_number=invoice_number)
    product_id = request.POST.get('product_id')
    product = get_object_or_404(Product, id=product_id)
    imei = request.POST.get('imei', '').strip()
    condition = request.POST.get('condition_assessment', 'Ready-to-resell')
    reason = request.POST.get('customer_reason', '').strip()
    refund_amount = Decimal(str(request.POST.get('refund_amount', product.selling_price)))
    refund_method = request.POST.get('refund_method', 'Cash')
    recommended_routing = request.POST.get('staff_recommended_routing', 'return_to_resale')

    rtn_num = f"RTN-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    CustomerReturn.objects.create(
        return_number=rtn_num,
        original_sale=sale,
        customer=sale.customer,
        product=product,
        imei=imei,
        condition_assessment=condition,
        customer_reason=reason,
        refund_amount=refund_amount,
        refund_method=refund_method,
        staff_recommended_routing=recommended_routing,
        status='restock_pending',
        processed_by_staff=request.user
    )
    messages.success(request, f"Return {rtn_num} logged. Restock proposal sent for Admin authorization.")
    return redirect('pos:returns_list')

@login_required
@require_POST
def approve_restock_routing(request, pk):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Permission denied: Only Administrators can authorize physical restock routing.")
        return redirect('pos:returns_list')

    return_obj = get_object_or_404(CustomerReturn, pk=pk)
    routing = request.POST.get('admin_approved_routing', return_obj.staff_recommended_routing)
    admin_notes = request.POST.get('admin_notes', '')

    with transaction.atomic():
        return_obj.admin_approved_routing = routing
        return_obj.admin_notes = admin_notes
        return_obj.approved_by_admin = request.user
        return_obj.approved_at = timezone.now()
        return_obj.status = 'restocked'
        return_obj.save()

        # Execute routing disposition
        if routing == 'return_to_resale':
            return_obj.product.adjust_stock(
                delta=1,
                movement_type='return',
                user=request.user,
                reference=return_obj.return_number,
                notes=f"Approved resale restock from return {return_obj.return_number}"
            )
            if return_obj.imei:
                ProductIMEI.objects.filter(imei1=return_obj.imei).update(status='AVAILABLE', sold_invoice='')
        elif routing == 'route_to_repair':
            # Create a repair ticket for technician
            from repair.models import RepairTicket
            RepairTicket.objects.create(
                ticket_number=f"REP-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}",
                customer=return_obj.customer,
                customer_name=return_obj.customer.name if return_obj.customer else 'Returned Unit',
                customer_phone=return_obj.customer.phone if return_obj.customer else 'N/A',
                brand_name=return_obj.product.brand.name if return_obj.product.brand else 'Unknown',
                model_name=return_obj.product.name,
                imei_or_serial=return_obj.imei or return_obj.product.sku,
                reported_issue=f"Customer Return: {return_obj.customer_reason}",
                warranty_type='store_warranty',
                stage='received',
                intake_by=request.user
            )
        elif routing == 'spare_parts_harvest':
            return_obj.product.adjust_stock(
                delta=0,
                movement_type='parts_salvaged',
                user=request.user,
                reference=return_obj.return_number,
                notes="Unit designated for spare parts salvage"
            )

    messages.success(request, f"Approved restock routing '{routing}' for {return_obj.return_number}.")
    return redirect('pos:returns_list')

@login_required
def resume_held_sale_api(request, pk):
    sale = get_object_or_404(Sale.objects.prefetch_related('items'), pk=pk, status='HELD')
    items = []
    for it in sale.items.all():
        items.append({
            'id': it.product_id,
            'name': it.product_name,
            'sku': it.sku,
            'imei': it.imei or '',
            'price': float(it.unit_price),
            'quantity': it.quantity,
            'maxStock': it.product.quantity if it.product else 999
        })
    data = {
        'sale_id': sale.id,
        'customer_id': sale.customer_id or '',
        'customer_name': sale.customer_name,
        'customer_phone': sale.customer_phone or '',
        'tax_percent': float(sale.tax_percent),
        'discount_amount': float(sale.discount_amount),
        'payment_method': sale.payment_method,
        'items': items
    }
    sale.delete()
    return JsonResponse({'success': True, 'order': data})

@login_required
def receipt_view(request, pk):
    sale = get_object_or_404(Sale.objects.prefetch_related('items'), pk=pk)
    return render(request, 'pos/receipt.html', {'sale': sale})

@login_required
def sales_history_view(request):
    sales_qs = Sale.objects.all().select_related('cashier', 'customer')
    total_revenue = sum((s.total_amount for s in sales_qs if s.status == 'COMPLETED'), Decimal('0.00'))
    total_orders = sales_qs.filter(status='COMPLETED').count()
    sales = sales_qs[:60]
    return render(request, 'pos/sales_history.html', {
        'sales': sales,
        'total_revenue': total_revenue,
        'total_orders': total_orders,
    })

@login_required
def void_sale_view(request, pk):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Permission denied: Only Administrators can void sales.")
        return redirect('pos:sales_history')

    sale = get_object_or_404(Sale, pk=pk)
    if sale.status == 'VOIDED':
        messages.warning(request, f"Sale {sale.invoice_number} is already voided.")
        return redirect('pos:sales_history')

    with transaction.atomic():
        sale.status = 'VOIDED'
        sale.save()

        for item in sale.items.all():
            if item.product:
                item.product.adjust_stock(
                    delta=item.quantity,
                    movement_type='return',
                    user=request.user,
                    reference=f"VOID-{sale.invoice_number}",
                    notes=f"Restock from voided sale {sale.invoice_number}"
                )
            if item.imei:
                ProductIMEI.objects.filter(imei1=item.imei).update(status='AVAILABLE', sold_invoice='')

    messages.success(request, f"Sale {sale.invoice_number} voided and stock restored.")
    return redirect('pos:sales_history')

@login_required
def customer_list_view(request):
    customers = Customer.objects.all().order_by('-created_at')
    return render(request, 'pos/customers.html', {'customers': customers})
