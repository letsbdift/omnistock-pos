import json
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Q
from django.contrib import messages
from inventory.models import Product, StockMovement, ProductIMEI
from .models import Sale, SaleItem, Customer

@login_required
def terminal_view(request):
    products = Product.objects.filter(quantity__gt=0, status='Ready to Sell').select_related('brand', 'category')
    customers = Customer.objects.all().order_by('name')[:50]
    held_sales = Sale.objects.filter(status='HELD').order_by('-created_at')[:10]
    return render(request, 'pos/terminal.html', {
        'products': products,
        'customers': customers,
        'held_sales': held_sales,
    })

@login_required
def product_search_api(request):
    query = request.GET.get('q', '').strip()
    barcode = request.GET.get('barcode', '').strip()
    imei = request.GET.get('imei', '').strip()

    if imei:
        imei_obj = ProductIMEI.objects.filter(imei1__iexact=imei, status='AVAILABLE').select_related('product').first()
        if imei_obj:
            p = imei_obj.product
            return JsonResponse({'products': [{
                'id': p.id,
                'name': f"{p.name} (IMEI: {imei_obj.imei1})",
                'sku': p.sku,
                'barcode': p.barcode or '',
                'imei': imei_obj.imei1,
                'price': float(p.selling_price),
                'stock': p.quantity,
                'category': p.category.name if p.category else '',
                'image_url': p.image_url or '',
            }]})

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
        results.append({
            'id': p.id,
            'name': p.name,
            'sku': p.sku,
            'barcode': p.barcode or '',
            'price': float(p.selling_price),
            'stock': p.quantity,
            'ram': p.ram or '',
            'rom': p.rom or '',
            'grade': p.grade if p.grade != 'N/A' else '',
            'category': p.category.name if p.category else '',
            'image_url': p.image_url or '',
        })

    return JsonResponse({'products': results})

@login_required
def customer_search_api(request):
    q = request.GET.get('q', '').strip()
    customers = Customer.objects.all()
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(phone__icontains=q))[:15]
    else:
        customers = customers[:15]

    data = [{'id': c.id, 'name': c.name, 'phone': c.phone, 'gstin': c.gstin or ''} for c in customers]
    return JsonResponse({'customers': data})

@login_required
@require_POST
def add_customer_api(request):
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        gstin = data.get('gstin', '').strip()
        if not name or not phone:
            return JsonResponse({'success': False, 'error': 'Name and Phone are required'}, status=400)
        
        customer, created = Customer.objects.get_or_create(
            phone=phone,
            defaults={'name': name, 'gstin': gstin}
        )
        if not created and name:
            customer.name = name
            if gstin: customer.gstin = gstin
            customer.save()

        return JsonResponse({'success': True, 'customer': {'id': customer.id, 'name': customer.name, 'phone': customer.phone, 'gstin': customer.gstin or ''}})
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
        tax_percent = Decimal(str(data.get('tax_percent', 0)))
        discount_amount = Decimal(str(data.get('discount_amount', 0)))
        notes = data.get('notes', '')

        customer = None
        if customer_id:
            customer = Customer.objects.filter(id=customer_id).first()
        elif customer_phone:
            customer, _ = Customer.objects.get_or_create(phone=customer_phone, defaults={'name': customer_name, 'gstin': customer_gstin})

        with transaction.atomic():
            subtotal = Decimal('0.00')
            validated_items = []

            for item in items:
                p_id = item.get('id')
                qty = int(item.get('quantity', 1))
                item_imei = item.get('imei', '').strip()
                if qty <= 0:
                    continue

                product = Product.objects.select_for_update().get(id=p_id)
                if action == 'checkout' and product.quantity < qty:
                    return JsonResponse({
                        'success': False,
                        'error': f"Insufficient stock for '{product.name}'. In stock: {product.quantity}, requested: {qty}"
                    }, status=400)

                line_total = product.selling_price * qty
                subtotal += line_total
                validated_items.append((product, qty, product.selling_price, line_total, item_imei))

            tax_amount = (subtotal * (tax_percent / Decimal('100'))).quantize(Decimal('0.01'))
            # Calculate CGST (50%) and SGST (50%) for GST billing
            cgst_amount = (tax_amount / Decimal('2.00')).quantize(Decimal('0.01'))
            sgst_amount = tax_amount - cgst_amount
            total_amount = max(Decimal('0.00'), subtotal + tax_amount - discount_amount)

            sale_status = 'HELD' if action == 'park' else 'COMPLETED'
            sale = Sale.objects.create(
                invoice_number=Sale.generate_invoice_number(),
                cashier=request.user,
                customer=customer,
                customer_name=customer.name if customer else customer_name,
                customer_phone=customer.phone if customer else customer_phone,
                customer_gstin=customer.gstin if customer and customer.gstin else customer_gstin,
                subtotal=subtotal,
                tax_percent=tax_percent,
                cgst_amount=cgst_amount,
                sgst_amount=sgst_amount,
                tax_amount=tax_amount,
                discount_amount=discount_amount,
                total_amount=total_amount,
                payment_method=payment_method,
                split_cash_amount=split_cash,
                split_online_amount=split_online,
                status=sale_status,
                notes=notes
            )

            for product, qty, unit_price, line_total, item_imei in validated_items:
                SaleItem.objects.create(
                    sale=sale,
                    product=product,
                    product_name=product.name,
                    sku=product.sku,
                    imei=item_imei,
                    unit_price=unit_price,
                    quantity=qty,
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

        return JsonResponse({
            'success': True,
            'invoice_number': sale.invoice_number,
            'sale_id': sale.id,
            'status': sale.status,
            'receipt_url': f"/pos/receipt/{sale.id}/"
        })

    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'One or more products were not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

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
    # Void the held order record once resumed so it can be completed anew
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
    if not (request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_manager)):
        messages.error(request, "Permission denied: Only managers/admins can void sales.")
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
