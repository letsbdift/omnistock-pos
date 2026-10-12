from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('new/', views.product_create, name='product_create'),
    path('<int:pk>/', views.product_detail, name='product_detail'),
    path('<int:pk>/edit/', views.product_update, name='product_update'),
    path('movements/', views.stock_movement_list, name='movement_list'),
    path('barcodes/', views.barcode_labels_view, name='barcode_labels'),
    path('suppliers/', views.supplier_list_view, name='supplier_list'),
    path('import/', views.import_csv_view, name='import_csv'),
    path('export/', views.export_csv_view, name='export_csv'),
]
