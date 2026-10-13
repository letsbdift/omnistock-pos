from django.urls import path
from . import views

app_name = 'pos'

urlpatterns = [
    path('', views.terminal_view, name='terminal'),
    path('api/search/', views.product_search_api, name='product_search_api'),
    path('api/customers/', views.customer_search_api, name='customer_search_api'),
    path('api/customers/add/', views.add_customer_api, name='add_customer_api'),
    path('api/checkout/', views.checkout_api, name='checkout_api'),
    path('api/resume-held/<int:pk>/', views.resume_held_sale_api, name='resume_held_sale_api'),
    path('receipt/<int:pk>/', views.receipt_view, name='receipt'),
    path('history/', views.sales_history_view, name='sales_history'),
    path('customers/', views.customer_list_view, name='customer_list'),
    path('void/<int:pk>/', views.void_sale_view, name='void_sale'),
    
    # Feature 3: Price Override & Discount Approvals
    path('api/override/request/', views.request_override_api, name='request_override_api'),
    path('overrides/', views.override_requests_view, name='override_requests'),
    path('overrides/<int:pk>/action/', views.handle_override_action, name='handle_override_action'),
    
    # Feature 8: Cash Register & Custody
    path('register/', views.cash_register_view, name='cash_register'),
    path('register/expense/', views.add_petty_expense, name='add_petty_expense'),
    path('register/deposit/request/', views.request_cash_deposit, name='request_cash_deposit'),
    path('register/deposit/<int:pk>/confirm/', views.confirm_cash_deposit, name='confirm_cash_deposit'),
    
    # Feature 5: Returns & Restock Desk
    path('returns/', views.returns_list_view, name='returns_list'),
    path('returns/log/', views.log_customer_return, name='log_customer_return'),
    path('returns/<int:pk>/approve/', views.approve_restock_routing, name='approve_restock_routing'),
]
