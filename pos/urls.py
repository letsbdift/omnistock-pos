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
]
