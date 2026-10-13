import csv
import uuid
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, Sum, Count, F
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import (
    Product, StockMovement, Category, Brand, Supplier, ProductIMEI,
    PurchaseOrder, PurchaseOrderItem, LiquidationLot, StockShift
)
from .forms import ProductForm, StockAdjustmentForm, CSVImportForm
from .utils import import_omnistock_file
from pos.models import Sale, SaleItem
from finance.models import ImmutableAuditLog

@login_required
def dashboard_view(request):
    """Executive Dashboard with sales analytics and stock alerts"""
    profile = getattr(request.user, 'profile', None)
    can_view_cost = profile.can_view_cost_and_profit if profile else False

    today = timezone.now().date()
    today_sales = Sale.objects.filter(status='COMPLETED', created_at__date=today)
    today_revenue = sum((s.total_amount for s in today_sales), Decimal('0.00'))
    today_orders = today_sales.count()

    total_products = Product.objects.count()
    low_stock_products = Product.objects.filter(quantity__lte=F('min_stock_alert_level'))
    out_of_stock_count = Product.objects.filter(quantity=0).count()
    total_stock_value = sum((p.quantity * p.unit_cost for p in Product.objects.all()), Decimal('0.00')) if can_view_cost else None

    recent_sales = Sale.objects.filter(status='COMPLETED').order_by('-created_at')[:8]
    top_items = SaleItem.objects.values('product_name').annotate(total_qty=Sum('quantity')).order_by('-total_qty')[:5]

    context = {
        'today_revenue': today_revenue,
        'today_orders': today_orders,
        'total_products': total_products,
        'low_stock_count': len(low_stock_products),
        'out_of_stock_count': out_of_stock_count,
        'total_stock_value': total_stock_value,
        'recent_sales': recent_sales,
        'top_items': top_items,
        'can_view_cost': can_view_cost,
    }
    return render(request, 'inventory/dashboard.html', context)

@login_required
def product_list(request):
    query = request.GET.get('q', '').strip()
    category_id = request.GET.get('category')
    status_filter = request.GET.get('status')
    grade_filter = request.GET.get('grade')
    has_imei = request.GET.get('has_imei')
    profile = getattr(request.user, 'profile', None)
    can_view_cost = profile.can_view_cost_and_profit if profile else False

    products = Product.objects.all().select_related('brand', 'category', 'liquidation_lot').prefetch_related('imei_numbers').order_by('name')

    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(sku__icontains=query) |
            Q(barcode__icontains=query) |
            Q(brand__name__icontains=query) |
            Q(tracking_id__icontains=query) |
            Q(imei_numbers__imei1__icontains=query)
        ).distinct()

    if category_id:
        products = products.filter(category_id=category_id)

    if status_filter:
        products = products.filter(status=status_filter)

    if grade_filter:
        products = products.filter(grade=grade_filter)

    if has_imei:
        products = products.filter(imei_numbers__isnull=False).distinct()

    categories = Category.objects.all()
    total_products = products.count()
    total_stock_value = sum((p.quantity * p.unit_cost for p in products), Decimal('0.00')) if can_view_cost else None
    total_retail_value = sum((p.quantity * p.selling_price for p in products), Decimal('0.00'))
    low_stock_count = sum(1 for p in products if p.is_low_stock)

    context = {
        'products': products,
        'categories': categories,
        'query': query,
        'selected_category': category_id,
        'selected_status': status_filter,
        'selected_grade': grade_filter,
        'total_products': total_products,
        'total_stock_value': total_stock_value,
        'total_retail_value': total_retail_value,
        'low_stock_count': low_stock_count,
        'can_view_cost': can_view_cost,
    }
    return render(request, 'inventory/product_list.html', context)

@login_required
def product_detail(request, pk):
    product = get_object_or_404(Product.objects.prefetch_related('imei_numbers', 'movements'), pk=pk)
    movements = product.movements.all()[:15]
    imeis = product.imei_numbers.all()
    form = StockAdjustmentForm()
    profile = getattr(request.user, 'profile', None)
    can_view_cost = profile.can_view_cost_and_profit if profile else False

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_imei':
            imei_val = request.POST.get('imei1', '').strip()
            if imei_val:
                ProductIMEI.objects.get_or_create(product=product, imei1=imei_val, defaults={'status': 'AVAILABLE', 'location': product.warehouse_location})
                messages.success(request, f"IMEI {imei_val} attached to {product.name}!")
                return redirect('inventory:product_detail', pk=pk)
        else:
            form = StockAdjustmentForm(request.POST)
            if form.is_valid():
                delta = form.cleaned_data['delta']
                m_type = form.cleaned_data['movement_type']
                notes = form.cleaned_data['notes']
                try:
                    product.adjust_stock(
                        delta=delta,
                        movement_type=m_type,
                        user=request.user,
                        reference='Manual Adjustment',
                        notes=notes
                    )
                    messages.success(request, f"Stock updated successfully for {product.name}!")
                    return redirect('inventory:product_detail', pk=pk)
                except ValueError as e:
                    messages.error(request, str(e))

    return render(request, 'inventory/product_detail.html', {
        'product': product,
        'movements': movements,
        'imeis': imeis,
        'adjustment_form': form,
        'can_view_cost': can_view_cost,
    })

@login_required
def product_create(request):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Permission denied: Sales staff cannot create products directly.")
        return redirect('inventory:product_list')

    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save()
            if product.quantity > 0:
                StockMovement.objects.create(
                    product=product,
                    movement_type='intake',
                    quantity=product.quantity,
                    previous_quantity=0,
                    new_quantity=product.quantity,
                    reference='Initial Creation',
                    user=request.user,
                    notes='Initial stock intake on creation'
                )
            messages.success(request, f"Product {product.name} created successfully!")
            return redirect('inventory:product_detail', pk=product.pk)
    else:
        form = ProductForm()
    return render(request, 'inventory/product_form.html', {'form': form, 'title': 'Add New Product'})

@login_required
def product_update(request, pk):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Permission denied: Sales staff cannot edit products directly.")
        return redirect('inventory:product_list')

    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, f"Product {product.name} updated!")
            return redirect('inventory:product_detail', pk=product.pk)
    else:
        form = ProductForm(instance=product)
    return render(request, 'inventory/product_form.html', {'form': form, 'title': f'Edit {product.name}'})

@login_required
def stock_movement_list(request):
    movements = StockMovement.objects.all().select_related('product', 'user')[:100]
    return render(request, 'inventory/stock_movement_list.html', {'movements': movements})

@login_required
def barcode_labels_view(request):
    """Feature 1: Interactive Barcode & SKU Label Printing Studio"""
    product_ids = request.GET.getlist('p')
    all_products = Product.objects.all().select_related('brand', 'category').order_by('name')
    if product_ids:
        selected_products = Product.objects.filter(id__in=product_ids)
    else:
        selected_products = all_products.filter(quantity__gt=0)[:25]
    
    return render(request, 'inventory/barcode_labels.html', {
        'all_products': all_products,
        'selected_products': selected_products,
    })

# Feature 6: Liquidation Lots & Grading Views
@login_required
def liquidation_lots_view(request):
    lots = LiquidationLot.objects.all().order_by('-created_at')
    suppliers = Supplier.objects.filter(supplier_type='Liquidation Source')
    return render(request, 'inventory/liquidation_lots.html', {'lots': lots, 'suppliers': suppliers})

@login_required
@require_POST
def create_liquidation_lot(request):
    lot_id = request.POST.get('lot_id', '').strip() or f"LOT-{uuid.uuid4().hex[:6].upper()}"
    manifest_id = request.POST.get('source_manifest_id', '').strip()
    vendor_id = request.POST.get('source_vendor')
    cost = Decimal(str(request.POST.get('total_lot_cost', 0)))
    unit_count = int(request.POST.get('unit_count', 0))

    lot = LiquidationLot.objects.create(
        lot_id=lot_id,
        source_manifest_id=manifest_id,
        source_vendor_id=vendor_id if vendor_id else None,
        total_lot_cost=cost,
        unit_count=unit_count,
        status='intake'
    )
    messages.success(request, f"Liquidation lot {lot.lot_id} intake registered.")
    return redirect('inventory:liquidation_lots')

# Feature 7: Multi-Location Stock Shifts & In-Transit Tracking
@login_required
def stock_shifts_view(request):
    shifts = StockShift.objects.all().select_related('product', 'dispatched_by', 'received_by').order_by('-dispatched_at')
    products = Product.objects.filter(quantity__gt=0)
    return render(request, 'inventory/stock_shifts.html', {'shifts': shifts, 'products': products})

@login_required
@require_POST
def dispatch_stock_shift(request):
    product_id = request.POST.get('product_id')
    product = get_object_or_404(Product, id=product_id)
    from_loc = request.POST.get('from_location', 'Mumbai Bandra')
    to_loc = request.POST.get('to_location', 'Delhi Connaught')
    qty = int(request.POST.get('quantity', 1))
    carrier = request.POST.get('carrier_name', '').strip()
    tracking_no = request.POST.get('tracking_number', '').strip()

    if product.quantity < qty:
        messages.error(request, f"Insufficient stock at origin. Available: {product.quantity}, requested: {qty}")
        return redirect('inventory:stock_shifts')

    shift_num = f"SHIFT-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    
    # Deduct origin stock and log shift movement
    product.adjust_stock(
        delta=-qty,
        movement_type='shift_dispatch',
        user=request.user,
        reference=shift_num,
        notes=f"Stock shift dispatch to {to_loc} via {carrier}"
    )

    StockShift.objects.create(
        shift_number=shift_num,
        product=product,
        from_location=from_loc,
        to_location=to_loc,
        dispatched_quantity=qty,
        dispatched_by=request.user,
        carrier_name=carrier,
        tracking_number=tracking_no,
        status='in_transit'
    )
    messages.success(request, f"Stock shift {shift_num} dispatched! Tracking state: In-Transit.")
    return redirect('inventory:stock_shifts')

@login_required
@require_POST
def receive_stock_shift(request, pk):
    shift = get_object_or_404(StockShift, pk=pk)
    if shift.status != 'in_transit':
        messages.warning(request, f"Shift {shift.shift_number} is already processed.")
        return redirect('inventory:stock_shifts')

    received_qty = int(request.POST.get('received_quantity', shift.dispatched_quantity))
    discrepancy_notes = request.POST.get('discrepancy_notes', '').strip()

    shift.received_quantity = received_qty
    shift.received_by = request.user
    shift.received_at = timezone.now()
    shift.discrepancy_notes = discrepancy_notes
    shift.status = 'discrepancy' if received_qty != shift.dispatched_quantity else 'received'
    shift.save()

    # Credit received items to product stock at destination
    shift.product.adjust_stock(
        delta=received_qty,
        movement_type='shift_received',
        user=request.user,
        reference=shift.shift_number,
        notes=f"Received shift from {shift.from_location} at {shift.to_location}. {discrepancy_notes}"
    )
    messages.success(request, f"Shift {shift.shift_number} received into {shift.to_location} stock.")
    return redirect('inventory:stock_shifts')

@login_required
def supplier_list_view(request):
    suppliers = Supplier.objects.all()
    return render(request, 'inventory/suppliers.html', {'suppliers': suppliers})

@login_required
def import_csv_view(request):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Permission denied: Only Administrators can perform bulk file restock imports.")
        return redirect('inventory:product_list')

    if request.method == 'POST':
        form = CSVImportForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES['csv_file']
            created, updated, errors = import_omnistock_file(uploaded_file, filename=uploaded_file.name, user=request.user)
            messages.success(request, f"Import complete: {created} products created, {updated} updated.")
            if errors:
                for err in errors[:5]:
                    messages.warning(request, err)
            return redirect('inventory:product_list')
    else:
        form = CSVImportForm()
    return render(request, 'inventory/import_export.html', {'form': form})

@login_required
def export_csv_view(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="omnistock_inventory_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        "Product Name", "SKU", "Barcode", "Brand", "Category", "RAM", "ROM",
        "Grade", "Quantity", "Stock Unit", "Unit Cost", "Selling Price", "MRP", "Condition",
        "Status", "Warehouse / Location", "Received Date", "Stock Age (Days)", "Notes"
    ])

    for p in Product.objects.all().select_related('brand', 'category'):
        writer.writerow([
            p.name, p.sku, p.barcode or '',
            p.brand.name if p.brand else '',
            p.category.name if p.category else '',
            p.ram or '', p.rom or '', p.grade,
            p.quantity, p.stock_unit,
            p.unit_cost, p.selling_price, p.mrp or '', p.condition,
            p.status, p.warehouse_location, p.received_date, p.stock_age_days, p.notes or ''
        ])

    return response
