from .models import Department


def warehouse_access(request):
    """
    Context processor to add warehouse access information to all templates.
    
    Returns True if user has ANY level of warehouse access:
    - Supervisor access (owns warehouse)
    - Write access (delegated)
    - Read access (delegated)
    - Staff/Superuser access (administrative override)
    
    NOTE: IT Managers are EXCLUDED from Department Warehouse access.
    IT Managers use the separate hierarchical IT Inventory system (مدیریت موجودی).
    """
    # Safely check if user exists and is authenticated
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {'has_warehouse_access': False}
    
    user = request.user
    
    # EXCLUDE IT MANAGERS: They use the hierarchical IT Inventory system, not Department Warehouse
    if user.role == 'it_manager':
        return {'has_warehouse_access': False}
    
    # Staff and Superusers have global warehouse access
    if hasattr(user, 'is_staff') and user.is_staff:
        try:
            from dwms.models import DepartmentWarehouse
            if DepartmentWarehouse.objects.filter(is_active=True).exists():
                return {'has_warehouse_access': True}
        except Exception:
            pass
    
    if hasattr(user, 'is_superuser') and user.is_superuser:
        try:
            from dwms.models import DepartmentWarehouse
            if DepartmentWarehouse.objects.filter(is_active=True).exists():
                return {'has_warehouse_access': True}
        except Exception:
            pass
    
    # Only employees can access warehouses (IT Managers excluded above)
    if user.role != 'employee':
        return {'has_warehouse_access': False}
    
    # Check if user is a supervisor with warehouse access
    is_supervisor = user.department_role in ['senior', 'manager']
    
    if is_supervisor:
        # Check if user's own department has warehouse
        if user.department and user.department.has_warehouse:
            return {'has_warehouse_access': True}
        
        # Check supervised departments (M2M)
        if hasattr(user, 'supervised_departments'):
            for dept in user.supervised_departments.all():
                if dept.has_warehouse:
                    return {'has_warehouse_access': True}
        
        # Check departments where user is supervisor via ForeignKey
        if hasattr(user, 'departments_as_supervisor'):
            for dept in user.departments_as_supervisor.all():
                if dept.has_warehouse:
                    return {'has_warehouse_access': True}
    
    # Check for delegated access (read or write) via WarehouseAccess table
    # This allows non-supervisor employees with delegated access to see the menu
    try:
        from dwms.models import WarehouseAccess
        delegated_accesses = WarehouseAccess.objects.filter(
            user=user,
            is_active=True
        ).exists()
        
        if delegated_accesses:
            return {'has_warehouse_access': True}
    except Exception:
        # If WarehouseAccess model doesn't exist or query fails, continue
        pass
    
    return {'has_warehouse_access': False}

