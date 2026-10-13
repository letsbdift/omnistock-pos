import csv
import json
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import (
    CustomerInvoiceAR, VendorBillAP, GSTCompliancePeriod, OperatingExpense,
    ImmutableAuditLog, RewardProduct, StaffRewardRedemption, SystemIDSequence
)
from pos.models import Sale, SaleItem, Customer
from inventory.models import Product, Supplier, PurchaseOrder

@login_required
def financial_dashboard_view(request):
    """Feature 12: Real-time P&L Statement & Financial Analytics"""
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Permission denied: Only Administrators can access financial statements.")
        return redirect('pos:terminal')

    # Date range default: current month
    today = timezone.now().date()
    start_of_month = today.replace(day=1)
    
    completed_sales = Sale.objects.filter(status='COMPLETED', created_at__date__gte=start_of_month)
    gross_revenue = sum((s.total_amount for s in completed_sales), Decimal('0.00'))
    total_cogs = sum((s.total_cost for s in completed_sales), Decimal('0.00'))
    gross_profit = sum((s.gross_profit for s in completed_sales), Decimal('0.00'))

    operating_expenses = OperatingExpense.objects.filter(expense_date__gte=start_of_month)
    total_operating_expenses = sum((e.amount for e in operating_expenses), Decimal('0.00'))
    net_operating_income = gross_profit - total_operating_expenses

    return render(request, 'finance/pl_statement.html', {
        'gross_revenue': gross_revenue,
        'total_cogs': total_cogs,
        'gross_profit': gross_profit,
        'operating_expenses': operating_expenses,
        'total_operating_expenses': total_operating_expenses,
        'net_operating_income': net_operating_income,
        'start_of_month': start_of_month,
        'today': today,
    })

@login_required
@require_POST
def add_operating_expense(request):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Unauthorized")
        return redirect('finance:pl_statement')

    category = request.POST.get('category')
    amount = Decimal(str(request.POST.get('amount', 0)))
    desc = request.POST.get('description', '').strip()

    OperatingExpense.objects.create(
        category=category,
        amount=amount,
        description=desc,
        recorded_by=request.user
    )
    messages.success(request, f"Added operating expense ₹{amount} for {category}.")
    return redirect('finance:pl_statement')

# Feature 9: Accounts Receivable (AR) & Credit Management
@login_required
def ar_aging_view(request):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Unauthorized")
        return redirect('pos:terminal')

    invoices = CustomerInvoiceAR.objects.all().select_related('customer').order_by('due_date')
    wholesale_customers = Customer.objects.filter(customer_type='WHOLESALE')
    
    total_receivable = sum((inv.balance_due for inv in invoices if inv.status != 'paid'), Decimal('0.00'))

    return render(request, 'finance/ar_aging.html', {
        'invoices': invoices,
        'wholesale_customers': wholesale_customers,
        'total_receivable': total_receivable,
    })

@login_required
@require_POST
def record_ar_payment(request, pk):
    invoice = get_object_or_404(CustomerInvoiceAR, pk=pk)
    amount = Decimal(str(request.POST.get('payment_amount', invoice.balance_due)))
    invoice.record_payment(amount)
    messages.success(request, f"Payment of ₹{amount} recorded against invoice {invoice.invoice_number}.")
    return redirect('finance:ar_aging')

# Feature 10: Accounts Payable (AP) & Vendor Bills
@login_required
def ap_aging_view(request):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Unauthorized")
        return redirect('pos:terminal')

    bills = VendorBillAP.objects.all().select_related('vendor').order_by('due_date')
    total_payable = sum((b.balance_due for b in bills if b.status != 'paid'), Decimal('0.00'))

    return render(request, 'finance/ap_aging.html', {
        'bills': bills,
        'total_payable': total_payable,
    })

# Feature 11: GST Compliance & Filing
@login_required
def gst_compliance_view(request):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Unauthorized")
        return redirect('pos:terminal')

    periods = GSTCompliancePeriod.objects.all().order_by('-start_date')
    
    # Calculate GSTR-1 and GSTR-3B aggregates for current month
    today = timezone.now().date()
    month_start = today.replace(day=1)
    
    sales_month = Sale.objects.filter(status='COMPLETED', created_at__date__gte=month_start)
    b2b_sales = sales_month.filter(customer__customer_type='WHOLESALE')
    b2c_sales = sales_month.exclude(customer__customer_type='WHOLESALE')

    b2b_taxable = sum((s.subtotal for s in b2b_sales), Decimal('0.00'))
    b2b_tax = sum((s.tax_amount for s in b2b_sales), Decimal('0.00'))
    b2c_taxable = sum((s.subtotal for s in b2c_sales), Decimal('0.00'))
    b2c_tax = sum((s.tax_amount for s in b2c_sales), Decimal('0.00'))

    total_output_tax = b2b_tax + b2c_tax
    
    # ITC from vendor bills
    ap_bills = VendorBillAP.objects.filter(bill_date__gte=month_start, is_itc_eligible=True)
    eligible_itc = sum((b.total_amount * Decimal('0.18') for b in ap_bills), Decimal('0.00'))
    net_cash_tax = max(Decimal('0.00'), total_output_tax - eligible_itc)

    return render(request, 'finance/gst_compliance.html', {
        'periods': periods,
        'b2b_taxable': b2b_taxable,
        'b2b_tax': b2b_tax,
        'b2c_taxable': b2c_taxable,
        'b2c_tax': b2c_tax,
        'total_output_tax': total_output_tax,
        'eligible_itc': eligible_itc,
        'net_cash_tax': net_cash_tax,
        'month_start': month_start,
    })

@login_required
@require_POST
def lock_gst_period(request):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Unauthorized")
        return redirect('finance:gst_compliance')

    period_name = request.POST.get('period_name', '').strip()
    arn = request.POST.get('arn_number', '').strip()
    notes = request.POST.get('amendment_notes', '').strip()

    today = timezone.now().date()
    p, created = GSTCompliancePeriod.objects.get_or_create(
        period_name=period_name,
        defaults={
            'start_date': today.replace(day=1),
            'end_date': today,
            'status': 'locked_and_filed',
            'arn_number': arn,
            'locked_by': request.user,
            'locked_at': timezone.now(),
            'amendment_notes': notes
        }
    )
    if not created:
        p.status = 'locked_and_filed'
        p.arn_number = arn
        p.locked_by = request.user
        p.locked_at = timezone.now()
        p.amendment_notes = notes
        p.save()

    ImmutableAuditLog.objects.create(
        user=request.user,
        user_identifier=request.user.username,
        action=f"Locked GST Compliance Period {period_name} with ARN {arn}",
        module="GST Compliance Engine",
        severity="critical",
        after_state=f"ARN: {arn}, Locked At: {timezone.now()}"
    )

    messages.success(request, f"Period {period_name} permanently locked and filed with ARN {arn}.")
    return redirect('finance:gst_compliance')

# Feature 12: Immutable Audit Log Viewer
@login_required
def audit_logs_view(request):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Permission denied: Audit log access is restricted to Administrators.")
        return redirect('pos:terminal')

    logs = ImmutableAuditLog.objects.all()[:150]
    return render(request, 'finance/audit_logs.html', {'logs': logs})

# Feature 13: Staff Performance & Rewards
@login_required
def staff_rewards_view(request):
    rewards = RewardProduct.objects.filter(available_stock__gt=0)
    profile = getattr(request.user, 'profile', None)
    my_redemptions = request.user.redemptions.all().order_by('-claimed_at')

    return render(request, 'finance/staff_rewards.html', {
        'rewards': rewards,
        'profile': profile,
        'my_redemptions': my_redemptions,
    })

@login_required
@require_POST
def claim_reward(request, pk):
    reward = get_object_or_404(RewardProduct, pk=pk)
    profile = getattr(request.user, 'profile', None)

    if not profile or profile.reward_points < reward.points_required:
        messages.error(request, f"Insufficient points! You need {reward.points_required} points but have {profile.reward_points if profile else 0}.")
        return redirect('finance:staff_rewards')

    if reward.available_stock <= 0:
        messages.error(request, "This reward product is currently out of stock.")
        return redirect('finance:staff_rewards')

    code = f"RWD-{uuid.uuid4().hex[:6].upper()}"
    profile.reward_points -= reward.points_required
    profile.save()

    reward.available_stock -= 1
    reward.save()

    StaffRewardRedemption.objects.create(
        redemption_code=code,
        staff=request.user,
        reward=reward,
        points_spent=reward.points_required
    )

    messages.success(request, f"Congratulations! Reward certificate {code} issued for {reward.name}.")
    return redirect('finance:staff_rewards')

# Feature 15: Cloud Backup & Multi-Module Export Engine
@login_required
def backup_export_view(request):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        messages.error(request, "Permission denied")
        return redirect('pos:terminal')

    return render(request, 'finance/backup_export.html')

@login_required
def export_module_csv(request, module_name):
    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and profile.is_admin)):
        return HttpResponse("Unauthorized", status=403)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="omnistock_{module_name}_export.csv"'
    writer = csv.writer(response)

    if module_name == 'audit':
        writer.writerow(["Timestamp", "User", "Module", "Severity", "Action", "Before State", "After State"])
        for l in ImmutableAuditLog.objects.all():
            writer.writerow([l.timestamp, l.user_identifier, l.module, l.severity, l.action, l.before_state, l.after_state])
    elif module_name == 'sales':
        writer.writerow(["Invoice", "Cashier", "Customer", "Subtotal", "Tax", "Discount", "Total", "Payment Method", "Status", "Date"])
        for s in Sale.objects.all():
            writer.writerow([s.invoice_number, s.cashier.username if s.cashier else '', s.customer_name, s.subtotal, s.tax_amount, s.discount_amount, s.total_amount, s.payment_method, s.status, s.created_at])
    elif module_name == 'ar':
        writer.writerow(["Invoice Number", "Customer", "Due Date", "Total Amount", "Paid Amount", "Balance Due", "Status"])
        for a in CustomerInvoiceAR.objects.all():
            writer.writerow([a.invoice_number, a.customer.name, a.due_date, a.total_amount, a.paid_amount, a.balance_due, a.status])
    else:
        writer.writerow(["Entity", "Count"])
        writer.writerow([module_name, 1])

    return response
