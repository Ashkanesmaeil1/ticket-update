from django.urls import path
from . import views

app_name = 'dwms'

urlpatterns = [
    # Warehouse Selection (entry point)
    path('', views.warehouse_selection, name='warehouse_selection'),
    
    # Dashboard
    path('<int:department_id>/', views.warehouse_dashboard, name='dashboard'),
    
    # Storage Locations
    path('<int:department_id>/locations/', views.location_list, name='location_list'),
    path('<int:department_id>/locations/create/', views.location_create, name='location_create'),
    path('<int:department_id>/locations/<int:location_id>/edit/', views.location_edit, name='location_edit'),
    
    # Items
    path('<int:department_id>/items/', views.item_list, name='item_list'),
    path('<int:department_id>/items/create/', views.item_create, name='item_create'),
    path('<int:department_id>/items/<int:item_id>/', views.item_detail, name='item_detail'),
    path('<int:department_id>/items/<int:item_id>/edit/', views.item_edit, name='item_edit'),
    
    # Stock Movements
    path('<int:department_id>/movements/create/', views.movement_create, name='movement_create'),
    path('<int:department_id>/movements/create/<int:item_id>/', views.movement_create, name='movement_create_item'),
    path('<int:department_id>/movements/history/', views.movement_history, name='movement_history'),
    
    # Lending
    path('<int:department_id>/lends/', views.lend_list, name='lend_list'),
    path('<int:department_id>/lends/create/', views.lend_create, name='lend_create'),
    path('<int:department_id>/lends/create/<int:item_id>/', views.lend_create, name='lend_create_item'),
    path('<int:department_id>/lends/<int:lend_id>/return/', views.lend_return, name='lend_return'),
    
    # QR Scanning
    path('<int:department_id>/scan/', views.scan_interface, name='scan'),
    path('<int:department_id>/api/scan/', views.scan_api, name='scan_api'),
    
    # Reports
    path('<int:department_id>/reports/daily/', views.reports_daily, name='reports_daily'),
    path('<int:department_id>/reports/weekly/', views.reports_weekly, name='reports_weekly'),
    path('<int:department_id>/reports/monthly/', views.reports_monthly, name='reports_monthly'),
]

