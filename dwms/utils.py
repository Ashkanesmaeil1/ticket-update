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

        # Must be a supervisor
        if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
            logger.warning(f'get_authorized_warehouse_for_user: User {user.id} is not a supervisor (role={user.role}, dept_role={user.department_role})')
            return None

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
        else:
            # User is not a supervisor of this department
            logger.warning(f'get_authorized_warehouse_for_user: User {user.id} is NOT authorized for department {department_id}')
            return None

        # Get or create warehouse
        from .models import DepartmentWarehouse
        try:
            warehouse, created = DepartmentWarehouse.objects.get_or_create(
                department=department,
                defaults={
                    'name': f"{department.name} انبار",
                    'created_by': user,
                }
            )
            if created:
                logger.info(f'get_authorized_warehouse_for_user: Created new warehouse {warehouse.id} for department {department_id}')
            else:
                logger.info(f'get_authorized_warehouse_for_user: Retrieved existing warehouse {warehouse.id} for department {department_id}')
            return warehouse
        except Exception as warehouse_error:
            # Log error but don't crash - return None so view can handle it
            logger.error(f"Error creating/getting warehouse for department {department_id}: {str(warehouse_error)}", exc_info=True)
            import traceback
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            return None
    except Exception as e:
        # Catch any unexpected errors in the function itself
        logger.error(f'get_authorized_warehouse_for_user: Unexpected error: {str(e)}', exc_info=True)
        import traceback
        logger.error(f'Full traceback:\n{traceback.format_exc()}')
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

