from django.urls import path
from . import views

app_name = 'tickets'

urlpatterns = [
    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Main views
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # Ticket management
    path('tickets/', views.ticket_list, name='ticket_list'),
    path('tickets/create/', views.ticket_create, name='ticket_create'),
    path('tickets/<int:ticket_id>/', views.ticket_detail, name='ticket_detail'),
    path('tickets/<int:ticket_id>/update/', views.ticket_update, name='ticket_update'),
    path('tickets/<int:ticket_id>/delete/', views.ticket_delete, name='ticket_delete'),
    
    # User profile - REMOVED
# path('profile/', views.profile_view, name='profile'),
    
    # SuperAdmin profile
    path('superadmin-profile/', views.superadmin_profile, name='superadmin_profile'),
    
    # IT Manager profile
    path('profile/', views.it_manager_profile, name='it_manager_profile'),
    
    # IT Manager specific views
    path('technician-management/', views.technician_management, name='technician_management'),
    path('statistics/', views.statistics, name='statistics'),
    path('email-settings/', views.email_settings, name='email_settings'),
    path('email-settings/test-connection/', views.test_email_connection, name='test_email_connection'),
    path('user-management/', views.user_management, name='user_management'),
    path('user-management/<int:user_id>/delete/', views.delete_user, name='delete_user'),
    path('user-management/<int:user_id>/edit-employee/', views.edit_employee, name='edit_employee'),
    path('user-management/<int:user_id>/edit-technician/', views.edit_technician, name='edit_technician'),
    path('user-management/<int:user_id>/edit-it-manager/', views.edit_it_manager, name='edit_it_manager'),
    
    # Department management
    path('department-management/', views.department_management, name='department_management'),
    path('department-management/create/', views.department_create, name='department_create'),
    path('department-management/<int:department_id>/edit/', views.department_edit, name='department_edit'),
    path('department-management/<int:department_id>/delete/', views.department_delete, name='department_delete'),
    path('department-management/<int:department_id>/toggle-tickets/', views.department_toggle_tickets, name='department_toggle_tickets'),
    path('department-management/<int:department_id>/toggle-warehouse/', views.department_toggle_warehouse, name='department_toggle_warehouse'),
    
    # Supervisor assignment management
    path('supervisor-assignment/', views.supervisor_assignment, name='supervisor_assignment'),
    path('supervisor-assignment/<int:department_id>/remove/', views.remove_supervisor_from_department, name='remove_supervisor_from_department'),
    
    # Supervisor ticket responder management
    path('supervisor/ticket-responder/', views.supervisor_ticket_responder_management, name='supervisor_ticket_responder_management'),
    
    # Branch management
    path('branch-management/', views.branch_management, name='branch_management'),
    path('branch-management/create/', views.branch_create, name='branch_create'),
    path('branch-management/<int:branch_id>/edit/', views.branch_edit, name='branch_edit'),
    path('branch-management/<int:branch_id>/delete/', views.branch_delete, name='branch_delete'),
    
    # Received tickets (for department supervisors)
    path('received-tickets/', views.received_tickets_list, name='received_tickets_list'),
    
    # Warehouse management (for supervisors)
    path('warehouse/', views.warehouse_management, name='warehouse_management'),
    path('warehouse/department/<int:department_id>/', views.department_warehouse_inventory, name='department_warehouse_inventory'),
    path('warehouse/department/<int:department_id>/create/', views.department_warehouse_element_create, name='department_warehouse_element_create'),
    path('warehouse/department/<int:department_id>/element/<int:element_id>/', views.department_warehouse_element_detail, name='department_warehouse_element_detail'),
    path('warehouse/department/<int:department_id>/element/<int:element_id>/edit/', views.department_warehouse_element_edit, name='department_warehouse_element_edit'),
    path('warehouse/department/<int:department_id>/element/<int:element_id>/delete/', views.department_warehouse_element_delete, name='department_warehouse_element_delete'),
    
    # Category Management (Supervisor only)
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('categories/<int:category_id>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:category_id>/delete/', views.category_delete, name='category_delete'),
    
    # API endpoints
    path('api/branches/<int:branch_id>/departments/', views.get_departments_for_branch, name='get_departments_for_branch'),
    path('api/departments/without-team-lead/', views.get_departments_without_team_lead, name='get_departments_without_team_lead'),
    path('api/departments/all-employee/', views.get_all_employee_departments, name='get_all_employee_departments'),
    path('api/departments/<int:department_id>/categories/', views.get_department_categories, name='department_categories_api'),
    
    # API endpoints
    path('api/tickets/<int:ticket_id>/status/', views.update_ticket_status, name='update_ticket_status'),
    path('api/tickets/<int:ticket_id>/activity-logs/', views.get_ticket_activity_logs, name='get_ticket_activity_logs'),
    path('api/search/', views.search_tickets, name='search_tickets'),
    
    # Reply management
    path('replies/', views.view_all_replies, name='view_all_replies'),
    # Notifications
    path('notifications/', views.notifications_list, name='notifications'),
    path('notifications/category/<str:category>/ajax/', views.notifications_category_ajax, name='notifications_category_ajax'),
    path('notifications/<int:notification_id>/mark-read/', views.mark_notification_read, name='mark_notification_read'),
    path('notifications/category/<str:category>/mark-read/', views.mark_category_read, name='mark_category_read'),
    path('notifications/<int:notification_id>/delete/', views.delete_notification, name='delete_notification'),
    path('notifications/category/<str:category>/delete/', views.delete_category_notifications, name='delete_category_notifications'),
    path('notifications/delete-all/', views.delete_all_notifications, name='delete_all_notifications'),
    
    # Team Leader notifications
    path('team-leader-notifications/', views.team_leader_notifications_list, name='team_leader_notifications'),
    path('team-leader-notifications/<int:ticket_id>/approve/', views.team_leader_approve_access, name='team_leader_approve_access'),
    path('team-leader-notifications/<int:ticket_id>/reject/', views.team_leader_reject_access, name='team_leader_reject_access'),
    path('team-leader-notifications/<int:notification_id>/delete/', views.delete_team_leader_notification, name='delete_team_leader_notification'),
    path('team-leader-notifications/delete-all/', views.delete_all_team_leader_notifications, name='delete_all_team_leader_notifications'),
    
    # Statistics API endpoints
    path('api/statistics/overview/', views.statistics_overview_api, name='statistics_overview_api'),
    path('api/statistics/agent-performance/', views.agent_performance_api, name='agent_performance_api'),
    path('api/statistics/ticket-trends/', views.ticket_trends_api, name='ticket_trends_api'),
    
    # Inventory management (IT Manager only)
    path('inventory/', views.inventory_management, name='inventory_management'),
    path('inventory/create/', views.inventory_element_create, name='inventory_element_create'),
    path('inventory/<int:element_id>/', views.inventory_element_detail, name='inventory_element_detail'),
    path('inventory/<int:element_id>/edit/', views.inventory_element_edit, name='inventory_element_edit'),
    path('inventory/<int:element_id>/delete/', views.inventory_element_delete, name='inventory_element_delete'),
    path('inventory/<int:element_id>/specifications/create/', views.inventory_specification_create, name='inventory_specification_create'),
    path('inventory/<int:element_id>/specifications/<int:specification_id>/edit/', views.inventory_specification_edit, name='inventory_specification_edit'),
    path('inventory/<int:element_id>/specifications/<int:specification_id>/delete/', views.inventory_specification_delete, name='inventory_specification_delete'),
    # API endpoints for parent elements
    path('api/inventory/users/<int:user_id>/parent-elements/', views.get_parent_elements_for_user, name='get_parent_elements_for_user'),
    path('api/inventory/warehouse/<int:warehouse_id>/sub-elements/', views.get_warehouse_sub_elements, name='get_warehouse_sub_elements'),
    
    # Ticket Task management (IT Manager)
    path('ticket-tasks/', views.ticket_task_list, name='ticket_task_list'),
    path('ticket-tasks/create/', views.ticket_task_create, name='ticket_task_create'),
    path('ticket-tasks/<int:task_id>/', views.ticket_task_detail, name='ticket_task_detail'),
    path('ticket-tasks/<int:task_id>/edit/', views.ticket_task_edit, name='ticket_task_edit'),
    path('ticket-tasks/<int:task_id>/delete/', views.ticket_task_delete, name='ticket_task_delete'),
    path('ticket-tasks/<int:task_id>/update-status/', views.ticket_task_update_status, name='ticket_task_update_status'),
    path('ticket-tasks/<int:task_id>/reply/', views.ticket_task_reply, name='ticket_task_reply'),
    path('my-tasks/', views.my_ticket_tasks, name='my_ticket_tasks'),
    path('tasks/<int:task_id>/request-extension/', views.request_deadline_extension, name='request_deadline_extension'),
    path('tasks/<int:task_id>/extension-requests/', views.task_extension_requests, name='task_extension_requests'),
    path('extension-requests/', views.extension_requests_list, name='extension_requests_list'),
    path('extension-requests/<int:request_id>/<str:action>/', views.handle_extension_request, name='handle_extension_request'),
    # API endpoint for getting employees by department
    path('api/departments/<int:department_id>/employees/', views.get_employees_for_department, name='get_employees_for_department'),
    
    # Calendar API endpoints
    path('api/calendar/', views.calendar_api_view, name='calendar_api'),
    path('api/current-jalali-date/', views.get_current_jalali_date_api, name='current_jalali_date_api'),

] 