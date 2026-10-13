from django.urls import path
from . import views

app_name = 'repair'

urlpatterns = [
    path('', views.repair_tickets_view, name='ticket_list'),
    path('new/', views.create_repair_ticket, name='create_ticket'),
    path('<int:pk>/', views.repair_ticket_detail, name='ticket_detail'),
    path('<int:pk>/part/add/', views.add_consumed_part, name='add_consumed_part'),
    path('<int:pk>/stage/update/', views.update_ticket_status, name='update_ticket_status'),
]
