from django.urls import path
from . import views

app_name = 'finance'

urlpatterns = [
    path('pl/', views.financial_dashboard_view, name='pl_statement'),
    path('pl/expense/add/', views.add_operating_expense, name='add_operating_expense'),
    path('ar/', views.ar_aging_view, name='ar_aging'),
    path('ar/<int:pk>/pay/', views.record_ar_payment, name='record_ar_payment'),
    path('ap/', views.ap_aging_view, name='ap_aging'),
    path('gst/', views.gst_compliance_view, name='gst_compliance'),
    path('gst/lock/', views.lock_gst_period, name='lock_gst_period'),
    path('audit/', views.audit_logs_view, name='audit_logs'),
    path('rewards/', views.staff_rewards_view, name='staff_rewards'),
    path('rewards/<int:pk>/claim/', views.claim_reward, name='claim_reward'),
    path('backup/', views.backup_export_view, name='backup_export'),
    path('export/<str:module_name>/', views.export_module_csv, name='export_module_csv'),
]
