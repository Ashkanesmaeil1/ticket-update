from .models import Department


def warehouse_access(request):
    """Context processor to add warehouse access information to all templates"""
    # Safely check if user exists and is authenticated
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {'has_warehouse_access': False}
    
    user = request.user
    
    # Only check for supervisors
    if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
        return {'has_warehouse_access': False}
    
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
    
    return {'has_warehouse_access': False}

