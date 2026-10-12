import csv
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, Sum, Count, F
from django.utils import timezone
from .models import Product, StockMovement, Category, Brand, Supplier, ProductIMEI, PurchaseOrder, PurchaseOrderItem
from .forms import ProductForm, StockAdjustmentForm, CSVImportForm
from .utils import import_omnistock_file
from pos.models import Sale, SaleItem

@login_required
def dashboard_view(request):
    """Executive Dashboard with sales analytics and stock alerts"""
    today = timezone.now().date()
    today_sales = Sale.objects.filter(status='COMPLETED', created_at__date=today)
    today_revenue = sum((s.total_amount for s in today_sales), Decimal('0.00'))
    today_orders = today_sales.count()

    total_products = Product.objects.count()
    low_stock_products = Product.objects.filter(quantity__lte=F('min_stock_alert_level'))
    out_of_stock_count = Product.objects.filter(quantity=0).count()
    total_stock_value = sum((p.quantity * p.unit_cost for p in Product.objects.all()), Decimal('0.00'))

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
    }
    return render(request, 'inventory/dashboard.html', context)

@login_required
def product_list(request):
    query = request.GET.get('q', '').strip()
    category_id = request.GET.get('category')
    status_filter = request.GET.get('status')
    grade_filter = request.GET.get('grade')
    has_imei = request.GET.get('has_imei')

    products = Product.objects.all().select_related('brand', 'category').prefetch_related('imei_numbers').order_by('name')

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
    total_stock_value = sum((p.quantity * p.unit_cost for p in products), Decimal('0.00'))
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
    }
    return render(request, 'inventory/product_list.html', context)

@login_required
def product_detail(request, pk):
    product = get_object_or_404(Product.objects.prefetch_related('imei_numbers', 'movements'), pk=pk)
    movements = product.movements.all()[:15]
    imeis = product.imei_numbers.all()
    form = StockAdjustmentForm()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_imei':
            imei_val = request.POST.get('imei1', '').strip()
            if imei_val:
                ProductIMEI.objects.get_or_create(product=product, imei1=imei_val, defaults={'status': 'AVAILABLE'})
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
        'adjustment_form': form
    })

@login_required
def product_create(request):
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
    """Printable barcode label sheet generator"""
    product_ids = request.GET.getlist('p')
    if product_ids:
        products = Product.objects.filter(id__in=product_ids)
    else:
        products = Product.objects.filter(quantity__gt=0)[:30]
    return render(request, 'inventory/barcode_labels.html', {'products': products})

@login_required
def supplier_list_view(request):
    suppliers = Supplier.objects.all()
    return render(request, 'inventory/suppliers.html', {'suppliers': suppliers})

@login_required
def import_csv_view(request):
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
    response['Content-Disposition'] = 'attachment; filename="omnistock_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        "Product Name", "SKU", "Barcode", "Brand", "Category", "RAM", "ROM",
        "Grade", "Quantity", "Stock Unit", "Unit Cost", "Selling Price", "MRP", "Condition",
        "Status", "Warehouse / Location", "Received Date", "Notes"
    ])

    for p in Product.objects.all().select_related('brand', 'category'):
        writer.writerow([
            p.name, p.sku, p.barcode or '',
            p.brand.name if p.brand else '',
            p.category.name if p.category else '',
            p.ram or '', p.rom or '', p.grade,
            p.quantity, p.stock_unit,
            p.unit_cost, p.selling_price, p.mrp or '', p.condition,
            p.status, p.warehouse_location, p.received_date, p.notes or ''
        ])

    return response
