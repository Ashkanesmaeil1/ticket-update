from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.db.models import Sum, Q, Count
from django.http import JsonResponse, HttpResponseRedirect
from django.views.decorators.http import require_http_methods, require_POST
from django.core.paginator import Paginator
from django.utils import timezone
from django.urls import reverse
from datetime import timedelta
import json

from tickets.models import Department
from django.contrib.auth import get_user_model
from .models import (
    DepartmentWarehouse, StorageLocation, ItemCategory, Item,
    StockBatch, StockMovement, LendRecord, ItemCode, LowStockAlert
)

User = get_user_model()
from .forms import (
    StorageLocationForm, ItemCategoryForm, ItemForm,
    StockBatchForm, StockMovementForm, LendRecordForm
)
from .utils import (
    get_authorized_warehouse_for_user, require_warehouse_access,
    get_item_stock, create_stock_movement, create_lend_record,
    return_lend_record, generate_item_code
)


# ==================== Warehouse Selection ====================

@login_required
def warehouse_selection(request):
    """Entry point - show all warehouses user has access to"""
    user = request.user
    
    # Must be a supervisor
    if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
        messages.error(request, _('شما اجازه دسترسی به این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get all departments user supervises with warehouse enabled
    from tickets.models import Department
    supervised_depts = []
    
    # Get supervised departments via method if available
    if hasattr(user, 'get_supervised_departments'):
        try:
            depts = user.get_supervised_departments()
            if depts:
                supervised_depts = list(depts) if hasattr(depts, '__iter__') else [depts]
        except Exception as e:
            supervised_depts = []
    
    warehouses = []
    # Check own department
    if hasattr(user, 'department') and user.department:
        try:
            if user.department.has_warehouse:
                if user.department not in supervised_depts:
                    supervised_depts.append(user.department)
        except:
            pass
    
    # Get warehouses for supervised departments
    for dept in supervised_depts:
        if dept.has_warehouse:
            warehouse = get_authorized_warehouse_for_user(dept.id, user)
            if warehouse:
                warehouses.append({
                    'department': dept,
                    'warehouse': warehouse,
                })
    
    if not warehouses:
        messages.info(request, _('شما به هیچ انباری دسترسی ندارید.'))
        return redirect('tickets:dashboard')
    
    # If only one warehouse, redirect directly
    if len(warehouses) == 1:
        return redirect('dwms:dashboard', department_id=warehouses[0]['department'].id)
    
    context = {
        'warehouses': warehouses,
    }
    
    return render(request, 'dwms/warehouse_selection.html', context)


# ==================== Dashboard & Overview ====================

@login_required
def warehouse_dashboard(request, department_id):
    """Main dashboard for department warehouse"""
    try:
        warehouse = get_authorized_warehouse_for_user(department_id, request.user)
        if not warehouse:
            messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
            return redirect('tickets:dashboard')
    except Exception as e:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"Error in warehouse_dashboard: {str(e)}\n{traceback.format_exc()}")
        messages.error(request, _('خطا در دسترسی به انبار: {}').format(str(e)))
        return redirect('tickets:dashboard')

    # Get statistics
    try:
        total_items = Item.objects.filter(warehouse=warehouse, is_active=True).count()
    except Exception:
        total_items = 0
    total_stock_value = 0  # Can be calculated if price is added to items
    
    # Low stock items
    low_stock_items = []
    try:
        for item in Item.objects.filter(warehouse=warehouse, is_active=True):
            try:
                if item.is_low_stock():
                    low_stock_items.append({
                        'item': item,
                        'current_stock': get_item_stock(item),
                        'threshold': item.min_stock_threshold,
                    })
            except Exception as e:
                # Skip items with errors
                continue
    except Exception as e:
        # If there's an error, just set empty list
        low_stock_items = []
    low_stock_count = len(low_stock_items)
    
    # Recent movements
    try:
        recent_movements = list(StockMovement.objects.filter(
            warehouse=warehouse
        ).select_related('item', 'performed_by', 'location')[:10])
    except Exception:
        recent_movements = []
    
    # Open lends
    try:
        open_lends = list(LendRecord.objects.filter(
            warehouse=warehouse,
            status__in=['OUT', 'OVERDUE']
        ).select_related('item', 'borrower', 'issued_by')[:10])
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting open lends: {str(e)}")
        open_lends = []
    
    # Get top consumed items (last 30 days)
    try:
        thirty_days_ago = timezone.now() - timedelta(days=30)
        top_consumed = list(StockMovement.objects
                       .filter(warehouse=warehouse, movement_type='OUT',
                              movement_date__gte=thirty_days_ago)
                       .values('item__name', 'item__id')
                       .annotate(total=Sum('quantity'))
                       .order_by('-total')[:5])
    except Exception:
        top_consumed = []

    try:
        department = warehouse.department
    except Exception as e:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting department: {str(e)}\n{traceback.format_exc()}")
        messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
        return redirect('tickets:dashboard')
    
    context = {
        'warehouse': warehouse,
        'department': department,
        'total_items': total_items,
        'total_stock_value': total_stock_value,
        'low_stock_items': low_stock_items[:5],  # Top 5
        'low_stock_count': low_stock_count,
        'recent_movements': recent_movements or [],
        'open_lends': open_lends or [],
        'top_consumed': top_consumed or [],
    }
    
    try:
        return render(request, 'dwms/dashboard.html', context)
    except Exception as e:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"Error rendering template: {str(e)}\n{traceback.format_exc()}")
        messages.error(request, _('خطا در نمایش صفحه: {}').format(str(e)))
        return redirect('tickets:dashboard')


# ==================== Storage Locations ====================

@login_required
def location_list(request, department_id):
    """List all storage locations"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    locations = StorageLocation.objects.filter(warehouse=warehouse).order_by('name')
    
    # Add stock statistics for each location
    for location in locations:
        location.total_items = StockBatch.objects.filter(
            location=location
        ).aggregate(total=Sum('quantity'))['total'] or 0
        location.item_count = StockBatch.objects.filter(
            location=location
        ).values('item').distinct().count()

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'locations': locations,
    }
    
    return render(request, 'dwms/location_list.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def location_create(request, department_id):
    """Create a new storage location"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    if request.method == 'POST':
        form = StorageLocationForm(request.POST)
        if form.is_valid():
            location = form.save(commit=False)
            location.warehouse = warehouse
            location.save()
            messages.success(request, _('محل نگهداری با موفقیت ایجاد شد.'))
            return redirect('dwms:location_list', department_id=department_id)
    else:
        form = StorageLocationForm()

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'form': form,
        'action': _('ایجاد'),
    }
    
    return render(request, 'dwms/location_form.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def location_edit(request, department_id, location_id):
    """Edit a storage location"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    location = get_object_or_404(StorageLocation, id=location_id, warehouse=warehouse)

    if request.method == 'POST':
        form = StorageLocationForm(request.POST, instance=location)
        if form.is_valid():
            form.save()
            messages.success(request, _('محل نگهداری با موفقیت بروزرسانی شد.'))
            return redirect('dwms:location_list', department_id=department_id)
    else:
        form = StorageLocationForm(instance=location)

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'location': location,
        'form': form,
        'action': _('ویرایش'),
    }
    
    return render(request, 'dwms/location_form.html', context)


# ==================== Items Management ====================

@login_required
def item_list(request, department_id):
    """List all items"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    # Filters
    search_query = request.GET.get('search', '')
    category_filter = request.GET.get('category', '')
    low_stock_only = request.GET.get('low_stock', '') == 'on'
    
    items = Item.objects.filter(warehouse=warehouse, is_active=True)
    
    if search_query:
        items = items.filter(
            Q(name__icontains=search_query) |
            Q(sku__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    if category_filter:
        items = items.filter(category_id=category_filter)
    
    # Add stock information
    items_with_stock = []
    for item in items:
        total_stock = get_item_stock(item)
        is_low = item.is_low_stock()
        
        if low_stock_only and not is_low:
            continue
            
        items_with_stock.append({
            'item': item,
            'total_stock': total_stock,
            'is_low_stock': is_low,
        })
    
    # Get categories for filter
    categories = ItemCategory.objects.filter(warehouse=warehouse).order_by('name')
    
    # Pagination
    paginator = Paginator(items_with_stock, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'page_obj': page_obj,
        'categories': categories,
        'search_query': search_query,
        'category_filter': category_filter,
        'low_stock_only': low_stock_only,
    }
    
    return render(request, 'dwms/item_list.html', context)


@login_required
def item_detail(request, department_id, item_id):
    """View item details"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    # Safely get department
    try:
        department = warehouse.department
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Error accessing warehouse.department in item_detail: {str(e)}')
        messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
        return redirect('tickets:dashboard')

    item = get_object_or_404(Item, id=item_id, warehouse=warehouse)
    
    # Get stock by location
    from .utils import get_item_stock_by_location
    stock_by_location = get_item_stock_by_location(item)
    
    # Get all batches
    batches = StockBatch.objects.filter(item=item).select_related('location').order_by('-created_at')
    
    # Get recent movements
    recent_movements = StockMovement.objects.filter(
        item=item
    ).select_related('performed_by', 'location')[:20]
    
    # Get active lends
    active_lends = LendRecord.objects.filter(
        item=item,
        status='OUT'
    ).select_related('borrower')[:10]
    
    # Get or generate QR code
    qr_code = ItemCode.objects.filter(item=item).first()
    if not qr_code:
        qr_code = generate_item_code(item)
    
    total_stock = get_item_stock(item)
    is_low_stock = item.is_low_stock()

    context = {
        'warehouse': warehouse,
        'department': department,
        'item': item,
        'total_stock': total_stock,
        'is_low_stock': is_low_stock,
        'stock_by_location': stock_by_location,
        'batches': batches,
        'recent_movements': recent_movements,
        'active_lends': active_lends,
        'qr_code': qr_code,
    }
    
    return render(request, 'dwms/item_detail.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def item_create(request, department_id):
    """Create a new item"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    if request.method == 'POST':
        form = ItemForm(request.POST, warehouse=warehouse)
        if form.is_valid():
            item = form.save(commit=False)
            item.warehouse = warehouse
            item.save()
            # Generate QR code
            generate_item_code(item)
            messages.success(request, _('کالا با موفقیت ایجاد شد.'))
            return redirect('dwms:item_detail', department_id=department_id, item_id=item.id)
    else:
        form = ItemForm(warehouse=warehouse)

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'form': form,
        'action': _('ایجاد'),
    }
    
    return render(request, 'dwms/item_form.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def item_edit(request, department_id, item_id):
    """Edit an item"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    item = get_object_or_404(Item, id=item_id, warehouse=warehouse)

    if request.method == 'POST':
        form = ItemForm(request.POST, instance=item, warehouse=warehouse)
        if form.is_valid():
            form.save()
            # Update low stock alerts
            from .utils import update_low_stock_alerts
            update_low_stock_alerts(item)
            messages.success(request, _('کالا با موفقیت بروزرسانی شد.'))
            return redirect('dwms:item_detail', department_id=department_id, item_id=item.id)
    else:
        form = ItemForm(instance=item, warehouse=warehouse)

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'item': item,
        'form': form,
        'action': _('ویرایش'),
    }
    
    return render(request, 'dwms/item_form.html', context)


# ==================== Stock Movements ====================

@login_required
@require_http_methods(["GET", "POST"])
def movement_create(request, department_id, item_id=None):
    """Create a stock movement"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    item = None
    if item_id:
        item = get_object_or_404(Item, id=item_id, warehouse=warehouse)

    # Check if locations exist
    has_locations = StorageLocation.objects.filter(warehouse=warehouse, is_active=True).exists()

    if request.method == 'POST':
        form = StockMovementForm(request.POST, warehouse=warehouse, item=item)
        if form.is_valid():
            try:
                item = form.cleaned_data['item']
                location = form.cleaned_data['location']
                movement_type = form.cleaned_data['movement_type']
                quantity = form.cleaned_data['quantity']
                reason = form.cleaned_data.get('reason', 'OTHER')
                notes = form.cleaned_data.get('notes', '')
                
                # Get or create batch
                batch = form.cleaned_data.get('batch')
                if not batch:
                    batch, created = StockBatch.objects.get_or_create(
                        item=item,
                        location=location,
                        defaults={'quantity': 0}
                    )
                
                # Create movement
                create_stock_movement(
                    item=item,
                    batch=batch,
                    location=location,
                    warehouse=warehouse,
                    movement_type=movement_type,
                    quantity=quantity,
                    performed_by=request.user,
                    reason=reason,
                    notes=notes,
                )
                
                messages.success(request, _('حرکت موجودی با موفقیت ثبت شد.'))
                if item:
                    return redirect('dwms:item_detail', department_id=department_id, item_id=item.id)
                else:
                    return redirect('dwms:item_list', department_id=department_id)
            except ValueError as e:
                messages.error(request, str(e))
    else:
        form = StockMovementForm(warehouse=warehouse, item=item)

    try:
        department = warehouse.department
    except Exception:
        messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
        return redirect('tickets:dashboard')

    context = {
        'warehouse': warehouse,
        'department': department,
        'item': item,
        'form': form,
        'has_locations': has_locations,
    }
    
    return render(request, 'dwms/movement_form.html', context)


@login_required
def movement_history(request, department_id):
    """View movement history"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    # Filters
    item_filter = request.GET.get('item', '')
    movement_type_filter = request.GET.get('movement_type', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    movements = StockMovement.objects.filter(warehouse=warehouse).select_related(
        'item', 'performed_by', 'location', 'batch'
    ).order_by('-movement_date')
    
    if item_filter:
        movements = movements.filter(item_id=item_filter)
    
    if movement_type_filter:
        movements = movements.filter(movement_type=movement_type_filter)
    
    if date_from:
        movements = movements.filter(movement_date__gte=date_from)
    
    if date_to:
        movements = movements.filter(movement_date__lte=date_to)
    
    # Pagination
    paginator = Paginator(movements, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get items for filter
    items = Item.objects.filter(warehouse=warehouse, is_active=True).order_by('name')

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'page_obj': page_obj,
        'items': items,
        'item_filter': item_filter,
        'movement_type_filter': movement_type_filter,
        'date_from': date_from,
        'date_to': date_to,
    }
    
    return render(request, 'dwms/movement_history.html', context)


# ==================== Lending Management ====================

@login_required
def lend_list(request, department_id):
    """List all lend records"""
    import logging
    import traceback
    logger = logging.getLogger(__name__)
    
    # CRITICAL: Log entry point with full context
    logger.info(f'=== lend_list ENTRY === department_id={department_id}, user_id={request.user.id}, user_role={getattr(request.user, "role", None)}, dept_role={getattr(request.user, "department_role", None)}')
    logger.info(f'Request method: {request.method}')
    logger.info(f'Request path: {request.path}')
    logger.info(f'Request GET params: {dict(request.GET)}')
    
    # CRITICAL: In DEBUG mode, let exceptions propagate to see actual error
    from django.conf import settings
    DEBUG_MODE = settings.DEBUG
    
    try:
        # Step 1: Validate department_id
        # URL pattern uses <int:department_id> so it should already be an int
        # But let's be defensive and handle edge cases
        logger.info(f'Step 1: Validating department_id: {department_id} (type: {type(department_id)})')
        try:
            if department_id is None:
                raise ValueError('department_id is None')
            # Ensure it's an integer
            original_dept_id = department_id
            department_id = int(department_id)
            logger.info(f'Validated department_id: {department_id} (converted from {original_dept_id}, type: {type(department_id)})')
        except (ValueError, TypeError) as validation_error:
            logger.error(f'Invalid department_id: {department_id} (type: {type(department_id)}), error: {str(validation_error)}')
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            if DEBUG_MODE:
                raise  # In DEBUG, show the actual error
            messages.error(request, _('شناسه بخش نامعتبر است.'))
            return redirect('tickets:dashboard')
        
        # Step 2: Get warehouse with detailed logging
        logger.info(f'Step 2: Calling get_authorized_warehouse_for_user(department_id={department_id}, user={request.user.id})')
        try:
            warehouse = get_authorized_warehouse_for_user(department_id, request.user)
            if warehouse:
                logger.info(f'Warehouse retrieved: id={warehouse.id}, name={warehouse.name}')
            else:
                logger.warning(f'get_authorized_warehouse_for_user returned None for department_id={department_id}, user={request.user.id}')
                if DEBUG_MODE:
                    logger.error('DEBUG: Warehouse authorization failed - check logs above for details')
                    # In DEBUG, we might want to see why authorization failed, but still redirect
                messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
                # Use absolute path for redirect to avoid URL resolution issues
                try:
                    return HttpResponseRedirect('/')
                except Exception as redirect_error:
                    logger.error(f'Error in redirect: {str(redirect_error)}', exc_info=True)
                    if DEBUG_MODE:
                        raise
                    # Final fallback
                    return HttpResponseRedirect('/')
        except Exception as warehouse_error:
            logger.error(f'Exception in get_authorized_warehouse_for_user: {str(warehouse_error)}', exc_info=True)
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            if DEBUG_MODE:
                raise  # In DEBUG, show the actual error
            messages.error(request, _('خطا در بررسی دسترسی به انبار.'))
            # Use absolute path to avoid URL resolution issues
            try:
                return HttpResponseRedirect('/')
            except Exception as redirect_error:
                logger.error(f'Error in redirect: {str(redirect_error)}', exc_info=True)
                if DEBUG_MODE:
                    raise
                # Final fallback
                return HttpResponseRedirect('/')

        # Step 3: Get department with detailed logging
        logger.info(f'Step 3: Accessing warehouse.department for warehouse {warehouse.id}')
        try:
            department = warehouse.department
            if department:
                logger.info(f'Department retrieved: id={department.id}, name={department.name}')
            else:
                logger.error(f'warehouse.department is None for warehouse {warehouse.id}')
                if DEBUG_MODE:
                    raise AttributeError(f'warehouse.department is None for warehouse {warehouse.id}')
                messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
                return redirect('tickets:dashboard')
        except Exception as dept_error:
            logger.error(f'Exception accessing warehouse.department: {str(dept_error)}', exc_info=True)
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            if DEBUG_MODE:
                raise  # In DEBUG, show the actual error
            messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
            return redirect('tickets:dashboard')
        
        # Step 4: Get filters
        status_filter = request.GET.get('status', '')
        borrower_filter = request.GET.get('borrower', '')
        logger.info(f'Filters: status={status_filter}, borrower={borrower_filter}')
        
        # Step 5: Build QuerySet with error handling
        logger.info(f'Step 5: Building LendRecord QuerySet for warehouse {warehouse.id}...')
        try:
            # Validate warehouse exists before querying
            if not warehouse or not hasattr(warehouse, 'id'):
                raise ValueError(f'Invalid warehouse object: {warehouse}')
            
            lends = LendRecord.objects.filter(warehouse=warehouse).select_related(
                'item', 'borrower', 'issued_by', 'batch'
            ).order_by('-issue_date')
            
            # Use .exists() first to avoid expensive count() on large datasets
            record_exists = lends.exists()
            logger.info(f'Base QuerySet created, exists={record_exists}')
            if record_exists:
                count = lends.count()
                logger.info(f'Total records: {count}')
        except Exception as qs_error:
            logger.error(f'Error creating base QuerySet: {str(qs_error)}', exc_info=True)
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            if DEBUG_MODE:
                raise  # In DEBUG, show the actual error
            # Use empty queryset instead of crashing
            lends = LendRecord.objects.none()
        
        # Step 6: Apply filters
        try:
            if status_filter:
                # User explicitly selected a status filter
                lends = lends.filter(status=status_filter)
                logger.info(f'Applied status filter: {status_filter}, count={lends.count()}')
            else:
                # Default: show ALL lends (no filter) - let user filter if needed
                # This ensures the list is not empty by default
                logger.info(f'No status filter applied, showing all lends, count={lends.count()}')
            
            if borrower_filter:
                try:
                    borrower_id = int(borrower_filter)
                    lends = lends.filter(borrower_id=borrower_id)
                    logger.info(f'Applied borrower filter: {borrower_id}, count={lends.count()}')
                except (ValueError, TypeError):
                    logger.warning(f'Invalid borrower_filter: {borrower_filter}')
        except Exception as filter_error:
            logger.error(f'Error applying filters: {str(filter_error)}', exc_info=True)
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            # Continue with unfiltered queryset
        
        logger.info(f'Final QuerySet count: {lends.count()}')
        
        # Step 7: Pagination with error handling
        logger.info('Step 7: Starting pagination...')
        try:
            # Validate lends is a QuerySet before pagination
            if not hasattr(lends, 'exists'):
                logger.error(f'lends is not a QuerySet! Type: {type(lends)}')
                raise TypeError(f'lends is not a QuerySet, it is {type(lends)}')
            
            # Check total count before pagination for logging
            total_count = lends.count()
            logger.info(f'Total lends before pagination: {total_count}')
            
            paginator = Paginator(lends, 30)
            page_number = request.GET.get('page', 1)
            try:
                page_number = int(page_number)
                if page_number < 1:
                    page_number = 1
            except (ValueError, TypeError):
                logger.warning(f'Invalid page number: {request.GET.get("page")}, defaulting to 1')
                page_number = 1
            
            page_obj = paginator.get_page(page_number)
            logger.info(f'Pagination successful: page {page_obj.number} of {paginator.num_pages}, {len(page_obj)} items on page')
            
            # Empty list is normal, not an error - log it but don't show warning
            if total_count == 0:
                logger.info('No lends found - this is normal if no records exist yet')
        except Exception as pagination_error:
            logger.error(f'Error in pagination: {str(pagination_error)}', exc_info=True)
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            if DEBUG_MODE:
                raise  # In DEBUG, show the actual error
            # Create empty paginator instead of crashing
            empty_qs = LendRecord.objects.none()
            paginator = Paginator(empty_qs, 30)
            page_obj = paginator.get_page(1)
            # Don't show error message - empty list is normal, not an error
            logger.warning('Pagination failed, using empty paginator')
        
        # Step 8: Update overdue status (non-critical, don't fail on error)
        logger.info('Checking overdue status...')
        try:
            updated_count = 0
            # Only iterate if page_obj has items
            if page_obj and hasattr(page_obj, '__iter__'):
                for lend in page_obj:
                    try:
                        # Check if lend has is_overdue method and required attributes
                        if hasattr(lend, 'is_overdue') and hasattr(lend, 'status'):
                            if lend.is_overdue() and lend.status != 'RETURNED':
                                lend.status = 'OVERDUE'
                                lend.save(update_fields=['status'])
                                updated_count += 1
                    except AttributeError as attr_error:
                        logger.warning(f'Lend {getattr(lend, "id", "unknown")} missing required attribute: {str(attr_error)}')
                        continue
                    except Exception as lend_error:
                        logger.warning(f'Error updating overdue for lend {getattr(lend, "id", "unknown")}: {str(lend_error)}')
                        continue
            if updated_count > 0:
                logger.info(f'Updated {updated_count} lends to OVERDUE status')
        except Exception as overdue_error:
            logger.warning(f'Error in overdue check: {str(overdue_error)}', exc_info=True)
            logger.warning(f'Full traceback:\n{traceback.format_exc()}')
            # Continue execution, don't fail the whole view
        
        # Step 9: Get borrowers for filter (non-critical)
        logger.info('Fetching borrowers for filter...')
        try:
            # Use direct query through LendRecord to avoid relationship issues
            # Get distinct borrower IDs from LendRecord, then fetch User objects
            borrower_ids = LendRecord.objects.filter(
                warehouse=warehouse
            ).values_list('borrower_id', flat=True).distinct()
            
            if borrower_ids:
                borrowers = User.objects.filter(id__in=borrower_ids).order_by('first_name', 'last_name')
                logger.info(f'Found {borrowers.count()} borrowers')
            else:
                borrowers = User.objects.none()
                logger.info('No borrowers found')
        except Exception as borrower_error:
            logger.warning(f'Error fetching borrowers: {str(borrower_error)}', exc_info=True)
            logger.warning(f'Full traceback:\n{traceback.format_exc()}')
            # Use empty queryset as fallback
            borrowers = User.objects.none()

        # Step 10: Build context
        context = {
            'warehouse': warehouse,
            'department': department,
            'page_obj': page_obj,
            'borrowers': borrowers,
            'status_filter': status_filter,
            'borrower_filter': borrower_filter,
        }
        
        # Step 11: Validate context
        if not department:
            logger.error('CRITICAL: department is None in context!')
            messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
            return redirect('tickets:dashboard')
        
        if not warehouse:
            logger.error('CRITICAL: warehouse is None in context!')
            messages.error(request, _('خطا در بارگذاری اطلاعات انبار.'))
            return redirect('tickets:dashboard')
        
        # Step 12: Render template
        logger.info(f'Rendering template with context: warehouse={warehouse.id}, department={department.id}, page_obj.count={page_obj.paginator.count}')
        try:
            # Pre-validate all lends in page_obj to catch any data issues before template render
            logger.info('Pre-validating lend records for template safety...')
            for lend in page_obj:
                try:
                    # Check critical attributes that template will access
                    if not hasattr(lend, 'item') or lend.item is None:
                        logger.warning(f'Lend {lend.id} has no item - template will handle with fallback')
                    if not hasattr(lend, 'borrower') or lend.borrower is None:
                        logger.warning(f'Lend {lend.id} has no borrower - template will handle with fallback')
                    if not hasattr(lend, 'warehouse') or lend.warehouse is None:
                        logger.warning(f'Lend {lend.id} has no warehouse - template will handle with fallback')
                    if hasattr(lend, 'warehouse') and lend.warehouse:
                        if not hasattr(lend.warehouse, 'department') or lend.warehouse.department is None:
                            logger.warning(f'Lend {lend.id} warehouse has no department - template will handle with fallback')
                    # Test is_overdue() method safely
                    if hasattr(lend, 'is_overdue'):
                        try:
                            _ = lend.is_overdue()
                        except Exception as overdue_test_error:
                            logger.warning(f'Lend {lend.id} is_overdue() method failed: {str(overdue_test_error)}')
                except Exception as validation_error:
                    logger.warning(f'Error validating lend {getattr(lend, "id", "unknown")}: {str(validation_error)}')
                    continue
            
            response = render(request, 'dwms/lend_list.html', context)
            logger.info('=== lend_list SUCCESS === Template rendered successfully')
            return response
        except Exception as render_error:
            logger.error(f'CRITICAL: Error rendering lend_list template: {str(render_error)}', exc_info=True)
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            logger.error(f'Context keys: {list(context.keys())}')
            logger.error(f'Context values: warehouse={context.get("warehouse")}, department={context.get("department")}')
            
            # Check if department or warehouse is None in context
            if not context.get('department'):
                logger.error('CRITICAL: department is None in context during template render!')
            if not context.get('warehouse'):
                logger.error('CRITICAL: warehouse is None in context during template render!')
            
            # In DEBUG mode, re-raise to see the actual error
            from django.conf import settings
            if settings.DEBUG:
                logger.error('DEBUG mode: Re-raising template render error')
                raise
            
            # In production, let outer try-except handle it
            raise
            
    except Exception as e:
        # CRITICAL: Log full error details with unique error ID
        import uuid
        error_id = str(uuid.uuid4())[:8].upper()
        error_traceback = traceback.format_exc()
        
        logger.error(f'=== lend_list CRITICAL ERROR [ID: {error_id}] ===')
        logger.error(f'Error type: {type(e).__name__}')
        logger.error(f'Error message: {str(e)}')
        logger.error(f'Full traceback:\n{error_traceback}')
        logger.error(f'Request path: {request.path}')
        logger.error(f'Request method: {request.method}')
        logger.error(f'Department ID: {department_id} (type: {type(department_id)})')
        logger.error(f'User: {request.user.id if request.user.is_authenticated else "Anonymous"}')
        logger.error(f'User authenticated: {request.user.is_authenticated}')
        if request.user.is_authenticated:
            logger.error(f'User role: {getattr(request.user, "role", None)}')
            logger.error(f'User department_role: {getattr(request.user, "department_role", None)}')
        
        # CRITICAL: Always expose the actual error in development
        # In production, we'll still log it but show a user-friendly message
        from django.conf import settings
        
        # Show error to user with error ID for tracking
        error_message = _('خطا در نمایش لیست امانت‌ها. لطفاً با مدیر سیستم تماس بگیرید.')
        error_message += f' (کد خطا: {error_id})'
        messages.error(request, error_message)
        
        # In DEBUG mode, re-raise to see the actual error page
        if settings.DEBUG:
            logger.error(f'DEBUG mode: Re-raising exception to see actual error')
            logger.error(f'Error ID: {error_id}')
            logger.error(f'Full error details logged above')
            raise
        
        # In production, try to redirect to a safe location
        # First, try to redirect back to warehouse dashboard if we have department_id
        try:
            if department_id:
                try:
                    department_id = int(department_id)
                    redirect_path = f'/dwms/{department_id}/'
                    logger.info(f'Redirecting to warehouse dashboard: {redirect_path}')
                    return HttpResponseRedirect(redirect_path)
                except (ValueError, TypeError):
                    logger.error(f'Invalid department_id for redirect: {department_id}')
        except Exception as redirect_error:
            logger.error(f'Error in redirect to warehouse dashboard: {str(redirect_error)}', exc_info=True)
        
        # Final fallback: redirect to main dashboard
        logger.warning(f'Falling back to main dashboard redirect')
        return redirect('tickets:dashboard')


@login_required
@require_http_methods(["GET", "POST"])
def lend_create(request, department_id, item_id=None):
    """Create a lend record"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        from django.db import transaction
        from django.core.exceptions import ValidationError
        
        logger.info(f'lend_create called: department_id={department_id}, item_id={item_id}, method={request.method}')
        
        warehouse = get_authorized_warehouse_for_user(department_id, request.user)
        if not warehouse:
            logger.warning(f'User {request.user.id} not authorized for warehouse {department_id}')
            messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
            return redirect('tickets:dashboard')

        # Safely get department
        try:
            department = warehouse.department
            if not department:
                logger.error(f'warehouse.department is None for warehouse {warehouse.id}')
                messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
                return redirect('tickets:dashboard')
        except Exception as e:
            logger.error(f'Error accessing warehouse.department: {str(e)}', exc_info=True)
            messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
            return redirect('tickets:dashboard')

        item = None
        if item_id:
            try:
                item = get_object_or_404(Item, id=item_id, warehouse=warehouse)
            except Exception as e:
                logger.error(f'Error fetching item {item_id}: {str(e)}', exc_info=True)
                messages.error(request, _('کالای مورد نظر یافت نشد.'))
                return redirect('dwms:item_list', department_id=department_id)

        if request.method == 'POST':
            form = LendRecordForm(request.POST, warehouse=warehouse, item=item)
            
            # Debug: Log form data and validation status
            logger.info(f'Form POST data: {request.POST}')
            logger.info(f'Form is_valid: {form.is_valid()}')
            if not form.is_valid():
                logger.warning(f'Form validation errors: {form.errors}')
                logger.warning(f'Form non_field_errors: {form.non_field_errors()}')
            
            if form.is_valid():
                try:
                    item = form.cleaned_data['item']
                    batch = form.cleaned_data.get('batch')
                    quantity = form.cleaned_data['quantity']
                    borrower = form.cleaned_data['borrower']
                    # due_date is already converted to Gregorian date in form.clean_due_date()
                    # The form.save() method will handle setting the converted date
                    notes = form.cleaned_data.get('notes', '')
                    
                    # Debug logging
                    logger.info(f'Creating lend record: item={item}, batch={batch}, quantity={quantity}, borrower={borrower}')
                    
                    # Get or create batch if not provided
                    if not batch:
                        # Get first available batch with sufficient quantity
                        batch = StockBatch.objects.filter(
                            item=item,
                            quantity__gte=quantity
                        ).select_related('location').first()
                        if not batch:
                            messages.error(request, _('موجودی کافی برای این کالا وجود ندارد.'))
                            context = {
                                'warehouse': warehouse,
                                'department': department,
                                'item': item,
                                'form': form,
                            }
                            return render(request, 'dwms/lend_form.html', context)
                    
                    # Validate batch has location
                    if not batch.location:
                        messages.error(request, _('بچ انتخاب شده محل نگهداری ندارد.'))
                        context = {
                            'warehouse': warehouse,
                            'department': department,
                            'item': item,
                            'form': form,
                        }
                        return render(request, 'dwms/lend_form.html', context)
                    
                    # Get location from batch
                    location = batch.location
                    
                    # Use transaction to ensure atomicity
                    try:
                        with transaction.atomic():
                            # Save form to get instance with converted due_date
                            logger.info('Starting transaction for lend record creation')
                            lend_record = form.save(commit=False)
                            logger.info(f'Form saved (commit=False), lend_record={lend_record}')
                            
                            lend_record.warehouse = warehouse
                            lend_record.item = item
                            lend_record.batch = batch
                            # Note: LendRecord model doesn't have a location field
                            # Location is accessed via batch.location when needed
                            lend_record.quantity = quantity
                            lend_record.borrower = borrower
                            lend_record.issued_by = request.user
                            lend_record.notes = notes
                            lend_record.status = 'OUT'
                            
                            logger.info('Saving lend_record to database...')
                            # Check if due_date is set before saving
                            if not hasattr(lend_record, 'due_date') or not lend_record.due_date:
                                logger.error('lend_record.due_date is not set!')
                                raise ValueError('تاریخ موعد بازگشت تنظیم نشده است.')
                            lend_record.save()
                            logger.info(f'Lend record saved successfully, ID={lend_record.id}')
                            # Verify the save was successful
                            if not lend_record.id:
                                logger.error('lend_record.id is None after save!')
                                raise ValueError('خطا در ذخیره‌سازی رکورد امانت.')
                            
                            # Create stock movement via utility function (this also updates batch quantity)
                            from .utils import create_stock_movement
                            logger.info('Creating stock movement...')
                            create_stock_movement(
                                item=item,
                                batch=batch,
                                location=location,
                                warehouse=warehouse,
                                movement_type='OUT',
                                quantity=quantity,
                                performed_by=request.user,
                                reason='LEND',
                                notes=f"امانت به {borrower.get_full_name()}. {notes}",
                            )
                            logger.info('Stock movement created successfully')
                    except Exception as e:
                        logger.error(f'Error in transaction block: {str(e)}', exc_info=True)
                        raise
                    
                    # Ensure transaction is committed before redirect
                    # Transaction is already committed when exiting the 'with' block
                    logger.info('Transaction completed successfully, preparing redirect...')
                    
                    # Add success message BEFORE redirect
                    messages.success(request, _('امانت با موفقیت ثبت شد.'))
                    logger.info('Success message added')
                    
                    # CRITICAL FIX: Use absolute URL path - most reliable redirect method
                    # This avoids any URL resolution or namespace issues
                    redirect_path = f'/dwms/{department_id}/lends/'
                    logger.info(f'Transaction successful. Redirecting to absolute path: {redirect_path}')
                    logger.info(f'Department ID: {department_id}, Warehouse ID: {warehouse.id}')
                    
                    # Double-check the path is valid
                    if not department_id or not isinstance(department_id, int):
                        logger.error(f'Invalid department_id: {department_id}, type: {type(department_id)}')
                        raise ValueError(f'Invalid department_id: {department_id}')
                    
                    return HttpResponseRedirect(redirect_path)
                except ValueError as e:
                    logger.error(f'ValueError in lend_create: {str(e)}', exc_info=True)
                    messages.error(request, str(e))
                    # Re-render form with errors
                    context = {
                        'warehouse': warehouse,
                        'department': department,
                        'item': item,
                        'form': form,
                    }
                    return render(request, 'dwms/lend_form.html', context)
                except ValidationError as e:
                    logger.error(f'ValidationError in lend_create: {str(e)}', exc_info=True)
                    messages.error(request, _('خطا در اعتبارسنجی داده‌ها: {}').format(str(e)))
                    context = {
                        'warehouse': warehouse,
                        'department': department,
                        'item': item,
                        'form': form,
                    }
                    return render(request, 'dwms/lend_form.html', context)
                except Exception as e:
                    logger.error(f'Unexpected error creating lend record: {str(e)}', exc_info=True)
                    messages.error(request, _('خطا در ثبت امانت: {}').format(str(e)))
                    context = {
                        'warehouse': warehouse,
                        'department': department,
                        'item': item,
                        'form': form,
                    }
                    return render(request, 'dwms/lend_form.html', context)
            else:
                # Form is invalid, show errors
                logger.warning(f'Form is invalid. Errors: {form.errors}')
                # Form errors will be displayed in template - re-render with errors
                context = {
                    'warehouse': warehouse,
                    'department': department,
                    'item': item,
                    'form': form,
                }
                return render(request, 'dwms/lend_form.html', context)
        else:
            # GET request - show form
            try:
                form = LendRecordForm(warehouse=warehouse, item=item)
                logger.info('LendRecordForm created successfully for GET request')
            except Exception as e:
                logger.error(f'Error creating LendRecordForm: {str(e)}', exc_info=True)
                messages.error(request, _('خطا در بارگذاری فرم.'))
                return redirect('dwms:lend_list', department_id=department_id)

            context = {
                'warehouse': warehouse,
                'department': department,
                'item': item,
                'form': form,
            }
            
            try:
                logger.info('Rendering lend_form template...')
                return render(request, 'dwms/lend_form.html', context)
            except Exception as e:
                import traceback
                logger.error(f'Error rendering lend_form template: {str(e)}', exc_info=True)
                logger.error(f'Full traceback:\n{traceback.format_exc()}')
                messages.error(request, _('خطا در نمایش فرم.'))
                # Use absolute path for redirect
                return HttpResponseRedirect(f'/dwms/{department_id}/lends/')
    
    except Exception as e:
        import traceback
        import uuid
        error_id = str(uuid.uuid4())[:8].upper()
        error_traceback = traceback.format_exc()
        logger.error(f'=== lend_create CRITICAL ERROR [ID: {error_id}] ===')
        logger.error(f'Error type: {type(e).__name__}')
        logger.error(f'Error message: {str(e)}')
        logger.error(f'Full traceback:\n{error_traceback}')
        logger.error(f'Request path: {request.path}')
        logger.error(f'Request method: {request.method}')
        logger.error(f'Department ID: {department_id}')
        logger.error(f'User: {request.user.id if request.user.is_authenticated else "Anonymous"}')
        
        # Show error to user with error ID for tracking
        error_message = _('خطا در ثبت امانت. لطفاً دوباره تلاش کنید.')
        error_message += f' (کد خطا: {error_id})'
        messages.error(request, error_message)
        
        # Use absolute path for redirect - most reliable
        try:
            # Validate department_id before using it in URL
            if department_id:
                try:
                    department_id = int(department_id)
                    redirect_path = f'/dwms/{department_id}/lends/'
                    logger.info(f'Redirecting to: {redirect_path}')
                    return HttpResponseRedirect(redirect_path)
                except (ValueError, TypeError):
                    logger.error(f'Invalid department_id for redirect: {department_id}')
                    return redirect('tickets:dashboard')
            else:
                logger.warning('department_id is None, redirecting to dashboard')
                return redirect('tickets:dashboard')
        except Exception as redirect_error:
            logger.error(f'Error in redirect fallback: {str(redirect_error)}', exc_info=True)
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            return redirect('tickets:dashboard')


@login_required
@require_http_methods(["GET", "POST"])
def lend_return(request, department_id, lend_id):
    """Return a lent item"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    lend_record = get_object_or_404(LendRecord, id=lend_id, warehouse=warehouse)

    if request.method == 'POST':
        location_id = request.POST.get('location')
        notes = request.POST.get('notes', '')
        
        if not location_id:
            messages.error(request, _('لطفاً محل بازگشت را انتخاب کنید.'))
        else:
            try:
                location = get_object_or_404(StorageLocation, id=location_id, warehouse=warehouse)
                return_lend_record(
                    lend_record=lend_record,
                    received_by=request.user,
                    location=location,
                    notes=notes,
                )
                messages.success(request, _('بازگشت امانت با موفقیت ثبت شد.'))
                return redirect('dwms:lend_list', department_id=department_id)
            except ValueError as e:
                messages.error(request, str(e))
    
    # Get available locations
    locations = StorageLocation.objects.filter(warehouse=warehouse, is_active=True).order_by('name')

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'lend_record': lend_record,
        'locations': locations,
    }
    
    return render(request, 'dwms/lend_return.html', context)


# ==================== QR Code Scanning ====================

@login_required
def scan_interface(request, department_id):
    """Mobile scanning interface"""
    import logging
    import traceback
    from django.conf import settings
    logger = logging.getLogger(__name__)
    DEBUG_MODE = settings.DEBUG
    
    try:
        # Step 1: Validate department_id
        logger.info(f'Step 1: Validating department_id={department_id}')
        try:
            department_id = int(department_id)
        except (ValueError, TypeError) as e:
            logger.error(f'Invalid department_id: {department_id} - {str(e)}')
            if DEBUG_MODE:
                raise
            messages.error(request, _('شناسه بخش نامعتبر است.'))
            return HttpResponseRedirect('/')
        
        # Step 2: Get warehouse with authorization
        logger.info(f'Step 2: Getting authorized warehouse for department_id={department_id}, user={request.user.id}')
        try:
            warehouse = get_authorized_warehouse_for_user(department_id, request.user)
            if not warehouse:
                logger.warning(f'User {request.user.id} not authorized for department {department_id}')
                messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
                return HttpResponseRedirect('/')
            logger.info(f'Warehouse retrieved: id={warehouse.id}, name={warehouse.name}')
        except Exception as warehouse_error:
            logger.error(f'Exception in get_authorized_warehouse_for_user: {str(warehouse_error)}', exc_info=True)
            if DEBUG_MODE:
                raise
            messages.error(request, _('خطا در بررسی دسترسی به انبار.'))
            return HttpResponseRedirect('/')

        # Step 3: Safely get department
        logger.info(f'Step 3: Getting department for warehouse {warehouse.id}')
        try:
            department = warehouse.department
            if not department:
                logger.error(f'warehouse.department is None for warehouse {warehouse.id}')
                if DEBUG_MODE:
                    raise AttributeError(f'warehouse.department is None for warehouse {warehouse.id}')
                messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
                return HttpResponseRedirect('/')
            logger.info(f'Department retrieved: id={department.id}, name={department.name}')
        except Exception as dept_error:
            logger.error(f'Error accessing warehouse.department: {str(dept_error)}', exc_info=True)
            if DEBUG_MODE:
                raise
            messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
            return HttpResponseRedirect('/')

        # Step 4: Build context
        logger.info('Step 4: Building context')
        context = {
            'warehouse': warehouse,
            'department': department,
            'department_id': department_id,  # Add for template fallback
        }
        
        # Step 5: Render template
        logger.info('Step 5: Rendering scan template')
        try:
            return render(request, 'dwms/scan.html', context)
        except Exception as render_error:
            logger.error(f'Error rendering scan template: {str(render_error)}', exc_info=True)
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            if DEBUG_MODE:
                raise
            messages.error(request, _('خطا در بارگذاری صفحه اسکن.'))
            # Try to redirect back to warehouse dashboard
            try:
                return HttpResponseRedirect(f'/dwms/{department_id}/')
            except:
                return HttpResponseRedirect('/')
                
    except Exception as e:
        import uuid
        error_id = str(uuid.uuid4())[:8].upper()
        error_traceback = traceback.format_exc()
        logger.error(f'=== scan_interface CRITICAL ERROR [ID: {error_id}] ===')
        logger.error(f'Error type: {type(e).__name__}')
        logger.error(f'Error message: {str(e)}')
        logger.error(f'Full traceback:\n{error_traceback}')
        logger.error(f'Request path: {request.path}')
        logger.error(f'Request method: {request.method}')
        logger.error(f'Department ID: {department_id}')
        logger.error(f'User: {request.user.id if request.user.is_authenticated else "Anonymous"}')
        
        if DEBUG_MODE:
            raise
        
        messages.error(request, _('خطا در بارگذاری صفحه اسکن. لطفاً با مدیر سیستم تماس بگیرید.'))
        return HttpResponseRedirect('/')


@login_required
@require_POST
def scan_api(request, department_id):
    """API endpoint for QR code scanning"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        return JsonResponse({'error': _('دسترسی رد شد')}, status=403)

    try:
        data = json.loads(request.body)
        code_value = data.get('code')
        action = data.get('action')  # IN, OUT, LEND, RETURN
        
        if not code_value:
            return JsonResponse({'error': _('کد یافت نشد')}, status=400)
        
        # Find item by code - try ItemCode first, then Item.code field
        item = None
        code_value = code_value.strip()  # Trim whitespace
        
        try:
            # First, try to find by ItemCode
            try:
                item_code = ItemCode.objects.get(code_value=code_value)
                item = item_code.item
            except ItemCode.DoesNotExist:
                # Fallback: try to find by Item.code field
                try:
                    from .models import Item
                    item = Item.objects.get(code=code_value, warehouse=warehouse, is_active=True)
                except Item.DoesNotExist:
                    # Try case-insensitive search
                    item = Item.objects.filter(
                        code__iexact=code_value,
                        warehouse=warehouse,
                        is_active=True
                    ).first()
            
            if not item:
                return JsonResponse({'success': False, 'error': _('کد یافت نشد')}, status=404)
            
            # Verify item belongs to this warehouse
            if item.warehouse != warehouse:
                return JsonResponse({'success': False, 'error': _('این کالا به این انبار تعلق ندارد')}, status=403)
            
            # Get stock information
            total_stock = get_item_stock(item)
            batches = StockBatch.objects.filter(item=item).select_related('location')
            
            return JsonResponse({
                'success': True,
                'item': {
                    'id': item.id,
                    'name': item.name,
                    'unit': item.unit,
                    'total_stock': float(total_stock),
                    'is_low_stock': item.is_low_stock(),
                },
                'batches': [
                    {
                        'id': batch.id,
                        'location_id': batch.location.id,
                        'location_name': batch.location.name,
                        'quantity': float(batch.quantity),
                        'batch_code': batch.batch_code or '',
                    }
                    for batch in batches
                ],
                'action': action,
            })
        except Exception as lookup_error:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Error looking up item by code {code_value}: {str(lookup_error)}', exc_info=True)
            return JsonResponse({'success': False, 'error': _('خطا در جستجوی کالا')}, status=500)
    except json.JSONDecodeError:
        return JsonResponse({'error': _('داده نامعتبر')}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ==================== Reports ====================

@login_required
def reports_daily(request, department_id):
    """Daily report with Jalali calendar"""
    import logging
    import traceback
    from django.conf import settings
    logger = logging.getLogger(__name__)
    DEBUG_MODE = settings.DEBUG
    
    try:
        # Step 1: Validate department_id
        logger.info(f'Step 1: Validating department_id={department_id}')
        try:
            department_id = int(department_id)
        except (ValueError, TypeError) as e:
            logger.error(f'Invalid department_id: {department_id} - {str(e)}')
            if DEBUG_MODE:
                raise
            messages.error(request, _('شناسه بخش نامعتبر است.'))
            return HttpResponseRedirect('/')
        
        # Step 2: Get warehouse with authorization
        logger.info(f'Step 2: Getting authorized warehouse for department_id={department_id}, user={request.user.id}')
        try:
            warehouse = get_authorized_warehouse_for_user(department_id, request.user)
            if not warehouse:
                logger.warning(f'User {request.user.id} not authorized for department {department_id}')
                messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
                return HttpResponseRedirect('/')
            logger.info(f'Warehouse retrieved: id={warehouse.id}, name={warehouse.name}')
        except Exception as warehouse_error:
            logger.error(f'Exception in get_authorized_warehouse_for_user: {str(warehouse_error)}', exc_info=True)
            if DEBUG_MODE:
                raise
            messages.error(request, _('خطا در بررسی دسترسی به انبار.'))
            return HttpResponseRedirect('/')

        # Step 3: Safely get department
        logger.info(f'Step 3: Getting department for warehouse {warehouse.id}')
        try:
            department = warehouse.department
            if not department:
                logger.error(f'warehouse.department is None for warehouse {warehouse.id}')
                if DEBUG_MODE:
                    raise AttributeError(f'warehouse.department is None for warehouse {warehouse.id}')
                messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
                return HttpResponseRedirect('/')
            logger.info(f'Department retrieved: id={department.id}, name={department.name}')
        except Exception as dept_error:
            logger.error(f'Error accessing warehouse.department: {str(dept_error)}', exc_info=True)
            if DEBUG_MODE:
                raise
            messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
            return HttpResponseRedirect('/')

        # Get date from request (Jalali format expected)
        from tickets.calendar_services.jalali_calendar import JalaliCalendarService
        
        # Default to today
        today = timezone.now().date()
        today_jalali = JalaliCalendarService.gregorian_to_jalali(timezone.now())
        default_jalali_date = f"{today_jalali['year']}-{today_jalali['month']:02d}-{today_jalali['day']:02d}"
        jalali_date = request.GET.get('date', default_jalali_date)
        
        # Convert Jalali to Gregorian
        try:
            year, month, day = map(int, jalali_date.split('-'))
            gregorian_date = JalaliCalendarService.jalali_to_gregorian(year, month, day).date()
        except Exception as e:
            logger.warning(f'Error parsing Jalali date {jalali_date}: {str(e)}')
            gregorian_date = today
        
        # Get movements for this date - with error handling
        try:
            movements = StockMovement.objects.filter(
                warehouse=warehouse,
                movement_date__date=gregorian_date
            ).select_related('item', 'performed_by', 'location')
            logger.info(f'Found {movements.count()} movements for date {gregorian_date}')
        except Exception as e:
            logger.error(f'Error fetching movements: {str(e)}', exc_info=True)
            movements = StockMovement.objects.none()
        
        # Aggregate by item - with error handling
        try:
            from django.db.models import Sum
            item_summary = list(movements.values('item__name', 'item__id', 'movement_type')
                           .annotate(total=Sum('quantity'))
                           .order_by('item__name'))
            logger.info(f'Item summary created with {len(item_summary)} items')
        except Exception as e:
            logger.error(f'Error creating item summary: {str(e)}', exc_info=True)
            item_summary = []
        
        # Low stock items - with error handling
        try:
            all_items = Item.objects.filter(warehouse=warehouse, is_active=True)
            low_stock_items = []
            for item in all_items:
                try:
                    if item.is_low_stock():
                        low_stock_items.append(item)
                except Exception as e:
                    logger.warning(f'Error checking low stock for item {item.id}: {str(e)}')
                    continue
            logger.info(f'Found {len(low_stock_items)} low stock items')
        except Exception as e:
            logger.error(f'Error fetching low stock items: {str(e)}', exc_info=True)
            low_stock_items = []
        
        # New lends - with error handling
        try:
            new_lends = LendRecord.objects.filter(
                warehouse=warehouse,
                issue_date__date=gregorian_date
            ).select_related('item', 'borrower')
            logger.info(f'Found {new_lends.count()} new lends for date {gregorian_date}')
        except Exception as e:
            logger.error(f'Error fetching new lends: {str(e)}', exc_info=True)
            new_lends = LendRecord.objects.none()

        context = {
            'warehouse': warehouse,
            'department': department,
            'date': jalali_date,
            'gregorian_date': gregorian_date,
            'movements': movements,
            'item_summary': item_summary,
            'low_stock_items': low_stock_items,
            'new_lends': new_lends,
        }
        
        # Step 6: Render template
        logger.info('Step 6: Rendering reports_daily template')
        try:
            return render(request, 'dwms/reports_daily.html', context)
        except Exception as render_error:
            logger.error(f'Error rendering reports_daily template: {str(render_error)}', exc_info=True)
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            if DEBUG_MODE:
                raise
            messages.error(request, _('خطا در نمایش گزارش.'))
            # Try to redirect back to warehouse dashboard
            try:
                return HttpResponseRedirect(f'/dwms/{department_id}/')
            except:
                return HttpResponseRedirect('/')
                
    except Exception as e:
        import uuid
        error_id = str(uuid.uuid4())[:8].upper()
        error_traceback = traceback.format_exc()
        logger.error(f'=== reports_daily CRITICAL ERROR [ID: {error_id}] ===')
        logger.error(f'Error type: {type(e).__name__}')
        logger.error(f'Error message: {str(e)}')
        logger.error(f'Full traceback:\n{error_traceback}')
        logger.error(f'Request path: {request.path}')
        logger.error(f'Request method: {request.method}')
        logger.error(f'Department ID: {department_id}')
        logger.error(f'User: {request.user.id if request.user.is_authenticated else "Anonymous"}')
        
        if DEBUG_MODE:
            raise
        
        messages.error(request, _('خطا در بارگذاری گزارش روزانه. لطفاً با مدیر سیستم تماس بگیرید.'))
        return HttpResponseRedirect('/')


@login_required
def reports_weekly(request, department_id):
    """Weekly report"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        warehouse = get_authorized_warehouse_for_user(department_id, request.user)
        if not warehouse:
            messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
            return redirect('tickets:dashboard')

        # Safely get department
        try:
            department = warehouse.department
            if not department:
                logger.error(f'warehouse.department is None for warehouse {warehouse.id}')
                messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
                return redirect('tickets:dashboard')
        except Exception as e:
            logger.error(f'Error accessing warehouse.department in reports_weekly: {str(e)}', exc_info=True)
            messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
            return redirect('tickets:dashboard')

        # Get week from request
        week_start = request.GET.get('week_start')
        # Implementation similar to daily but for week range
        # ... (similar logic)

        context = {
            'warehouse': warehouse,
            'department': department,
        }
        
        try:
            return render(request, 'dwms/reports_weekly.html', context)
        except Exception as render_error:
            import traceback
            logger.error(f'Error rendering reports_weekly template: {str(render_error)}', exc_info=True)
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            raise
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        logger.error(f'Unexpected error in reports_weekly: {str(e)}', exc_info=True)
        logger.error(f'Full traceback:\n{error_traceback}')
        messages.error(request, _('خطا در بارگذاری گزارش هفتگی. لطفاً با مدیر سیستم تماس بگیرید.'))
        return redirect('tickets:dashboard')


@login_required
def reports_monthly(request, department_id):
    """Monthly report"""
    import logging
    import traceback
    from django.conf import settings
    from tickets.calendar_services.jalali_calendar import JalaliCalendarService
    logger = logging.getLogger(__name__)
    DEBUG_MODE = settings.DEBUG
    
    try:
        # Step 1: Validate department_id
        logger.info(f'Step 1: Validating department_id={department_id}')
        try:
            department_id = int(department_id)
        except (ValueError, TypeError) as e:
            logger.error(f'Invalid department_id: {department_id} - {str(e)}')
            if DEBUG_MODE:
                raise
            messages.error(request, _('شناسه بخش نامعتبر است.'))
            return HttpResponseRedirect('/')
        
        # Step 2: Get warehouse with authorization
        logger.info(f'Step 2: Getting authorized warehouse for department_id={department_id}, user={request.user.id}')
        try:
            warehouse = get_authorized_warehouse_for_user(department_id, request.user)
            if not warehouse:
                logger.warning(f'User {request.user.id} not authorized for department {department_id}')
                messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
                return HttpResponseRedirect('/')
            logger.info(f'Warehouse retrieved: id={warehouse.id}, name={warehouse.name}')
        except Exception as warehouse_error:
            logger.error(f'Exception in get_authorized_warehouse_for_user: {str(warehouse_error)}', exc_info=True)
            if DEBUG_MODE:
                raise
            messages.error(request, _('خطا در بررسی دسترسی به انبار.'))
            return HttpResponseRedirect('/')

        # Step 3: Safely get department
        logger.info(f'Step 3: Getting department for warehouse {warehouse.id}')
        try:
            department = warehouse.department
            if not department:
                logger.error(f'warehouse.department is None for warehouse {warehouse.id}')
                if DEBUG_MODE:
                    raise AttributeError(f'warehouse.department is None for warehouse {warehouse.id}')
                messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
                return HttpResponseRedirect('/')
            logger.info(f'Department retrieved: id={department.id}, name={department.name}')
        except Exception as dept_error:
            logger.error(f'Error accessing warehouse.department: {str(dept_error)}', exc_info=True)
            if DEBUG_MODE:
                raise
            messages.error(request, _('خطا در بارگذاری اطلاعات بخش.'))
            return HttpResponseRedirect('/')

        # Step 4: Get month range (simplified implementation)
        logger.info('Step 4: Calculating month range')
        try:
            from datetime import timedelta
            today = timezone.now().date()
            month_start = today.replace(day=1)
            # Get last day of month
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1) - timedelta(days=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1) - timedelta(days=1)
            
            movements = StockMovement.objects.filter(
                warehouse=warehouse,
                movement_date__date__range=[month_start, month_end]
            ).select_related('item', 'performed_by', 'location')
            logger.info(f'Found {movements.count()} movements for month {month_start} to {month_end}')
        except Exception as e:
            logger.error(f'Error fetching monthly movements: {str(e)}', exc_info=True)
            movements = StockMovement.objects.none()

        context = {
            'warehouse': warehouse,
            'department': department,
            'month_start': month_start,
            'month_end': month_end,
            'movements': movements,
        }
        
        # Step 5: Render template
        logger.info('Step 5: Rendering reports_monthly template')
        try:
            return render(request, 'dwms/reports_monthly.html', context)
        except Exception as render_error:
            logger.error(f'Error rendering reports_monthly template: {str(render_error)}', exc_info=True)
            logger.error(f'Full traceback:\n{traceback.format_exc()}')
            if DEBUG_MODE:
                raise
            messages.error(request, _('خطا در نمایش گزارش.'))
            try:
                return HttpResponseRedirect(f'/dwms/{department_id}/')
            except:
                return HttpResponseRedirect('/')
                
    except Exception as e:
        import uuid
        error_id = str(uuid.uuid4())[:8].upper()
        error_traceback = traceback.format_exc()
        logger.error(f'=== reports_monthly CRITICAL ERROR [ID: {error_id}] ===')
        logger.error(f'Error type: {type(e).__name__}')
        logger.error(f'Error message: {str(e)}')
        logger.error(f'Full traceback:\n{error_traceback}')
        logger.error(f'Request path: {request.path}')
        logger.error(f'Request method: {request.method}')
        logger.error(f'Department ID: {department_id}')
        logger.error(f'User: {request.user.id if request.user.is_authenticated else "Anonymous"}')
        
        if DEBUG_MODE:
            raise
        
        messages.error(request, _('خطا در بارگذاری گزارش ماهانه. لطفاً با مدیر سیستم تماس بگیرید.'))
        return HttpResponseRedirect('/')
