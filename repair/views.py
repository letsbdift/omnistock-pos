import uuid
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import RepairTicket, RepairConsumedPart
from inventory.models import Product, StockMovement
from pos.models import Customer
from finance.models import ImmutableAuditLog

@login_required
def repair_tickets_view(request):
    """Feature 4: Repair Service Desk & Warranty Management Dashboard"""
    tickets = RepairTicket.objects.all().select_related('customer', 'assigned_technician').order_by('-created_at')
    spare_parts = Product.objects.filter(is_spare_part=True, quantity__gt=0)
    if not spare_parts.exists():
        spare_parts = Product.objects.filter(quantity__gt=0)[:30]

    return render(request, 'repair/tickets.html', {
        'tickets': tickets,
        'spare_parts': spare_parts,
    })

@login_required
@require_POST
def create_repair_ticket(request):
    c_name = request.POST.get('customer_name', '').strip()
    c_phone = request.POST.get('customer_phone', '').strip()
    dev_type = request.POST.get('device_type', 'Smartphone')
    brand = request.POST.get('brand_name', '').strip()
    model = request.POST.get('model_name', '').strip()
    imei_serial = request.POST.get('imei_or_serial', '').strip()
    passcode = request.POST.get('lock_passcode', '').strip()
    issue = request.POST.get('reported_issue', '').strip()
    warranty = request.POST.get('warranty_type', 'out_of_warranty')
    labor = Decimal(str(request.POST.get('labor_charge', 0)))

    customer = None
    if c_phone:
        customer, _ = Customer.objects.get_or_create(phone=c_phone, defaults={'name': c_name})

    ticket_num = f"REP-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    ticket = RepairTicket.objects.create(
        ticket_number=ticket_num,
        customer=customer,
        customer_name=c_name,
        customer_phone=c_phone,
        device_type=dev_type,
        brand_name=brand,
        model_name=model,
        imei_or_serial=imei_serial,
        lock_passcode=passcode,
        reported_issue=issue,
        warranty_type=warranty,
        labor_charge=labor,
        total_billed=labor if warranty == 'out_of_warranty' else Decimal('0.00'),
        stage='received',
        intake_by=request.user
    )

    ImmutableAuditLog.objects.create(
        user=request.user,
        user_identifier=request.user.username,
        action=f"Intake Repair Ticket {ticket.ticket_number}",
        module="Repair Service Desk",
        severity="info",
        after_state=f"Device: {brand} {model}, Issue: {issue}, Warranty: {warranty}"
    )

    messages.success(request, f"Repair Ticket {ticket_num} created successfully.")
    return redirect('repair:ticket_detail', pk=ticket.pk)

@login_required
def repair_ticket_detail(request, pk):
    ticket = get_object_or_404(RepairTicket.objects.prefetch_related('consumed_parts'), pk=pk)
    spare_parts = Product.objects.filter(quantity__gt=0)
    return render(request, 'repair/ticket_detail.html', {
        'ticket': ticket,
        'spare_parts': spare_parts,
    })

@login_required
@require_POST
def add_consumed_part(request, pk):
    ticket = get_object_or_404(RepairTicket, pk=pk)
    part_id = request.POST.get('part_product_id')
    part_product = get_object_or_404(Product, id=part_id)
    qty = int(request.POST.get('quantity', 1))

    if part_product.quantity < qty:
        messages.error(request, f"Insufficient stock for part '{part_product.name}'. Available: {part_product.quantity}")
        return redirect('repair:ticket_detail', pk=pk)

    unit_price = part_product.selling_price
    line_total = unit_price * qty

    # Deduct part from inventory immediately
    part_product.adjust_stock(
        delta=-qty,
        movement_type='repair_consumed',
        user=request.user,
        reference=ticket.ticket_number,
        notes=f"Part consumed for repair {ticket.ticket_number}"
    )

    RepairConsumedPart.objects.create(
        ticket=ticket,
        part_product=part_product,
        quantity=qty,
        unit_cost=part_product.unit_cost,
        unit_price=unit_price,
        line_total=line_total
    )

    ticket.calculate_total()
    messages.success(request, f"Consumed {qty}x {part_product.name} attached to {ticket.ticket_number}.")
    return redirect('repair:ticket_detail', pk=pk)

@login_required
@require_POST
def update_ticket_status(request, pk):
    ticket = get_object_or_404(RepairTicket, pk=pk)
    new_stage = request.POST.get('stage')
    tech_notes = request.POST.get('technician_diagnostic_notes', '')

    ticket.stage = new_stage
    if tech_notes:
        ticket.technician_diagnostic_notes = tech_notes
    if new_stage == 'ready':
        ticket.ready_at = timezone.now()
    elif new_stage == 'delivered':
        ticket.delivered_at = timezone.now()
    ticket.save()

    messages.success(request, f"Ticket {ticket.ticket_number} stage updated to {ticket.get_stage_display()}.")
    return redirect('repair:ticket_detail', pk=pk)
