"""
Utility functions for DWMS access control and business logic
"""
from django.shortcuts import get_object_or_404
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from django.utils import timezone
from tickets.models import Department


def get_authorized_warehouse_for_user(department_id, user):
    """
    Check if user is authorized to access a department's warehouse.
    Returns DepartmentWarehouse if authorized, None otherwise.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        if not user or not user.is_authenticated:
            logger.warning(f'get_authorized_warehouse_for_user: User not authenticated or None')
            return None

        # EXCLUDE IT MANAGERS: They use the hierarchical IT Inventory system, not Department Warehouse
        if user.role == 'it_manager':
            logger.info(f'get_authorized_warehouse_for_user: User {user.id} is IT Manager - excluded from Department Warehouse access (uses IT Inventory system)')
            return None
        
        # ADMINISTRATIVE OVERRIDE: Staff and Superusers can access warehouses
        # Employees can access warehouses (supervisors OR delegated users)
        is_admin_user = False
        if (hasattr(user, 'is_staff') and user.is_staff) or (hasattr(user, 'is_superuser') and user.is_superuser):
            is_admin_user = True
            logger.info(f'get_authorized_warehouse_for_user: User {user.id} is Staff/Superuser - granting administrative access')
        
        if user.role != 'employee' and not is_admin_user:
            logger.warning(f'get_authorized_warehouse_for_user: User {user.id} is not an employee (role={user.role})')
            return None
        
        # Check if user is a supervisor (will check delegated access later if not)
        is_supervisor_role = user.department_role in ['senior', 'manager']

        # Validate department_id
        try:
            department_id = int(department_id)
        except (ValueError, TypeError):
            logger.error(f'get_authorized_warehouse_for_user: Invalid department_id: {department_id}')
            return None

        # Get department
        try:
            department = Department.objects.get(id=department_id, has_warehouse=True)
            logger.info(f'get_authorized_warehouse_for_user: Department {department_id} found: {department.name}')
        except Department.DoesNotExist:
            logger.warning(f'get_authorized_warehouse_for_user: Department {department_id} does not exist or has_warehouse=False')
            return None
        except Exception as dept_error:
            logger.error(f'get_authorized_warehouse_for_user: Error fetching department {department_id}: {str(dept_error)}', exc_info=True)
            return None

        # Check if user is supervisor of this department
        supervised_depts = []
        if hasattr(user, 'get_supervised_departments'):
            try:
                depts = user.get_supervised_departments()
                if depts:
                    supervised_depts = list(depts) if hasattr(depts, '__iter__') and not isinstance(depts, str) else [depts]
                logger.info(f'get_authorized_warehouse_for_user: User supervises {len(supervised_depts)} departments via M2M')
            except Exception as supervised_error:
                logger.warning(f'get_authorized_warehouse_for_user: Error getting supervised departments: {str(supervised_error)}')
                supervised_depts = []
        
        user_dept = getattr(user, 'department', None)
        logger.info(f'get_authorized_warehouse_for_user: User department: {user_dept.id if user_dept else None}')
        
        # Check if user is supervisor via own department
        is_authorized = False
        if department == user_dept:
            # User's own department, allow
            is_authorized = True
            logger.info(f'get_authorized_warehouse_for_user: User authorized via own department')
        # Check if user is supervisor via M2M
        elif department in supervised_depts:
            # User supervises this department via M2M, allow
            is_authorized = True
            logger.info(f'get_authorized_warehouse_for_user: User authorized via M2M supervision')
        # Check if user is supervisor via ForeignKey
        elif hasattr(department, 'supervisor') and department.supervisor == user:
            # User is supervisor via ForeignKey, allow
            is_authorized = True
            logger.info(f'get_authorized_warehouse_for_user: User authorized via ForeignKey supervision')
        
        # Get or create warehouse first
        from .models import DepartmentWarehouse, WarehouseAccess
        try:
            warehouse, created = DepartmentWarehouse.objects.get_or_create(
                department=department,
                defaults={
                    'name': f"{department.name} انبار",
                    'created_by': user if (is_authorized or is_admin_user) else None,
                }
            )
            if created:
                logger.info(f'get_authorized_warehouse_for_user: Created new warehouse {warehouse.id} for department {department_id}')
            else:
                logger.info(f'get_authorized_warehouse_for_user: Retrieved existing warehouse {warehouse.id} for department {department_id}')
        except Exception as warehouse_error:
            logger.error(f"Error creating/getting warehouse for department {department_id}: {str(warehouse_error)}", exc_info=True)
            return None
        
        # ADMINISTRATIVE OVERRIDE: Staff and Superusers have access to all warehouses
        if (hasattr(user, 'is_staff') and user.is_staff) or (hasattr(user, 'is_superuser') and user.is_superuser):
            logger.info(f'get_authorized_warehouse_for_user: User {user.id} is Staff/Superuser - granting access to warehouse {warehouse.id}')
            return warehouse
        
        # If user is supervisor, return warehouse
        if is_authorized:
            logger.info(f'get_authorized_warehouse_for_user: User {user.id} is supervisor - returning warehouse {warehouse.id}')
            return warehouse
        
        # Check for delegated access (even if user is not a supervisor)
        # This allows regular employees with delegated access to view reports
        try:
            access = WarehouseAccess.objects.filter(
                warehouse=warehouse,
                user=user,
                is_active=True
            ).first()
            
            if access:
                logger.info(f'get_authorized_warehouse_for_user: User {user.id} has delegated {access.access_level} access to warehouse {warehouse.id}')
                return warehouse
            else:
                # User is not supervisor and has no delegated access
                if is_supervisor_role:
                    logger.warning(f'get_authorized_warehouse_for_user: Supervisor user {user.id} has NO access to warehouse {warehouse.id} (not supervising this department)')
                else:
                    logger.warning(f'get_authorized_warehouse_for_user: Regular employee {user.id} has NO delegated access to warehouse {warehouse.id}')
                return None
        except Exception as access_error:
            logger.error(f'get_authorized_warehouse_for_user: Error checking delegated access: {str(access_error)}', exc_info=True)
            return None

    except Exception as e:
        # Catch any unexpected errors in the function itself
        logger.error(f'get_authorized_warehouse_for_user: Unexpected error: {str(e)}', exc_info=True)
        import traceback
        logger.error(f'Full traceback:\n{traceback.format_exc()}')
        return None


def verify_warehouse_access(user, department_id):
    """
    Diagnostic function to verify warehouse access records and permissions.
    Returns a dictionary with diagnostic information for debugging.
    
    Usage:
        diagnostic = verify_warehouse_access(request.user, department_id)
        logger.info(f'Access diagnostic: {diagnostic}')
    """
    import logging
    logger = logging.getLogger(__name__)
    
    result = {
        'user_id': user.id if user and user.is_authenticated else None,
        'department_id': department_id,
        'department_exists': False,
        'warehouse_exists': False,
        'has_access_record': False,
        'access_level': None,
        'is_supervisor': False,
        'is_authorized': False,
        'errors': []
    }
    
    try:
        if not user or not user.is_authenticated:
            result['errors'].append('User not authenticated')
            return result
        
        # Validate department_id
        try:
            department_id = int(department_id)
        except (ValueError, TypeError):
            result['errors'].append(f'Invalid department_id: {department_id}')
            return result
        
        # Check if department exists
        try:
            department = Department.objects.get(id=department_id, has_warehouse=True)
            result['department_exists'] = True
            result['department_name'] = department.name
        except Department.DoesNotExist:
            result['errors'].append(f'Department {department_id} does not exist or has_warehouse=False')
            return result
        except Exception as e:
            result['errors'].append(f'Error fetching department: {str(e)}')
            return result
        
        # Check if warehouse exists
        from .models import DepartmentWarehouse, WarehouseAccess
        try:
            warehouse = DepartmentWarehouse.objects.get(department=department)
            result['warehouse_exists'] = True
            result['warehouse_id'] = warehouse.id
            result['warehouse_name'] = warehouse.name
        except DepartmentWarehouse.DoesNotExist:
            result['errors'].append(f'Warehouse does not exist for department {department_id}')
            return result
        except Exception as e:
            result['errors'].append(f'Error fetching warehouse: {str(e)}')
            return result
        
        # Check if user is supervisor
        is_supervisor_result = _is_supervisor_direct(warehouse, user)
        result['is_supervisor'] = is_supervisor_result
        
        # Check for delegated access
        try:
            access = WarehouseAccess.objects.filter(
                warehouse=warehouse,
                user=user,
                is_active=True
            ).first()
            
            if access:
                result['has_access_record'] = True
                result['access_level'] = access.access_level
                result['access_granted_by'] = access.granted_by.id if access.granted_by else None
                result['access_granted_at'] = str(access.granted_at) if hasattr(access, 'granted_at') else None
            else:
                result['has_access_record'] = False
        except Exception as e:
            result['errors'].append(f'Error checking WarehouseAccess: {str(e)}')
        
        # Determine if user is authorized
        result['is_authorized'] = is_supervisor_result or result['has_access_record']
        
        logger.info(f'verify_warehouse_access diagnostic: {result}')
        return result
        
    except Exception as e:
        result['errors'].append(f'Unexpected error in verify_warehouse_access: {str(e)}')
        logger.error(f'verify_warehouse_access error: {str(e)}', exc_info=True)
        return result


def _is_supervisor_direct(warehouse, user):
    """
    NON-RECURSIVE supervisor check using direct database queries.
    This function avoids calling model methods that might cause recursion.
    Returns True if user is supervisor, False otherwise.
    """
    if not user or not user.is_authenticated:
        return False
    
    department = warehouse.department
    
    # Priority 1: Check ForeignKey supervisor (direct database query)
    try:
        if hasattr(department, 'supervisor_id') and department.supervisor_id == user.id:
            return True
    except (AttributeError, Exception):
        pass
    
    # Priority 2: Check M2M supervisors (direct database query)
    try:
        if hasattr(department, 'supervisors'):
            # Use direct query to avoid recursion
            from tickets.models import Department
            dept = Department.objects.filter(id=department.id).prefetch_related('supervisors').first()
            if dept and user.id in dept.supervisors.values_list('id', flat=True):
                return True
    except (AttributeError, Exception):
        pass
    
    # Priority 3: Check if user's own department matches (for department heads)
    try:
        if hasattr(user, 'department_id') and user.department_id == department.id:
            # Additional check: user must be a supervisor role
            if hasattr(user, 'department_role') and user.department_role in ['senior', 'manager']:
                return True
    except (AttributeError, Exception):
        pass
    
    return False


def get_warehouse_access_level(warehouse, user):
    """
    Get user's access level for a warehouse.
    CRITICAL: This function MUST prioritize supervisor ownership over delegation.
    CRITICAL: Uses non-recursive direct database queries to prevent infinite loops.
    Returns: 'supervisor', 'write', 'read', or None
    
    Logic Hierarchy:
    1. IF user is supervisor (owner) → 'supervisor' (FULL ACCESS)
    2. ELSE IF user has delegated 'write' access → 'write'
    3. ELSE IF user has delegated 'read' access → 'read'
    4. ELSE → None (no access)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not user or not user.is_authenticated:
        logger.debug(f'get_warehouse_access_level: User not authenticated or None')
        return None
    
    # PRIORITY 1: Check if supervisor (OWNER-FIRST CHECK)
    # Use non-recursive direct check to prevent infinite loops
    is_supervisor_result = _is_supervisor_direct(warehouse, user)
    logger.debug(f'get_warehouse_access_level: User {user.id} is_supervisor check: {is_supervisor_result}')
    
    if is_supervisor_result:
        logger.info(f'get_warehouse_access_level: User {user.id} is supervisor of warehouse {warehouse.id} - returning "supervisor"')
        return 'supervisor'
    
    # PRIORITY 2: Check delegated access (only if NOT supervisor)
    from .models import WarehouseAccess
    try:
        access = WarehouseAccess.objects.get(warehouse=warehouse, user=user, is_active=True)
        logger.info(f'get_warehouse_access_level: User {user.id} has delegated {access.access_level} access to warehouse {warehouse.id}')
        return access.access_level
    except WarehouseAccess.DoesNotExist:
        logger.debug(f'get_warehouse_access_level: User {user.id} has no delegated access to warehouse {warehouse.id}')
        return None
    except Exception as e:
        logger.error(f'get_warehouse_access_level: Error checking WarehouseAccess for user {user.id}, warehouse {warehouse.id}: {str(e)}', exc_info=True)
        return None


def require_warehouse_access(view_func):
    """
    Decorator to ensure user has access to warehouse.
    Expects department_id as first URL parameter after request.
    """
    def wrapper(request, department_id, *args, **kwargs):
        warehouse = get_authorized_warehouse_for_user(department_id, request.user)
        if not warehouse:
            messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
            from django.shortcuts import redirect
            return redirect('tickets:dashboard')
        return view_func(request, department_id, warehouse, *args, **kwargs)
    return wrapper


def get_warehouse_permissions(warehouse, user):
    """
    Get comprehensive permission flags for a user's warehouse access.
    Returns a dictionary with permission flags for template rendering.
    
    Returns:
        dict: {
            'access_level': 'supervisor' | 'write' | 'read' | None,
            'can_write': bool,      # True for supervisor or write
            'can_read': bool,        # True for any access level
            'is_supervisor': bool,   # True only for supervisor
            'is_read_only': bool,   # True only for read access
        }
    """
    access_level = get_warehouse_access_level(warehouse, user)
    
    return {
        'access_level': access_level,
        'can_write': access_level in ['supervisor', 'write'],
        'can_read': access_level is not None,
        'is_supervisor': access_level == 'supervisor',
        'is_read_only': access_level == 'read',
    }


def require_warehouse_write_access(view_func):
    """
    Decorator to ensure user has WRITE access to warehouse.
    Blocks READ-only users from write operations.
    
    This decorator validates write access before allowing the view to execute.
    It does NOT pass warehouse to the view - views should get it themselves.
    
    Usage:
        @require_warehouse_write_access
        def movement_create(request, department_id, ...):
            warehouse = get_authorized_warehouse_for_user(department_id, request.user)
            ...
    """
    def wrapper(request, department_id, *args, **kwargs):
        warehouse = get_authorized_warehouse_for_user(department_id, request.user)
        if not warehouse:
            messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
            from django.shortcuts import redirect
            return redirect('tickets:dashboard')
        
        access_level = get_warehouse_access_level(warehouse, request.user)
        if access_level not in ['supervisor', 'write']:
            messages.error(request, _('شما فقط اجازه مشاهده این انبار را دارید. برای انجام این عملیات به دسترسی ویرایش نیاز دارید.'))
            from django.shortcuts import redirect
            return redirect('dwms:dashboard', department_id=department_id)
        
        # View function gets warehouse itself, decorator just validates access
        return view_func(request, department_id, *args, **kwargs)
    return wrapper


def get_item_stock(item):
    """Calculate total stock for an item across all locations"""
    from django.db.models import Sum
    try:
        result = item.stock_batches.aggregate(total=Sum('quantity'))
        return float(result['total'] or 0)
    except Exception:
        return 0.0
        return 0


def get_item_stock_by_location(item):
    """Get stock breakdown by location"""
    from django.db.models import Sum
    from .models import StockBatch
    return (StockBatch.objects
            .filter(item=item)
            .values('location__id', 'location__name')
            .annotate(total=Sum('quantity'))
            .order_by('location__name'))


def update_low_stock_alerts(item):
    """
    Update low stock alerts for an item.
    Called after any stock movement.
    """
    from .models import LowStockAlert
    total_stock = get_item_stock(item)
    threshold = item.min_stock_threshold

    if threshold is None or threshold == 0:
        # No threshold set, resolve any open alerts
        LowStockAlert.objects.filter(
            item=item,
            warehouse=item.warehouse,
            status='OPEN'
        ).update(status='RESOLVED', resolved_at=timezone.now())
        return

    warehouse = item.warehouse
    alert = LowStockAlert.objects.filter(
        item=item,
        warehouse=warehouse,
        status='OPEN'
    ).first()

    if total_stock < threshold:
        if not alert:
            LowStockAlert.objects.create(
                item=item,
                warehouse=warehouse,
                current_stock=total_stock,
                threshold=threshold,
                status='OPEN',
            )
    else:
        if alert:
            alert.status = 'RESOLVED'
            alert.current_stock = total_stock
            alert.resolved_at = timezone.now()
            alert.save()


@transaction.atomic
def create_stock_movement(*, item, batch, location, warehouse,
                          movement_type, quantity, performed_by,
                          reason='OTHER', notes=''):
    """
    Central function to create stock movement and update batch quantity.
    Ensures data integrity with transactions.
    """
    from .models import StockMovement

    # Validate quantity
    if quantity <= 0:
        raise ValueError(_("مقدار باید بیشتر از صفر باشد"))

    # Update batch quantity
    if movement_type == 'IN':
        batch.quantity += quantity
    elif movement_type == 'OUT':
        if batch.quantity < quantity:
            raise ValueError(_("موجودی کافی نیست. موجودی فعلی: {}").format(batch.quantity))
        batch.quantity -= quantity
    elif movement_type == 'ADJUSTMENT':
        # For adjustment, set quantity directly
        batch.quantity = quantity
    else:
        raise ValueError(_("نوع حرکت نامعتبر است"))

    # Ensure quantity doesn't go negative
    if batch.quantity < 0:
        raise ValueError(_("موجودی نمی‌تواند منفی باشد"))

    batch.save()

    # Create movement record
    movement = StockMovement.objects.create(
        warehouse=warehouse,
        item=item,
        batch=batch,
        location=location,
        movement_type=movement_type,
        quantity=quantity,
        movement_date=timezone.now(),
        performed_by=performed_by,
        reason=reason,
        notes=notes,
    )

    # Update low stock alerts
    update_low_stock_alerts(item)

    return movement


def create_lend_record(*, warehouse, item, batch, location, quantity,
                       borrower, issued_by, due_date, notes=''):
    """
    Create a lend record and corresponding OUT movement.
    """
    from .models import LendRecord

    # Validate stock
    if batch.quantity < quantity:
        raise ValueError(_("موجودی کافی نیست"))

    # Create lend record
    lend_record = LendRecord.objects.create(
        warehouse=warehouse,
        item=item,
        batch=batch,
        quantity=quantity,
        borrower=borrower,
        issued_by=issued_by,
        due_date=due_date,
        notes=notes,
        status='OUT',
    )

    # Create OUT movement
    create_stock_movement(
        item=item,
        batch=batch,
        location=location,
        warehouse=warehouse,
        movement_type='OUT',
        quantity=quantity,
        performed_by=issued_by,
        reason='LEND',
        notes=f"امانت به {borrower.get_full_name()}. {notes}",
    )

    return lend_record


def return_lend_record(*, lend_record, received_by, location, notes=''):
    """
    Mark a lend record as returned and create IN movement.
    """
    from .models import LendRecord

    if lend_record.status == 'RETURNED':
        raise ValueError(_("این امانت قبلاً بازگردانده شده است"))

    # Update lend record
    lend_record.status = 'RETURNED'
    lend_record.return_date = timezone.now()
    lend_record.received_by = received_by
    if notes:
        lend_record.notes = f"{lend_record.notes or ''}\nبازگشت: {notes}"
    lend_record.save()

    # Create IN movement
    create_stock_movement(
        item=lend_record.item,
        batch=lend_record.batch,
        location=location,
        warehouse=lend_record.warehouse,
        movement_type='IN',
        quantity=lend_record.quantity,
        performed_by=received_by,
        reason='RETURN',
        notes=f"بازگشت از امانت {lend_record.borrower.get_full_name()}. {notes}",
    )

    return lend_record


def generate_item_code(item):
    """
    Generate a unique QR code for an item.
    Format: DWMS-{dept_id}-{item_id}-{random}
    """
    import secrets
    from .models import ItemCode

    # Check if code already exists
    existing = ItemCode.objects.filter(item=item).first()
    if existing:
        return existing

    # Generate unique code
    dept_id = item.warehouse.department.id
    random_part = secrets.token_hex(4).upper()
    code_value = f"DWMS-{dept_id}-{item.id}-{random_part}"

    # Ensure uniqueness
    while ItemCode.objects.filter(code_value=code_value).exists():
        random_part = secrets.token_hex(4).upper()
        code_value = f"DWMS-{dept_id}-{item.id}-{random_part}"

    code = ItemCode.objects.create(
        item=item,
        code_type='QR',
        code_value=code_value,
    )

    return code

