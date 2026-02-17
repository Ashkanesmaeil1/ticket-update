from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.db.models import Sum, Q, Count
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.core.paginator import Paginator
from django.utils import timezone
from django.conf import settings
from datetime import timedelta, datetime
import json
import logging
import traceback

from tickets.models import Department, User
from .models import (
    DepartmentWarehouse, StorageLocation, ItemCategory, Item,
    StockBatch, StockMovement, LendRecord, ItemCode, LowStockAlert
)
from .forms import (
    StorageLocationForm, ItemCategoryForm, ItemForm,
    StockBatchForm, StockMovementForm, LendRecordForm
)
from .utils import (
    get_authorized_warehouse_for_user, require_warehouse_access,
    require_warehouse_write_access, get_item_stock, create_stock_movement,
    create_lend_record, return_lend_record, generate_item_code,
    verify_warehouse_access, get_warehouse_permissions
)


# ==================== Warehouse Selection ====================

@login_required
def warehouse_selection(request):
    """Entry point - show list of warehouses user can access"""
    user = request.user
    
    # EXCLUDE IT MANAGERS: They use the hierarchical IT Inventory system, not Department Warehouse
    if user.role == 'it_manager':
        messages.info(request, _('IT Managers use the Inventory Management system (مدیریت موجودی) for hierarchical asset management.'))
        return redirect('tickets:dashboard')
    
    # ADMINISTRATIVE OVERRIDE: Staff and Superusers can access warehouses
    # Employees can access warehouses (supervisors OR delegated users)
    if user.role != 'employee':
        # Check for staff/superuser override
        if not (hasattr(user, 'is_staff') and user.is_staff) and not (hasattr(user, 'is_superuser') and user.is_superuser):
            messages.error(request, _('شما اجازه دسترسی به این بخش را ندارید.'))
            return redirect('tickets:dashboard')
    
    warehouses_list = []
    
    # ADMINISTRATIVE OVERRIDE: Staff and Superusers see ALL department warehouses
    # Use Department.has_warehouse to ensure we show all sections with warehouse enabled,
    # not just warehouses that were already created/accessed
    if (hasattr(user, 'is_staff') and user.is_staff) or (hasattr(user, 'is_superuser') and user.is_superuser):
        try:
            depts_with_warehouse = Department.objects.filter(has_warehouse=True).order_by('name')
            for dept in depts_with_warehouse:
                warehouse, _ = DepartmentWarehouse.objects.get_or_create(
                    department=dept,
                    defaults={
                        'name': f"انبار {dept.name}",
                        'created_by': user,
                    }
                )
                if warehouse.is_active and not any(w['warehouse'].id == warehouse.id for w in warehouses_list):
                    warehouses_list.append({
                        'warehouse': warehouse,
                        'department': dept,
                        'access_type': 'admin',  # Administrative access
                    })
        except Exception:
            pass
    
    # Get all departments user supervises (supervisor access)
    supervised_depts = []
    if hasattr(user, 'get_supervised_departments'):
        try:
            depts = user.get_supervised_departments()
            if depts:
                supervised_depts = list(depts) if hasattr(depts, '__iter__') and not isinstance(depts, str) else [depts]
        except Exception:
            supervised_depts = []
    
    # Add user's own department if it has warehouse (for department heads)
    if user.department and user.department.has_warehouse and user.department not in supervised_depts:
        supervised_depts.append(user.department)
    
    # Get warehouses for supervised departments
    for dept in supervised_depts:
        if dept.has_warehouse:
            try:
                warehouse = DepartmentWarehouse.objects.get(department=dept)
                # Only add if not already in list (admin access may have already added it)
                if not any(w['warehouse'].id == warehouse.id for w in warehouses_list):
                    warehouses_list.append({
                        'warehouse': warehouse,
                        'department': dept,
                        'access_type': 'supervisor',  # Track access type for UI
                    })
            except DepartmentWarehouse.DoesNotExist:
                pass
    
    # Get warehouses where user has delegated access (read or write)
    from .models import WarehouseAccess
    delegated_accesses = WarehouseAccess.objects.filter(
        user=user,
        is_active=True
    ).select_related('warehouse', 'warehouse__department')
    
    for access in delegated_accesses:
        # Only add if not already in list (supervisor/admin access takes precedence)
        if not any(w['warehouse'].id == access.warehouse.id for w in warehouses_list):
            warehouses_list.append({
                'warehouse': access.warehouse,
                'department': access.warehouse.department,
                'access_type': access.access_level,  # 'read' or 'write'
            })
    
    # If no warehouses found, show helpful message
    if not warehouses_list:
        messages.info(request, _('شما به هیچ انباری دسترسی ندارید. لطفاً با سرپرست انبار تماس بگیرید.'))
        return redirect('tickets:dashboard')
    
    # If only one warehouse, redirect directly (except for staff/superuser - they should always see selection)
    is_admin_override = (hasattr(user, 'is_staff') and user.is_staff) or (hasattr(user, 'is_superuser') and user.is_superuser)
    if len(warehouses_list) == 1 and not is_admin_override:
        return redirect('dwms:dashboard', department_id=warehouses_list[0]['department'].id)
    
    context = {
        'warehouses': warehouses_list,
    }
    
    return render(request, 'dwms/warehouse_selection.html', context)


# ==================== Dashboard & Overview ====================

@login_required
def warehouse_dashboard(request, department_id):
    """Main dashboard for department warehouse"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    # Get statistics
    total_items = Item.objects.filter(warehouse=warehouse, is_active=True).count()
    total_stock_value = 0  # Can be calculated if price is added to items
    
    # Low stock items
    low_stock_items = []
    for item in Item.objects.filter(warehouse=warehouse, is_active=True):
        if item.is_low_stock():
            low_stock_items.append({
                'item': item,
                'current_stock': get_item_stock(item),
                'threshold': item.min_stock_threshold,
            })
    low_stock_count = len(low_stock_items)
    
    # Recent movements
    recent_movements = StockMovement.objects.filter(
        warehouse=warehouse
    ).select_related('item', 'performed_by', 'location')[:10]
    
    # Open lends
    open_lends = LendRecord.objects.filter(
        warehouse=warehouse,
        status='OUT'
    ).select_related('item', 'borrower')[:10]
    
    # Get top consumed items (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    top_consumed = (StockMovement.objects
                   .filter(warehouse=warehouse, movement_type='OUT',
                          movement_date__gte=thirty_days_ago)
                   .values('item__name', 'item__id')
                   .annotate(total=Sum('quantity'))
                   .order_by('-total')[:5])

    # Get comprehensive permissions for template rendering
    from .utils import get_warehouse_permissions
    permissions = get_warehouse_permissions(warehouse, request.user)
    
    # Build list of accessible warehouses for switcher (when user has multi-warehouse access)
    accessible_warehouses = []
    user = request.user
    if (hasattr(user, 'is_staff') and user.is_staff) or (hasattr(user, 'is_superuser') and user.is_superuser):
        depts = Department.objects.filter(has_warehouse=True).order_by('name')
        for dept in depts:
            w, _ = DepartmentWarehouse.objects.get_or_create(
                department=dept,
                defaults={'name': f"انبار {dept.name}", 'created_by': user}
            )
            if w.is_active:
                accessible_warehouses.append({'warehouse': w, 'department': dept})
    else:
        supervised_depts = []
        if hasattr(user, 'get_supervised_departments'):
            try:
                depts = user.get_supervised_departments()
                supervised_depts = list(depts) if depts else []
            except Exception:
                supervised_depts = []
        if user.department and user.department.has_warehouse and user.department not in supervised_depts:
            supervised_depts.append(user.department)
        for dept in supervised_depts:
            if dept.has_warehouse:
                try:
                    w = DepartmentWarehouse.objects.get(department=dept)
                    accessible_warehouses.append({'warehouse': w, 'department': dept})
                except DepartmentWarehouse.DoesNotExist:
                    pass
        from .models import WarehouseAccess
        for acc in WarehouseAccess.objects.filter(user=user, is_active=True).select_related('warehouse', 'warehouse__department'):
            if not any(a['warehouse'].id == acc.warehouse.id for a in accessible_warehouses):
                accessible_warehouses.append({'warehouse': acc.warehouse, 'department': acc.warehouse.department})
    
    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'accessible_warehouses': accessible_warehouses,
        'total_items': total_items,
        'total_stock_value': total_stock_value,
        'low_stock_items': low_stock_items[:5],  # Top 5
        'low_stock_count': low_stock_count,
        'recent_movements': recent_movements,
        'open_lends': open_lends,
        'top_consumed': top_consumed,
        'can_write': permissions['can_write'],
        'is_supervisor': permissions['is_supervisor'],
        'is_read_only': permissions['is_read_only'],
        'access_level': permissions['access_level'],
    }
    
    return render(request, 'dwms/dashboard.html', context)


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
@require_warehouse_write_access
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
@require_warehouse_write_access
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

    # Get comprehensive permissions for template rendering
    permissions = get_warehouse_permissions(warehouse, request.user)
    
    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'page_obj': page_obj,
        'categories': categories,
        'search_query': search_query,
        'category_filter': category_filter,
        'low_stock_only': low_stock_only,
        'can_write': permissions['can_write'],
        'is_supervisor': permissions['is_supervisor'],
        'is_read_only': permissions['is_read_only'],
        'access_level': permissions['access_level'],
    }
    
    return render(request, 'dwms/item_list.html', context)


@login_required
def item_detail(request, department_id, item_id):
    """View item details"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
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

    # Get comprehensive permissions for template rendering
    permissions = get_warehouse_permissions(warehouse, request.user)
    
    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'item': item,
        'total_stock': total_stock,
        'is_low_stock': is_low_stock,
        'stock_by_location': stock_by_location,
        'batches': batches,
        'recent_movements': recent_movements,
        'active_lends': active_lends,
        'qr_code': qr_code,
        'can_write': permissions['can_write'],
        'is_supervisor': permissions['is_supervisor'],
        'is_read_only': permissions['is_read_only'],
        'access_level': permissions['access_level'],
    }
    
    return render(request, 'dwms/item_detail.html', context)


@login_required
@require_http_methods(["GET", "POST"])
@require_warehouse_write_access
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
@require_warehouse_write_access
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
@require_warehouse_write_access
def movement_create(request, department_id, item_id=None):
    """Create a stock movement"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    item = None
    if item_id:
        item = get_object_or_404(Item, id=item_id, warehouse=warehouse)

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
                return redirect('dwms:item_detail', department_id=department_id, item_id=item.id)
            except ValueError as e:
                messages.error(request, str(e))
    else:
        form = StockMovementForm(warehouse=warehouse, item=item)

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'item': item,
        'form': form,
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
    
    # Filter by date (Persian/Jalali date expected: YYYY-MM-DD or YYYY/MM/DD)
    from tickets.calendar_services.jalali_calendar import JalaliCalendarService
    from tickets.utils import PERSIAN_TO_ENGLISH

    def _normalize_date_str(s):
        if not s:
            return ''
        s = s.strip().replace('/', '-')
        return ''.join(PERSIAN_TO_ENGLISH.get(c, c) for c in s)

    if date_from:
        try:
            date_from_clean = _normalize_date_str(date_from)
            year, month, day = map(int, date_from_clean.split('-'))
            gregorian_dt = JalaliCalendarService.jalali_to_gregorian(year, month, day)
            date_from_start = gregorian_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            movements = movements.filter(movement_date__gte=date_from_start)
        except (ValueError, TypeError, AttributeError):
            pass
    
    if date_to:
        try:
            date_to_clean = _normalize_date_str(date_to)
            year, month, day = map(int, date_to_clean.split('-'))
            gregorian_dt = JalaliCalendarService.jalali_to_gregorian(year, month, day)
            date_to_end = gregorian_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            movements = movements.filter(movement_date__lte=date_to_end)
        except (ValueError, TypeError, AttributeError):
            pass
    
    # Pagination
    paginator = Paginator(movements, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get items for filter
    items = Item.objects.filter(warehouse=warehouse, is_active=True).order_by('name')

    # Server's today (Tehran timezone) for correct "today" highlight in datepicker
    today_components = JalaliCalendarService.gregorian_to_jalali(timezone.now())

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'page_obj': page_obj,
        'today_jalali_year': today_components['year'],
        'today_jalali_month': today_components['month'],
        'today_jalali_day': today_components['day'],
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
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    # Filters
    status_filter = request.GET.get('status', '')
    borrower_filter = request.GET.get('borrower', '')
    
    lends = LendRecord.objects.filter(warehouse=warehouse).select_related(
        'item', 'borrower', 'issued_by'
    ).order_by('-issue_date')
    
    if status_filter:
        lends = lends.filter(status=status_filter)
    else:
        # Default: show active lends
        lends = lends.filter(status='OUT')
    
    if borrower_filter:
        lends = lends.filter(borrower_id=borrower_filter)
    
    # Check for overdue
    for lend in lends:
        if lend.is_overdue() and lend.status != 'RETURNED':
            lend.status = 'OVERDUE'
            lend.save()
    
    # Pagination
    paginator = Paginator(lends, 30)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get borrowers for filter
    borrowers = User.objects.filter(
        borrowed_items__warehouse=warehouse
    ).distinct().order_by('first_name', 'last_name')

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'page_obj': page_obj,
        'borrowers': borrowers,
        'status_filter': status_filter,
        'borrower_filter': borrower_filter,
    }
    
    return render(request, 'dwms/lend_list.html', context)


@login_required
@require_http_methods(["GET", "POST"])
@require_warehouse_write_access
def lend_create(request, department_id, item_id=None):
    """Create a lend record"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    item = None
    if item_id:
        item = get_object_or_404(Item, id=item_id, warehouse=warehouse)

    if request.method == 'POST':
        form = LendRecordForm(request.POST, warehouse=warehouse, item=item)
        if form.is_valid():
            try:
                item = form.cleaned_data['item']
                batch = form.cleaned_data.get('batch')
                quantity = form.cleaned_data['quantity']
                borrower = form.cleaned_data['borrower']
                # Use the converted Gregorian date, not the original Jalali string
                due_date = form.cleaned_data.get('due_date_converted')
                if not due_date:
                    # Fallback: if conversion failed, try to get from form's save method
                    # This should not happen if clean_due_date worked correctly
                    messages.error(request, _('خطا در تبدیل تاریخ. لطفاً دوباره تلاش کنید.'))
                    context = {
                        'warehouse': warehouse,
                        'department': warehouse.department,
                        'item': item,
                        'form': form,
                    }
                    return render(request, 'dwms/lend_form.html', context)
                notes = form.cleaned_data.get('notes', '')
                
                # Get or create batch if not provided
                if not batch:
                    # Get first available batch
                    batch = StockBatch.objects.filter(
                        item=item,
                        quantity__gte=quantity
                    ).first()
                    if not batch:
                        messages.error(request, _('موجودی کافی برای این کالا وجود ندارد.'))
                        context = {
                            'warehouse': warehouse,
                            'department': warehouse.department,
                            'item': item,
                            'form': form,
                        }
                        return render(request, 'dwms/lend_form.html', context)
                
                # Get location from batch
                location = batch.location
                
                # Create lend record
                lend_record = create_lend_record(
                    warehouse=warehouse,
                    item=item,
                    batch=batch,
                    location=location,
                    quantity=quantity,
                    borrower=borrower,
                    issued_by=request.user,
                    due_date=due_date,
                    notes=notes,
                )
                
                messages.success(request, _('امانت با موفقیت ثبت شد.'))
                return redirect('dwms:lend_list', department_id=department_id)
            except ValueError as e:
                messages.error(request, str(e))
    else:
        form = LendRecordForm(warehouse=warehouse, item=item)

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
        'item': item,
        'form': form,
    }
    
    return render(request, 'dwms/lend_form.html', context)


@login_required
@require_http_methods(["GET", "POST"])
@require_warehouse_write_access
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
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
    }
    
    return render(request, 'dwms/scan.html', context)


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
        
        # Find item by code
        try:
            item_code = ItemCode.objects.get(code_value=code_value)
            item = item_code.item
            
            # Verify item belongs to this warehouse
            if item.warehouse != warehouse:
                return JsonResponse({'error': _('این کالا به این انبار تعلق ندارد')}, status=403)
            
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
        except ItemCode.DoesNotExist:
            return JsonResponse({'error': _('کد یافت نشد')}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': _('داده نامعتبر')}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ==================== Reports ====================

@login_required
def reports_daily(request, department_id):
    """
    Daily report with Jalali calendar.
    
    Access Control:
    - Supervisors: Full access to their supervised departments
    - Delegated Users: Read/Write access based on WarehouseAccess table
    - All employees can view reports (read-only for delegated users)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Validate department_id parameter
        try:
            department_id = int(department_id)
        except (ValueError, TypeError):
            logger.error(f'reports_daily: Invalid department_id parameter: {department_id}')
            messages.error(request, _('شناسه بخش نامعتبر است.'))
            return redirect('tickets:dashboard')
        
        # Get warehouse with permission check
        warehouse = get_authorized_warehouse_for_user(department_id, request.user)
        if not warehouse:
            # Permission denied - this is expected for unauthorized users
            logger.warning(f'reports_daily: Access denied for user_id={request.user.id}, department_id={department_id}')
            
            # Run diagnostic to understand why access was denied
            from .utils import verify_warehouse_access
            diagnostic = verify_warehouse_access(request.user, department_id)
            logger.warning(f'reports_daily: Access diagnostic: {diagnostic}')
            
            messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
            return redirect('tickets:dashboard')
        
        logger.info(f'reports_daily: Access granted for user_id={request.user.id}, warehouse_id={warehouse.id}, department_id={department_id}')

        # Get date from request (Jalali format expected)
        from tickets.calendar_services.jalali_calendar import JalaliCalendarService
        
        # Default to today
        today = timezone.now()
        today_date = today.date()
        
        # Get current Jalali date as default
        jalali_components = JalaliCalendarService.gregorian_to_jalali(today)
        default_jalali_date = f"{jalali_components['year']}-{jalali_components['month']:02d}-{jalali_components['day']:02d}"
        
        jalali_date = request.GET.get('date', default_jalali_date)
        # Normalize Persian/Arabic digits to ASCII for parsing
        from tickets.utils import PERSIAN_TO_ENGLISH
        _norm = lambda s: ''.join(PERSIAN_TO_ENGLISH.get(c, c) for c in (s or ''))
        jalali_date_clean = _norm(jalali_date.strip().replace('/', '-'))
        
        # Convert Jalali to Gregorian
        try:
            year, month, day = map(int, jalali_date_clean.split('-'))
            gregorian_datetime = JalaliCalendarService.jalali_to_gregorian(year, month, day)
            gregorian_date = gregorian_datetime.date()
        except (ValueError, AttributeError, TypeError):
            gregorian_date = today_date
            # Recalculate Jalali date from today
            jalali_components = JalaliCalendarService.gregorian_to_jalali(today)
            jalali_date = f"{jalali_components['year']}-{jalali_components['month']:02d}-{jalali_components['day']:02d}"
        else:
            jalali_date = jalali_date_clean
        
        # Get movements for this date
        movements = StockMovement.objects.filter(
            warehouse=warehouse,
            movement_date__date=gregorian_date
        ).select_related('item', 'performed_by', 'location')
        
        # Calculate total IN and OUT movements
        from django.db.models import Sum, Q
        total_in = movements.filter(movement_type='IN').aggregate(
            total=Sum('quantity')
        )['total'] or 0
        
        total_out = movements.filter(movement_type='OUT').aggregate(
            total=Sum('quantity')
        )['total'] or 0
        
        # Aggregate by item
        item_summary = (movements.values('item__name', 'item__id', 'movement_type')
                       .annotate(total=Sum('quantity'))
                       .order_by('item__name'))
        
        # Low stock items - safely handle potential errors
        low_stock_items = []
        try:
            for item in Item.objects.filter(warehouse=warehouse, is_active=True):
                try:
                    if item.is_low_stock():
                        low_stock_items.append(item)
                except Exception:
                    # Skip items that cause errors in is_low_stock()
                    continue
        except Exception:
            # If query fails, use empty list
            low_stock_items = []
        
        # New lends
        try:
            new_lends = LendRecord.objects.filter(
                warehouse=warehouse,
                issue_date__date=gregorian_date
            ).select_related('item', 'borrower')
        except Exception:
            new_lends = LendRecord.objects.none()

        # Get comprehensive permissions for template rendering
        try:
            permissions = get_warehouse_permissions(warehouse, request.user)
        except Exception:
            # Fallback to safe defaults if permission check fails
            permissions = {
                'can_write': False,
                'is_supervisor': False,
                'is_read_only': False,
                'access_level': None,
            }
        
        # Ensure all numeric values are properly converted
        try:
            total_in = float(total_in) if total_in else 0.0
        except (TypeError, ValueError):
            total_in = 0.0
        
        try:
            total_out = float(total_out) if total_out else 0.0
        except (TypeError, ValueError):
            total_out = 0.0
        
        # Validate warehouse and department exist
        if not warehouse or not hasattr(warehouse, 'department'):
            logger.error(f'reports_daily: Invalid warehouse object for department_id={department_id}')
            messages.error(request, _('انبار یافت نشد. لطفاً با مدیر سیستم تماس بگیرید.'))
            return redirect('tickets:dashboard')
        
        context = {
            'warehouse': warehouse,
            'department': warehouse.department,
            'date': jalali_date,
            'today_jalali_year': jalali_components['year'],
            'today_jalali_month': jalali_components['month'],
            'today_jalali_day': jalali_components['day'],
            'gregorian_date': gregorian_date,
            'movements': movements,
            'item_summary': item_summary,
            'low_stock_items': low_stock_items,
            'new_lends': new_lends,
            'total_in': total_in,
            'total_out': total_out,
            'can_write': permissions['can_write'],
            'is_supervisor': permissions['is_supervisor'],
            'is_read_only': permissions['is_read_only'],
            'access_level': permissions['access_level'],
        }
        
        return render(request, 'dwms/reports_daily.html', context)
    
    except Exception as e:
        # Enhanced error logging with full diagnostic context
        logger = logging.getLogger(__name__)
        
        # Collect diagnostic information
        diagnostic_info = {
            'department_id': department_id,
            'user_id': request.user.id if request.user.is_authenticated else None,
            'user_role': getattr(request.user, 'role', None) if request.user.is_authenticated else None,
            'exception_type': type(e).__name__,
            'exception_message': str(e),
            'request_path': request.path,
            'request_method': request.method,
        }
        
        # Add warehouse info if available
        if 'warehouse' in locals() and warehouse is not None:
            diagnostic_info['warehouse_id'] = warehouse.id
            diagnostic_info['warehouse_name'] = warehouse.name
        else:
            diagnostic_info['warehouse_id'] = None
            diagnostic_info['warehouse_exists'] = False
        
        # Log comprehensive error information
        logger.error(
            f'REPORTS_DAILY_ERROR: {diagnostic_info}',
            exc_info=True
        )
        logger.error(f'Full traceback:\n{traceback.format_exc()}')
        
        # In DEBUG mode, re-raise exception to expose full Django debug page
        # This allows developers to see the exact error and traceback
        if settings.DEBUG:
            logger.error('DEBUG mode: Re-raising exception to expose traceback')
            raise  # Re-raise to show Django debug page with full traceback
        
        # Production error handling
        # Check if it's a permission issue
        if 'warehouse' in locals() and warehouse is None:
            messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        else:
            # Return user-friendly error with more context for debugging
            error_msg = _('خطا در بارگذاری گزارش. لطفاً دوباره تلاش کنید.')
            if request.user.is_superuser or request.user.is_staff:
                # Show more details to admins for debugging
                error_msg += f' (Error: {str(e)})'
            messages.error(request, error_msg)
        
        return redirect('tickets:dashboard')


@login_required
def reports_weekly(request, department_id):
    """Weekly report"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    # Get week from request
    week_start = request.GET.get('week_start')
    # Implementation similar to daily but for week range
    # ... (similar logic)

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
    }
    
    return render(request, 'dwms/reports_weekly.html', context)


@login_required
def reports_monthly(request, department_id):
    """Monthly report"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')

    # Get month from request
    month = request.GET.get('month')
    # Implementation similar to daily but for month range
    # ... (similar logic)

    context = {
        'warehouse': warehouse,
        'department': warehouse.department,
    }
    
    return render(request, 'dwms/reports_monthly.html', context)


# ==================== Access Management ====================

@login_required
@require_http_methods(["GET", "POST"])
def warehouse_access_manage(request, department_id):
    """Manage warehouse access permissions for department members"""
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    if not warehouse:
        messages.error(request, _('شما اجازه دسترسی به این انبار را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Only supervisors can manage access
    from .utils import get_warehouse_access_level
    access_level = get_warehouse_access_level(warehouse, request.user)
    if access_level != 'supervisor':
        messages.error(request, _('فقط سرپرست انبار می‌تواند دسترسی‌ها را مدیریت کند.'))
        return redirect('dwms:dashboard', department_id=department_id)
    
    department = warehouse.department
    
    # Get all department members (excluding supervisors)
    from tickets.models import User
    department_members = User.objects.filter(
        department=department,
        role='employee'
    ).exclude(
        department_role__in=['senior', 'manager']
    ).order_by('first_name', 'last_name')
    
    # Get existing access records
    from .models import WarehouseAccess
    access_records = WarehouseAccess.objects.filter(
        warehouse=warehouse,
        is_active=True
    ).select_related('user', 'granted_by')
    
    # Create access map for template
    access_map = {access.user.id: access for access in access_records}
    
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        action = request.POST.get('action')  # 'grant', 'update', or 'revoke'
        
        if not user_id:
            messages.error(request, _('کاربر انتخاب نشده است.'))
        else:
            try:
                target_user = User.objects.get(id=user_id, department=department)
                
                if action == 'grant':
                    # Validation: Prevent supervisors from granting themselves access
                    from .utils import _is_supervisor_direct
                    if _is_supervisor_direct(warehouse, target_user):
                        messages.warning(request, _('سرپرست انبار نیازی به دسترسی امانی ندارد. دسترسی سرپرست به صورت خودکار اعمال می‌شود.'))
                    else:
                        access_level = request.POST.get('access_level', 'read')
                        if access_level not in ['read', 'write']:
                            access_level = 'read'
                        
                        # Use update_or_create to handle existing records (upsert logic)
                        # This prevents UNIQUE constraint violations
                        access, created = WarehouseAccess.objects.update_or_create(
                            warehouse=warehouse,
                            user=target_user,
                            defaults={
                                'access_level': access_level,
                                'granted_by': request.user,
                                'is_active': True,
                                'revoked_at': None,  # Clear revocation if reactivating
                            }
                        )
                        
                        if created:
                            messages.success(request, _('دسترسی با موفقیت اعطا شد.'))
                        else:
                            # Record existed (could be inactive or different access level)
                            if not access.is_active:
                                messages.success(request, _('دسترسی قبلی فعال شد و به‌روزرسانی شد.'))
                            else:
                                messages.success(request, _('سطح دسترسی به‌روزرسانی شد.'))
                
                elif action == 'update':
                    # Validation: Prevent supervisors from updating their own access
                    from .utils import _is_supervisor_direct
                    if _is_supervisor_direct(warehouse, target_user):
                        messages.warning(request, _('سرپرست انبار نیازی به دسترسی امانی ندارد. دسترسی سرپرست به صورت خودکار اعمال می‌شود.'))
                    else:
                        access_level = request.POST.get('access_level', 'read')
                        if access_level not in ['read', 'write']:
                            access_level = 'read'
                        
                        # Use update_or_create for consistency (handles both active and inactive records)
                        access, created = WarehouseAccess.objects.update_or_create(
                            warehouse=warehouse,
                            user=target_user,
                            defaults={
                                'access_level': access_level,
                                'granted_by': request.user,
                                'is_active': True,
                                'revoked_at': None,  # Clear revocation if reactivating
                            }
                        )
                        
                        if created:
                            messages.success(request, _('دسترسی ایجاد و به‌روزرسانی شد.'))
                        else:
                            messages.success(request, _('سطح دسترسی با موفقیت به‌روزرسانی شد.'))
                
                elif action == 'revoke':
                    # Validation: Prevent revoking supervisor access (they don't have delegation records)
                    from .utils import _is_supervisor_direct
                    if _is_supervisor_direct(warehouse, target_user):
                        messages.warning(request, _('نمی‌توان دسترسی سرپرست را لغو کرد. دسترسی سرپرست به صورت خودکار اعمال می‌شود.'))
                    else:
                        # Find access record (check both active and inactive to handle edge cases)
                        existing = WarehouseAccess.objects.filter(
                            warehouse=warehouse,
                            user=target_user
                        ).first()
                        
                        if existing:
                            if existing.is_active:
                                existing.revoke(revoked_by=request.user)
                                messages.success(request, _('دسترسی با موفقیت لغو شد.'))
                            else:
                                messages.info(request, _('این دسترسی قبلاً لغو شده است.'))
                        else:
                            messages.error(request, _('دسترسی یافت نشد.'))
                
                else:
                    messages.error(request, _('عملیات نامعتبر است.'))
                
            except User.DoesNotExist:
                messages.error(request, _('کاربر یافت نشد.'))
            except Exception as e:
                messages.error(request, _('خطا در انجام عملیات: {}').format(str(e)))
        
        # Redirect to refresh the page
        return redirect('dwms:warehouse_access_manage', department_id=department_id)
    
    # Refresh access map after POST
    access_records = WarehouseAccess.objects.filter(
        warehouse=warehouse,
        is_active=True
    ).select_related('user', 'granted_by')
    access_map = {access.user.id: access for access in access_records}
    
    context = {
        'warehouse': warehouse,
        'department': department,
        'department_members': department_members,
        'access_map': access_map,
    }
    
    return render(request, 'dwms/warehouse_access_manage.html', context)
