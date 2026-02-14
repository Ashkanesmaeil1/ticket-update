from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.core.paginator import Paginator
from django.db.models import Q, Count, Exists, OuterRef, F
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy, reverse
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.decorators import user_passes_test
from django.utils.translation import gettext_lazy as _
from django.template.response import TemplateResponse
from django.core.exceptions import ValidationError

from .models import User, Ticket, Reply, Department, Branch, InventoryElement, ElementSpecification, Notification, TicketTask, TaskReply, TicketActivityLog, TicketCategory, DeadlineExtensionRequest
from .services import notify_department_supervisor
from .admin_security import get_admin_superuser_queryset_filter, is_admin_superuser


def get_warehouse_element():
    """
    Helper function to get or create the default warehouse element.
    
    - Warehouse is represented as exactly ONE InventoryElement.
    - It is created automatically if it does not exist.
    - It is always active and is a top-level element (no parent).
    - It is assigned to the first IT manager found (or created with a system user).
    - It can be used as a parent for other inventory elements.
    """
    # Try to find existing warehouse element
    warehouse = InventoryElement.objects.filter(
        name='انبار',
        parent_element__isnull=True
    ).first()
    
    if warehouse:
        # Ensure it's active and has no parent
        warehouse.is_active = True
        warehouse.parent_element = None
        warehouse.save(update_fields=['is_active', 'parent_element'])
        return warehouse
    
    # Create warehouse element - assign to first IT manager
    it_manager = User.objects.filter(role='it_manager', is_active=True).first()
    if not it_manager:
        # If no IT manager exists, create a system user (shouldn't happen in practice)
        it_manager = User.objects.filter(is_active=True).first()
        if not it_manager:
            raise ValueError(_('هیچ کاربر فعالی برای اختصاص انبار وجود ندارد.'))
    
    warehouse = InventoryElement.objects.create(
        name='انبار',
        element_type='انبار',
        description=_('انبار پیش‌فرض سیستم - تمام عناصر موجودی می‌توانند زیرمجموعه این انبار باشند'),
        assigned_to=it_manager,
        parent_element=None,
        is_active=True,
        created_by=it_manager
    )
    
    return warehouse


def get_department_warehouse(department):
    """
    Helper function to get or create a warehouse element for a specific department.
    
    - Each department with warehouse enabled gets its own warehouse element
    - Warehouse is represented as an InventoryElement with name = department name + " انبار"
    - It is created automatically if it does not exist
    - It is always active and is a top-level element (no parent)
    - It is assigned to the department supervisor
    """
    if not department or not department.has_warehouse:
        return None
    
    warehouse_name = f"{department.name} انبار"
    
    # Try to find existing department warehouse element
    warehouse = InventoryElement.objects.filter(
        name=warehouse_name,
        parent_element__isnull=True,
        element_type='انبار'
    ).first()
    
    if warehouse:
        # Ensure it's active and has no parent
        warehouse.is_active = True
        warehouse.parent_element = None
        # Update assigned_to to current supervisor if changed
        if department.supervisor and warehouse.assigned_to != department.supervisor:
            warehouse.assigned_to = department.supervisor
        warehouse.save(update_fields=['is_active', 'parent_element', 'assigned_to'])
        return warehouse
    
    # Create department warehouse element - assign to department supervisor
    supervisor = department.supervisor
    if not supervisor:
        # If no supervisor, assign to first active user in department
        supervisor = department.users.filter(is_active=True).first()
        if not supervisor:
            raise ValueError(_('بخش "{}" هیچ سرپرست یا کاربر فعالی ندارد.').format(department.name))
    
    warehouse = InventoryElement.objects.create(
        name=warehouse_name,
        element_type='انبار',
        description=_('انبار بخش {} - تمام عناصر موجودی این بخش می‌توانند زیرمجموعه این انبار باشند').format(department.name),
        assigned_to=supervisor,
        parent_element=None,
        is_active=True,
        created_by=supervisor
    )
    
    return warehouse


def is_department_warehouse_element(element):
    """
    Check if an inventory element belongs to a department warehouse.
    Returns (is_department_warehouse, department) tuple.
    
    This function checks:
    1. If the element itself is a department warehouse
    2. If any parent in the hierarchy is a department warehouse
    """
    if not element:
        return False, None
    
    # Check if element itself is a department warehouse
    if element.name.endswith(' انبار') and element.element_type == 'انبار':
        dept_name = element.name.replace(' انبار', '').strip()
        department = Department.objects.filter(name=dept_name, has_warehouse=True).first()
        if department:
            return True, department
    
    # Check parent recursively (up the entire hierarchy)
    parent = element.parent_element
    visited = set()  # Prevent infinite loops
    while parent and parent.id not in visited:
        visited.add(parent.id)
        if parent.name.endswith(' انبار') and parent.element_type == 'انبار':
            dept_name = parent.name.replace(' انبار', '').strip()
            department = Department.objects.filter(name=dept_name, has_warehouse=True).first()
            if department:
                return True, department
        parent = parent.parent_element
    
    return False, None


def get_it_department():
    """
    Helper function to get or create the single IT department.
    
    - IT department is represented as exactly ONE Department row.
    - It is created automatically if it does not exist.
    - It is always active and always has can_receive_tickets=True so that
      users can select it in the ticket creation form.
    - IT Manager can later change its name and branch from the department
      management UI without breaking the logic.
    """
    # We treat all departments with department_type='technician' as IT-capable,
    # but we only want ONE canonical IT department row.
    it_dept = Department.objects.filter(department_type='technician').order_by('id').first()

    # If no technician department exists, create a default IT department
    if not it_dept:
        it_dept = Department.objects.create(
            name=_('بخش IT'),
            department_type='technician',
            description=_('بخش اصلی فناوری اطلاعات سیستم'),
            is_active=True,
            can_receive_tickets=True,
        )

    # Ensure IT department is always active and can receive tickets
    changed = False
    if not it_dept.is_active:
        it_dept.is_active = True
        changed = True
    if not it_dept.can_receive_tickets:
        it_dept.can_receive_tickets = True
        changed = True
    if changed:
        it_dept.save(update_fields=['is_active', 'can_receive_tickets'])

    return it_dept
from .forms import (
    CustomAuthenticationForm, TicketForm, TaskTicketForm, ReplyForm, 
    TicketStatusForm, UserCreationByManagerForm,
    EmployeeCreationForm, TechnicianCreationForm, EmployeeEditForm, TechnicianEditForm,
    ITManagerProfileForm, DepartmentForm, EmailConfigForm, BranchForm,
    InventoryElementForm, ElementSpecificationForm, TicketTaskForm, TaskReplyForm, TaskStatusForm,
    SupervisorAssignmentForm, TicketCategoryForm
)
from .services import StatisticsService, notify_it_manager, notify_employee_ticket_created, notify_employee_ticket_replied, notify_employee_ticket_status_changed, notify_employee_ticket_assigned, create_it_manager_login_notification
from .models import Notification, EmailConfig
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponseForbidden

def login_view(request):
    """Custom login view using national ID and employee code"""
    if request.user.is_authenticated:
        return redirect('tickets:dashboard')
    
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            
            # Create notification only for IT managers about their own login
            if user.role == 'it_manager':
                try:
                    # Get client IP address
                    ip_address = get_client_ip(request)
                    create_it_manager_login_notification(user, ip_address)
                except Exception:
                    pass
            
            messages.success(request, _('{}، خوش آمدید!').format(user.get_full_name()))
            return redirect('tickets:dashboard')
        else:
            # Form validation errors will be displayed automatically
            pass
    else:
        form = CustomAuthenticationForm()
    
    return render(request, 'tickets/login.html', {'form': form})

def get_client_ip(request):
    """Get the client's IP address from the request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def logout_view(request):
    """Logout view"""
    logout(request)
    return redirect('tickets:login')

@login_required
def test_email_connection(request):
    """AJAX endpoint to test email connection"""
    if request.user.role != 'it_manager':
        return JsonResponse({'success': False, 'message': _('دسترسی رد شد. فقط مدیر IT میتواند این بخش را دریافت کند.')})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': _('درخواست نامعتبر')})
    
    try:
        config = EmailConfig.get_active()
        
        if not config.host:
            return JsonResponse({'success': False, 'message': _('هاست SMTP تنظیم نشده است')})
        
        # Test connection
        import smtplib
        from email.mime.text import MIMEText
        
        # Create simple test message
        msg = MIMEText('این یک ایمیل آزمایشی از سیستم تیکت است.', 'plain', 'utf-8')
        msg['Subject'] = 'آزمایش اتصال ایمیل'
        
        if config.username:
            msg['From'] = config.from_name + f" <{config.username}>" if config.from_name else config.username
            msg['To'] = config.username
        else:
            return JsonResponse({'success': False, 'message': _('ایمیل فرستنده تنظیم نشده است')})
        
        # Connect to SMTP server
        if config.use_ssl:
            server = smtplib.SMTP_SSL(config.host, config.port)
        else:
            server = smtplib.SMTP(config.host, config.port)
        
        if config.use_tls and not config.use_ssl:
            server.starttls()
        
        if config.username and config.password:
            server.login(config.username, config.password)
        
        # Send test email
        server.sendmail(msg['From'], msg['To'], msg.as_string())
        server.quit()
        
        return JsonResponse({
            'success': True, 
            'message': _('اتصال ایمیل با موفقیت تست شد و ایمیل آزمایشی ارسال شد.')
        })
        
    except smtplib.SMTPAuthenticationError:
        return JsonResponse({'success': False, 'message': _('احراز هویت ناموفق. لطفاً نام کاربری و رمز عبور را بررسی کنید.')})
    except smtplib.SMTPConnectError:
        return JsonResponse({'success': False, 'message': _('خطا در اتصال به سرور SMTP. لطفاً هاست و پورت را بررسی کنید.')})
    except smtplib.SMTPException as e:
        return JsonResponse({'success': False, 'message': _('خطای SMTP: {}').format(str(e))})
    except Exception as e:
        return JsonResponse({'success': False, 'message': _('خطا در تست اتصال: {}').format(str(e))})

@login_required
def email_settings(request):
    """IT Manager-only view to manage SMTP settings used by the app."""
    if request.user.role != 'it_manager':
        return HttpResponseForbidden(_('دسترسی رد شد. فقط مدیر IT میتواند این بخش را دریافت کند.'))

    config = EmailConfig.get_active()
    if request.method == 'POST':
        form = EmailConfigForm(request.POST, instance=config if config and config.pk else None)
        if form.is_valid():
            config = form.save()
            messages.success(request, _('تنظیمات ایمیل با موفقیت ذخیره شد.'))
            return redirect('tickets:email_settings')
        else:
            messages.error(request, _('لطفاً خطاهای فرم را برطرف کنید.'))
    else:
        form = EmailConfigForm(instance=config if config and config.pk else None)

    return render(request, 'tickets/email_settings.html', {
        'form': form,
        'config': config,
    })

@login_required
def dashboard(request):
    """Dashboard view with role-based content"""
    # #region agent log - Dashboard error tracking
    import json
    import os
    import traceback
    from datetime import datetime
    log_path = r'c:\Users\User\Desktop\pticket-main\.cursor\debug.log'
    def log_debug(hypothesis_id, location, message, data):
        try:
            log_dir = os.path.dirname(log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            entry = {
                'id': f'log_{int(datetime.now().timestamp() * 1000)}',
                'timestamp': int(datetime.now().timestamp() * 1000),
                'location': location,
                'message': message,
                'data': data,
                'sessionId': 'debug-session',
                'runId': 'run1',
                'hypothesisId': hypothesis_id
            }
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception as log_err:
            # Silently fail logging - don't break the main flow
            pass
    # #endregion
    
    # Log entry immediately to confirm function is called
    try:
        log_debug('DASHBOARD', 'tickets/views.py:245', 'Dashboard function entry', {'timestamp': 'start'})
    except Exception:
        pass
    
    try:
        log_debug('DASHBOARD', 'tickets/views.py:245', 'Dashboard entry', {
            'user_id': request.user.id if request.user.is_authenticated else None,
            'user_role': request.user.role if request.user.is_authenticated else None
        })
        user = request.user
        log_debug('DASHBOARD', 'tickets/views.py:250', 'User retrieved', {
            'user_role': user.role,
            'department_role': getattr(user, 'department_role', None)
        })

        # Global flag: can this user create ticket tasks?
        can_create_tasks = False
        try:
            if user.role == 'it_manager':
                can_create_tasks = True
            elif user.role == 'employee' and user.department_role in ['senior', 'manager']:
                # Supervisors/managers can always create tasks for their supervised departments
                can_create_tasks = True
            elif user.role == 'employee' and user.department and getattr(user.department, 'task_creator_id', None) == user.id:
                # Regular employee explicitly designated as task creator for their department
                can_create_tasks = True
        except Exception:
            can_create_tasks = False
        
        if user.role == 'employee':
            # Get ticket tasks: assigned to this user OR created by this user (if task creator) OR created by task creators in supervised departments (if supervisor)
            # Check if user is a task creator
            is_task_creator_for_tasks = False
            try:
                if user.department and user.department.task_creator_id == user.id:
                    is_task_creator_for_tasks = True
            except Exception:
                pass
            
            # Check if user is a supervisor
            is_supervisor_for_tasks = user.department_role in ['senior', 'manager']
            
            # Build queryset based on user role
            if is_supervisor_for_tasks:
                # Supervisors see: tasks assigned to them OR tasks they created OR tasks created by task creators in their supervised departments
                supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
                supervised_dept_ids = [dept.id for dept in supervised_depts] if supervised_depts else []
                
                # Get task creators in supervised departments
                task_creators_in_supervised_depts = User.objects.filter(
                    department__in=supervised_dept_ids,
                    department__task_creator__isnull=False,
                    is_active=True
                ).values_list('id', flat=True)
                
                # Build query: assigned to supervisor OR created by supervisor OR created by task creators in supervised departments
                task_query = Q(assigned_to=user) | Q(created_by=user)
                if task_creators_in_supervised_depts:
                    task_query |= Q(created_by__in=task_creators_in_supervised_depts)
                
                my_tasks_queryset = TicketTask.objects.filter(task_query).defer('deadline')
            elif is_task_creator_for_tasks:
                # Task creators see both assigned tasks and tasks they created
                my_tasks_queryset = TicketTask.objects.filter(
                    Q(assigned_to=user) | Q(created_by=user)
                ).defer('deadline')
            else:
                # Regular employees only see tasks assigned to them
                my_tasks_queryset = TicketTask.objects.filter(assigned_to=user).defer('deadline')
            
            my_tasks = my_tasks_queryset.order_by('-created_at')[:5]
            my_tasks_count = my_tasks_queryset.count()
            my_open_tasks_count = my_tasks_queryset.filter(status='open').count()
            my_resolved_tasks_count = my_tasks_queryset.filter(status__in=['resolved', 'closed']).count()
            
            if user.department_role == 'manager':
                # Manager dashboard - can see all tickets across the company
                # Get all tickets (EXCLUDING manager's own tickets to avoid duplication)
                all_tickets = Ticket.objects.all().exclude(created_by=user).order_by('-created_at')[:5]
                # Get manager's own tickets (these will NOT appear in all tickets)
                my_tickets = Ticket.objects.filter(created_by=user).order_by('-created_at')[:5]
                # Get task tickets assigned to manager by IT managers/technicians
                task_tickets = Ticket.objects.filter(assigned_to=user).order_by('-created_at')[:5]
                # Only replies to manager's own tickets
                recent_replies = Reply.objects.filter(ticket__created_by=user).order_by('-created_at')[:3]
                
                context = {
                    'all_tickets': all_tickets,
                    'my_tickets': my_tickets,
                    'task_tickets': task_tickets,
                    'recent_replies': recent_replies,
                    'total_tickets': Ticket.objects.filter(created_by=user).count(),
                    'open_tickets': Ticket.objects.filter(created_by=user, status='open').count(),
                    'resolved_tickets': Ticket.objects.filter(created_by=user, status='resolved').count(),
                    'my_total_tickets': Ticket.objects.filter(created_by=user).count(),
                    'my_open_tickets': Ticket.objects.filter(created_by=user, status='open').count(),
                    'my_resolved_tickets': Ticket.objects.filter(created_by=user, status='resolved').count(),
                    'all_total_tickets': Ticket.objects.all().count(),
                    'all_open_tickets': Ticket.objects.filter(status='open').count(),
                    'all_resolved_tickets': Ticket.objects.filter(status='resolved').count(),
                    'task_total_tickets': Ticket.objects.filter(assigned_to=user).count(),
                    'task_open_tickets': Ticket.objects.filter(assigned_to=user, status='open').count(),
                    'task_resolved_tickets': Ticket.objects.filter(assigned_to=user, status='resolved').count(),
                    'my_tasks': my_tasks,
                    'my_tasks_count': my_tasks_count,
                    'my_open_tasks_count': my_open_tasks_count,
                    'my_resolved_tasks_count': my_resolved_tasks_count,
                    'is_manager': True,
                    'can_create_tasks': can_create_tasks,
                }
            elif user.department_role == 'senior':
                # Senior employee dashboard - can see tickets from all supervised departments
                try:
                    supervised_depts = user.get_supervised_departments()
                    # Ensure it's always a list
                    if not isinstance(supervised_depts, list):
                        supervised_depts = []
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Dashboard error - get_supervised_departments: {e}", exc_info=True)
                    supervised_depts = []
                
                # Initialize variables
                departments_that_can_receive = []
                can_receive = False
                
                if supervised_depts:
                    # Get department tickets from all supervised departments (EXCLUDING senior's own tickets)
                    department_tickets = Ticket.objects.filter(
                        created_by__department__in=[d.id for d in supervised_depts]
                    ).exclude(created_by=user).order_by('-created_at')[:5]
                    # Get senior's own tickets
                    my_tickets = Ticket.objects.filter(created_by=user).order_by('-created_at')[:5]
                    # Get task tickets assigned to senior
                    task_tickets = Ticket.objects.filter(assigned_to=user).order_by('-created_at')[:5]
                    recent_replies = Reply.objects.filter(
                        ticket__created_by__department__in=[d.id for d in supervised_depts]
                    ).order_by('-created_at')[:3]
                    
                    # Get received tickets from all supervised departments that can receive tickets
                    departments_that_can_receive = [d for d in supervised_depts if d.can_receive_tickets]
                    received_tickets = None
                    received_total_tickets = 0
                    received_open_tickets = 0
                    received_resolved_tickets = 0
                    
                    if departments_that_can_receive:
                        received_tickets = Ticket.objects.filter(
                            target_department__in=[d.id for d in departments_that_can_receive]
                        ).order_by('-created_at')[:5]
                        received_total_tickets = Ticket.objects.filter(
                            target_department__in=[d.id for d in departments_that_can_receive]
                        ).count()
                        received_open_tickets = Ticket.objects.filter(
                            target_department__in=[d.id for d in departments_that_can_receive],
                            status='open'
                        ).count()
                        received_resolved_tickets = Ticket.objects.filter(
                            target_department__in=[d.id for d in departments_that_can_receive],
                            status='resolved'
                        ).count()
                    
                    # Check if user is ticket responder for any department
                    is_ticket_responder = any(
                        d.can_receive_tickets and d.ticket_responder == user 
                        for d in supervised_depts
                    )
                else:
                    # Fallback to old behavior if no supervised departments (backward compatibility)
                    if user.department:
                        department_tickets = Ticket.objects.filter(created_by__department=user.department).exclude(created_by=user).order_by('-created_at')[:5]
                        my_tickets = Ticket.objects.filter(created_by=user).order_by('-created_at')[:5]
                        task_tickets = Ticket.objects.filter(assigned_to=user).order_by('-created_at')[:5]
                        recent_replies = Reply.objects.filter(ticket__created_by__department=user.department).order_by('-created_at')[:3]
                        
                        can_receive = user.department.can_receive_tickets
                        is_ticket_responder = (user.department.can_receive_tickets and user.department.ticket_responder == user)
                        received_tickets = None
                        received_total_tickets = 0
                        received_open_tickets = 0
                        received_resolved_tickets = 0
                        
                        if can_receive:
                            received_tickets = Ticket.objects.filter(target_department=user.department).order_by('-created_at')[:5]
                            received_total_tickets = Ticket.objects.filter(target_department=user.department).count()
                            received_open_tickets = Ticket.objects.filter(target_department=user.department, status='open').count()
                            received_resolved_tickets = Ticket.objects.filter(target_department=user.department, status='resolved').count()
                    else:
                        department_tickets = Ticket.objects.none()
                        my_tickets = Ticket.objects.filter(created_by=user).order_by('-created_at')[:5]
                        task_tickets = Ticket.objects.filter(assigned_to=user).order_by('-created_at')[:5]
                        recent_replies = Reply.objects.none()
                        is_ticket_responder = False
                        received_tickets = None
                        received_total_tickets = 0
                        received_open_tickets = 0
                        received_resolved_tickets = 0
                
                # Calculate statistics for all supervised departments
                supervised_dept_ids = [d.id for d in supervised_depts] if supervised_depts else ([user.department.id] if user.department else [])
                
                # Check if user has warehouse access (supervisor of any department with warehouse enabled)
                has_warehouse_access = False
                warehouse_departments = []
                if supervised_depts:
                    warehouse_departments = [d for d in supervised_depts if d.has_warehouse]
                    has_warehouse_access = len(warehouse_departments) > 0
                elif user.department:
                    has_warehouse_access = user.department.has_warehouse
                    if has_warehouse_access:
                        warehouse_departments = [user.department]
                
                context = {
                    'department_tickets': department_tickets,
                    'received_tickets': received_tickets,
                    'my_tickets': my_tickets,
                    'task_tickets': task_tickets,
                    'recent_replies': recent_replies,
                    'total_tickets': Ticket.objects.filter(created_by=user).count(),
                    'open_tickets': Ticket.objects.filter(created_by=user, status='open').count(),
                    'resolved_tickets': Ticket.objects.filter(created_by=user, status='resolved').count(),
                    'my_total_tickets': Ticket.objects.filter(created_by=user).count(),
                    'my_open_tickets': Ticket.objects.filter(created_by=user, status='open').count(),
                    'my_resolved_tickets': Ticket.objects.filter(created_by=user, status='resolved').count(),
                    'department_total_tickets': Ticket.objects.filter(created_by__department__in=supervised_dept_ids).count() if supervised_dept_ids else 0,
                    'department_open_tickets': Ticket.objects.filter(created_by__department__in=supervised_dept_ids, status='open').count() if supervised_dept_ids else 0,
                    'department_resolved_tickets': Ticket.objects.filter(created_by__department__in=supervised_dept_ids, status='resolved').count() if supervised_dept_ids else 0,
                    'received_total_tickets': received_total_tickets,
                    'received_open_tickets': received_open_tickets,
                    'received_resolved_tickets': received_resolved_tickets,
                    'can_receive_tickets': bool(departments_that_can_receive) if supervised_depts else can_receive,
                    'has_warehouse_access': has_warehouse_access,
                    'warehouse_departments': warehouse_departments,
                    'task_total_tickets': Ticket.objects.filter(assigned_to=user).count(),
                    'task_open_tickets': Ticket.objects.filter(assigned_to=user, status='open').count(),
                    'task_resolved_tickets': Ticket.objects.filter(assigned_to=user, status='resolved').count(),
                    'my_tasks': my_tasks,
                    'my_tasks_count': my_tasks_count,
                    'my_open_tasks_count': my_open_tasks_count,
                    'my_resolved_tasks_count': my_resolved_tasks_count,
                    'is_senior': True,
                    'supervised_departments': supervised_depts if supervised_depts else [],
                    'department_name': supervised_depts[0] if supervised_depts and len(supervised_depts) > 0 else (user.department if user.department else None),
                    'can_create_tasks': can_create_tasks,
                }
            else:
                # Regular employee dashboard
                my_tickets = Ticket.objects.filter(created_by=user).order_by('-created_at')[:5]
                # Get task tickets assigned to employee by IT managers/technicians
                task_tickets = Ticket.objects.filter(assigned_to=user).order_by('-created_at')[:5]
                recent_replies = Reply.objects.filter(ticket__created_by=user).order_by('-created_at')[:3]
                
                # Check if user is a ticket responder
                is_ticket_responder = (user.department and 
                                     user.department.can_receive_tickets and 
                                     user.department.ticket_responder == user)
                received_tickets = None
                received_total_tickets = 0
                received_open_tickets = 0
                received_resolved_tickets = 0
                
                if is_ticket_responder:
                    # Get received tickets - tickets sent to this department
                    received_tickets = Ticket.objects.filter(
                        target_department=user.department
                    ).order_by('-created_at')[:5]
                    received_total_tickets = Ticket.objects.filter(target_department=user.department).count()
                    received_open_tickets = Ticket.objects.filter(target_department=user.department, status='open').count()
                    received_resolved_tickets = Ticket.objects.filter(target_department=user.department, status='resolved').count()
                
                context = {
                    'tickets': my_tickets,  # Use 'tickets' to match template
                    'my_tickets': my_tickets,
                    'task_tickets': task_tickets,
                    'recent_replies': recent_replies,
                    'received_tickets': received_tickets,
                    'total_tickets': Ticket.objects.filter(created_by=user).count(),
                    'open_tickets': Ticket.objects.filter(created_by=user, status='open').count(),
                    'resolved_tickets': Ticket.objects.filter(created_by=user, status='resolved').count(),
                    'in_progress_tickets': Ticket.objects.filter(created_by=user, status='in_progress').count(),
                    'task_total_tickets': Ticket.objects.filter(assigned_to=user).count(),
                    'task_open_tickets': Ticket.objects.filter(assigned_to=user, status='open').count(),
                    'received_total_tickets': received_total_tickets,
                    'received_open_tickets': received_open_tickets,
                    'received_resolved_tickets': received_resolved_tickets,
                    'can_receive_tickets': is_ticket_responder,
                    'is_ticket_responder': is_ticket_responder,
                    'task_resolved_tickets': Ticket.objects.filter(assigned_to=user, status='resolved').count(),
                    'my_tasks': my_tasks,
                    'my_tasks_count': my_tasks_count,
                    'my_open_tasks_count': my_open_tasks_count,
                    'my_resolved_tasks_count': my_resolved_tasks_count,
                    'is_manager': False,
                    'is_senior': False,
                    'can_create_tasks': can_create_tasks,
                }
        
        elif user.role == 'technician':
            # Technician dashboard - only assigned IT department tickets
            # Get ticket tasks assigned to technician
            # Temporarily defer 'deadline' field until migration is applied
            my_tasks = TicketTask.objects.filter(assigned_to=user).defer('deadline').order_by('-created_at')[:5]
            my_tasks_count = TicketTask.objects.filter(assigned_to=user).defer('deadline').count()
            my_open_tasks_count = TicketTask.objects.filter(assigned_to=user, status='open').defer('deadline').count()
            my_resolved_tasks_count = TicketTask.objects.filter(assigned_to=user, status__in=['resolved', 'closed']).defer('deadline').count()
            
            it_department = get_it_department()
            if it_department:
                assigned_tickets = Ticket.objects.filter(
                    Q(assigned_to=user) & (Q(target_department__isnull=True) | Q(target_department=it_department))
                ).order_by('-created_at')[:5]
                recent_replies = Reply.objects.filter(
                    Q(ticket__assigned_to=user) & (Q(ticket__target_department__isnull=True) | Q(ticket__target_department=it_department))
                ).order_by('-created_at')[:3]
            else:
                assigned_tickets = Ticket.objects.filter(assigned_to=user).order_by('-created_at')[:5]
                recent_replies = Reply.objects.filter(ticket__assigned_to=user).order_by('-created_at')[:3]
            # Get technician's own created tickets
            my_tickets = Ticket.objects.filter(created_by=user).order_by('-created_at')[:5]
            
            # Statistics for IT department tickets only
            if it_department:
                it_assigned_tickets = Ticket.objects.filter(
                    Q(assigned_to=user) & (Q(target_department__isnull=True) | Q(target_department=it_department))
                )
                total_assigned = it_assigned_tickets.count()
                open_assigned = it_assigned_tickets.filter(status='open').count()
                in_progress = it_assigned_tickets.filter(status='in_progress').count()
                resolved_tickets = it_assigned_tickets.filter(status='resolved').count()
            else:
                total_assigned = Ticket.objects.filter(assigned_to=user).count()
                open_assigned = Ticket.objects.filter(assigned_to=user, status='open').count()
                in_progress = Ticket.objects.filter(assigned_to=user, status='in_progress').count()
                resolved_tickets = Ticket.objects.filter(assigned_to=user, status='resolved').count()
            
            context = {
                'tickets': assigned_tickets,  # Use 'tickets' to match template
                'assigned_tickets': assigned_tickets,
                'my_tickets': my_tickets,
                'recent_replies': recent_replies,
                'total_tickets': total_assigned,
                'open_tickets': open_assigned,
                'resolved_tickets': resolved_tickets,
                'in_progress_tickets': in_progress,
                'total_assigned': total_assigned,
                'open_assigned': open_assigned,
                'in_progress': in_progress,
                'total_my_tickets': Ticket.objects.filter(created_by=user).count(),
                'open_my_tickets': Ticket.objects.filter(created_by=user, status='open').count(),
                'resolved_my_tickets': Ticket.objects.filter(created_by=user, status='resolved').count(),
                'my_tasks': my_tasks,
                'my_tasks_count': my_tasks_count,
                'my_open_tasks_count': my_open_tasks_count,
                'my_resolved_tasks_count': my_resolved_tasks_count,
                'can_create_tasks': can_create_tasks,
            }
        
        elif is_admin_superuser(user):
            # Administrator dashboard - can see all tickets and manage everything
            from .services import get_it_manager_ticket_ordering
            all_tickets = Ticket.objects.exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')).order_by(*get_it_manager_ticket_ordering())[:15]
            my_tickets = Ticket.objects.filter(created_by=user).order_by('-created_at')[:5]
            recent_replies = Reply.objects.all().order_by('-created_at')[:3]
            unread_notifications = Notification.objects.filter(recipient=user, is_read=False).order_by('-created_at')
            
            # Statistics for all tickets
            all_tickets_stats = Ticket.objects.all()
            
            context = {
                'tickets': all_tickets,
                'all_tickets': all_tickets,
                'my_tickets': my_tickets,
                'recent_replies': recent_replies,
                'total_tickets': all_tickets_stats.count(),
                'open_tickets': all_tickets_stats.filter(status='open').count(),
                'resolved_tickets': all_tickets_stats.filter(status='resolved').count(),
                'in_progress_tickets': all_tickets_stats.filter(status='in_progress').count(),
                'total_my_tickets': Ticket.objects.filter(created_by=user).count(),
                'open_my_tickets': Ticket.objects.filter(created_by=user, status='open').count(),
                'resolved_my_tickets': Ticket.objects.filter(created_by=user, status='resolved').count(),
                'unread_notifications': unread_notifications[:5],
                'unread_count': unread_notifications.count(),
                'is_administrator': True,
                'can_create_tasks': can_create_tasks,
            }
        
        else:  # IT Manager
            # IT Manager dashboard - only IT department tickets
            from .services import get_it_manager_ticket_ordering
            it_department = get_it_department()
            
            # Only show tickets that:
            # 1. Have no target_department (old tickets, default to IT)
            # 2. Have target_department = IT department
            # 3. Are created by IT manager themselves
            if it_department:
                all_tickets = Ticket.objects.filter(
                    Q(target_department__isnull=True) |  # Old tickets without target_department
                    Q(target_department=it_department) |  # Tickets for IT department
                    Q(created_by=user)  # IT manager's own tickets
                ).exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')).order_by(*get_it_manager_ticket_ordering())[:15]
                
                # Statistics for IT department tickets only
                it_tickets = Ticket.objects.filter(
                    Q(target_department__isnull=True) | Q(target_department=it_department)
                )
            else:
                # Fallback: if no IT department found, show all tickets (backward compatibility)
                all_tickets = Ticket.objects.exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')).order_by(*get_it_manager_ticket_ordering())[:15]
                it_tickets = Ticket.objects.all()
            
            # Get IT manager's own created tickets
            my_tickets = Ticket.objects.filter(created_by=user).order_by('-created_at')[:5]
            
            # Get replies for IT department tickets only
            if it_department:
                recent_replies = Reply.objects.filter(
                    Q(ticket__target_department__isnull=True) | Q(ticket__target_department=it_department)
                ).order_by('-created_at')[:3]
            else:
                recent_replies = Reply.objects.all().order_by('-created_at')[:3]
            
            # Notifications (admin-only phase)
            unread_notifications = Notification.objects.filter(recipient=user, is_read=False).order_by('-created_at')

            # Get ticket tasks for IT manager
            # Temporarily defer 'deadline' field until migration is applied
            my_created_tasks = TicketTask.objects.filter(created_by=user).defer('deadline').order_by('-created_at')[:5]
            all_tasks_count = TicketTask.objects.filter(created_by=user).defer('deadline').count()
            open_tasks_count = TicketTask.objects.filter(created_by=user, status='open').defer('deadline').count()
            resolved_tasks_count = TicketTask.objects.filter(created_by=user, status__in=['resolved', 'closed']).defer('deadline').count()
            
            context = {
                'tickets': all_tickets,  # Use 'tickets' to match template
                'all_tickets': all_tickets,
                'my_tickets': my_tickets,
                'recent_replies': recent_replies,
                'unread_notifications': unread_notifications,
                'total_tickets': it_tickets.count() if it_department else Ticket.objects.count(),
                'open_tickets': it_tickets.filter(status='open').count() if it_department else Ticket.objects.filter(status='open').count(),
                'resolved_tickets': it_tickets.filter(status='resolved').count() if it_department else Ticket.objects.filter(status='resolved').count(),
                'in_progress_tickets': it_tickets.filter(status='in_progress').count() if it_department else Ticket.objects.filter(status='in_progress').count(),
                'urgent_tickets': it_tickets.filter(priority='urgent').count() if it_department else Ticket.objects.filter(priority='urgent').count(),
                'technicians': User.objects.filter(role='technician').count(),
                'total_my_tickets': Ticket.objects.filter(created_by=user).count(),
                'open_my_tickets': Ticket.objects.filter(created_by=user, status='open').count(),
                'resolved_my_tickets': Ticket.objects.filter(created_by=user, status='resolved').count(),
                'my_created_tasks': my_created_tasks,
                'all_tasks_count': all_tasks_count,
                'open_tasks_count': open_tasks_count,
                'resolved_tasks_count': resolved_tasks_count,
                'can_create_tasks': can_create_tasks,
            }
        
        # Ensure context exists before proceeding
        if 'context' not in locals():
            raise ValueError("Context variable not defined - this should not happen. User role: {}, Department role: {}".format(
                getattr(user, 'role', 'unknown'),
                getattr(user, 'department_role', 'unknown')
            ))
        
        try:
            log_debug('DASHBOARD', 'tickets/views.py:665', 'Context created successfully', {
                'context_keys': list(context.keys()),
                'context_type': type(context).__name__,
                'user_role': getattr(user, 'role', None),
                'department_role': getattr(user, 'department_role', None)
            })
        except Exception:
            pass  # Don't fail if logging fails
        
        try:
            return render(request, 'tickets/dashboard.html', context)
        except Exception as render_error:
            # If template rendering fails, log it and return error
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Dashboard template render error: {render_error}", exc_info=True)
            try:
                log_debug('DASHBOARD', 'tickets/views.py:678', 'Template render error', {
                    'error_type': type(render_error).__name__,
                    'error_message': str(render_error)
                })
            except Exception:
                pass
            raise  # Re-raise to be caught by outer exception handler
        
    except Exception as e:
        import logging
        error_traceback = traceback.format_exc()
        logger = logging.getLogger(__name__)
        
        # Get user info for debugging
        user_info = {}
        try:
            user_info = {
                'user_id': getattr(request.user, 'id', None) if request.user.is_authenticated else None,
                'user_role': getattr(request.user, 'role', None) if request.user.is_authenticated else None,
                'department_role': getattr(request.user, 'department_role', None) if request.user.is_authenticated else None,
                'is_authenticated': request.user.is_authenticated
            }
        except Exception:
            user_info = {'error': 'Could not get user info'}
        
        # Log to Django logger (this should always work)
        logger.error(f"Dashboard error: {e}", exc_info=True)
        logger.error(f"Dashboard error - User info: {user_info}")
        logger.error(f"Dashboard error - Traceback: {error_traceback}")
        
        # Try to log to debug file (may fail silently)
        try:
            log_debug('DASHBOARD', 'tickets/views.py:695', 'Dashboard exception caught', {
                'error_type': type(e).__name__,
                'error_message': str(e),
                'user_info': user_info,
                'traceback': error_traceback[:1000] if error_traceback else None
            })
        except Exception:
            pass  # Don't fail if logging fails
        
        # CRITICAL: Do NOT redirect to login if user is already authenticated
        # This would cause an infinite redirect loop:
        # Dashboard error -> redirect to login -> user authenticated -> redirect to dashboard -> repeat
        # Instead, return an error page directly
        from django.contrib import messages
        from django.http import HttpResponseServerError
        
        # Show error message to user
        messages.error(request, _('خطا در بارگذاری داشبورد. لطفاً با مدیر سیستم تماس بگیرید.'))
        
        # Return a proper error response with detailed error info (for debugging)
        # In production, you might want to hide the actual error message
        error_html = f"""
        <html dir="rtl" lang="fa">
        <head>
            <meta charset="UTF-8">
            <title>خطا در بارگذاری داشبورد</title>
            <style>
                body {{ font-family: Tahoma, Arial, sans-serif; padding: 2rem; background: #f5f5f5; }}
                .error-box {{ background: white; padding: 2rem; border-radius: 8px; max-width: 800px; margin: 0 auto; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                h1 {{ color: #dc3545; }}
                .error-details {{ background: #f8f9fa; padding: 1rem; border-radius: 4px; margin: 1rem 0; font-family: monospace; font-size: 0.9em; }}
            </style>
        </head>
        <body>
            <div class="error-box">
                <h1>خطا در بارگذاری داشبورد</h1>
                <p>متأسفانه خطایی در بارگذاری داشبورد رخ داده است.</p>
                <p>لطفاً با مدیر سیستم تماس بگیرید.</p>
                <div class="error-details">
                    <strong>نوع خطا:</strong> {type(e).__name__}<br>
                    <strong>پیام خطا:</strong> {str(e)}<br>
                    <strong>نقش کاربر:</strong> {user_info.get('user_role', 'نامشخص')}<br>
                    <strong>نقش بخش:</strong> {user_info.get('department_role', 'نامشخص')}
                </div>
                <p><a href="/login/">بازگشت به صفحه ورود</a></p>
            </div>
        </body>
        </html>
        """
        return HttpResponseServerError(error_html)

@login_required
def view_all_replies(request):
    """View all replies with role-based filtering"""
    user = request.user
    search_query = request.GET.get('search', '')
    
    # Base query for replies based on user role
    if is_admin_superuser(user):
        # Administrator can see all replies
        replies = Reply.objects.all()
    elif user.role == 'employee':
        if user.department_role in ['manager', 'senior']:
            # Team leaders and general managers should only see replies to their own tickets
            replies = Reply.objects.filter(ticket__created_by=user)
        else:
            # Regular employee can only see replies to their own tickets
            replies = Reply.objects.filter(ticket__created_by=user)
    elif user.role == 'technician':
        # Technician can see replies to tickets assigned to them
        replies = Reply.objects.filter(ticket__assigned_to=user)
    else:  # IT Manager
        # IT Manager should see replies only for IT department tickets
        it_department = get_it_department()
        if it_department:
            replies = Reply.objects.filter(
                Q(ticket__target_department__isnull=True) | Q(ticket__target_department=it_department)
            )
        else:
            # Fallback: show all replies if no IT department found
            replies = Reply.objects.all()
    
    # Apply search filter (only ticket ID, creator name, and title)
    if search_query:
        # Normalize Persian digits to Latin for search compatibility
        from tickets.templatetags.persian_numbers import _persian_to_latin
        normalized_query = _persian_to_latin(search_query)
        
        replies = replies.filter(
            Q(ticket__id__icontains=normalized_query) |
            Q(ticket__created_by__first_name__icontains=normalized_query) |
            Q(ticket__created_by__last_name__icontains=normalized_query) |
            Q(ticket__title__icontains=normalized_query)
        )
    
    # Order by creation date (newest first)
    replies = replies.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(replies, 20)  # 20 replies per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'replies': page_obj,
        'search_query': search_query,
    }
    
    return render(request, 'tickets/view_replies.html', context)

@login_required
def ticket_list(request):
    """Ticket list view with role-based filtering"""
    user = request.user
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    my_tickets_filter = request.GET.get('my_tickets', '')
    department_filter = request.GET.get('department', '')
    all_tickets_filter = request.GET.get('all_tickets', '')
    task_tickets_filter = request.GET.get('task_tickets', '')
    
    if user.role == 'employee':
        if user.department_role == 'manager':
            # Manager can see all tickets across the company
            if all_tickets_filter:
                # Show all tickets (excluding manager's own tickets)
                tickets = Ticket.objects.all().exclude(created_by=user)
            elif my_tickets_filter:
                # Show only my tickets
                tickets = Ticket.objects.filter(created_by=user)
            elif task_tickets_filter:
                # Show only task tickets assigned to user
                tickets = Ticket.objects.filter(assigned_to=user)
            else:
                # Default: show my tickets (not all tickets)
                tickets = Ticket.objects.filter(created_by=user)
        elif user.department_role == 'senior':
            # Senior employees can see all tickets from their supervised departments
            supervised_depts = user.get_supervised_departments()
            supervised_dept_ids = [d.id for d in supervised_depts] if supervised_depts else ([user.department.id] if user.department else [])
            
            if department_filter:
                # Show only department tickets from all supervised departments (excluding senior's own tickets)
                tickets = Ticket.objects.filter(created_by__department__in=supervised_dept_ids).exclude(created_by=user) if supervised_dept_ids else Ticket.objects.none()
            elif my_tickets_filter:
                # Show only my tickets
                tickets = Ticket.objects.filter(created_by=user)
            elif task_tickets_filter:
                # Show only task tickets assigned to user
                tickets = Ticket.objects.filter(assigned_to=user)
            else:
                # Default: show my tickets (not department tickets)
                tickets = Ticket.objects.filter(created_by=user)
        else:
            # Regular employees only see their own tickets
            tickets = Ticket.objects.filter(created_by=user)
    elif is_admin_superuser(user):
        # Administrator can see all tickets
        tickets = Ticket.objects.exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending'))
    elif user.role == 'technician':
        # Technicians should not see access tickets pending approval
        # Also filter to only show IT department tickets
        it_department = get_it_department()
        if it_department:
            tickets = Ticket.objects.filter(
                Q(assigned_to=user) & (Q(target_department__isnull=True) | Q(target_department=it_department))
            ).exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending'))
        else:
            tickets = Ticket.objects.filter(assigned_to=user).exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending'))
    else:  # IT Manager
        from .services import get_it_manager_ticket_ordering
        it_department = get_it_department()
        
        # Only show tickets that:
        # 1. Have no target_department (old tickets, default to IT)
        # 2. Have target_department = IT department
        # 3. Are created by IT manager themselves
        if it_department:
            tickets = Ticket.objects.filter(
                Q(target_department__isnull=True) |  # Old tickets without target_department
                Q(target_department=it_department) |  # Tickets for IT department
                Q(created_by=user)  # IT manager's own tickets
            ).exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')).order_by(*get_it_manager_ticket_ordering())
        else:
            # Fallback: if no IT department found, show all tickets (backward compatibility)
            tickets = Ticket.objects.exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')).order_by(*get_it_manager_ticket_ordering())
    
    # Apply filters
    if search_query:
        # Normalize Persian digits to Latin for search compatibility
        # This allows users to search with either Persian (#۱۲۳) or Latin (#123) digits
        from tickets.templatetags.persian_numbers import _persian_to_latin
        normalized_query = _persian_to_latin(search_query)
        
        # Remove hash prefix if present for ID search
        query_for_id = normalized_query.lstrip('#')
        
        # Check if search query is a number (potential ticket ID)
        try:
            ticket_id = int(query_for_id)
            # If it's a number, search by ID first, then by other fields
            tickets = tickets.filter(
                Q(id=ticket_id) |
                Q(title__icontains=normalized_query) |
                Q(description__icontains=normalized_query) |
                Q(created_by__first_name__icontains=normalized_query) |
                Q(created_by__last_name__icontains=normalized_query)
            )
        except ValueError:
            # If it's not a number, search by text fields only (using normalized query)
            tickets = tickets.filter(
                Q(title__icontains=normalized_query) |
                Q(description__icontains=normalized_query) |
                Q(created_by__first_name__icontains=normalized_query) |
                Q(created_by__last_name__icontains=normalized_query)
            )
    
    if status_filter:
        tickets = tickets.filter(status=status_filter)
    
    if priority_filter:
        # Support multiple priorities separated by comma
        if ',' in priority_filter:
            priorities = [p.strip() for p in priority_filter.split(',')]
            tickets = tickets.filter(priority__in=priorities)
        else:
            tickets = tickets.filter(priority=priority_filter)
    
    # Pagination
    paginator = Paginator(tickets, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'department_filter': department_filter,
        'my_tickets_filter': my_tickets_filter,
        'all_tickets_filter': all_tickets_filter,
        'task_tickets_filter': task_tickets_filter,
        'status_choices': Ticket.STATUS_CHOICES,
        'priority_choices': Ticket.PRIORITY_CHOICES,
    }
    
    return render(request, 'tickets/ticket_list.html', context)

@login_required
def received_tickets_list(request):
    """View for department supervisors and ticket responders to see tickets received by their department"""
    user = request.user
    
    # Check if user is a supervisor (has at least one supervised department) or ticket responder
    supervised_depts = user.get_supervised_departments() if user.department_role == 'senior' else []
    is_supervisor = (user.role == 'employee' and user.department_role == 'senior' and len(supervised_depts) > 0)
    is_ticket_responder = (user.role == 'employee' and 
                          user.department and 
                          user.department.can_receive_tickets and 
                          user.department.ticket_responder == user)
    
    if not (is_supervisor or is_ticket_responder):
        messages.error(request, _('دسترسی رد شد. فقط سرپرست بخش یا پاسخ‌دهنده تیکت می‌تواند تیکت‌های دریافتی را مشاهده کند.'))
        return redirect('tickets:dashboard')
    
    # Check if the department can receive tickets
    if not user.department.can_receive_tickets:
        messages.error(request, _('بخش شما قابلیت دریافت تیکت را ندارد. لطفاً با مدیر IT تماس بگیرید.'))
        return redirect('tickets:dashboard')
    
    # Get tickets that were sent to any of the supervised departments
    supervised_dept_ids = [d.id for d in supervised_depts]
    tickets = Ticket.objects.filter(
        target_department__in=supervised_dept_ids
    ).order_by('-created_at') if supervised_dept_ids else Ticket.objects.none()
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        # Normalize Persian digits to Latin for search compatibility
        from tickets.templatetags.persian_numbers import _persian_to_latin
        normalized_query = _persian_to_latin(search_query)
        
        tickets = tickets.filter(
            Q(title__icontains=normalized_query) |
            Q(description__icontains=normalized_query) |
            Q(created_by__first_name__icontains=normalized_query) |
            Q(created_by__last_name__icontains=normalized_query)
        )
    
    # Status filter
    status_filter = request.GET.get('status', '')
    if status_filter:
        tickets = tickets.filter(status=status_filter)
    
    # Pagination
    paginator = Paginator(tickets, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'status_choices': Ticket.STATUS_CHOICES,
        'priority_choices': Ticket.PRIORITY_CHOICES,
        'department': user.department,
    }
    
    return render(request, 'tickets/received_tickets.html', context)

@login_required
def ticket_detail(request, ticket_id):
    """Ticket detail view with replies"""
    user = request.user
    
    if user.role == 'employee':
        if user.department_role == 'manager':
            # Manager can see all tickets across the company
            ticket = get_object_or_404(Ticket, id=ticket_id)
        elif user.department_role == 'senior':
            # Senior employees can see tickets from their supervised departments OR tickets received by their supervised departments
            supervised_depts = user.get_supervised_departments()
            supervised_dept_ids = [d.id for d in supervised_depts] if supervised_depts else ([user.department.id] if user.department else [])
            
            if supervised_dept_ids:
                ticket = get_object_or_404(
                    Ticket.objects.filter(
                        Q(created_by__department__in=supervised_dept_ids, created_by__isnull=False) | 
                        Q(target_department__in=supervised_dept_ids)
                    ),
                    id=ticket_id
                )
            else:
                # Fallback if no supervised departments
                ticket = get_object_or_404(Ticket, id=ticket_id, created_by=user)
        elif user.department and user.department.can_receive_tickets and user.department.ticket_responder == user:
            # Ticket responder can see their own tickets, tickets received by their department, OR task tickets assigned to them
            ticket = get_object_or_404(
                Ticket.objects.filter(
                    Q(created_by=user) | 
                    Q(target_department=user.department) | 
                    Q(assigned_to=user)
                ),
                id=ticket_id
            )
        else:
            # Regular employees can see their own tickets OR task tickets assigned to them
            ticket = get_object_or_404(
                Ticket.objects.filter(
                    Q(created_by=user) | Q(assigned_to=user)
                ),
                id=ticket_id
            )
    elif user.role == 'technician':
        # Technicians cannot see pending access tickets and only IT department tickets
        it_department = get_it_department()
        if it_department:
            ticket = get_object_or_404(
                Ticket.objects.filter(
                    Q(assigned_to=user) & (Q(target_department__isnull=True) | Q(target_department=it_department))
                ).exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')),
                id=ticket_id
            )
        else:
            ticket = get_object_or_404(Ticket.objects.exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')), id=ticket_id, assigned_to=user)
    else:  # IT Manager
        # IT Manager cannot see pending access tickets until approved
        # IT Manager can only see IT department tickets
        it_department = get_it_department()
        if it_department:
            ticket = get_object_or_404(
                Ticket.objects.filter(
                    Q(target_department__isnull=True) | Q(target_department=it_department) | Q(created_by=user)
                ).exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')),
                id=ticket_id
            )
        else:
            ticket = get_object_or_404(Ticket.objects.exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')), id=ticket_id)
    
    # Get filtered replies based on user permissions
    try:
        from .services import get_filtered_replies_for_user
        replies = get_filtered_replies_for_user(ticket, user)
    except Exception as e:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting filtered replies: {e}")
        logger.error(traceback.format_exc())
        # Fallback to empty queryset - use Reply.objects.none() instead of ticket.replies.none()
        from .models import Reply
        replies = Reply.objects.none()

    # Senior approval actions
    if request.method == 'POST' and request.user.role == 'employee' and request.user.department_role == 'senior':
        # Check if ticket requires supervisor approval (using ticket_category.requires_supervisor_approval)
        requires_approval = ticket.ticket_category and ticket.ticket_category.requires_supervisor_approval
        if request.POST.get('access_approval_action') in ['approve', 'reject']:
            # Validate all conditions and provide specific error messages
            if not requires_approval:
                messages.error(request, _('این تیکت نیاز به تایید سرپرست ندارد.'))
            elif ticket.access_approval_status != 'pending':
                messages.error(request, _('این تیکت در وضعیت انتظار تایید نیست. وضعیت فعلی: {status}').format(
                    status=ticket.get_access_approval_status_display() if hasattr(ticket, 'get_access_approval_status_display') else ticket.access_approval_status
                ))
            elif not ticket.created_by:
                messages.error(request, _('تیکت ایجادکننده ندارد.'))
            elif not ticket.created_by.department:
                messages.error(request, _('بخش ایجادکننده تیکت مشخص نیست.'))
            elif not request.user.is_supervisor_of(ticket.created_by.department):
                # Provide more detailed error message
                creator_dept = ticket.created_by.department.name if ticket.created_by.department else _('نامشخص')
                user_depts = [d.name for d in request.user.get_supervised_departments()] if hasattr(request.user, 'get_supervised_departments') else []
                messages.error(request, _('شما سرپرست بخش "{dept}" نیستید. بخش‌های تحت سرپرستی شما: {supervised}').format(
                    dept=creator_dept,
                    supervised=', '.join(user_depts) if user_depts else _('هیچ بخشی')
                ))
            else:
                # All conditions met, proceed with approval/rejection
                action = request.POST['access_approval_action']
                if action == 'approve':
                    ticket.access_approval_status = 'approved'
                    ticket.save(update_fields=['access_approval_status'])
                    # Create notification for IT managers about access approval
                    try:
                        from .models import Notification
                        it_managers = User.objects.filter(role='it_manager')
                        for manager in it_managers:
                            created_by_name = ticket.created_by.get_full_name() if ticket.created_by else _('نامشخص')
                            department_display = ticket.created_by.get_department_display() if (ticket.created_by and ticket.created_by.department) else _('نامشخص')
                            Notification.objects.create(
                                recipient=manager,
                                title=f"تایید دسترسی شبکه: {ticket.title}",
                                message=f"کاربر: {created_by_name}\nسرپرست تایید کننده: {request.user.get_full_name()}\nبخش: {department_display}",
                                notification_type='access_approved',
                                category='access',
                                ticket=ticket,
                                user_actor=request.user
                            )
                    except Exception:
                        pass
                    # After approval, notify IT manager about the ticket
                    created_by_name = ticket.created_by.get_full_name() if ticket.created_by else _('نامشخص')
                    department_display = ticket.created_by.get_department_display() if (ticket.created_by and ticket.created_by.department) else _('نامشخص')
                    notify_it_manager(
                        action_type='access_approved',
                        ticket=ticket,
                        user=request.user,
                        additional_info=(
                            f"تاییدکننده: {request.user.get_full_name()}\n"
                            f"بخش: {department_display}\n"
                            f"ایجادکننده: {created_by_name}\n"
                            f"توضیحات: {ticket.description}"
                        )
                    )
                    messages.success(request, _('درخواست دسترسی شبکه تایید شد و برای مدیر IT ارسال گردید.'))
                    return redirect('tickets:ticket_detail', ticket_id=ticket.id)
                else:
                    # On reject, delete the ticket entirely
                    ticket.delete()
                    messages.warning(request, _('درخواست دسترسی شبکه توسط سرپرست رد و حذف شد.'))
                    return redirect('tickets:ticket_list')
    
    # Initialize forms
    reply_form = ReplyForm()
    
    status_form = None
    # Allow status form for IT managers, technicians, department supervisors (seniors), and ticket responders for received tickets
    can_change_status = False
    try:
        if user.role in ['it_manager', 'technician']:
            can_change_status = True
            status_form = TicketStatusForm(instance=ticket, user=user)
            status_form.user = user  # Store user for the save method
            status_form.request = request  # Store request for messages
        elif user.role == 'employee' and user.department:
            # Check if user is supervisor or ticket responder
            # Safely check target_department
            # Check if user is supervisor of the ticket's target department
            is_supervisor = (user.department_role == 'senior' and 
                           ticket.target_department and 
                           user.is_supervisor_of(ticket.target_department))
            # Ticket responder can change status for:
            # 1. Tickets received by their department (target_department matches)
            # 2. Tickets assigned to them (assigned_to matches)
            is_ticket_responder = (user.department.can_receive_tickets and 
                                  user.department.ticket_responder == user and 
                                  ((ticket.target_department and ticket.target_department == user.department) or
                                   (ticket.assigned_to == user)))
            
            if is_supervisor or is_ticket_responder:
                can_change_status = True
                status_form = TicketStatusForm(instance=ticket, user=user)
                status_form.user = user  # Store user for the save method
                status_form.request = request  # Store request for messages
    except Exception as e:
        # Log the error but don't break the page
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"Error initializing status form: {e}")
        logger.error(traceback.format_exc())
        can_change_status = False
        status_form = None
    
    if request.method == 'POST':
        # Check if this is a status update form submission
        if 'status' in request.POST and can_change_status:
            # Store original status BEFORE creating the form instance
            original_status = ticket.status
            
            status_form = TicketStatusForm(request.POST, instance=ticket, user=user)
            status_form.user = user  # Store user for the save method
            status_form.request = request  # Store request for messages
            if status_form.is_valid():
                # Save the form (this may trigger auto-status changes)
                status_form.save()
                
                # Refresh the ticket object to get the final status after all auto-changes
                ticket.refresh_from_db()
                
                # Only send notification if status actually changed
                if original_status != ticket.status:
                    try:
                        # Notify IT manager only for IT department tickets
                        it_department = get_it_department()
                        if it_department and (ticket.target_department == it_department or ticket.target_department is None):
                            from tickets.services import get_status_display_persian as _pers
                            _prev = _pers(original_status)
                            _new = _pers(ticket.status)
                            notify_it_manager(
                                action_type='status_change',
                                ticket=ticket,
                                user=request.user,
                                additional_info=f"وضعیت قبلی: {_prev}\nوضعیت جدید: {_new}"
                            )
                        
                        # Create notification for IT managers about status change to resolved (only for IT tickets)
                        if ticket.status == 'resolved' and it_department and (ticket.target_department == it_department or ticket.target_department is None):
                            try:
                                from .models import Notification
                                from .services import get_status_display_persian
                                it_managers = User.objects.filter(role='it_manager')
                                for manager in it_managers:
                                    status_persian = get_status_display_persian(ticket.status)
                                    Notification.objects.create(
                                        recipient=manager,
                                        title=f"تغییر وضعیت تیکت به انجام شده: {ticket.title}",
                                        message=f"وضعیت جدید: {status_persian}",
                                        notification_type='status_done',
                                        category='tickets',
                                        ticket=ticket,
                                        user_actor=request.user
                                    )
                            except Exception:
                                pass
                        
                        # Notify employee about status change
                        notify_employee_ticket_status_changed(ticket, request.user)
                        messages.success(request, _('وضعیت تیکت با موفقیت بروزرسانی شد.'))
                    except Exception as e:
                        print(f"⚠️ Error in status change notification: {e}")
                        messages.warning(request, _('وضعیت تیکت بروزرسانی شد اما در ارسال اعلان مشکلی پیش آمد.'))
                else:
                    # Status didn't change
                    messages.info(request, _('وضعیت تیکت تغییر نکرد.'))
                
                return redirect('tickets:ticket_detail', ticket_id=ticket.id)
            else:
                # Form validation failed - show form errors
                error_messages = []
                for field, errors in status_form.errors.items():
                    for error in errors:
                        error_messages.append(f"{field}: {error}")
                if error_messages:
                    messages.error(request, _('خطا در بروزرسانی وضعیت تیکت: ') + '; '.join(error_messages))
                else:
                    messages.error(request, _('خطا در بروزرسانی وضعیت تیکت. لطفاً اطلاعات را بررسی کنید.'))
        else:
            # This is a reply form submission
            reply_form = ReplyForm(request.POST, request.FILES)
            reply_form.user = user  # Set user for activity logging
            if reply_form.is_valid():
                reply = reply_form.save(commit=False)
                reply.ticket = ticket
                reply.author = user
                reply._activity_user = user  # Also set directly for signal
                
                # Handle private reply logic
                if reply.is_private and user.role == 'it_manager':
                    # Private replies are only visible to the ticket creator
                    reply.is_private = True
                else:
                    # Non-IT managers cannot send private replies
                    reply.is_private = False
                
                reply.save()
                # Notify IT manager only for IT department tickets
                it_department = get_it_department()
                if it_department and (ticket.target_department == it_department or ticket.target_department is None):
                    notify_it_manager(
                        action_type='reply',
                        ticket=ticket,
                        user=user,
                        additional_info=reply.content
                    )
                    
                    # Create notification for IT managers about new reply (only if from ticket creator/employee)
                    # Use create_notification which has self-exclusion built-in
                    try:
                        from .services import create_notification, get_user_role_display
                        it_managers = User.objects.filter(role='it_manager')
                        for manager in it_managers:
                            # Only notify if reply is from ticket creator (employee), not from IT staff
                            if user.role == 'employee' and user.id == ticket.created_by.id:
                                create_notification(
                                    recipient=manager,
                                    title=f"پاسخ جدید به تیکت: {ticket.title}",
                                    message=f"کاربر پاسخ دهنده: {user.get_full_name()}\nنقش: {get_user_role_display(user)}\nمحتوا: {'[پاسخ محرمانه]' if reply.is_private else reply.content[:100]}{'...' if not reply.is_private and len(reply.content) > 100 else ''}",
                                    notification_type='ticket_urgent',  # Using existing type for replies
                                    category='tickets',
                                    ticket=ticket,
                                    user_actor=user
                                )
                    except Exception:
                        pass
                
                # Notify employee about reply (only if reply is from IT Manager or Technician)
                if user.role in ['it_manager', 'technician']:
                    notify_employee_ticket_replied(ticket, reply)
                
                # Manual State Control: Reply operations do not change ticket status
                # Status must be changed explicitly via the status update interface

                messages.success(request, _('پاسخ با موفقیت اضافه شد.'))
                return redirect('tickets:ticket_detail', ticket_id=ticket.id)
    
    # Check if user came from department tickets view or all tickets view
    came_from_department = False
    came_from_all_tickets = False
    if user.role == 'employee' and user.department_role == 'senior':
        # Check if the user came from a department tickets URL
        referer = request.META.get('HTTP_REFERER', '')
        if 'department=1' in referer:
            came_from_department = True
    elif user.role == 'employee' and user.department_role == 'manager':
        # Check if the user came from an all tickets URL
        referer = request.META.get('HTTP_REFERER', '')
        if 'all_tickets=1' in referer:
            came_from_all_tickets = True
    
    # Safely check if user can approve access
    can_approve_access = False
    if (request.user.role == 'employee' and 
        request.user.department_role == 'senior' and 
        ticket.created_by and 
        ticket.created_by.department and 
        request.user.is_supervisor_of(ticket.created_by.department)):
        can_approve_access = True
    
    # Track first view by assigned person, ticket responder, technician, or IT manager (only for open tickets)
    if ticket.status == 'open' and ticket.created_by and ticket.created_by != user:
        # Check if user is the assigned person, ticket responder, technician, or IT manager
        is_assigned_person = (ticket.assigned_to == user)
        is_ticket_responder = (user.department and 
                              user.department.can_receive_tickets and 
                              user.department.ticket_responder == user and 
                              ticket.target_department == user.department)
        is_technician_or_it_manager = (user.role in ['technician', 'it_manager'])
        
        if is_assigned_person or is_ticket_responder or is_technician_or_it_manager:
            # Check if this is the first time this user is viewing the ticket
            has_viewed = TicketActivityLog.objects.filter(
                ticket=ticket,
                user=user,
                action='viewed'
            ).exists()
            
            if not has_viewed:
                # Log the view
                TicketActivityLog.objects.create(
                    ticket=ticket,
                    user=user,
                    action='viewed',
                    description=_('تیکت برای اولین بار مشاهده شد'),
                    new_value=user.get_full_name() or user.username
                )
                
                # Send email to ticket creator
                try:
                    from .services import notify_employee
                    viewer_name = user.get_full_name() or user.username
                    if user.department:
                        viewer_display = f"{user.department.name} ({viewer_name})"
                    else:
                        viewer_display = viewer_name
                    
                    notify_employee(
                        action_type='view',
                        ticket=ticket,
                        user=user,
                        additional_info=f"تیکت شما توسط {viewer_display} مشاهده شد."
                    )
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error sending view notification email: {e}", exc_info=True)
    
    context = {
        'ticket': ticket,
        'replies': replies,
        'reply_form': reply_form,
        'status_form': status_form,
        'can_change_status': can_change_status,
        'requires_access_approval': ticket.ticket_category and ticket.ticket_category.requires_supervisor_approval and ticket.access_approval_status == 'pending',
        'can_approve_access': can_approve_access,
        'came_from_department': came_from_department,
        'came_from_all_tickets': came_from_all_tickets,
    }
    
    return render(request, 'tickets/ticket_detail.html', context)

@login_required
def ticket_create(request):
    """Create new ticket (Employees, IT Managers, Technicians)"""
    user = request.user
    
    if user.role == 'employee':
        # Regular employees can only create support tickets
        if request.method == 'POST':
            form = TicketForm(request.POST, request.FILES, user=user)
            if form.is_valid():
                ticket = form.save(commit=False)
                ticket.created_by = request.user
                ticket._activity_user = request.user  # Set for activity logging
                
                # Set branch, target_department, and ticket_category from form
                ticket.branch = form.cleaned_data.get('branch')
                ticket.target_department = form.cleaned_data.get('target_department')
                ticket.ticket_category = form.cleaned_data.get('ticket_category')  # Explicitly set the new category field
                
                # Determine if approval is needed based on ticket_category.requires_supervisor_approval and user role
                if ticket.ticket_category and ticket.ticket_category.requires_supervisor_approval:
                    if user.department_role in ['senior', 'manager']:
                        # Senior employees and managers don't need approval even if category requires it
                        ticket.access_approval_status = 'not_required'
                    else:
                        # Regular employees need senior approval for categories that require it
                        ticket.access_approval_status = 'pending'
                else:
                    # Categories that don't require approval, or legacy tickets without ticket_category
                    ticket.access_approval_status = 'not_required'
                
                ticket.save()
                
                # Get target department and IT department
                target_dept = ticket.target_department
                it_department = get_it_department()
                
                # Now handle notifications after ticket is saved
                #
                # IMPORTANT ROUTING RULE:
                #   - If user explicitly selected a department in the form, the ticket
                #     belongs ONLY to that department.
                #   - IT Manager should only be notified when the selected department
                #     IS the IT department (or for legacy tickets without a target_department).
                if ticket.ticket_category and ticket.ticket_category.requires_supervisor_approval:
                    if user.department_role in ['senior', 'manager']:
                        # Tickets requiring approval created by seniors/managers - no approval needed
                        if target_dept == it_department or not target_dept:
                            # Ticket is explicitly for IT (or legacy without target)
                            notify_it_manager(
                                action_type='create',
                                ticket=ticket,
                                user=request.user,
                                additional_info=ticket.description
                            )
                        elif target_dept:
                            # Ticket is for another department -> notify that department's supervisor ONLY
                            notify_department_supervisor(ticket, target_dept, request.user)
                    else:
                        # Regular employee - notify their own team leader only (not IT)
                        from .services import notify_team_leader_network_access, notify_team_leader_access_email
                        print(f"🔍 About to notify team leader for ticket #{ticket.id} created by {request.user.get_full_name()}")
                        notify_team_leader_network_access(ticket, request.user)
                        # Also send email to team leader instead of IT manager
                        notify_team_leader_access_email('create', ticket, request.user, ticket.description)
                        print(f"🔍 Team leader notification call completed for ticket #{ticket.id}")
                        # DO NOT notify IT managers until approved
                else:
                    # Tickets that don't require approval
                    if target_dept == it_department or not target_dept:
                        # Ticket is for IT department (or legacy without target)
                        notify_it_manager(
                            action_type='create',
                            ticket=ticket,
                            user=request.user,
                            additional_info=ticket.description
                        )
                    elif target_dept:
                        # Ticket is for another department -> notify that department's supervisor ONLY
                        notify_department_supervisor(ticket, target_dept, request.user)
                
                # Notifications are now handled in the notify_it_manager function
                
                # Notify employee about their ticket creation
                notify_employee_ticket_created(ticket)
                messages.success(request, _('تیکت با موفقیت ایجاد شد.'))
                return redirect('tickets:ticket_detail', ticket_id=ticket.id)
        else:
            form = TicketForm(user=user)
        
        return render(request, 'tickets/ticket_form.html', {'form': form, 'action': _('ایجاد')})
    
    elif user.role in ['it_manager', 'technician']:
        # IT Managers and Technicians can create task tickets
        if request.method == 'POST':
            form = TaskTicketForm(request.POST, request.FILES, user=user)
            if form.is_valid():
                ticket = form.save(commit=False)
                ticket.created_by = request.user
                ticket.save()
                
                # Create notification for IT managers about new task ticket
                try:
                    from .models import Notification
                    it_managers = User.objects.filter(role='it_manager')
                    for manager in it_managers:
                        if manager != request.user:  # Don't notify yourself
                            Notification.objects.create(
                                recipient=manager,
                                title=f"وظیفه جدید: {ticket.title}",
                                message=f"ایجاد شده توسط: {request.user.get_full_name()}\nاختصاص داده شده به: {ticket.assigned_to.get_full_name() if ticket.assigned_to else 'نامشخص'}",
                                notification_type='ticket_created',
                                category='tickets',
                                ticket=ticket,
                                user_actor=request.user
                            )
                except Exception:
                    pass
                
                messages.success(request, _('وظیفه با موفقیت ایجاد و تخصیص داده شد.'))
                return redirect('tickets:ticket_detail', ticket_id=ticket.id)
        else:
            form = TaskTicketForm(user=user)
        
        return render(request, 'tickets/task_ticket_form.html', {'form': form, 'action': _('ایجاد وظیفه')})
    
    else:
        messages.error(request, _('شما مجوز ایجاد تیکت را ندارید.'))
        return redirect('tickets:ticket_list')

@login_required
def ticket_update(request, ticket_id):
    """Update ticket (Employees can update their own tickets)"""
    user = request.user
    
    if user.role == 'employee':
        ticket = get_object_or_404(Ticket, id=ticket_id, created_by=user)
        # Prevent employees from editing tickets that are not open
        if ticket.status != 'open':
            messages.error(request, _('شما فقط می‌توانید تیکت‌های باز را ویرایش کنید.'))
            return redirect('tickets:ticket_detail', ticket_id=ticket.id)
    elif user.role == 'technician':
        ticket = get_object_or_404(Ticket, id=ticket_id, assigned_to=user)
    else:  # IT Manager
        ticket = get_object_or_404(Ticket, id=ticket_id)
    
    if request.method == 'POST':
        # Capture original values before applying changes
        original_status = ticket.status
        original_assignment = ticket.assigned_to

        if user.role == 'employee':
            form = TicketForm(request.POST, request.FILES, instance=ticket)
        else:
            form = TicketStatusForm(request.POST, instance=ticket, user=user)
            form.user = user  # Store user for the save method
            form.request = request  # Store request for messages

        if form.is_valid():
            # Set user for activity logging
            if hasattr(form, 'instance'):
                form.instance._activity_user = user
            # For employee ticket updates, explicitly preserve ticket_category
            if user.role == 'employee' and hasattr(form, 'cleaned_data') and 'ticket_category' in form.cleaned_data:
                ticket.ticket_category = form.cleaned_data.get('ticket_category')
            form.save()

            # Send specific notifications based on what changed
            changes_notified = False

            # Status changed
            if ticket.status != original_status:
                from tickets.services import get_status_display_persian as _pers
                _prev = _pers(original_status)
                _new = _pers(ticket.status)
                # For access tickets pending approval, notify team leader instead of IT manager
                if ticket.ticket_category and ticket.ticket_category.requires_supervisor_approval and getattr(ticket, 'access_approval_status', 'not_required') == 'pending':
                    from .services import notify_team_leader_access_email
                    notify_team_leader_access_email('status_change', ticket, request.user, f"وضعیت قبلی: {_prev}\nوضعیت جدید: {_new}")
                else:
                    notify_it_manager(
                        action_type='status_change',
                        ticket=ticket,
                        user=request.user,
                        additional_info=f"وضعیت قبلی: {_prev}\nوضعیت جدید: {_new}"
                    )
                # Create notification for IT managers about status change
                try:
                    from .models import Notification
                    from .services import get_status_display_persian
                    it_managers = User.objects.filter(role='it_manager')
                    for manager in it_managers:
                        if manager != request.user:  # Don't notify yourself
                            Notification.objects.create(
                                recipient=manager,
                                title=f"تغییر وضعیت تیکت: {ticket.title}",
                                message=f"وضعیت قبلی: {_prev}\nوضعیت جدید: {_new}",
                                notification_type='ticket_urgent',
                                category='tickets',
                                ticket=ticket,
                                user_actor=request.user
                            )
                except Exception:
                    pass
                notify_employee_ticket_status_changed(ticket, request.user)
                changes_notified = True

            # Assignment changed
            if ticket.assigned_to != original_assignment and ticket.assigned_to:
                notify_it_manager(
                    action_type='assignment',
                    ticket=ticket,
                    user=request.user,
                    additional_info=f"اختصاص داده شده به: {ticket.assigned_to.get_full_name()}"
                )
                notify_employee_ticket_assigned(ticket, request.user)
                changes_notified = True
                
                # Create notification for IT managers about ticket assignment
                try:
                    from .models import Notification
                    it_managers = User.objects.filter(role='it_manager')
                    for manager in it_managers:
                        if manager != request.user:  # Don't notify yourself
                            Notification.objects.create(
                                recipient=manager,
                                title=f"اختصاص تیکت: {ticket.title}",
                                message=f"اختصاص داده شده به: {ticket.assigned_to.get_full_name()}\nتوسط: {request.user.get_full_name()}",
                                notification_type='ticket_urgent',  # Using existing type for assignments
                                category='tickets',
                                ticket=ticket,
                                user_actor=request.user
                            )
                except Exception:
                    pass

            # Fallback: generic update when no status/assignment change
            if not changes_notified:
                if ticket.ticket_category and ticket.ticket_category.requires_supervisor_approval and getattr(ticket, 'access_approval_status', 'not_required') == 'pending':
                    from .services import notify_team_leader_access_email
                    notify_team_leader_access_email('update', ticket, request.user, "تیکت بروزرسانی شد")
                else:
                    notify_it_manager(
                        action_type='update',
                        ticket=ticket,
                        user=request.user,
                        additional_info="تیکت بروزرسانی شد"
                    )
                
                # Create notification for IT managers about ticket update
                try:
                    from .models import Notification
                    it_managers = User.objects.filter(role='it_manager')
                    for manager in it_managers:
                        if manager != request.user:  # Don't notify yourself
                            Notification.objects.create(
                                recipient=manager,
                                title=f"بروزرسانی تیکت: {ticket.title}",
                                message=f"بروزرسانی شده توسط: {request.user.get_full_name()}",
                                notification_type='ticket_urgent',  # Using existing type for updates
                                category='tickets',
                                ticket=ticket,
                                user_actor=request.user
                            )
                except Exception:
                    pass

            messages.success(request, _('تیکت با موفقیت بروزرسانی شد.'))
            return redirect('tickets:ticket_detail', ticket_id=ticket.id)
    else:
        if user.role == 'employee':
            # Check if user is ticket responder for their department
            is_ticket_responder = (user.department and 
                                 user.department.can_receive_tickets and 
                                 user.department.ticket_responder == user)
            # Ticket responder can change status for tickets received by their department OR assigned to them
            if is_ticket_responder and ((ticket.target_department == user.department) or (ticket.assigned_to == user)):
                # Ticket responder can change status and reply
                form = TicketStatusForm(instance=ticket, user=user)
                form.user = user
                form.request = request
            else:
                form = TicketForm(instance=ticket)
        else:
            form = TicketStatusForm(instance=ticket, user=user)
            form.user = user  # Store user for the save method
            form.request = request  # Store request for messages
    
    return render(request, 'tickets/ticket_form.html', {
        'form': form, 
        'action': _('بروزرسانی'),
        'ticket': ticket
    })

@login_required
def ticket_delete(request, ticket_id):
    """Delete ticket (Employees can delete their own tickets only when open, IT Manager can delete any, Senior can delete received tickets)"""
    user = request.user
    
    if user.role == 'employee':
        if user.department_role == 'senior':
            # Senior can delete tickets received by their supervised departments
            supervised_depts = user.get_supervised_departments()
            supervised_dept_ids = [d.id for d in supervised_depts] if supervised_depts else []
            
            if supervised_dept_ids:
                ticket = get_object_or_404(
                    Ticket.objects.filter(
                        Q(created_by=user) | Q(target_department__in=supervised_dept_ids)
                    ),
                    id=ticket_id
                )
            else:
                ticket = get_object_or_404(Ticket, id=ticket_id, created_by=user)
            # Senior can only delete received tickets (not their own created tickets) when status is 'open'
            if ticket.target_department != user.department:
                # This is their own ticket, apply normal employee rules
                if ticket.status != 'open':
                    messages.error(request, _('شما فقط می‌توانید تیکت‌های باز خود را حذف کنید.'))
                    return redirect('tickets:ticket_list')
            # For received tickets, senior can delete them
        elif user.department and user.department.can_receive_tickets and user.department.ticket_responder == user:
            # Ticket responder can delete tickets received by their department
            ticket = get_object_or_404(
                Ticket.objects.filter(target_department=user.department),
                id=ticket_id
            )
        else:
            ticket = get_object_or_404(Ticket, id=ticket_id, created_by=user)
            # Employees can only delete their own tickets when status is 'open'
            if ticket.status != 'open':
                messages.error(request, _('شما فقط می‌توانید تیکت‌های باز خود را حذف کنید.'))
                return redirect('tickets:ticket_list')
    elif user.role == 'technician':
        # Technicians cannot delete tickets
        messages.error(request, _('شما مجوز حذف تیکت‌ها را ندارید.'))
        return redirect('tickets:ticket_list')
    elif user.role == 'it_manager':
        ticket = get_object_or_404(Ticket, id=ticket_id)
    else:
        messages.error(request, _('شما مجوز حذف تیکت‌ها را ندارید.'))
        return redirect('tickets:ticket_list')
    
    if request.method == 'POST':
        try:
            # Store ticket info before deletion for email notification
            ticket_title = ticket.title
            ticket_description = ticket.description
            ticket_id = ticket.id
            ticket_creator = ticket.created_by  # Store reference to ticket creator
            
            ticket.delete()
            
            # Note: No email notification sent to the ticket creator (as requested)
            
            # Create a dummy ticket object for email notification to IT managers/team leaders
            dummy_ticket = Ticket.objects.first()  # Get first ticket for template
            if dummy_ticket:
                # If access ticket pending approval, route delete email to team leader instead of IT manager
                if ticket.ticket_category and ticket.ticket_category.requires_supervisor_approval and getattr(ticket, 'access_approval_status', 'not_required') == 'pending':
                    from .services import notify_team_leader_access_email
                    notify_team_leader_access_email(
                        'delete',
                        dummy_ticket,
                        request.user,
                        f"تیکت حذف شده:\nعنوان: {ticket_title}\nتوضیحات: {ticket_description}\nشماره تیکت: #{ticket_id}"
                    )
                else:
                    notify_it_manager(
                        action_type='delete',
                        ticket=dummy_ticket,
                        user=request.user,
                        additional_info=f"تیکت حذف شده:\nعنوان: {ticket_title}\nتوضیحات: {ticket_description}\nشماره تیکت: #{ticket_id}"
                    )
            
            # Create notification for IT managers about ticket deletion
            try:
                from .models import Notification
                it_managers = User.objects.filter(role='it_manager')
                for manager in it_managers:
                    if manager != request.user:  # Don't notify yourself
                        Notification.objects.create(
                            recipient=manager,
                            title=f"حذف تیکت: {ticket_title}",
                            message=f"حذف شده توسط: {request.user.get_full_name()}\nشماره تیکت: #{ticket_id}",
                            notification_type='ticket_urgent',  # Using existing type for deletions
                            category='tickets',
                            user_actor=request.user
                        )
            except Exception:
                pass
            
            messages.success(request, _('تیکت با موفقیت حذف شد.'))
            return redirect('tickets:ticket_list')
        except Exception as e:
            messages.error(request, _('خطا در حذف تیکت: {}').format(str(e)))
            return redirect('tickets:ticket_list')
    
    return render(request, 'tickets/ticket_confirm_delete.html', {'ticket': ticket})

# Profile view removed - no longer needed
# @login_required
# def profile_view(request):
#     """User profile view"""
#     if request.method == 'POST':
#         form = UserProfileForm(request.POST, instance=request.user)
#         if form.is_valid():
#             form.save()
#             messages.success(request, _('پروفایل با موفقیت بروزرسانی شد.'))
#             return redirect('tickets:profile')
#     else:
#         form = UserProfileForm(instance=request.user)
#     
#     return render(request, 'tickets/profile.html', {'form': form})

@login_required
def superadmin_profile(request):
    """SuperAdmin profile view for editing national_id and employee_code"""
    from .admin_security import is_admin_superuser
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    if request.method == 'POST':
        from .forms import SuperAdminProfileForm
        form = SuperAdminProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            # Save the form
            user = form.save()
            # Update the admin_security constants to reflect the new values
            # Note: This is a critical security operation - the user must be aware of the implications
            messages.success(request, _('پروفایل با موفقیت بروزرسانی شد. لطفاً توجه داشته باشید که تغییر کد ملی و کد پرسنلی ممکن است بر ورود به سیستم تأثیر بگذارد.'))
            return redirect('tickets:superadmin_profile')
        else:
            messages.error(request, _('خطا در بروزرسانی پروفایل. لطفاً اطلاعات را بررسی کنید.'))
    else:
        from .forms import SuperAdminProfileForm
        form = SuperAdminProfileForm(instance=request.user)
    
    context = {
        'form': form,
    }
    
    return render(request, 'tickets/superadmin_profile.html', context)

@login_required
def it_manager_profile(request):
    """IT Manager profile view with password verification for email changes"""
    if request.user.role != 'it_manager':
        messages.error(request, _('دسترسی رد شد. فقط مدیر IT میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    # Get IT department for context
    it_dept = get_it_department()
    
    if request.method == 'POST':
        form = ITManagerProfileForm(request.POST, instance=request.user, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, _('پروفایل و تنظیمات بخش IT با موفقیت بروزرسانی شد.'))
            return redirect('tickets:it_manager_profile')
        else:
            messages.error(request, _('خطا در بروزرسانی پروفایل. لطفاً اطلاعات را بررسی کنید.'))
    else:
        form = ITManagerProfileForm(instance=request.user, user=request.user)
    
    context = {
        'form': form,
        'it_department': it_dept,
    }
    
    return render(request, 'tickets/it_manager_profile.html', context)

@login_required
def technician_management(request):
    """IT Manager view for managing technicians"""
    if request.user.role != 'it_manager':
        messages.error(request, _('دسترسی رد شد. فقط مدیر IT میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    # Exclude admin superuser from lists
    admin_filter = get_admin_superuser_queryset_filter()
    technicians = User.objects.filter(role='technician').filter(admin_filter)
    employees = User.objects.filter(role='employee').filter(admin_filter)
    
    if request.method == 'POST':
        technician_id = request.POST.get('technician_id')
        action = request.POST.get('action')
        
        if technician_id and action:
            technician = get_object_or_404(User, id=technician_id, role='technician')
            
            if action == 'assign':
                employee_id = request.POST.get('employee_id')
                if employee_id:
                    employee = get_object_or_404(User, id=employee_id, role='employee')
                    employee.assigned_by = technician
                    employee.save()
                    messages.success(request, _('کارمند {} به {} تخصیص داده شد.').format(employee.get_full_name(), technician.get_full_name()))
            
            elif action == 'remove_assignment':
                assigned_employees = User.objects.filter(assigned_by=technician)
                assigned_employees.update(assigned_by=None)
                messages.success(request, _('تمام تخصیص‌ها از {} حذف شدند.').format(technician.get_full_name()))
    
    context = {
        'technicians': technicians,
        'employees': employees,
    }
    
    return render(request, 'tickets/technician_management.html', context)

@login_required
def statistics(request):
    """Comprehensive statistics view for Administrator"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    # Get date filters from request
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    # Parse dates if provided
    if date_from:
        try:
            date_from = datetime.strptime(date_from, '%Y-%m-%d')
        except ValueError:
            date_from = None
    
    if date_to:
        try:
            date_to = datetime.strptime(date_to, '%Y-%m-%d')
        except ValueError:
            date_to = None
    
    # Initialize statistics service
    stats_service = StatisticsService(date_from, date_to)
    
    # Get comprehensive statistics
    stats = stats_service.get_comprehensive_statistics()
    
    # Add filter options for the template
    context = {
        'stats': stats,
        'date_from': date_from,
        'date_to': date_to,
        'filter_periods': [
            {'name': _('امروز'), 'value': 'today'},
            {'name': _('هفته گذشته'), 'value': 'last_week'},
            {'name': _('ماه گذشته'), 'value': 'last_month'},
            {'name': _('۳۰ روز گذشته'), 'value': 'last_30_days'},
            {'name': _('۹۰ روز گذشته'), 'value': 'last_90_days'},
        ]
    }
    
    return render(request, 'tickets/statistics.html', context)

# API Views for AJAX requests
@login_required
@require_POST
def update_ticket_status(request, ticket_id):
    """AJAX view for updating ticket status"""
    user = request.user
    
    if user.role not in ['it_manager', 'technician']:
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    ticket = get_object_or_404(Ticket, id=ticket_id)
    
    if user.role == 'technician' and ticket.assigned_to != user:
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    status = request.POST.get('status')
    assigned_to_id = request.POST.get('assigned_to')
    
    # Store original values for comparison
    original_status = ticket.status
    original_assignment = ticket.assigned_to
    
    # Set user for activity logging
    ticket._activity_user = user
    
    # Handle status update (only if explicitly provided)
    if status:
        ticket.status = status
    
    # Handle assignment
    if assigned_to_id:
        try:
            assigned_user = User.objects.get(id=assigned_to_id)
            if user.role == 'it_manager' or (user.role == 'technician' and assigned_user.id == user.id):
                ticket.assigned_to = assigned_user
                
                # Manual State Control: Assignment operations do not change ticket status
                # Status must be changed explicitly via the status parameter
                # Use update_fields to prevent signal-based status changes
                ticket.save(update_fields=['assigned_to'])
                
                # After assignment or status change in update_ticket_status
                if assigned_to_id and assigned_user:
                    # For access tickets pending approval, notify team leader instead of IT manager
                    if ticket.ticket_category and ticket.ticket_category.requires_supervisor_approval and getattr(ticket, 'access_approval_status', 'not_required') == 'pending':
                        from .services import notify_team_leader_access_email
                        notify_team_leader_access_email('assignment', ticket, request.user, f"تخصیص داده شده به: {assigned_user.get_full_name() or assigned_user.username}")
                    else:
                        notify_it_manager(
                            action_type='assignment',
                            ticket=ticket,
                            user=request.user,
                            additional_info=f"تخصیص داده شده به: {assigned_user.get_full_name() or assigned_user.username}"
                        )
                elif status and status != original_status:
                    from tickets.services import get_status_display_persian as _pers
                    _prev = _pers(original_status)
                    _new = _pers(ticket.status)
                    if ticket.ticket_category and ticket.ticket_category.requires_supervisor_approval and getattr(ticket, 'access_approval_status', 'not_required') == 'pending':
                        from .services import notify_team_leader_access_email
                        notify_team_leader_access_email('status_change', ticket, request.user, f"وضعیت قبلی: {_prev}\nوضعیت جدید: {_new}")
                    else:
                        notify_it_manager(
                            action_type='status_change',
                            ticket=ticket,
                            user=request.user,
                            additional_info=f"وضعیت قبلی: {_prev}\nوضعیت جدید: {_new}"
                        )
                    # Create notification for IT managers about status change
                    try:
                        from .models import Notification
                        from .services import get_status_display_persian
                        it_managers = User.objects.filter(role='it_manager')
                        for manager in it_managers:
                            if manager != request.user:  # Don't notify yourself
                                Notification.objects.create(
                                    recipient=manager,
                                    title=f"تغییر وضعیت تیکت: {ticket.title}",
                                    message=f"وضعیت قبلی: {_prev}\nوضعیت جدید: {_new}",
                                    notification_type='ticket_urgent',
                                    category='tickets',
                                    ticket=ticket,
                                    user_actor=request.user
                                )
                    except Exception:
                        pass
                
                # Manual State Control: Assignment success message (no status change)
                return JsonResponse({
                    'success': True, 
                    'status': ticket.status,
                    'message': _('تیکت به کارشناس فنی تخصیص داده شد.')
                })
        except User.DoesNotExist:
            pass
    
    # Only save if status was explicitly provided, otherwise skip save
    if status:
        ticket.save()
    return JsonResponse({'success': True, 'status': ticket.status})

@login_required
def get_ticket_activity_logs(request, ticket_id):
    """API endpoint to fetch activity logs for a ticket"""
    import logging
    logger = logging.getLogger(__name__)
    user = request.user
    
    # Check if user has permission to view this ticket
    try:
        if user.role == 'employee':
            if user.department_role == 'manager':
                ticket = get_object_or_404(Ticket, id=ticket_id)
            elif user.department_role == 'senior':
                supervised_depts = user.get_supervised_departments()
                supervised_dept_ids = [d.id for d in supervised_depts] if supervised_depts else ([user.department.id] if user.department else [])
                
                if supervised_dept_ids:
                    ticket = get_object_or_404(
                        Ticket.objects.filter(
                            Q(created_by__department__in=supervised_dept_ids, created_by__isnull=False) | 
                            Q(target_department__in=supervised_dept_ids)
                        ),
                        id=ticket_id
                    )
                else:
                    ticket = get_object_or_404(Ticket, id=ticket_id, created_by=user)
            elif user.department and user.department.can_receive_tickets and user.department.ticket_responder == user:
                ticket = get_object_or_404(
                    Ticket.objects.filter(
                        Q(created_by=user) | 
                        Q(target_department=user.department) | 
                        Q(assigned_to=user)
                    ),
                    id=ticket_id
                )
            else:
                ticket = get_object_or_404(
                    Ticket.objects.filter(
                        Q(created_by=user) | Q(assigned_to=user)
                    ),
                    id=ticket_id
                )
        elif user.role == 'technician':
            it_department = get_it_department()
            if it_department:
                ticket = get_object_or_404(
                    Ticket.objects.filter(
                        Q(assigned_to=user) & (Q(target_department__isnull=True) | Q(target_department=it_department))
                    ).exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')),
                    id=ticket_id
                )
            else:
                ticket = get_object_or_404(Ticket.objects.exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')), id=ticket_id, assigned_to=user)
        else:  # IT Manager
            it_department = get_it_department()
            if it_department:
                ticket = get_object_or_404(
                    Ticket.objects.filter(
                        Q(target_department__isnull=True) | Q(target_department=it_department) | Q(created_by=user)
                    ).exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')),
                    id=ticket_id
                )
            else:
                ticket = get_object_or_404(Ticket.objects.exclude(Q(ticket_category__requires_supervisor_approval=True, access_approval_status='pending')), id=ticket_id)
    except Exception as e:
        logger.error(f"Error checking ticket permissions for activity logs: {e}", exc_info=True)
        return JsonResponse({'error': 'دسترسی رد شد', 'details': str(e)}, status=403)
    
    # Get activity logs for this ticket
    try:
        import jdatetime
        from django.utils import timezone
        import zoneinfo
        
        logs = TicketActivityLog.objects.filter(ticket=ticket).order_by('-created_at')
        
        # Convert to JSON-serializable format
        logs_data = []
        for log in logs:
            # Format user name as "Department name (person's name)"
            try:
                if log.user:
                    # Refresh user from database to ensure we have latest data
                    try:
                        log.user.refresh_from_db()
                    except Exception:
                        pass
                    
                    user_full_name = log.user.get_full_name()
                    if not user_full_name or user_full_name.strip() == '':
                        user_full_name = log.user.username or _('نامشخص')
                    
                    # Get department name
                    if log.user.department:
                        department_name = log.user.department.name
                        user_name = f"{department_name} ({user_full_name})"
                    else:
                        user_name = user_full_name
                else:
                    user_name = _('سیستم')
            except Exception as e:
                logger.error(f"Error formatting user name for log {log.id}: {e}", exc_info=True)
                user_name = _('سیستم')
            
            # Convert date to Persian (Jalali) format
            try:
                # Convert to Tehran timezone if timezone-aware
                created_at = log.created_at
                if timezone.is_aware(created_at):
                    tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
                    created_at = created_at.astimezone(tehran_tz)
                
                # Convert to Persian calendar (same logic as persian_date filter)
                persian_date = jdatetime.datetime.fromgregorian(datetime=created_at)
                created_at_persian = persian_date.strftime('%Y/%m/%d %H:%M')
            except Exception as e:
                logger.error(f"Error converting date to Persian for log {log.id}: {e}", exc_info=True)
                # Fallback to Gregorian date if conversion fails
                created_at_persian = log.created_at.strftime('%Y/%m/%d %H:%M')
            
            logs_data.append({
                'id': log.id,
                'action': log.action,
                'action_display': log.get_action_display(),
                'description': log.description,
                'old_value': log.old_value or '',
                'new_value': log.new_value or '',
                'user_name': user_name,
                'created_at': log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'created_at_persian': created_at_persian,
            })
        
        return JsonResponse({
            'success': True,
            'logs': logs_data,
            'total': len(logs_data)
        })
    except Exception as e:
        logger.error(f"Error fetching activity logs: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'خطا در دریافت تاریخچه',
            'details': str(e)
        }, status=500)

@login_required
def search_tickets(request):
    """AJAX search for tickets"""
    user = request.user
    query = request.GET.get('q', '')
    
    if user.role == 'employee':
        tickets = Ticket.objects.filter(created_by=user)
    elif user.role == 'technician':
        tickets = Ticket.objects.filter(assigned_to=user)
    else:  # IT Manager
        tickets = Ticket.objects.all()
    
    if query:
        # Normalize Persian digits to Latin for search compatibility
        from tickets.templatetags.persian_numbers import _persian_to_latin
        normalized_query = _persian_to_latin(query)
        
        tickets = tickets.filter(
            Q(title__icontains=normalized_query) |
            Q(description__icontains=normalized_query) |
            Q(created_by__first_name__icontains=normalized_query) |
            Q(created_by__last_name__icontains=normalized_query)
        )[:10]
    
    results = []
    for ticket in tickets:
        results.append({
            'id': ticket.id,
            'title': ticket.title,
            'status': ticket.status,
            'priority': ticket.priority,
            'created_by': ticket.created_by.get_full_name(),
            'created_at': ticket.created_at.strftime('%Y-%m-%d %H:%M'),
        })
    
    return JsonResponse({'results': results}) 

def it_manager_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.role == 'it_manager')(view_func)


@login_required
def user_management(request):
    """Comprehensive user management for Administrator"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    # Initialize forms
    employee_form = None
    technician_form = None
    
    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        
        if form_type == 'employee':
            employee_form = EmployeeCreationForm(request.POST)
            if employee_form.is_valid():
                try:
                    user = employee_form.save()
                    # Notification: user created (admin-only)
                    try:
                        from .models import Notification
                        from .services import get_user_role_display
                        it_manager = request.user if request.user.role == 'it_manager' else None
                        if it_manager:
                            Notification.objects.create(
                                recipient=it_manager,
                                title=f"ایجاد کاربر: {user.first_name} {user.last_name}",
                                message=f"نقش: {get_user_role_display(user)}",
                                notification_type='user_created',
                                category='users'
                            )
                    except Exception:
                        pass
                    # Notify IT manager about user creation
                    from .services import notify_it_manager_user_management
                    notify_it_manager_user_management(
                        action_type='create',
                        user=user,
                        actor=request.user
                    )
                    # Note: No email notification sent to the new user (as requested)
                    messages.success(request, _('کارمند با موفقیت ایجاد شد: {} {}').format(
                        user.first_name, user.last_name
                    ))
                    # Clear the form after successful creation
                    employee_form = EmployeeCreationForm()
                    return redirect('tickets:user_management')
                except Exception as e:
                    messages.error(request, _('خطا در ایجاد کارمند: {}').format(str(e)))
            else:
                # Debug: Print form errors to console
                print("Employee form errors:", employee_form.errors)
                print("Employee form non-field errors:", employee_form.non_field_errors())
                print("Employee form data:", request.POST)
                # Show specific field errors to user
                error_messages = []
                for field, errors in employee_form.errors.items():
                    for error in errors:
                        error_messages.append(f"{field}: {error}")
                if error_messages:
                    messages.error(request, _('خطاهای فرم: ') + '; '.join(error_messages))
                else:
                    messages.error(request, _('لطفاً خطاهای فرم را برطرف کنید.'))
                
        elif form_type == 'technician':
            technician_form = TechnicianCreationForm(request.POST)
            if technician_form.is_valid():
                try:
                    user = technician_form.save()
                    # Notification: user created (admin-only)
                    try:
                        from .models import Notification
                        it_manager = request.user if request.user.role == 'it_manager' else None
                        if it_manager:
                            Notification.objects.create(
                                recipient=it_manager,
                                title=f"ایجاد کاربر: {user.first_name} {user.last_name}",
                                message=f"نقش: {user.get_role_display()}",
                                notification_type='user_created',
                                category='users'
                            )
                    except Exception:
                        pass
                    # Notify IT manager about technician creation
                    from .services import notify_it_manager_user_management
                    notify_it_manager_user_management(
                        action_type='create',
                        user=user,
                        actor=request.user
                    )
                    messages.success(request, _('کارشناس فنی با موفقیت ایجاد شد: {} {}').format(
                        user.first_name, user.last_name
                    ))
                    # Clear the form after successful creation
                    technician_form = TechnicianCreationForm()
                    return redirect('tickets:user_management')
                except Exception as e:
                    messages.error(request, _('خطا در ایجاد کارشناس فنی: {}').format(str(e)))
            else:
                # Debug: Print form errors to console
                print("Technician form errors:", technician_form.errors)
                print("Technician form non-field errors:", technician_form.non_field_errors())
                print("Technician form data:", request.POST)
                # Show specific field errors to user
                error_messages = []
                for field, errors in technician_form.errors.items():
                    for error in errors:
                        error_messages.append(f"{field}: {error}")
                if error_messages:
                    messages.error(request, _('خطاهای فرم: ') + '; '.join(error_messages))
                else:
                    messages.error(request, _('لطفاً خطاهای فرم را برطرف کنید.'))
                

    
    # Initialize empty forms if not POST or if validation failed
    if employee_form is None:
        employee_form = EmployeeCreationForm()
    if technician_form is None:
        technician_form = TechnicianCreationForm()
    
    # Get users by role
    # Exclude admin superuser from all user lists
    admin_filter = get_admin_superuser_queryset_filter()
    employees = User.objects.filter(role='employee').filter(admin_filter).order_by('-date_joined')
    technicians = User.objects.filter(role='technician').filter(admin_filter).order_by('-date_joined')
    it_managers = User.objects.filter(role='it_manager').filter(admin_filter).order_by('-date_joined')
    
    # Statistics
    total_employees = employees.count()
    total_technicians = technicians.count()
    total_it_managers = it_managers.count()
    
    context = {
        'employee_form': employee_form,
        'technician_form': technician_form,
        'employees': employees,
        'technicians': technicians,
        'it_managers': it_managers,
        'total_employees': total_employees,
        'total_technicians': total_technicians,
        'total_it_managers': total_it_managers,
    }
    
    return render(request, 'tickets/user_management.html', context)

@login_required
def delete_user(request, user_id):
    """Delete user (Administrator only)"""
    try:
        if not is_admin_superuser(request.user):
            messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
            return redirect('tickets:dashboard')
        
        user_to_delete = get_object_or_404(User, id=user_id)
        
        # Prevent deletion of admin superuser
        if is_admin_superuser(user_to_delete):
            messages.error(request, _('نمی‌توانید این کاربر را حذف کنید. این کاربر ادمین سیستم است.'))
            return redirect('tickets:user_management')
        
        if request.method == 'POST':
            # Save user info before deletion (needed for notifications)
            user_full_name = user_to_delete.get_full_name()
            user_first_name = user_to_delete.first_name
            user_last_name = user_to_delete.last_name
            user_employee_code = user_to_delete.employee_code
            user_email = getattr(user_to_delete, 'email', '')
            user_department = str(user_to_delete.department) if user_to_delete.department else 'نامشخص'
            user_role = user_to_delete.get_role_display()
            
            user_to_delete.delete()
            
            # Create notification for IT managers about user deletion
            try:
                from .models import Notification
                it_managers = User.objects.filter(role='it_manager')
                for manager in it_managers:
                    # Notify all IT managers including the actor, so it appears in their feed too
                    Notification.objects.create(
                        recipient=manager,
                        title=f"حذف کاربر: {user_first_name} {user_last_name}",
                        message=f"حذف شده توسط: {request.user.get_full_name()}\nکد پرسنلی: {user_employee_code}",
                        notification_type='user_created',  # Reuse existing type; category ensures placement
                        category='users',
                        user_actor=request.user
                    )
            except Exception:
                pass
            # Notify IT manager about user deletion (create a mock user object for the email template)
            try:
                from .services import notify_it_manager_user_management
                # Create a simple object with the saved attributes for email notification
                class DeletedUser:
                    def get_full_name(self):
                        return user_full_name
                    def __init__(self):
                        self.employee_code = user_employee_code
                        self.email = user_email
                        self.department = user_department
                    def get_department_display(self):
                        return user_department
                    def get_role_display(self):
                        return user_role
                
                deleted_user_obj = DeletedUser()
                notify_it_manager_user_management(
                    action_type='delete',
                    user=deleted_user_obj,
                    actor=request.user
                )
            except Exception as e:
                print(f"⚠️ Failed to send deletion email: {e}")
            
            messages.success(request, _('کاربر با موفقیت حذف شد.'))
            return redirect('tickets:user_management')
        
        return render(request, 'tickets/user_confirm_delete.html', {'user_to_delete': user_to_delete})
    except Exception as e:
        import traceback
        print(f"❌ Error in delete_user: {e}")
        traceback.print_exc()
        messages.error(request, _('خطا در بارگذاری صفحه حذف: {}').format(str(e)))
        return redirect('tickets:user_management')

@login_required
def edit_employee(request, user_id):
    """Edit employee information"""
    try:
        if not is_admin_superuser(request.user):
            messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
            return redirect('tickets:dashboard')
        
        user = get_object_or_404(User, id=user_id, role='employee')
        
        # Prevent editing of admin superuser
        if is_admin_superuser(user):
            messages.error(request, _('نمی‌توانید این کاربر را ویرایش کنید. این کاربر ادمین سیستم است.'))
            return redirect('tickets:user_management')
        
        if request.method == 'POST':
            # #region agent log - Setup logging first
            import json
            import os
            import traceback
            from datetime import datetime
            log_path = r'c:\Users\User\Desktop\pticket-main\.cursor\debug.log'
            def log_debug(hypothesis_id, location, message, data):
                try:
                    os.makedirs(os.path.dirname(log_path), exist_ok=True)
                    entry = {
                        'id': f'log_{int(datetime.now().timestamp() * 1000)}',
                        'timestamp': int(datetime.now().timestamp() * 1000),
                        'location': location,
                        'message': message,
                        'data': data,
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': hypothesis_id
                    }
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
                except Exception as e:
                    # Fallback: try to write to a simpler log
                    try:
                        with open(log_path.replace('.log', '_error.log'), 'a') as f:
                            f.write(f"Logging error: {e}\n")
                    except:
                        pass
            
            log_debug('ENTRY', 'tickets/views.py:2110', 'edit_employee POST request received', {
                'user_id': user.id,
                'method': request.method,
                'request_user_id': request.user.id if request.user.is_authenticated else None,
                'request_user_is_active': request.user.is_active if request.user.is_authenticated else None
            })
            # #endregion
            
            form = EmployeeEditForm(request.POST, instance=user)
            log_debug('FORM', 'tickets/views.py:2112', 'Form created', {
                'form_valid': form.is_valid(),
                'form_errors': form.errors if not form.is_valid() else {}
            })
            
            if form.is_valid():
                try:
                    
                    # Capture old state BEFORE form save (critical for department transfer logic)
                    old_dept_id = user.department_id
                    old_dept_role = user.department_role
                    # Fetch old department fresh from database to avoid caching issues
                    old_dept = Department.objects.filter(id=old_dept_id).first() if old_dept_id else None
                    
                    # CRITICAL: Capture ALL authentication-critical fields before save
                    auth_fields_before = {
                        'is_active': user.is_active,
                        'role': user.role,
                        'national_id': user.national_id,
                        'employee_code': user.employee_code,
                        'department_role': user.department_role,
                        'has_usable_password': user.has_usable_password(),
                    }
                    
                    log_debug('UPDATE', 'tickets/views.py:2142', 'Before user update - ALL fields', {
                        'user_id': user.id,
                        'user_name': user.get_full_name(),
                        'old_department_id': old_dept_id,
                        'old_department_name': old_dept.name if old_dept else None,
                        'old_department_role': old_dept_role,
                        'is_team_lead': old_dept_role in ['senior', 'manager'],
                        'auth_fields': auth_fields_before
                    })
                    # #endregion
                    
                    # #region agent log - HYP_F: BEFORE form.save() - Track exact state
                    log_debug('HYP_F', 'tickets/views.py:2182', 'BEFORE form.save() - User state check', {
                        'user_id': user.id,
                        'is_active_before_save': user.is_active,
                        'national_id_before_save': user.national_id,
                        'employee_code_before_save': user.employee_code,
                        'password_hash_before_save': user.password[:20] if user.password else None,
                        'role_before_save': user.role,
                        'department_role_before_save': user.department_role
                    })
                    # #endregion
                    
                    # Save the form to update user fields
                    form.save()
                    
                    # #region agent log - HYP_F: IMMEDIATELY AFTER form.save() - Before refresh
                    log_debug('HYP_F', 'tickets/views.py:2184', 'IMMEDIATELY AFTER form.save() - Before refresh_from_db()', {
                        'user_id': user.id,
                        'is_active_after_save': user.is_active,
                        'national_id_after_save': user.national_id,
                        'employee_code_after_save': user.employee_code,
                        'password_hash_after_save': user.password[:20] if user.password else None,
                        'role_after_save': user.role,
                        'department_role_after_save': user.department_role
                    })
                    # #endregion
                    
                    # #region agent log - After user update
                    user.refresh_from_db()
                    new_dept_id = user.department_id
                    new_dept_role = user.department_role
                    # Fetch new department fresh from database to avoid caching
                    new_dept = Department.objects.filter(id=new_dept_id).first() if new_dept_id else None
                    
                    # CRITICAL: Verify authentication fields were NOT corrupted
                    auth_fields_after = {
                        'is_active': user.is_active,
                        'role': user.role,
                        'national_id': user.national_id,
                        'employee_code': user.employee_code,
                        'department_role': user.department_role,
                        'has_usable_password': user.has_usable_password(),
                    }
                    
                    # Check for authentication field corruption
                    auth_corruption = {}
                    for field, before_value in auth_fields_before.items():
                        after_value = auth_fields_after.get(field)
                        if before_value != after_value and field != 'department_role':  # department_role can change
                            auth_corruption[field] = {
                                'before': before_value,
                                'after': after_value
                            }
                    
                    log_debug('UPDATE', 'tickets/views.py:2205', 'After form save and refresh - ALL fields', {
                        'user_id': user.id,
                        'new_department_id': new_dept_id,
                        'new_department_name': new_dept.name if new_dept else None,
                        'new_department_role': new_dept_role,
                        'auth_fields': auth_fields_after,
                        'auth_corruption_detected': bool(auth_corruption),
                        'corrupted_fields': auth_corruption
                    })
                    
                    # If authentication fields were corrupted, log critical error
                    if auth_corruption:
                        log_debug('CRITICAL', 'tickets/views.py:2217', 'AUTHENTICATION FIELDS CORRUPTED AFTER form.save()', {
                            'user_id': user.id,
                            'corrupted_fields': auth_corruption,
                            'action_required': 'RESTORE_ORIGINAL_VALUES',
                            'hypothesis': 'HYP_A - form.save() corrupted fields'
                        })
                        # Restore original authentication fields
                        user.is_active = auth_fields_before['is_active']
                        user.role = auth_fields_before['role']
                        user.national_id = auth_fields_before['national_id']
                        user.employee_code = auth_fields_before['employee_code']
                        user.save(update_fields=['is_active', 'role', 'national_id', 'employee_code'])
                        log_debug('RECOVERY', 'tickets/views.py:2229', 'Restored authentication fields', {
                            'user_id': user.id,
                            'restored_fields': ['is_active', 'role', 'national_id', 'employee_code']
                        })
                    # #endregion
                    
                    # #region Atomic Department Supervisor Update for Team Leads
                    # CRITICAL: System-wide synchronized atomic transaction for Team Lead department transfer
                    # This ensures data consistency when a Team Lead is transferred between departments
                    # Uses Dept_ID (Department.id) as the primary identifier for all relational queries
                    # 
                    # FOUNDATION: Department ID (Dept_ID) is mandatory and unique (Django auto-generated primary key)
                    # All operations use Dept_ID for robust relational mapping
                    from django.db import transaction
                    # #region agent log - HYP_B: Track transaction state
                    log_debug('HYP_B', 'tickets/views.py:2250', 'BEFORE transaction.atomic() - User state', {
                        'user_id': user.id,
                        'is_active_before_tx': user.is_active,
                        'national_id_before_tx': user.national_id,
                        'employee_code_before_tx': user.employee_code,
                        'old_dept_id': old_dept_id,
                        'new_dept_id': new_dept_id,
                        'is_team_lead': user.department_role in ['senior', 'manager']
                    })
                    # #endregion
                    try:
                        with transaction.atomic():
                            # PRE-UPDATE CHECK: Verify department change and user state
                            # Re-check user state after refresh to ensure we have latest data
                            user.refresh_from_db()
                            is_team_lead = user.department_role in ['senior', 'manager']
                            
                            # CRITICAL: Detect Change using Dept_ID - Only proceed if department IDs are different
                            # This is the foundation check that triggers the entire atomic update sequence
                            dept_changed = False
                            if old_dept_id and new_dept_id:
                                dept_changed = old_dept_id != new_dept_id
                            elif old_dept_id is not None or new_dept_id is not None:
                                # User is being assigned to a department or removed from one
                                dept_changed = True
                            
                            log_debug('UPDATE', 'tickets/views.py:2252', 'Atomic transaction started - Pre-update check', {
                                'is_team_lead': is_team_lead,
                                'department_role': user.department_role,
                                'old_dept_id': old_dept_id,
                                'new_dept_id': new_dept_id,
                                'dept_changed': dept_changed,
                                'user_id': user.id,
                                'user_role': user.role,
                                'user_is_active': user.is_active
                            })
                            
                            # ABORT if no department change detected
                            if not dept_changed:
                                log_debug('SKIP', 'tickets/views.py:2265', 'No department change detected - skipping atomic update', {
                                    'old_dept_id': old_dept_id,
                                    'new_dept_id': new_dept_id
                                })
                                # Exit transaction early if no change
                                pass
                            
                            if is_team_lead and dept_changed:
                                # STEP 1: Cleanup Old Department (Dept A) - UNASSIGN Team Lead
                                # CRITICAL: Unconditionally clear ALL supervisor relationships for old department
                                if old_dept_id and old_dept_id != new_dept_id:
                                    # Fetch Department by Dept_ID (robust relational mapping)
                                    old_dept = Department.objects.filter(id=old_dept_id).first()
                                    
                                    if old_dept:
                                        # Refresh to get latest state from database
                                        old_dept.refresh_from_db()
                                        
                                        # Explicitly UNASSIGN: Clear FK supervisor if it points to this user
                                        # UNCONDITIONAL: Always clear if it matches, regardless of other conditions
                                        if old_dept.supervisor_id == user.id:
                                            old_dept.supervisor = None
                                            old_dept.save(update_fields=['supervisor'])
                                            log_debug('UPDATE', 'tickets/views.py:2256', 'UNASSIGNED: Cleared FK supervisor from old department', {
                                                'old_dept_id': old_dept_id,
                                                'old_dept_name': old_dept.name,
                                                'dept_id_used': old_dept.id,
                                                'supervisor_id_before': user.id,
                                                'supervisor_id_after': None
                                            })
                                        
                                        # Explicitly UNASSIGN: Remove from M2M supervised_departments
                                        # UNCONDITIONAL: Always remove old_dept from M2M, even if not currently present
                                        # Force removal using both ORM and direct SQL for maximum reliability
                                        try:
                                            # First try ORM method
                                            user.supervised_departments.remove(old_dept)
                                        except:
                                            pass
                                        
                                        # Also use direct SQL to ensure removal (works with SQLite, PostgreSQL, MySQL)
                                        from django.db import connection
                                        m2m_table = User.supervised_departments.through._meta.db_table
                                        with connection.cursor() as cursor:
                                            # Use parameterized query (works with all databases)
                                            cursor.execute(
                                                f"DELETE FROM {m2m_table} WHERE user_id = ? AND department_id = ?",
                                                [user.id, old_dept_id]
                                            )
                                        
                                        log_debug('UPDATE', 'tickets/views.py:2275', 'UNASSIGNED: Removed from M2M supervised_departments (unconditional)', {
                                            'old_dept_id': old_dept_id,
                                            'old_dept_name': old_dept.name,
                                            'dept_id_used': old_dept.id,
                                            'user_id': user.id,
                                            'm2m_table': m2m_table
                                        })
                                
                                # STEP 2: Assign to New Department (Dept B) - ASSIGN Team Lead
                                if new_dept_id and new_dept_id != old_dept_id:
                                    # Fetch Department by Dept_ID (robust relational mapping)
                                    new_dept = Department.objects.filter(id=new_dept_id).first()
                                    
                                    if new_dept:
                                        # Refresh to get latest state from database
                                        new_dept.refresh_from_db()
                                        
                                        # #region agent log - Hypothesis A: Check supervisor_id state BEFORE assignment
                                        log_debug('HYP_A', 'tickets/views.py:2343', 'BEFORE FK assignment check - supervisor_id state', {
                                            'new_dept_id': new_dept_id,
                                            'new_dept_name': new_dept.name,
                                            'supervisor_id_before_check': new_dept.supervisor_id,
                                            'supervisor_id_is_none': new_dept.supervisor_id is None,
                                            'user_id': user.id,
                                            'user_department_role': user.department_role
                                        })
                                        # #endregion
                                        
                                        # Explicitly ASSIGN: Set FK supervisor if department doesn't have another supervisor
                                        if new_dept.supervisor_id is None:
                                            # #region agent log - Hypothesis B: BEFORE save() call
                                            log_debug('HYP_B', 'tickets/views.py:2347', 'BEFORE save() - About to assign FK supervisor', {
                                                'new_dept_id': new_dept_id,
                                                'new_dept_supervisor_id_before': new_dept.supervisor_id,
                                                'user_id': user.id,
                                                'will_assign_to_user': True
                                            })
                                            # #endregion
                                            
                                            new_dept.supervisor = user
                                            new_dept.save(update_fields=['supervisor'])
                                            
                                            # #region agent log - Hypothesis B: AFTER save() - Verify it actually saved
                                            # Force fresh database query to verify the save actually committed
                                            from django.db import connection
                                            with connection.cursor() as cursor:
                                                cursor.execute("SELECT supervisor_id FROM tickets_department WHERE id = %s", [new_dept_id])
                                                row = cursor.fetchone()
                                                db_supervisor_id = row[0] if row else None
                                            
                                            new_dept.refresh_from_db()
                                            log_debug('HYP_B', 'tickets/views.py:2348', 'AFTER save() - Verify FK assignment committed', {
                                                'new_dept_id': new_dept_id,
                                                'new_dept_supervisor_id_after_refresh': new_dept.supervisor_id,
                                                'direct_db_query_supervisor_id': db_supervisor_id,
                                                'expected_user_id': user.id,
                                                'assignment_successful': new_dept.supervisor_id == user.id,
                                                'db_query_matches': db_supervisor_id == user.id
                                            })
                                            # #endregion
                                            
                                            log_debug('UPDATE', 'tickets/views.py:2235', 'ASSIGNED: Set FK supervisor on new department', {
                                                'new_dept_id': new_dept_id,
                                                'new_dept_name': new_dept.name,
                                                'dept_id_used': new_dept.id,
                                                'user_id': user.id
                                            })
                                        else:
                                            # #region agent log - Hypothesis A: Check failed
                                            log_debug('HYP_A', 'tickets/views.py:2346', 'FK assignment SKIPPED - supervisor_id is NOT None', {
                                                'new_dept_id': new_dept_id,
                                                'supervisor_id': new_dept.supervisor_id,
                                                'user_id': user.id,
                                                'assignment_blocked': True
                                            })
                                            # #endregion
                                        
                                        # Explicitly ASSIGN: Add to M2M supervised_departments
                                        # Get current supervised departments (excluding the old one)
                                        # #region agent log - Hypothesis C: BEFORE M2M add
                                        current_supervised_ids_before = list(
                                            user.supervised_departments.values_list('id', flat=True)
                                        )
                                        log_debug('HYP_C', 'tickets/views.py:2361', 'BEFORE M2M add - Current supervised departments', {
                                            'new_dept_id': new_dept_id,
                                            'current_supervised_ids': current_supervised_ids_before,
                                            'new_dept_id_in_list': new_dept_id in current_supervised_ids_before,
                                            'will_add_m2m': new_dept_id not in current_supervised_ids_before,
                                            'user_id': user.id
                                        })
                                        # #endregion
                                        
                                        if new_dept_id not in current_supervised_ids_before:
                                            user.supervised_departments.add(new_dept)
                                            
                                            # #region agent log - Hypothesis C: AFTER M2M add - Verify it actually added
                                            # Force fresh database query to verify M2M was actually committed
                                            from django.db import connection
                                            m2m_table = User.supervised_departments.through._meta.db_table
                                            with connection.cursor() as cursor:
                                                cursor.execute(
                                                    f"SELECT department_id FROM {m2m_table} WHERE user_id = %s AND department_id = %s",
                                                    [user.id, new_dept_id]
                                                )
                                                m2m_row = cursor.fetchone()
                                                m2m_exists_in_db = m2m_row is not None
                                            
                                            # Also refresh M2M relationship
                                            current_supervised_ids_after = list(
                                                user.supervised_departments.values_list('id', flat=True)
                                            )
                                            log_debug('HYP_C', 'tickets/views.py:2362', 'AFTER M2M add - Verify M2M assignment committed', {
                                                'new_dept_id': new_dept_id,
                                                'current_supervised_ids_after': current_supervised_ids_after,
                                                'direct_db_query_m2m_exists': m2m_exists_in_db,
                                                'm2m_add_successful': new_dept_id in current_supervised_ids_after,
                                                'db_query_matches': m2m_exists_in_db == (new_dept_id in current_supervised_ids_after),
                                                'user_id': user.id
                                            })
                                            # #endregion
                                            
                                            log_debug('UPDATE', 'tickets/views.py:2248', 'ASSIGNED: Added to M2M supervised_departments', {
                                                'new_dept_id': new_dept_id,
                                                'new_dept_name': new_dept.name,
                                                'dept_id_used': new_dept.id,
                                                'user_id': user.id
                                            })
                                
                                # STEP 3: Preserve User Role Status - Ensure Team Lead role is maintained
                                # The form.save() method already preserves department_role, but verify it here
                                user.refresh_from_db()
                                if user.department_role not in ['senior', 'manager']:
                                    # This should not happen if form.save() worked correctly, but log it
                                    log_debug('WARNING', 'tickets/views.py:2260', 'Team Lead role may have been lost', {
                                        'user_id': user.id,
                                        'current_department_role': user.department_role,
                                        'expected_role': 'senior or manager'
                                    })
                            elif not is_team_lead:
                                # If user is NOT a Team Lead, clear any supervisor relationships
                                if old_dept_id:
                                    old_dept = Department.objects.filter(id=old_dept_id).first()
                                    if old_dept:
                                        old_dept.refresh_from_db()
                                        if old_dept.supervisor_id == user.id:
                                            old_dept.supervisor = None
                                            old_dept.save(update_fields=['supervisor'])
                                user.supervised_departments.clear()
                                log_debug('UPDATE', 'tickets/views.py:2275', 'Cleared supervisor relationships (not Team Lead)', {})
                            
                            # Final refresh to get latest committed state
                            user.refresh_from_db()
                            # Force database query to get fresh M2M data
                            supervised_dept_ids = list(
                                user.supervised_departments.values_list('id', flat=True)
                            )
                            
                            # #region agent log - Hypothesis D: Direct DB query BEFORE verification (test for stale data)
                            from django.db import connection
                            with connection.cursor() as cursor:
                                # Direct SQL query for FK supervisor on new department
                                cursor.execute("SELECT supervisor_id FROM tickets_department WHERE id = %s", [new_dept_id])
                                db_fk_row = cursor.fetchone()
                                db_new_dept_supervisor_id = db_fk_row[0] if db_fk_row else None
                                
                                # Direct SQL query for M2M relationship
                                m2m_table = User.supervised_departments.through._meta.db_table
                                cursor.execute(
                                    f"SELECT department_id FROM {m2m_table} WHERE user_id = %s AND department_id = %s",
                                    [user.id, new_dept_id]
                                )
                                db_m2m_row = cursor.fetchone()
                                db_m2m_exists = db_m2m_row is not None
                            
                            # Also check ORM state (might be cached)
                            new_dept_orm_check = Department.objects.filter(id=new_dept_id).first()
                            new_dept_orm_supervisor_id = new_dept_orm_check.supervisor_id if new_dept_orm_check else None
                            
                            log_debug('HYP_D', 'tickets/views.py:2478', 'BEFORE verification - Direct DB query vs ORM state', {
                                'new_dept_id': new_dept_id,
                                'direct_db_fk_supervisor_id': db_new_dept_supervisor_id,
                                'orm_fk_supervisor_id': new_dept_orm_supervisor_id,
                                'direct_db_m2m_exists': db_m2m_exists,
                                'orm_m2m_in_list': new_dept_id in supervised_dept_ids,
                                'expected_user_id': user.id,
                                'fk_matches_direct_db': db_new_dept_supervisor_id == user.id,
                                'fk_matches_orm': new_dept_orm_supervisor_id == user.id,
                                'm2m_matches_direct_db': db_m2m_exists,
                                'm2m_matches_orm': new_dept_id in supervised_dept_ids
                            })
                            # #endregion
                            
                            # POST-UPDATE VERIFICATION: System-wide verification of atomic transaction success
                            # CRITICAL: Verify old department (Dept A) is unassigned and new department (Dept B) is assigned
                            # Force fresh database queries to verify the committed state (bypass any caching)
                            
                            # Verify old department (Dept A) is unassigned
                            old_dept_unassigned = True
                            old_dept_verification = {}
                            if old_dept_id:
                                old_dept_check = Department.objects.filter(id=old_dept_id).first()
                                if old_dept_check:
                                    old_dept_check.refresh_from_db()
                                    # Check FK supervisor
                                    has_fk_supervisor = old_dept_check.supervisor_id == user.id
                                    # Check M2M supervisor
                                    has_m2m_supervisor = old_dept_id in supervised_dept_ids
                                    # Old department should NOT have this user as supervisor
                                    old_dept_unassigned = not (has_fk_supervisor or has_m2m_supervisor)
                                    old_dept_verification = {
                                        'dept_id': old_dept_id,
                                        'dept_name': old_dept_check.name,
                                        'has_fk_supervisor': has_fk_supervisor,
                                        'has_m2m_supervisor': has_m2m_supervisor,
                                        'is_unassigned': old_dept_unassigned
                                    }
                            
                            # Verify new department (Dept B) is assigned
                            new_dept_assigned = False
                            new_dept_verification = {}
                            if new_dept_id:
                                new_dept_check = Department.objects.filter(id=new_dept_id).first()
                                if new_dept_check:
                                    new_dept_check.refresh_from_db()
                                    # Check FK supervisor
                                    has_fk_supervisor = new_dept_check.supervisor_id == user.id
                                    # Check M2M supervisor
                                    has_m2m_supervisor = new_dept_id in supervised_dept_ids
                                    # New department SHOULD have this user as supervisor
                                    new_dept_assigned = has_fk_supervisor or has_m2m_supervisor
                                    new_dept_verification = {
                                        'dept_id': new_dept_id,
                                        'dept_name': new_dept_check.name,
                                        'has_fk_supervisor': has_fk_supervisor,
                                        'has_m2m_supervisor': has_m2m_supervisor,
                                        'is_assigned': new_dept_assigned
                                    }
                            
                            # CRITICAL: Verify user authentication fields are preserved
                            auth_fields_after_tx = {
                                'is_active': user.is_active,
                                'role': user.role,
                                'department_role': user.department_role,
                                'national_id': user.national_id,
                                'employee_code': user.employee_code
                            }
                            
                            # Final verification: All checks must pass for system-wide synchronization
                            verification_passed = (
                                old_dept_unassigned and 
                                new_dept_assigned and 
                                user.department_role in ['senior', 'manager'] and
                                user.is_active == auth_fields_before.get('is_active', True)
                            )
                            
                            log_debug('UPDATE', 'tickets/views.py:2422', 'Final state after atomic update - System-wide verification', {
                                'user_id': user.id,
                                'department_id': user.department_id,
                                'department_role': user.department_role,
                                'supervised_dept_ids': supervised_dept_ids,
                                'old_dept_id': old_dept_id,
                                'new_dept_id': new_dept_id,
                                'old_dept_verification': old_dept_verification,
                                'new_dept_verification': new_dept_verification,
                                'auth_fields_after_tx': auth_fields_after_tx,
                                'transaction_complete': True,
                                'verification_passed': verification_passed,
                                'system_ready': verification_passed  # System is ready if verification passes
                            })
                            
                            # If verification failed, log critical error for system-wide awareness
                            if not verification_passed:
                                log_debug('CRITICAL', 'tickets/views.py:2450', 'ATOMIC TRANSACTION VERIFICATION FAILED', {
                                    'user_id': user.id,
                                    'old_dept_unassigned': old_dept_unassigned,
                                    'new_dept_assigned': new_dept_assigned,
                                    'department_role_preserved': user.department_role in ['senior', 'manager'],
                                    'action_required': 'MANUAL_INTERVENTION'
                                })
                    except Exception as e:
                        # #region agent log - HYP_B: Transaction exception - Check if user state corrupted
                        user.refresh_from_db()
                        log_debug('HYP_B', 'tickets/views.py:2607', 'EXCEPTION in atomic transaction - Check user state after rollback', {
                            'error': str(e),
                            'traceback': traceback.format_exc(),
                            'old_dept_id': old_dept_id,
                            'new_dept_id': new_dept_id,
                            'user_id': user.id,
                            'is_active_after_exception': user.is_active,
                            'national_id_after_exception': user.national_id,
                            'employee_code_after_exception': user.employee_code,
                            'department_id_after_exception': user.department_id,
                            'auth_fields_expected': auth_fields_before,
                            'transaction_rolled_back': True,
                            'hypothesis': 'HYP_B - Exception may have corrupted user state'
                        })
                        # #endregion
                        log_debug('ERROR', 'tickets/views.py:2607', 'Error in atomic transaction', {
                            'error': str(e),
                            'traceback': traceback.format_exc(),
                            'old_dept_id': old_dept_id,
                            'new_dept_id': new_dept_id
                        })
                        # Re-raise to ensure transaction rollback
                        raise
                    
                    # #region agent log - Hypothesis E: Check assignment state IMMEDIATELY after transaction commits
                    # Force fresh database query RIGHT after transaction to detect if assignment was cleared
                    from django.db import connection
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT supervisor_id FROM tickets_department WHERE id = %s", [new_dept_id])
                        db_post_tx_row = cursor.fetchone()
                        db_post_tx_supervisor_id = db_post_tx_row[0] if db_post_tx_row else None
                        
                        m2m_table = User.supervised_departments.through._meta.db_table
                        cursor.execute(
                            f"SELECT department_id FROM {m2m_table} WHERE user_id = %s AND department_id = %s",
                            [user.id, new_dept_id]
                        )
                        db_post_tx_m2m_row = cursor.fetchone()
                        db_post_tx_m2m_exists = db_post_tx_m2m_row is not None
                    
                    log_debug('HYP_E', 'tickets/views.py:2616', 'IMMEDIATELY after transaction commit - Check if assignment persists', {
                        'new_dept_id': new_dept_id,
                        'db_supervisor_id_after_tx': db_post_tx_supervisor_id,
                        'db_m2m_exists_after_tx': db_post_tx_m2m_exists,
                        'expected_user_id': user.id,
                        'assignment_still_present': db_post_tx_supervisor_id == user.id or db_post_tx_m2m_exists,
                        'fk_assignment_lost': db_post_tx_supervisor_id != user.id if db_post_tx_supervisor_id else True,
                        'm2m_assignment_lost': not db_post_tx_m2m_exists
                    })
                    # #endregion
                    # #endregion
                    
                    # #region agent log - HYP_E: Check session and request.user state before redirect
                    log_debug('HYP_E', 'tickets/views.py:2644', 'BEFORE redirect - Session and request.user state check', {
                        'request_user_id': request.user.id if request.user.is_authenticated else None,
                        'request_user_is_active': request.user.is_active if request.user.is_authenticated else None,
                        'request_user_has_session': hasattr(request, 'session'),
                        'edited_user_id': user.id,
                        'edited_user_is_active': user.is_active,
                        'edited_user_can_login': user.is_active and user.national_id and user.employee_code
                    })
                    # #endregion
                    
                    # Create notification for IT managers about employee edit
                    try:
                        from .models import Notification
                        it_managers = User.objects.filter(role='it_manager')
                        for manager in it_managers:
                            if manager != request.user:  # Don't notify yourself
                                Notification.objects.create(
                                    recipient=manager,
                                    title=f"ویرایش اطلاعات کارمند: {user.first_name} {user.last_name}",
                                    message=f"ویرایش شده توسط: {request.user.get_full_name()}\nکد پرسنلی: {user.employee_code}",
                                    notification_type='user_created',  # Using existing type for user updates
                                    category='users',
                                    user_actor=request.user
                                )
                    except Exception:
                        pass
                    # Notify IT manager about user edit
                    from .services import notify_it_manager_user_management
                    notify_it_manager_user_management(
                        action_type='update',
                        user=user,
                        actor=request.user
                    )
                    messages.success(request, _('اطلاعات کارمند با موفقیت بروزرسانی شد: {} {}').format(
                        user.first_name, user.last_name
                    ))
                    return redirect('tickets:user_management')
                except Exception as e:
                    # Log the exception for debugging
                    try:
                        # #region agent log - HYP_D: Exception caught - Check final user state
                        if 'user' in locals():
                            user.refresh_from_db()
                            log_debug('HYP_D', 'tickets/views.py:2672', 'EXCEPTION caught - Final user state after exception', {
                                'error': str(e),
                                'traceback': traceback.format_exc(),
                                'user_id': user.id,
                                'is_active_after_exception': user.is_active,
                                'national_id_after_exception': user.national_id,
                                'employee_code_after_exception': user.employee_code,
                                'department_id_after_exception': user.department_id,
                                'can_login': user.is_active and user.national_id and user.employee_code,
                                'hypothesis': 'HYP_D - Exception may have left user in corrupted state'
                            })
                        log_debug('EXCEPTION', 'tickets/views.py:2672', 'Exception in edit_employee', {
                            'error': str(e),
                            'traceback': traceback.format_exc(),
                            'user_id': user.id if 'user' in locals() else None
                        })
                        # #endregion
                    except:
                        pass
                    messages.error(request, _('خطا در بروزرسانی اطلاعات کارمند: {}').format(str(e)))
            else:
                # Show specific field errors to user
                error_messages = []
                for field, errors in form.errors.items():
                    for error in errors:
                        error_messages.append(f"{field}: {error}")
                if error_messages:
                    messages.error(request, _('خطاهای فرم: ') + '; '.join(error_messages))
                else:
                    messages.error(request, _('لطفاً خطاهای فرم را برطرف کنید.'))
        else:
            form = EmployeeEditForm(instance=user)
        
        context = {
            'form': form,
            'edited_user': user,
            'is_edit': True,
            'form_type': 'employee'
        }
        
        return render(request, 'tickets/edit_user.html', context)
    except Exception as e:
        import traceback
        print(f"❌ Error in edit_employee: {e}")
        traceback.print_exc()
        messages.error(request, _('خطا در بارگذاری صفحه ویرایش: {}').format(str(e)))
        return redirect('tickets:user_management')

@login_required
def edit_technician(request, user_id):
    """Edit technician information"""
    try:
        if not is_admin_superuser(request.user):
            messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
            return redirect('tickets:dashboard')
        
        user = get_object_or_404(User, id=user_id, role='technician')
        
        # Prevent editing of admin superuser
        if is_admin_superuser(user):
            messages.error(request, _('نمی‌توانید این کاربر را ویرایش کنید. این کاربر ادمین سیستم است.'))
            return redirect('tickets:user_management')
        
        if request.method == 'POST':
            form = TechnicianEditForm(request.POST, instance=user)
            if form.is_valid():
                try:
                    form.save()
                    # Create notification for IT managers about technician edit
                    try:
                        from .models import Notification
                        it_managers = User.objects.filter(role='it_manager')
                        for manager in it_managers:
                            if manager != request.user:  # Don't notify yourself
                                Notification.objects.create(
                                    recipient=manager,
                                    title=f"ویرایش اطلاعات کارشناس فنی: {user.first_name} {user.last_name}",
                                    message=f"ویرایش شده توسط: {request.user.get_full_name()}\nکد پرسنلی: {user.employee_code}",
                                    notification_type='user_created',  # Using existing type for user updates
                                    category='users',
                                    user_actor=request.user
                                )
                    except Exception:
                        pass
                    # Notify IT manager about technician edit
                    from .services import notify_it_manager_user_management
                    notify_it_manager_user_management(
                        action_type='update',
                        user=user,
                        actor=request.user
                    )
                    messages.success(request, _('اطلاعات کارشناس فنی با موفقیت بروزرسانی شد: {} {}').format(
                        user.first_name, user.last_name
                    ))
                    return redirect('tickets:user_management')
                except Exception as e:
                    messages.error(request, _('خطا در بروزرسانی اطلاعات کارشناس فنی: {}').format(str(e)))
            else:
                # Show specific field errors to user
                error_messages = []
                for field, errors in form.errors.items():
                    for error in errors:
                        error_messages.append(f"{field}: {error}")
                if error_messages:
                    messages.error(request, _('خطاهای فرم: ') + '; '.join(error_messages))
                else:
                    messages.error(request, _('لطفاً خطاهای فرم را برطرف کنید.'))
        else:
            form = TechnicianEditForm(instance=user)
        
        context = {
            'form': form,
            'edited_user': user,
            'is_edit': True,
            'form_type': 'technician'
        }
        
        return render(request, 'tickets/edit_user.html', context)
    except Exception as e:
        import traceback
        print(f"❌ Error in edit_technician: {e}")
        traceback.print_exc()
        messages.error(request, _('خطا در بارگذاری صفحه ویرایش: {}').format(str(e)))
        return redirect('tickets:user_management')


# Statistics API Views
@login_required
def statistics_overview_api(request):
    """API endpoint for statistics overview"""
    if not is_admin_superuser(request.user):
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    # Get date filters from request
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    data_type = request.GET.get('data_type')
    
    # Parse dates if provided
    if date_from:
        try:
            date_from = datetime.strptime(date_from, '%Y-%m-%d')
        except ValueError:
            date_from = None
    
    if date_to:
        try:
            date_to = datetime.strptime(date_to, '%Y-%m-%d')
        except ValueError:
            date_to = None
    
    # Initialize statistics service
    stats_service = StatisticsService(date_from, date_to)
    
    # If specific data type is requested, return only that data
    if data_type == 'hourly_distribution':
        hourly_distribution = stats_service.get_hourly_distribution()
        return JsonResponse({
            'success': True,
            'hourly_distribution': hourly_distribution
        })
    
    # Get overview statistics
    overview = {
        'success': True,
        'total_tickets': stats_service.get_total_tickets(),
        'status_breakdown': stats_service.get_ticket_status_breakdown(),
        'response_times': stats_service.get_average_response_time(),
        'user_stats': stats_service.get_user_statistics(),
        'high_priority': stats_service.get_high_priority_tickets(),
        'fcr_rate': stats_service.get_first_contact_resolution_rate(),
        'hourly_distribution': stats_service.get_hourly_distribution(),
    }
    
    return JsonResponse(overview)


@login_required
def agent_performance_api(request):
    """API endpoint for agent performance data"""
    if not is_admin_superuser(request.user):
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    # Get date filters from request
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    # Parse dates if provided
    if date_from:
        try:
            date_from = datetime.strptime(date_from, '%Y-%m-%d')
        except ValueError:
            date_from = None
    
    if date_to:
        try:
            date_to = datetime.strptime(date_to, '%Y-%m-%d')
        except ValueError:
            date_to = None
    
    # Initialize statistics service
    stats_service = StatisticsService(date_from, date_to)
    
    # Get agent performance data
    agent_performance = stats_service.get_agent_performance()
    
    # Convert to JSON-serializable format
    for agent in agent_performance:
        agent['agent_id'] = agent['agent'].id
        agent['agent_role'] = agent['agent'].role
        del agent['agent']  # Remove the User object
    
    return JsonResponse({'agent_performance': agent_performance})


@login_required
def ticket_trends_api(request):
    """API endpoint for ticket trends data"""
    if not is_admin_superuser(request.user):
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    # Get parameters from request
    period = request.GET.get('period', 'daily')
    days = int(request.GET.get('days', 30))
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    # Parse dates if provided
    if date_from:
        try:
            date_from = datetime.strptime(date_from, '%Y-%m-%d')
        except ValueError:
            date_from = None
    
    if date_to:
        try:
            date_to = datetime.strptime(date_to, '%Y-%m-%d')
        except ValueError:
            date_to = None
    
    # Initialize statistics service
    stats_service = StatisticsService(date_from, date_to)
    
    # Get trend data
    trends = {
        'creation_trend': stats_service.get_ticket_creation_trend(period, days),
        'category_stats': stats_service.get_category_statistics(),
        'priority_stats': stats_service.get_priority_statistics(),
        'hourly_distribution': stats_service.get_hourly_distribution(),
    }
    
    return JsonResponse(trends)


@login_required
def export_statistics(request):
    """Export statistics to Excel/CSV"""
    if not is_admin_superuser(request.user):
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    # Get date filters from request
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    # Parse dates if provided
    if date_from:
        try:
            date_from = datetime.strptime(date_from, '%Y-%m-%d')
        except ValueError:
            date_from = None
    
    if date_to:
        try:
            date_to = datetime.strptime(date_to, '%Y-%m-%d')
        except ValueError:
            date_to = None
    
    # Initialize statistics service
    stats_service = StatisticsService(date_from, date_to)
    
    # Get comprehensive statistics
    stats = stats_service.get_comprehensive_statistics()
    
    # For now, return JSON (Excel export can be implemented later)
    return JsonResponse({
        'message': 'Export functionality will be implemented in the next version',
        'stats': stats
    }) 


# ---------- Custom Error Handlers ----------
def _render_error(request, status_code, message=None):
    # Default messages per status
    default_messages = {
        400: _('درخواست نامعتبر است'),
        403: _('دسترسی غیرمجاز'),
        404: _('صفحه مورد نظر یافت نشد'),
        500: _('خطای داخلی سرور'),
    }
    context = {
        'status_code': status_code,
        'message': message or default_messages.get(status_code, _('خطا رخ داده است')),
    }
    return TemplateResponse(request, 'errors/error.html', context, status=status_code)


def bad_request(request, exception=None):
    return _render_error(request, 400)


def permission_denied(request, exception=None):
    return _render_error(request, 403)


def page_not_found(request, exception=None):
    return _render_error(request, 404)


def server_error(request):
    return _render_error(request, 500)

@login_required
def mark_notification_read(request, notification_id):
    """Mark a specific notification as read"""
    if request.user.role != 'it_manager':
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    try:
        notification = Notification.objects.get(id=notification_id, recipient=request.user)
        notification.is_read = True
        notification.save()
        return JsonResponse({'success': True})
    except Notification.DoesNotExist:
        return JsonResponse({'error': 'اعلان یافت نشد'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def mark_category_read(request, category):
    """Mark all notifications in a category as read"""
    if request.user.role != 'it_manager':
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    try:
        Notification.objects.filter(recipient=request.user, category=category, is_read=False).update(is_read=True)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def notifications_list(request):
    """Main notifications page - loads only metadata, content loaded via AJAX"""
    user = request.user
    if user.role != 'it_manager':
        messages.error(request, _('دسترسی رد شد. فقط مدیر IT میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')

    # Mark all as read if requested
    if request.GET.get('mark') == 'all_read':
        Notification.objects.filter(recipient=user, is_read=False).update(is_read=True)
        messages.success(request, _('تمام اعلان‌ها خوانده شدند.'))
        return redirect('tickets:notifications')

    # Optimized query for counts only - no full notification data loaded
    # Use select_related for foreign keys to avoid N+1 queries
    base_query = Notification.objects.filter(recipient=user).select_related('ticket', 'user_actor', 'recipient')
    
    # Get category display names (Users tab removed)
    category_names = {
        'tickets': _('تیکت‌ها'),
        'system': _('سیستم'),
        'access': _('دسترسی شبکه'),
    }
    
    # Optimized count queries using aggregation
    from django.db.models import Count, Q
    
    # Count unread notifications by category with optimized queries
    unread_counts = {}
    category_has_notifications = {}
    
    for category in category_names.keys():
        category_query = base_query.filter(category=category)
        
        # For tickets category, apply departmental filtering
        if category == 'tickets' and user.department:
            category_query = category_query.filter(
                Q(ticket__isnull=True) | Q(ticket__target_department=user.department)
            )
        
        unread_counts[category] = category_query.filter(is_read=False).count()
        category_has_notifications[category] = category_query.exists()
    
    return render(request, 'tickets/notifications.html', {
        'notifications': [],  # Empty - loaded via AJAX
        'category_names': category_names,
        'unread_counts': unread_counts,
        'category_has_notifications': category_has_notifications,
        'total_unread': sum(unread_counts.values()),
    })


@login_required
def notifications_category_ajax(request, category):
    """AJAX endpoint for loading notifications by category with pagination"""
    user = request.user
    if user.role != 'it_manager':
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    # Redirect 'users' category to 'tickets' (Users tab decommissioned)
    if category == 'users':
        category = 'tickets'
    
    # Validate category (Users tab removed - only tickets, system, access allowed)
    valid_categories = ['tickets', 'system', 'access']
    if category not in valid_categories:
        return JsonResponse({'error': 'دسته‌بندی نامعتبر'}, status=400)
    
    # Base query with optimized joins
    # Use select_related carefully to avoid errors when ticket is None
    base_query = Notification.objects.filter(
        recipient=user,
        category=category
    ).select_related(
        'user_actor',
        'recipient'
    ).order_by('-created_at')
    
    # Apply filtering for tickets category
    if category == 'tickets':
        # Self-action exclusion: Exclude notifications where IT Manager is the actor
        # This ensures only user-initiated actions (ticket creation, user replies) are shown
        base_query = base_query.exclude(user_actor=user)
        
        # Departmental filtering: Only show tickets that belong to IT department
        if user.department:
            base_query = base_query.filter(
                Q(ticket__isnull=True) | Q(ticket__target_department_id=user.department.id)
            )
        
        # Filter to only show user-initiated events from ticket creators (employees):
        # - ticket_created: When employee creates a new ticket (user_actor is the employee)
        # - ticket_urgent: Only when reply is from ticket creator (user_actor == ticket.created_by)
        # Exclude internal actions like status_done, assignment, status_change that are IT-initiated
        base_query = base_query.filter(
            Q(notification_type='ticket_created', user_actor__isnull=False) | 
            Q(
                notification_type='ticket_urgent', 
                ticket__isnull=False,
                user_actor__isnull=False,
                ticket__created_by_id=F('user_actor_id')  # Only show replies from ticket creator
            )
        )
        
        # Exclude notifications from technicians and IT managers (double-check for safety)
        base_query = base_query.exclude(
            Q(user_actor__role='technician') | Q(user_actor__role='it_manager')
        )
        
        base_query = base_query.select_related(
            'ticket',
            'ticket__target_department',
            'ticket__created_by',
            'user_actor'
        ).prefetch_related(
            'ticket__replies'
        )
    else:
        # For non-ticket categories, safely include ticket relations
        base_query = base_query.select_related(
            'ticket',
            'ticket__target_department',
            'ticket__created_by'
        ).prefetch_related(
            'ticket__replies'
        )
    
    # Pagination - load only 20 records per page
    try:
        page_number = int(request.GET.get('page', 1))
        if page_number < 1:
            page_number = 1
    except (ValueError, TypeError):
        page_number = 1
    
    try:
        paginator = Paginator(base_query, 20)
        page_obj = paginator.page(page_number)
    except Exception as e:
        # Log error and return empty page
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Error paginating notifications: {e}')
        page_obj = paginator.page(1) if 'paginator' in locals() else None
        if not page_obj:
            return JsonResponse({
                'notifications': [],
                'has_next': False,
                'has_previous': False,
                'current_page': 1,
                'total_pages': 0,
                'total_count': 0,
                'error': 'خطا در بارگذاری اعلان‌ها'
            }, status=500)
    
    # Serialize notifications with formatted dates
    from tickets.templatetags.persian_date import persian_date
    notifications_data = []
    
    try:
        for notification in page_obj:
            # Format date using the persian_date filter
            try:
                formatted_date = persian_date(notification.created_at)
            except Exception as e:
                # Fallback to ISO format if Persian date conversion fails
                formatted_date = notification.created_at.strftime('%Y-%m-%d %H:%M')
            
            # Safely get ticket info
            ticket_id = None
            ticket_title = None
            if notification.ticket:
                try:
                    ticket_id = notification.ticket.id
                    ticket_title = notification.ticket.title
                except Exception:
                    pass
            
            notification_data = {
                'id': notification.id,
                'title': notification.title or '',
                'message': notification.message or '',
                'notification_type': notification.notification_type,
                'is_read': notification.is_read,
                'created_at': notification.created_at.isoformat() if notification.created_at else '',
                'created_at_formatted': formatted_date,
                'ticket_id': ticket_id,
                'ticket_title': ticket_title,
            }
            notifications_data.append(notification_data)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Error serializing notifications: {e}')
        return JsonResponse({
            'notifications': [],
            'has_next': False,
            'has_previous': False,
            'current_page': 1,
            'total_pages': 0,
            'total_count': 0,
            'error': 'خطا در پردازش اعلان‌ها'
        }, status=500)
    
    return JsonResponse({
        'notifications': notifications_data,
        'has_next': page_obj.has_next() if page_obj else False,
        'has_previous': page_obj.has_previous() if page_obj else False,
        'current_page': page_obj.number if page_obj else 1,
        'total_pages': paginator.num_pages if 'paginator' in locals() else 0,
        'total_count': paginator.count if 'paginator' in locals() else 0,
    })

@login_required
def team_leader_notifications_list(request):
    user = request.user
    if user.role != 'employee' or user.department_role != 'senior':
        messages.error(request, _('دسترسی رد شد. فقط سرپرست.'))
        return redirect('tickets:dashboard')

    # Mark all as read if requested
    if request.GET.get('mark') == 'all_read':
        Notification.objects.filter(recipient=user, is_read=False, category='team_leader_access').update(is_read=True)
        messages.success(request, _('تمام اعلان‌ها خوانده شدند.'))
        return redirect('tickets:team_leader_notifications')

    # Get only team leader access notifications
    all_notifications = Notification.objects.filter(recipient=user, category='team_leader_access').order_by('-created_at')
    
    # Get category display names (only for team leader access)
    category_names = {
        'team_leader_access': _('درخواست‌های دسترسی شبکه'),
    }
    
    # Count unread notifications by category
    unread_counts = {}
    category_has_notifications = {}
    for category in category_names.keys():
        category_notifications = all_notifications.filter(category=category)
        unread_counts[category] = category_notifications.filter(is_read=False).count()
        category_has_notifications[category] = category_notifications.exists()

    return render(request, 'tickets/team_leader_notifications.html', {
        'notifications': all_notifications,
        'category_names': category_names,
        'unread_counts': unread_counts,
        'category_has_notifications': category_has_notifications,
        'total_unread': sum(unread_counts.values()),
    })

@login_required
@require_POST
def team_leader_approve_access(request, ticket_id):
    """Approve Network Access ticket from notification section"""
    user = request.user
    if user.role != 'employee' or user.department_role != 'senior':
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    try:
        # Use dynamic category system: check ticket_category.requires_supervisor_approval instead of hard-coded category='access'
        ticket = get_object_or_404(
            Ticket.objects.filter(
                ticket_category__requires_supervisor_approval=True,
                access_approval_status='pending'
            ),
            id=ticket_id
        )
        
        # Check if supervisor is supervisor of the ticket creator's department (not just same department)
        if not (ticket.created_by and ticket.created_by.department and user.is_supervisor_of(ticket.created_by.department)):
            return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
        
        # Approve the ticket
        ticket.access_approval_status = 'approved'
        ticket.save(update_fields=['access_approval_status'])
        
        # Send detailed email about approval to IT manager using dedicated action type
        from .services import notify_it_manager
        notify_it_manager(
            action_type='access_approved',
            ticket=ticket,
            user=user,
            additional_info=(
                f"تاییدکننده: {user.get_full_name()}\n"
                f"بخش: {ticket.created_by.get_department_display()}\n"
                f"ایجادکننده: {ticket.created_by.get_full_name()}\n"
                f"عنوان: {ticket.title}\n"
                f"توضیحات: {ticket.description}"
            )
        )

        # Create notification for IT managers about access approval
        try:
            it_managers = User.objects.filter(role='it_manager')
            for manager in it_managers:
                Notification.objects.create(
                    recipient=manager,
                    title=f"تایید دسترسی شبکه: {ticket.title}",
                    message=f"کاربر: {ticket.created_by.get_full_name()}\nسرپرست تایید کننده: {user.get_full_name()}\nبخش: {ticket.created_by.get_department_display()}",
                    notification_type='access_approved',
                    category='access',
                    ticket=ticket,
                    user_actor=user
                )
        except Exception:
            pass
        
        # Do not send a separate 'create' email here to avoid duplication for employee-created access tickets
        
        # Mark the team leader notification as read
        Notification.objects.filter(
            recipient=user,
            category='team_leader_access',
            ticket=ticket,
            notification_type='access_pending_approval'
        ).update(is_read=True)
        
        return JsonResponse({
            'success': True,
            'message': 'درخواست دسترسی شبکه تایید شد و برای مدیر IT ارسال گردید.'
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_POST
def team_leader_reject_access(request, ticket_id):
    """Reject Network Access ticket from notification section"""
    user = request.user
    if user.role != 'employee' or user.department_role != 'senior':
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    try:
        # Use dynamic category system: check ticket_category.requires_supervisor_approval instead of hard-coded category='access'
        ticket = get_object_or_404(
            Ticket.objects.filter(
                ticket_category__requires_supervisor_approval=True,
                access_approval_status='pending'
            ),
            id=ticket_id
        )
        
        # Check if supervisor is supervisor of the ticket creator's department (not just same department)
        if not (ticket.created_by and ticket.created_by.department and user.is_supervisor_of(ticket.created_by.department)):
            return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
        
        # Store ticket info before deletion for email/notification reference
        ticket_title = ticket.title
        ticket_creator_name = ticket.created_by.get_full_name()
        ticket_creator_department = ticket.created_by.get_department_display()
        ticket_description = ticket.description
        
        # Send rejection email to the employee (creator) and team leader keeps a record
        from .services import notify_employee
        notify_employee(
            action_type='access_rejected',
            ticket=ticket,
            user=user,
            additional_info=f"درخواست دسترسی شبکه رد شد.\nعنوان: {ticket_title}\nکاربر: {ticket_creator_name}\nسرپرست ردکننده: {user.get_full_name()}\nبخش: {ticket_creator_department}\nتوضیحات: {ticket_description}"
        )

        # Delete the rejected ticket completely from database
        ticket.delete()
        
        # Note: No notification to IT manager since they never knew about this ticket
        # The ticket was pending approval and never reached IT manager's attention
        
        # Mark the team leader notification as read
        Notification.objects.filter(
            recipient=user,
            category='team_leader_access',
            notification_type='access_pending_approval'
        ).filter(
            title__icontains=ticket_title
        ).update(is_read=True)
        
        return JsonResponse({
            'success': True,
            'message': 'درخواست دسترسی شبکه رد شد.'
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# Department Management Views
@login_required
def department_management(request):
    """Department management view for Administrator"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    departments = Department.objects.all().order_by('department_type', 'name')
    
    # Statistics
    employee_departments = departments.filter(department_type='employee')
    technician_departments = departments.filter(department_type='technician')
    
    context = {
        'departments': departments,
        'employee_departments': employee_departments,
        'technician_departments': technician_departments,
        'total_departments': departments.count(),
        'total_employee_departments': employee_departments.count(),
        'total_technician_departments': technician_departments.count(),
    }
    
    return render(request, 'tickets/department_management.html', context)

@login_required
def department_create(request):
    """Create a new department"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            # Additional validation to prevent IT Department creation
            department_name = form.cleaned_data.get('name', '').lower().strip()
            if department_name in ['it department', 'it', 'information technology', 'information technology department']:
                messages.error(request, _('ایجاد بخش IT برای دلایل امنیتی مجاز نیست.'))
                return redirect('tickets:department_management')
            
            department = form.save()
            if not department.branch:
                messages.warning(request, _('بخش "{}" با موفقیت ایجاد شد. لطفاً یک شعبه ایجاد کرده و به این بخش اختصاص دهید.').format(department.name))
            else:
                messages.success(request, _('بخش "{}" با موفقیت ایجاد شد.').format(department.name))
            return redirect('tickets:department_management')
        else:
            messages.error(request, _('خطا در ایجاد بخش. لطفاً اطلاعات را بررسی کنید.'))
    else:
        form = DepartmentForm()
    
    context = {
        'form': form,
        'action': 'create',
        'title': _('ایجاد بخش جدید')
    }
    
    return render(request, 'tickets/department_form.html', context)

@login_required
def department_edit(request, department_id):
    """Edit an existing department"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    department = get_object_or_404(Department, id=department_id)
    
    if request.method == 'POST':
        form = DepartmentForm(request.POST, instance=department)
        if form.is_valid():
            # Additional validation to prevent IT Department creation
            department_name = form.cleaned_data.get('name', '').lower().strip()
            if department_name in ['it department', 'it', 'information technology', 'information technology department']:
                messages.error(request, _('ایجاد بخش IT برای دلایل امنیتی مجاز نیست.'))
                return redirect('tickets:department_management')
            
            department = form.save()
            if not department.branch:
                messages.warning(request, _('بخش "{}" بروزرسانی شد. توجه: این بخش نیاز به یک شعبه دارد. لطفاً یک شعبه ایجاد کرده و به این بخش اختصاص دهید.').format(department.name))
            else:
                messages.success(request, _('بخش "{}" با موفقیت بروزرسانی شد.').format(department.name))
            return redirect('tickets:department_management')
        else:
            # Show detailed form errors
            error_messages = []
            for field, errors in form.errors.items():
                field_label = form.fields[field].label if field in form.fields else field
                for error in errors:
                    error_messages.append(f"{field_label}: {error}")
            if error_messages:
                messages.error(request, _('خطا در بروزرسانی بخش: {}').format(' | '.join(error_messages)))
            else:
                messages.error(request, _('خطا در بروزرسانی بخش. لطفاً اطلاعات را بررسی کنید.'))
    else:
        form = DepartmentForm(instance=department)
    
    context = {
        'form': form,
        'department': department,
        'action': 'edit',
        'title': _('ویرایش بخش')
    }
    
    return render(request, 'tickets/department_form.html', context)

@login_required
@require_POST
def department_toggle_tickets(request, department_id):
    """Toggle can_receive_tickets for a department"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    department = get_object_or_404(Department, id=department_id)
    
    # Check if department has a branch before enabling ticket reception
    if not department.branch and not department.can_receive_tickets:
        messages.error(request, _('ابتدا باید یک شعبه به بخش "{}" اختصاص دهید.').format(department.name))
        return redirect('tickets:department_management')
    
    # Toggle the can_receive_tickets status
    department.can_receive_tickets = not department.can_receive_tickets
    department.save(update_fields=['can_receive_tickets'])
    
    if department.can_receive_tickets:
        messages.success(request, _('بخش "{}" اکنون می‌تواند تیکت دریافت کند. تیکت‌های ارسالی به این بخش به سرپرست بخش ارسال می‌شوند.').format(department.name))
    else:
        messages.info(request, _('بخش "{}" دیگر نمی‌تواند تیکت دریافت کند.').format(department.name))
    
    return redirect('tickets:department_management')

@login_required
@require_POST
def department_toggle_warehouse(request, department_id):
    """Toggle has_warehouse for a department"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    department = get_object_or_404(Department, id=department_id)
    
    # Toggle the has_warehouse status
    was_enabled = department.has_warehouse
    department.has_warehouse = not department.has_warehouse
    department.save(update_fields=['has_warehouse'])
    
    if department.has_warehouse and not was_enabled:
        # Warehouse is being enabled - create the warehouse element
        try:
            warehouse = get_department_warehouse(department)
            if warehouse:
                messages.success(request, _('ماژول انبار برای بخش "{}" فعال شد. انبار با موفقیت ایجاد شد و سرپرست این بخش می‌تواند به آن دسترسی داشته باشد.').format(department.name))
            else:
                messages.warning(request, _('ماژول انبار برای بخش "{}" فعال شد، اما ایجاد انبار با مشکل مواجه شد. لطفاً مطمئن شوید که بخش دارای سرپرست است.').format(department.name))
        except Exception as e:
            messages.error(request, _('خطا در ایجاد انبار: {}').format(str(e)))
    elif not department.has_warehouse and was_enabled:
        # Warehouse is being disabled - deactivate the warehouse element (don't delete, just deactivate)
        try:
            warehouse = get_department_warehouse(department)
            if warehouse:
                warehouse.is_active = False
                warehouse.save(update_fields=['is_active'])
            messages.info(request, _('ماژول انبار برای بخش "{}" غیرفعال شد.').format(department.name))
        except Exception:
            messages.info(request, _('ماژول انبار برای بخش "{}" غیرفعال شد.').format(department.name))
    
    return redirect('tickets:department_management')

@login_required
def warehouse_management(request):
    """
    Warehouse management view - accessible to supervisors and delegated users.
    Redirects to the new DWMS system (warehouse_selection) which supports all access levels.
    """
    user = request.user
    
    # Only employees can access warehouses
    if user.role != 'employee':
        messages.error(request, _('شما اجازه دسترسی به این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Check if user has any warehouse access (supervisor OR delegate)
    has_access = False
    warehouse_departments = []
    
    # Check supervisor access
    is_supervisor = user.department_role in ['senior', 'manager']
    if is_supervisor:
        supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
        warehouse_departments = [d for d in supervised_depts if d.has_warehouse] if supervised_depts else []
        
        # Also check if user's own department has warehouse
        if user.department and user.department.has_warehouse and user.department not in warehouse_departments:
            warehouse_departments.append(user.department)
        
        if warehouse_departments:
            has_access = True
    
    # Check for delegated access (read or write) via WarehouseAccess table
    # This allows non-supervisor employees with delegated access
    try:
        from dwms.models import WarehouseAccess
        delegated_accesses = WarehouseAccess.objects.filter(
            user=user,
            is_active=True
        ).select_related('warehouse', 'warehouse__department')
        
        if delegated_accesses.exists():
            has_access = True
            # Add delegated warehouses to list
            for access in delegated_accesses:
                dept = access.warehouse.department
                if dept.has_warehouse and dept not in warehouse_departments:
                    warehouse_departments.append(dept)
    except Exception:
        # If WarehouseAccess model doesn't exist, continue with supervisor check only
        pass
    
    if not has_access:
        messages.error(request, _('شما به هیچ انباری دسترسی ندارید. لطفاً با مدیر سیستم تماس بگیرید.'))
        return redirect('tickets:dashboard')
    
    # Redirect to new DWMS system which supports all access levels (supervisor, write, read)
    # The DWMS system has proper permission handling and supports delegated users
    return redirect('dwms:warehouse_selection')

@login_required
def department_delete(request, department_id):
    """Delete a department"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    department = get_object_or_404(Department, id=department_id)
    
    # Check if department has users
    user_count = department.get_user_count()
    
    if request.method == 'POST':
        if user_count > 0:
            messages.error(request, _('نمی‌توان بخشی که دارای کاربر است را حذف کرد. ابتدا کاربران را به بخش دیگری منتقل کنید.'))
        else:
            department_name = department.name
            department.delete()
            messages.success(request, _('بخش "{}" با موفقیت حذف شد.').format(department_name))
        return redirect('tickets:department_management')
    
    context = {
        'department': department,
        'user_count': user_count
    }
    
    return render(request, 'tickets/department_confirm_delete.html', context)

@login_required
def category_list(request):
    """List ticket categories for supervisor's or IT manager's department"""
    user = request.user
    
    # Check if user is a supervisor or IT manager
    is_supervisor = (user.role == 'employee' and user.department_role in ['senior', 'manager'])
    is_it_manager = (user.role == 'it_manager')
    
    if not (is_supervisor or is_it_manager):
        messages.error(request, _('دسترسی رد شد. فقط سرپرست بخش یا مدیر IT میتواند این بخش را مشاهده کند.'))
        return redirect('tickets:dashboard')
    
    # Get user's department
    if is_it_manager:
        # For IT Manager, use the IT department
        department = get_it_department()
        if not department:
            messages.error(request, _('خطا: بخش IT یافت نشد. لطفاً با مدیر سیستم تماس بگیرید.'))
            return redirect('tickets:dashboard')
    else:
        # For supervisor, use their assigned department
        department = user.department
    
    if not department or not department.can_receive_tickets:
        messages.error(request, _('بخش شما مجاز به دریافت تیکت نیست.'))
        return redirect('tickets:dashboard')
    
    categories = TicketCategory.objects.filter(department=department).order_by('sort_order', 'name')
    
    context = {
        'categories': categories,
        'department': department,
    }
    
    return render(request, 'tickets/category_list.html', context)

@login_required
def category_create(request):
    """Create a new ticket category for supervisor's or IT manager's department"""
    user = request.user
    
    # Check if user is a supervisor or IT manager
    is_supervisor = (user.role == 'employee' and user.department_role in ['senior', 'manager'])
    is_it_manager = (user.role == 'it_manager')
    
    if not (is_supervisor or is_it_manager):
        messages.error(request, _('دسترسی رد شد. فقط سرپرست بخش یا مدیر IT میتواند این بخش را مشاهده کند.'))
        return redirect('tickets:dashboard')
    
    # Get user's department
    if is_it_manager:
        # For IT Manager, use the IT department
        department = get_it_department()
        if not department:
            messages.error(request, _('خطا: بخش IT یافت نشد. لطفاً با مدیر سیستم تماس بگیرید.'))
            return redirect('tickets:dashboard')
    else:
        # For supervisor, use their assigned department
        department = user.department
    
    if not department or not department.can_receive_tickets:
        messages.error(request, _('بخش شما مجاز به دریافت تیکت نیست.'))
        return redirect('tickets:category_list')
    
    if request.method == 'POST':
        form = TicketCategoryForm(request.POST)
        if form.is_valid():
            # Validate department exists and user has permission
            if not department:
                messages.error(request, _('خطا: بخش شما یافت نشد. لطفاً با مدیر سیستم تماس بگیرید.'))
                return redirect('tickets:category_list')
            
            # Create instance manually to avoid RelatedObjectDoesNotExist during form.save(commit=False)
            # The form doesn't include department field (for security), so we create the instance directly
            # This prevents Django from trying to access category.department before it's set
            category = TicketCategory()
            category.name = form.cleaned_data['name']
            category.description = form.cleaned_data.get('description', '')
            category.is_active = form.cleaned_data.get('is_active', True)
            category.sort_order = form.cleaned_data.get('sort_order', 0)
            
            # Assign required foreign key relationships before saving
            # Department is excluded from the form for security (supervisor can only create for their own department)
            category.department = department
            category.created_by = request.user
            
            # Now that department is set, run full validation
            try:
                category.full_clean()
            except ValidationError as e:
                # If validation fails, show errors
                for field, errors in e.error_dict.items():
                    for error in errors:
                        messages.error(request, f'{field}: {error}')
                # Re-render form with errors
            else:
                # Save the instance with all required relationships set and validated
                try:
                    category.save()
                    messages.success(request, _('دسته‌بندی "{}" با موفقیت ایجاد شد.').format(category.name))
                    return redirect('tickets:category_list')
                except Exception as e:
                    messages.error(request, _('خطا در ایجاد دسته‌بندی: {}').format(str(e)))
        else:
            messages.error(request, _('خطا در ایجاد دسته‌بندی. لطفاً اطلاعات را بررسی کنید.'))
    else:
        form = TicketCategoryForm()
    
    context = {
        'form': form,
        'department': department,
        'action': 'create',
        'title': _('ایجاد دسته‌بندی جدید')
    }
    
    return render(request, 'tickets/category_form.html', context)

@login_required
def category_edit(request, category_id):
    """Edit an existing ticket category"""
    user = request.user
    
    # Check if user is a supervisor or IT manager
    is_supervisor = (user.role == 'employee' and user.department_role in ['senior', 'manager'])
    is_it_manager = (user.role == 'it_manager')
    
    if not (is_supervisor or is_it_manager):
        messages.error(request, _('دسترسی رد شد. فقط سرپرست بخش یا مدیر IT میتواند این بخش را مشاهده کند.'))
        return redirect('tickets:dashboard')
    
    # Get user's department
    if is_it_manager:
        # For IT Manager, use the IT department
        department = get_it_department()
        if not department:
            messages.error(request, _('خطا: بخش IT یافت نشد. لطفاً با مدیر سیستم تماس بگیرید.'))
            return redirect('tickets:dashboard')
    else:
        # For supervisor, use their assigned department
        department = user.department
    
    if not department or not department.can_receive_tickets:
        messages.error(request, _('بخش شما مجاز به دریافت تیکت نیست.'))
        return redirect('tickets:category_list')
    
    category = get_object_or_404(TicketCategory, id=category_id, department=department)
    
    if request.method == 'POST':
        form = TicketCategoryForm(request.POST, instance=category)
        if form.is_valid():
            category = form.save()
            messages.success(request, _('دسته‌بندی "{}" با موفقیت بروزرسانی شد.').format(category.name))
            return redirect('tickets:category_list')
        else:
            messages.error(request, _('خطا در بروزرسانی دسته‌بندی. لطفاً اطلاعات را بررسی کنید.'))
    else:
        form = TicketCategoryForm(instance=category)
    
    context = {
        'form': form,
        'category': category,
        'department': department,
        'action': 'edit',
        'title': _('ویرایش دسته‌بندی')
    }
    
    return render(request, 'tickets/category_form.html', context)

@login_required
def category_delete(request, category_id):
    """Delete a ticket category"""
    user = request.user
    
    # Check if user is a supervisor or IT manager
    is_supervisor = (user.role == 'employee' and user.department_role in ['senior', 'manager'])
    is_it_manager = (user.role == 'it_manager')
    
    if not (is_supervisor or is_it_manager):
        messages.error(request, _('دسترسی رد شد. فقط سرپرست بخش یا مدیر IT میتواند این بخش را مشاهده کند.'))
        return redirect('tickets:dashboard')
    
    # Get user's department
    if is_it_manager:
        # For IT Manager, use the IT department
        department = get_it_department()
        if not department:
            messages.error(request, _('خطا: بخش IT یافت نشد. لطفاً با مدیر سیستم تماس بگیرید.'))
            return redirect('tickets:dashboard')
    else:
        # For supervisor, use their assigned department
        department = user.department
    
    if not department or not department.can_receive_tickets:
        messages.error(request, _('بخش شما مجاز به دریافت تیکت نیست.'))
        return redirect('tickets:category_list')
    
    category = get_object_or_404(TicketCategory, id=category_id, department=department)
    
    # Check if category is in use
    ticket_count = category.tickets.count()
    
    if request.method == 'POST':
        if ticket_count > 0:
            messages.error(request, _('نمی‌توان دسته‌بندی که در حال استفاده است را حذف کرد. {} تیکت از این دسته‌بندی استفاده می‌کند.').format(ticket_count))
        else:
            category_name = category.name
            category.delete()
            messages.success(request, _('دسته‌بندی "{}" با موفقیت حذف شد.').format(category_name))
        return redirect('tickets:category_list')
    
    context = {
        'category': category,
        'department': department,
        'ticket_count': ticket_count
    }
    
    return render(request, 'tickets/category_confirm_delete.html', context)

@login_required
def get_department_categories(request, department_id):
    """API endpoint to get categories for a department"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    department = get_object_or_404(Department, id=department_id)
    
    # Check if department can receive tickets
    if not department.can_receive_tickets:
        return JsonResponse({'error': 'Department cannot receive tickets'}, status=403)
    
    categories = TicketCategory.objects.filter(
        department=department,
        is_active=True
    ).order_by('sort_order', 'name').values('id', 'name', 'description')
    
    return JsonResponse({'categories': list(categories)})

@login_required
def supervisor_assignment(request):
    """View for assigning supervisors to departments (Administrator only)"""
    # #region agent log - entry point
    import json
    import os
    import traceback
    from datetime import datetime
    log_path = r'c:\Users\User\Desktop\pticket-main\.cursor\debug.log'
    def log_debug(hypothesis_id, location, message, data):
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            entry = {
                'id': f'log_{int(datetime.now().timestamp() * 1000)}',
                'timestamp': int(datetime.now().timestamp() * 1000),
                'location': location,
                'message': message,
                'data': data,
                'sessionId': 'debug-session',
                'runId': 'run1',
                'hypothesisId': hypothesis_id
            }
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception as e:
            try:
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({'error': str(e), 'traceback': traceback.format_exc()}, ensure_ascii=False) + '\n')
            except: pass
    log_debug('ENTRY', 'tickets/views.py:2833', 'supervisor_assignment view called', {'user': str(request.user)})
    # #endregion
    
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    if request.method == 'POST':
        form = SupervisorAssignmentForm(request.POST)
        if form.is_valid():
            supervisor = form.cleaned_data['supervisor']
            departments = form.cleaned_data['departments']
            
            try:
                # Assign supervisor to each selected department
                for department in departments:
                    # Check if department already has a supervisor
                    if department.supervisor and department.supervisor != supervisor:
                        messages.warning(
                            request,
                            _('بخش "{}" قبلاً سرپرست دارد. ابتدا سرپرست قبلی را حذف کنید.').format(department.name)
                        )
                        continue
                    
                    department.supervisor = supervisor
                    department.save(update_fields=['supervisor'])
                    
                    # Track in the ManyToMany helper field as well (this creates the M2M relationship)
                    supervisor.supervised_departments.add(department)
                    
                    # Refresh supervisor from database to ensure relationships are up-to-date
                    supervisor.refresh_from_db()
                
                if departments:
                    dept_names = ', '.join([d.name for d in departments])
                    messages.success(request, _('سرپرست "{}" با موفقیت به بخش‌های زیر اختصاص داده شد: {}').format(
                        supervisor.get_full_name(), dept_names
                    ))
                else:
                    messages.warning(request, _('هیچ بخشی انتخاب نشد.'))
            except Exception as exc:
                messages.error(request, _('خطا در ذخیره‌سازی سرپرست: {}').format(exc))
            
            return redirect('tickets:supervisor_assignment')
        else:
            messages.error(request, _('خطا در فرم. لطفاً اطلاعات را بررسی کنید.'))
    else:
        form = SupervisorAssignmentForm()
    
    # Get all supervisors and their departments (senior employees)
    # Include both M2M supervised_departments and FK supervisor relationships
    supervisors = User.objects.filter(
        role='employee',
        department_role__in=['senior', 'manager'],
        is_active=True
    ).prefetch_related('supervised_departments').order_by('first_name', 'last_name')
    
    # #region agent log - Bug 2: Supervisor availability
    log_debug('BUG2', 'tickets/views.py:2883', 'Available supervisors queryset', {
        'total_count': supervisors.count(),
        'supervisor_details': [
            {
                'id': s.id,
                'name': s.get_full_name(),
                'department_id': s.department_id,
                'department_name': s.department.name if s.department else None,
                'department_role': s.department_role,
                'is_active': s.is_active,
                'supervised_dept_ids': list(s.supervised_departments.values_list('id', flat=True))
            } for s in supervisors[:20]
        ]
    })
    # #endregion
    
    # Filter departments to only show those WITHOUT a supervisor (Team Lead)
    # A department has a Team Lead if ANY of the following is true:
    # 1. It has an ACTIVE ForeignKey supervisor (supervisor field is not null AND supervisor.is_active=True)
    # 2. It has an ACTIVE ManyToMany supervisor (in any user's supervised_departments AND user.is_active=True)
    # 3. It has an ACTIVE user with department_role='senior' or 'manager' who belongs to that department (user.department=dept)
    # 
    # We need to exclude departments that have ANY of these three types of Team Leads.
    # This includes:
    # - Empty departments (no employees) that also have no Team Lead
    # - Staffed departments (with employees) that have no Team Lead
    
    # Comprehensive filtering: Exclude departments with ANY type of active Team Lead
    # Method 1: Exclude departments with active FK supervisor
    depts_with_fk_supervisor = Department.objects.filter(
        is_active=True,
        department_type='employee',
        supervisor__isnull=False,
        supervisor__is_active=True
    ).values_list('id', flat=True)
    
    # Method 2: Exclude departments with active M2M supervisors
    depts_with_m2m_supervisor = Department.objects.filter(
        is_active=True,
        department_type='employee',
        supervisors__is_active=True
    ).values_list('id', flat=True)
    
    # Method 3: Exclude departments with active users having department_role='senior' or 'manager'
    # CRITICAL: Query from User side to avoid reverse relationship caching issues and ensure latest data
    # Use values_list with distinct to get fresh department IDs directly from database
    # This ensures we get the latest committed data without any object caching
    # SYSTEM-WIDE AWARENESS: This query executes against freshly committed data after atomic transactions
    depts_with_role_based_leads = list(
        User.objects.filter(
            role='employee',
            department_role__in=['senior', 'manager'],
            is_active=True,
            department__isnull=False,
            department__is_active=True,
            department__department_type='employee'
        ).select_related('department').values_list('department_id', flat=True).distinct()
    )
    
    # #region agent log - Bug 1: Department filtering analysis
    # Check specific departments and their role-based leads
    all_depts_for_check = Department.objects.filter(
        is_active=True,
        department_type='employee'
    ).select_related().prefetch_related('users')
    
    dept_analysis = []
    for dept in all_depts_for_check[:20]:  # Limit for log size
        role_based_users = dept.users.filter(
            department_role__in=['senior', 'manager'],
            is_active=True
        )
        dept_analysis.append({
            'dept_id': dept.id,
            'dept_name': dept.name,
            'has_fk_supervisor': dept.supervisor_id is not None,
            'fk_supervisor_id': dept.supervisor_id,
            'fk_supervisor_active': dept.supervisor.is_active if dept.supervisor else None,
            'role_based_users': [
                {
                    'user_id': u.id,
                    'user_name': u.get_full_name(),
                    'department_id': u.department_id,
                    'department_role': u.department_role,
                    'is_active': u.is_active
                } for u in role_based_users
            ],
            'in_fk_excluded': dept.id in depts_with_fk_supervisor,
            'in_m2m_excluded': dept.id in depts_with_m2m_supervisor,
            'in_role_excluded': dept.id in depts_with_role_based_leads
        })
    
    log_debug('BUG1', 'tickets/views.py:2918', 'Department filtering analysis', {
        'fk_excluded_ids': list(depts_with_fk_supervisor),
        'm2m_excluded_ids': list(depts_with_m2m_supervisor),
        'role_excluded_ids': list(depts_with_role_based_leads),
        'dept_analysis': dept_analysis
    })
    # #endregion
    
    # Combine all excluded department IDs
    all_excluded_dept_ids = set(depts_with_fk_supervisor) | set(depts_with_m2m_supervisor) | set(depts_with_role_based_leads)
    
    # Final queryset: All active employee departments EXCEPT those with any type of Team Lead
    if all_excluded_dept_ids:
        departments_without_supervisor = Department.objects.filter(
            is_active=True,
            department_type='employee'
        ).exclude(id__in=all_excluded_dept_ids).distinct().order_by('name')
    else:
        departments_without_supervisor = Department.objects.filter(
            is_active=True,
            department_type='employee'
        ).distinct().order_by('name')
    
    # #region agent log - Bug 1: Final filtered departments
    log_debug('BUG1', 'tickets/views.py:2935', 'Final departments without supervisor', {
        'filtered_count': departments_without_supervisor.count(),
        'filtered_dept_ids': list(departments_without_supervisor.values_list('id', flat=True)[:20]) if departments_without_supervisor.exists() else [],
        'filtered_dept_names': list(departments_without_supervisor.values_list('name', flat=True)[:20]) if departments_without_supervisor.exists() else []
    })
    # #endregion
    
    context = {
        'form': form,
        'supervisors': supervisors,
        'departments_without_supervisor': departments_without_supervisor,
    }
    
    return render(request, 'tickets/supervisor_assignment.html', context)

@login_required
def remove_supervisor_from_department(request, department_id):
    """Remove supervisor from a department (Administrator only)"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    department = get_object_or_404(Department, id=department_id)
    
    if request.method == 'POST':
        # Find supervisor through FK relationship
        supervisor_fk = department.supervisor
        
        # Find supervisor through M2M relationship
        supervisor_m2m = department.supervisors.filter(is_active=True).first()
        
        # Use FK supervisor if available, otherwise use M2M supervisor
        supervisor = supervisor_fk or supervisor_m2m
        
        if supervisor:
            # Remove from ManyToMany (works even if not present)
            supervisor.supervised_departments.remove(department)
            # Clear ForeignKey if it points to this supervisor
            if department.supervisor == supervisor:
                department.supervisor = None
                department.save()
            messages.success(request, _('سرپرست "{}" از بخش "{}" حذف شد.').format(
                supervisor.get_full_name(), department.name
            ))
        else:
            messages.warning(request, _('این بخش سرپرست ندارد.'))
        
        return redirect('tickets:supervisor_assignment')
    
    context = {
        'department': department,
    }
    return render(request, 'tickets/remove_supervisor_confirm.html', context)

@login_required
def supervisor_ticket_responder_management(request):
    """Supervisor view for managing ticket responder assignment"""
    user = request.user
    
    # Only allow supervisors (senior/manager) with at least one supervised department that can receive tickets
    is_supervisor = (user.role == 'employee' and user.department_role in ['senior', 'manager'])
    supervised_depts = user.get_supervised_departments() if is_supervisor else []
    
    if not is_supervisor or not supervised_depts:
        messages.error(request, _('دسترسی رد شد. فقط سرپرست بخش می‌تواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    # Check if at least one supervised department can receive tickets
    departments_that_can_receive = [d for d in supervised_depts if d.can_receive_tickets]
    if not departments_that_can_receive:
        messages.error(request, _('هیچ یک از بخش‌های تحت سرپرستی شما قابلیت دریافت تیکت را ندارد. لطفاً با مدیر IT تماس بگیرید.'))
        return redirect('tickets:dashboard')
    
    if request.method == 'POST':
        department_id = request.POST.get('department_id')
        ticket_responder_id = request.POST.get('ticket_responder')
        task_creator_id = request.POST.get('task_creator')
        
        if not department_id:
            messages.error(request, _('بخش انتخاب نشده است.'))
            # Redirect back with GET parameter if we had one
            if request.GET.get('department_id'):
                return redirect(f"{reverse('tickets:supervisor_ticket_responder_management')}?department_id={request.GET.get('department_id')}")
            return redirect('tickets:supervisor_ticket_responder_management')
        
        # Validate that the selected department is one of the user's supervised departments
        try:
            department = Department.objects.get(id=department_id)
            if department not in supervised_depts:
                messages.error(request, _('بخش انتخاب شده معتبر نیست.'))
                return redirect('tickets:supervisor_ticket_responder_management')
        except Department.DoesNotExist:
            messages.error(request, _('بخش انتخاب شده معتبر نیست.'))
            return redirect('tickets:supervisor_ticket_responder_management')
        
        # --- Update ticket responder (can respond to tickets) ---
        if ticket_responder_id:
            try:
                # Validate that the selected user belongs to one of the supervised departments and is not a supervisor
                supervised_dept_ids = [d.id for d in supervised_depts]
                ticket_responder = User.objects.get(
                    id=ticket_responder_id,
                    department__in=supervised_dept_ids,
                    role='employee',
                    is_active=True
                )
                # Exclude admin superuser and supervisors
                if is_admin_superuser(ticket_responder) or ticket_responder.department_role == 'senior':
                    messages.error(request, _('نمی‌توانید این کاربر را به‌عنوان پاسخ‌دهنده انتخاب کنید.'))
                    return redirect('tickets:supervisor_ticket_responder_management')
                
                department.ticket_responder = ticket_responder
                department.save(update_fields=['ticket_responder'])
                messages.success(request, _('پاسخ‌دهنده تیکت با موفقیت تعیین شد: {} {}').format(
                    ticket_responder.first_name, ticket_responder.last_name
                ))
            except User.DoesNotExist:
                messages.error(request, _('کاربر انتخاب شده برای پاسخ‌دهنده معتبر نیست.'))
        else:
            # Clear ticket responder
            department.ticket_responder = None
            department.save(update_fields=['ticket_responder'])
            messages.success(request, _('پاسخ‌دهنده تیکت حذف شد. تیکت‌ها به شما (سرپرست) ارسال می‌شوند.'))

        # --- Update task creator (can create tasks for this department) ---
        if task_creator_id:
            try:
                supervised_dept_ids = [d.id for d in supervised_depts]
                task_creator = User.objects.get(
                    id=task_creator_id,
                    department__in=supervised_dept_ids,
                    role='employee',
                    is_active=True
                )
                # Exclude admin superuser and supervisors
                if is_admin_superuser(task_creator) or task_creator.department_role == 'senior':
                    messages.error(request, _('نمی‌توانید این کاربر را به‌عنوان ایجادکننده تسک انتخاب کنید.'))
                    return redirect('tickets:supervisor_ticket_responder_management')
                
                department.task_creator = task_creator
                department.save(update_fields=['task_creator'])
                messages.success(request, _('ایجادکننده تسک با موفقیت تعیین شد: {} {}').format(
                    task_creator.first_name, task_creator.last_name
                ))
            except User.DoesNotExist:
                messages.error(request, _('کاربر انتخاب شده برای ایجادکننده تسک معتبر نیست.'))
        else:
            # Clear task creator
            department.task_creator = None
            department.save(update_fields=['task_creator'])
        
        return redirect('tickets:supervisor_ticket_responder_management')
    
    # Get selected department from GET parameter (for display)
    selected_dept_id = request.GET.get('department_id')
    selected_department = None
    if selected_dept_id:
        try:
            selected_department = next((d for d in supervised_depts if d.id == int(selected_dept_id)), None)
        except (ValueError, TypeError):
            pass
    
    # If no department selected and there are departments that can receive, use the first one
    if not selected_department and departments_that_can_receive:
        selected_department = departments_that_can_receive[0]
    elif not selected_department and supervised_depts:
        selected_department = supervised_depts[0]
    
    # Get employees from selected department (or all if no selection)
    from .admin_security import get_admin_superuser_queryset_filter
    admin_filter = get_admin_superuser_queryset_filter()
    
    if selected_department:
        employees = User.objects.filter(
            department=selected_department,
            role='employee',
            is_active=True
        ).filter(admin_filter).exclude(
            id=user.id  # Exclude the supervisor themselves
        ).exclude(
            department_role__in=['senior', 'manager']  # Exclude supervisors
        ).order_by('first_name', 'last_name')
        current_responder = selected_department.ticket_responder
        current_task_creator = selected_department.task_creator
    else:
        employees = User.objects.none()
        current_responder = None
        current_task_creator = None
    
    context = {
        'supervised_departments': supervised_depts,
        'departments_that_can_receive': departments_that_can_receive,
        'selected_department': selected_department,
        'employees': employees,
        'current_responder': current_responder,
        'current_task_creator': current_task_creator,
        'ticket_responders': {d.id: d.ticket_responder for d in supervised_depts if d.can_receive_tickets},
    }
    
    return render(request, 'tickets/supervisor_ticket_responder_management.html', context)

@login_required
def branch_management(request):
    """Branch management view for Administrator"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    branches = Branch.objects.all().order_by('name')
    
    context = {
        'branches': branches,
        'total_branches': branches.count(),
    }
    
    return render(request, 'tickets/branch_management.html', context)

@login_required
def branch_create(request):
    """Create a new branch"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            try:
                branch = form.save()
                messages.success(request, _('شعبه "{}" با موفقیت ایجاد شد. اکنون می‌توانید بخش‌ها را به این شعبه اختصاص دهید.').format(branch.name))
                return redirect('tickets:branch_management')
            except ValidationError as e:
                # Handle validation errors from form.save()
                error_messages = []
                if hasattr(e, 'error_dict'):
                    for field, errors in e.error_dict.items():
                        field_label = form.fields[field].label if field in form.fields else field
                        for error_list in errors:
                            if isinstance(error_list, list):
                                for error in error_list:
                                    error_messages.append(f"{field_label}: {error}")
                            else:
                                error_messages.append(f"{field_label}: {error_list}")
                elif hasattr(e, 'message'):
                    error_messages.append(str(e.message))
                else:
                    error_messages.append(str(e))
                
                if error_messages:
                    messages.error(request, _('خطا در ایجاد شعبه: {}').format(' | '.join(error_messages)))
                else:
                    messages.error(request, _('خطا در ایجاد شعبه. لطفاً اطلاعات را بررسی کنید.'))
            except Exception as e:
                import traceback
                traceback.print_exc()
                messages.error(request, _('خطا در ایجاد شعبه: {}').format(str(e)))
        else:
            # Show form errors
            error_messages = []
            for field, errors in form.errors.items():
                field_label = form.fields[field].label if field in form.fields else field
                for error in errors:
                    error_messages.append(f"{field_label}: {error}")
            if error_messages:
                messages.error(request, _('خطا در ایجاد شعبه: {}').format(' | '.join(error_messages)))
            else:
                messages.error(request, _('خطا در ایجاد شعبه. لطفاً اطلاعات را بررسی کنید.'))
    else:
        form = BranchForm()
    
    context = {
        'form': form,
        'action': 'create',
        'title': _('ایجاد شعبه جدید')
    }
    
    return render(request, 'tickets/branch_form.html', context)

@login_required
def branch_edit(request, branch_id):
    """Edit an existing branch"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    branch = get_object_or_404(Branch, id=branch_id)
    
    if request.method == 'POST':
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            try:
                updated_branch = form.save()
                messages.success(request, _('شعبه "{}" با موفقیت بروزرسانی شد.').format(updated_branch.name))
                return redirect('tickets:branch_management')
            except ValidationError as e:
                # Handle validation errors from form.save()
                error_messages = []
                if hasattr(e, 'error_dict'):
                    for field, errors in e.error_dict.items():
                        field_label = form.fields[field].label if field in form.fields else field
                        for error_list in errors:
                            if isinstance(error_list, list):
                                for error in error_list:
                                    error_messages.append(f"{field_label}: {error}")
                            else:
                                error_messages.append(f"{field_label}: {error_list}")
                elif hasattr(e, 'message'):
                    error_messages.append(str(e.message))
                else:
                    error_messages.append(str(e))
                
                if error_messages:
                    messages.error(request, _('خطا در بروزرسانی شعبه: {}').format(' | '.join(error_messages)))
                else:
                    messages.error(request, _('خطا در بروزرسانی شعبه. لطفاً اطلاعات را بررسی کنید.'))
            except Exception as e:
                import traceback
                traceback.print_exc()
                messages.error(request, _('خطا در بروزرسانی شعبه: {}').format(str(e)))
        else:
            # Show form errors
            error_messages = []
            for field, errors in form.errors.items():
                field_label = form.fields[field].label if field in form.fields else field
                for error in errors:
                    error_messages.append(f"{field_label}: {error}")
            if error_messages:
                messages.error(request, _('خطا در بروزرسانی شعبه: {}').format(' | '.join(error_messages)))
            else:
                messages.error(request, _('خطا در بروزرسانی شعبه. لطفاً اطلاعات را بررسی کنید.'))
    else:
        form = BranchForm(instance=branch)
    
    context = {
        'form': form,
        'branch': branch,
        'action': 'edit',
        'title': _('ویرایش شعبه')
    }
    
    return render(request, 'tickets/branch_form.html', context)

@login_required
def branch_delete(request, branch_id):
    """Delete a branch"""
    if not is_admin_superuser(request.user):
        messages.error(request, _('دسترسی رد شد. فقط مدیر سیستم میتواند این بخش را دریافت کند.'))
        return redirect('tickets:dashboard')
    
    branch = get_object_or_404(Branch, id=branch_id)
    
    # Check if branch has departments
    department_count = branch.departments.count()
    
    if request.method == 'POST':
        if department_count > 0:
            messages.error(request, _('نمی‌توان شعبه‌ای که دارای بخش است را حذف کرد. ابتدا بخش‌ها را به شعبه دیگری منتقل کنید.'))
        else:
            branch_name = branch.name
            branch.delete()
            messages.success(request, _('شعبه "{}" با موفقیت حذف شد.').format(branch_name))
        return redirect('tickets:branch_management')
    
    context = {
        'branch': branch,
        'department_count': department_count
    }
    
    return render(request, 'tickets/branch_confirm_delete.html', context)

@login_required
def get_departments_for_branch(request, branch_id):
    """API endpoint to get departments for a specific branch that can receive tickets"""
    try:
        branch = get_object_or_404(Branch, id=branch_id, is_active=True)
        
        # Get departments associated with this branch that can receive tickets
        departments = Department.objects.filter(
            branch=branch,
            is_active=True,
            can_receive_tickets=True  # Only show departments that can receive tickets
        ).order_by('name')
        
        # Always include IT department if:
        # 1. IT department has no branch assigned (appears in all branches)
        # 2. IT department is assigned to this specific branch
        it_department = get_it_department()
        if it_department and it_department.can_receive_tickets and it_department.is_active:
            # If IT department has no branch, include it for all branches
            # If IT department has a branch, only include it if it matches the selected branch
            if not it_department.branch or it_department.branch == branch:
                # Check if IT department is not already in the list
                if not departments.filter(id=it_department.id).exists():
                    departments = list(departments) + [it_department]
        
        departments_data = [{
            'id': dept.id,
            'name': dept.name
        } for dept in departments]
        
        return JsonResponse({
            'success': True,
            'departments': departments_data
        })
    except Branch.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': _('شعبه یافت نشد')
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_POST
def delete_notification(request, notification_id):
    """Delete a single notification"""
    user = request.user
    if user.role != 'it_manager':
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    try:
        notification = get_object_or_404(Notification, id=notification_id, recipient=user)
        notification.delete()
        return JsonResponse({'success': True, 'message': _('اعلان با موفقیت حذف شد.')})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_POST
def delete_category_notifications(request, category):
    """Delete all notifications in a specific category"""
    user = request.user
    if user.role != 'it_manager':
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    try:
        # Get category display name for the message (Users tab removed - no 'users' in UI)
        category_names = {
            'tickets': _('تیکت‌ها'),
            'system': _('سیستم'),
            'access': _('دسترسی شبکه'),
            'team_leader_access': _('درخواست‌های دسترسی شبکه'),
        }
        category_name = category_names.get(category, category)
        
        # Delete all notifications in this category for the user
        deleted_count = Notification.objects.filter(recipient=user, category=category).delete()[0]
        
        if deleted_count > 0:
            return JsonResponse({
                'success': True, 
                'message': f'{deleted_count} اعلان از دسته "{category_name}" با موفقیت حذف شد.'
            })
        else:
            return JsonResponse({'success': True, 'message': f'اعلانی در دسته "{category_name}" وجود نداشت.'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_POST
def delete_all_notifications(request):
    """Delete all notifications for the user"""
    user = request.user
    if user.role != 'it_manager':
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    try:
        deleted_count = Notification.objects.filter(recipient=user).delete()[0]
        return JsonResponse({
            'success': True, 
            'message': f'{deleted_count} اعلان با موفقیت حذف شد.'
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_POST
def delete_team_leader_notification(request, notification_id):
    """Delete a single team leader notification"""
    user = request.user
    if user.role != 'employee' or user.department_role != 'senior':
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    try:
        notification = get_object_or_404(Notification, id=notification_id, recipient=user, category='team_leader_access')
        notification.delete()
        return JsonResponse({'success': True, 'message': _('اعلان با موفقیت حذف شد.')})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_POST
def delete_all_team_leader_notifications(request):
    """Delete all team leader notifications for the user"""
    user = request.user
    if user.role != 'employee' or user.department_role != 'senior':
        return JsonResponse({'error': 'دسترسی رد شد'}, status=403)
    
    try:
        deleted_count = Notification.objects.filter(recipient=user, category='team_leader_access').delete()[0]
        return JsonResponse({
            'success': True, 
            'message': f'{deleted_count} اعلان دسترسی شبکه با موفقیت حذف شد.'
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# ==================== Inventory Management Views ====================

@login_required
def inventory_management(request):
    """List all inventory elements for IT manager - only top-level elements (organized by user)"""
    if request.user.role != 'it_manager':
        messages.error(request, _('دسترسی رد شد. فقط مدیر IT میتواند این بخش را مشاهده کند.'))
        return redirect('tickets:dashboard')
    
    # Ensure warehouse element exists
    warehouse = get_warehouse_element()
    
    # Get filter parameters
    user_filter = request.GET.get('user', '')
    element_type_filter = request.GET.get('element_type', '')
    search_query = request.GET.get('search', '')
    show_inactive = request.GET.get('show_inactive', '') == 'on'
    
    # Base queryset - ONLY top-level elements (no parent)
    elements = InventoryElement.objects.filter(parent_element__isnull=True)
    
    # Apply filters
    if not show_inactive:
        elements = elements.filter(is_active=True)
    
    if user_filter:
        elements = elements.filter(assigned_to_id=user_filter)
    
    if element_type_filter:
        elements = elements.filter(element_type__icontains=element_type_filter)
    
    if search_query:
        elements = elements.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(element_type__icontains=search_query) |
            Q(assigned_to__first_name__icontains=search_query) |
            Q(assigned_to__last_name__icontains=search_query)
        )
    
    # Group elements by user for better organization
    # Order by user name, then by element name
    elements = elements.select_related('assigned_to').order_by('assigned_to__first_name', 'assigned_to__last_name', 'name')
    
    # Get all users for filter dropdown
    # Exclude admin superuser from inventory assignment
    admin_filter = get_admin_superuser_queryset_filter()
    users = User.objects.filter(role='employee', is_active=True).filter(admin_filter).order_by('first_name', 'last_name')
    
    # Get unique element types for filter
    element_types = InventoryElement.objects.values_list('element_type', flat=True).distinct().order_by('element_type')
    
    # Separate warehouse from other elements
    warehouse_elements = [warehouse] if warehouse in elements else []
    other_elements = [e for e in elements if e.id != warehouse.id] if warehouse else list(elements)
    
    # Group other elements by user for display
    elements_by_user = {}
    for element in other_elements:
        user_key = element.assigned_to.id
        if user_key not in elements_by_user:
            elements_by_user[user_key] = {
                'user': element.assigned_to,
                'elements': []
            }
        elements_by_user[user_key]['elements'].append(element)
    
    # Pagination - we'll paginate the user groups
    user_groups_list = list(elements_by_user.values())
    paginator = Paginator(user_groups_list, 10)  # 10 users per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'user_groups': page_obj,
        'warehouse': warehouse,
        'warehouse_elements': warehouse_elements,
        'users': users,
        'element_types': element_types,
        'user_filter': user_filter,
        'element_type_filter': element_type_filter,
        'search_query': search_query,
        'show_inactive': show_inactive,
    }
    
    return render(request, 'tickets/inventory_management.html', context)

@login_required
def inventory_element_create(request):
    """Create a new inventory element"""
    if request.user.role != 'it_manager':
        messages.error(request, _('دسترسی رد شد. فقط مدیر IT میتواند عناصر موجودی را ایجاد کند.'))
        return redirect('tickets:dashboard')
    
    try:
        warehouse = get_warehouse_element()
        if request.method == 'POST':
            form = InventoryElementForm(request.POST, user=request.user)
            if form.is_valid():
                # Handle warehouse assignment
                assigned_to_value = request.POST.get('assigned_to', '')
                if assigned_to_value == 'warehouse':
                    # If warehouse is selected, assign to warehouse's assigned user
                    element = form.save(commit=False)
                    element.assigned_to = warehouse.assigned_to
                    element.created_by = request.user
                    # Set parent to warehouse if not specified
                    if not element.parent_element:
                        element.parent_element = warehouse
                    element.save()
                else:
                    element = form.save(commit=False)
                    element.created_by = request.user
                    element.save()
                messages.success(request, _('عنصر موجودی با موفقیت ایجاد شد.'))
                return redirect('tickets:inventory_element_detail', element_id=element.id)
            else:
                # Log form errors for debugging
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Form errors: {form.errors}")
        else:
            form = InventoryElementForm(user=request.user)
        
        return render(request, 'tickets/inventory_element_form.html', {
            'form': form,
            'warehouse': warehouse,
            'is_warehouse': False,
            'action': _('ایجاد'),
            'title': _('ایجاد عنصر موجودی جدید')
        })
    except Exception as e:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"Error in inventory_element_create: {str(e)}\n{traceback.format_exc()}")
        messages.error(request, _('خطا در ایجاد عنصر موجودی. لطفاً دوباره تلاش کنید.'))
        return redirect('tickets:inventory_management')

@login_required
def inventory_element_detail(request, element_id):
    """View details of an inventory element"""
    if request.user.role != 'it_manager':
        messages.error(request, _('دسترسی رد شد. فقط مدیر IT میتواند این بخش را مشاهده کند.'))
        return redirect('tickets:dashboard')
    
    element = get_object_or_404(InventoryElement, id=element_id)
    specifications = element.specifications.all().order_by('key')
    sub_elements = element.sub_elements.filter(is_active=True).order_by('name')
    
    # Check if this is the warehouse element
    warehouse = get_warehouse_element()
    is_warehouse = (element.id == warehouse.id)
    
    context = {
        'element': element,
        'specifications': specifications,
        'sub_elements': sub_elements,
        'is_warehouse': is_warehouse,
    }
    
    return render(request, 'tickets/inventory_element_detail.html', context)

# ==================== Department Warehouse Inventory Management Views ====================

@login_required
def department_warehouse_inventory(request, department_id):
    """List inventory elements for a department warehouse - only accessible to department supervisor"""
    user = request.user
    
    # Check if user is a supervisor
    if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
        messages.error(request, _('شما اجازه دسترسی به این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get department and verify access
    department = get_object_or_404(Department, id=department_id, has_warehouse=True)
    
    # Verify user is supervisor of this department
    supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
    if department not in supervised_depts and user.department != department:
        messages.error(request, _('شما اجازه دسترسی به انبار این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get or create department warehouse
    warehouse = get_department_warehouse(department)
    if not warehouse:
        messages.error(request, _('انبار این بخش یافت نشد. لطفاً با مدیر سیستم تماس بگیرید.'))
        return redirect('tickets:warehouse_management')
    
    # Get filter parameters
    element_type_filter = request.GET.get('element_type', '')
    search_query = request.GET.get('search', '')
    show_inactive = request.GET.get('show_inactive', '') == 'on'
    
    # Base queryset - elements in this department's warehouse (warehouse itself or sub-elements)
    elements = InventoryElement.objects.filter(
        Q(id=warehouse.id) | Q(parent_element=warehouse)
    )
    
    # Apply filters
    if not show_inactive:
        elements = elements.filter(is_active=True)
    
    if element_type_filter:
        elements = elements.filter(element_type__icontains=element_type_filter)
    
    if search_query:
        elements = elements.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(element_type__icontains=search_query)
        )
    
    # Order by name
    elements = elements.select_related('assigned_to', 'parent_element').order_by('name')
    
    # Get unique element types for filter
    element_types = InventoryElement.objects.filter(
        Q(id=warehouse.id) | Q(parent_element=warehouse)
    ).values_list('element_type', flat=True).distinct().order_by('element_type')
    
    # Separate warehouse from other elements
    warehouse_elements = [warehouse]
    other_elements = [e for e in elements if e.id != warehouse.id]
    
    # Pagination
    paginator = Paginator(other_elements, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'elements': page_obj,
        'warehouse': warehouse,
        'warehouse_elements': warehouse_elements,
        'department': department,
        'element_types': element_types,
        'element_type_filter': element_type_filter,
        'search_query': search_query,
        'show_inactive': show_inactive,
    }
    
    return render(request, 'tickets/department_warehouse_inventory.html', context)

@login_required
def department_warehouse_element_create(request, department_id):
    """Create a new inventory element in department warehouse"""
    user = request.user
    
    # Check if user is a supervisor
    if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
        messages.error(request, _('شما اجازه دسترسی به این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get department and verify access
    department = get_object_or_404(Department, id=department_id, has_warehouse=True)
    
    # Verify user is supervisor of this department
    supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
    if department not in supervised_depts and user.department != department:
        messages.error(request, _('شما اجازه دسترسی به انبار این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get department warehouse
    warehouse = get_department_warehouse(department)
    if not warehouse:
        messages.error(request, _('انبار این بخش یافت نشد.'))
        return redirect('tickets:warehouse_management')
    
    if request.method == 'POST':
        form = InventoryElementForm(request.POST, user=user)
        if form.is_valid():
            element = form.save(commit=False)
            element.created_by = user
            # Set parent to department warehouse
            element.parent_element = warehouse
            # Assign to warehouse's assigned user (department supervisor) by default
            if not element.assigned_to:
                element.assigned_to = warehouse.assigned_to
            element.save()
            messages.success(request, _('عنصر موجودی با موفقیت ایجاد شد.'))
            return redirect('tickets:department_warehouse_element_detail', department_id=department_id, element_id=element.id)
    else:
        form = InventoryElementForm(user=user)
        # Pre-set parent to warehouse
        form.fields['parent_element'].initial = warehouse
        # Limit parent_element choices to elements in this warehouse
        form.fields['parent_element'].queryset = InventoryElement.objects.filter(
            Q(id=warehouse.id) | Q(parent_element=warehouse)
        ).order_by('name')
    
    return render(request, 'tickets/inventory_element_form.html', {
        'form': form,
        'warehouse': warehouse,
        'department': department,
        'is_warehouse': False,
        'action': _('ایجاد'),
        'title': _('ایجاد عنصر موجودی جدید'),
        'back_url': reverse('tickets:department_warehouse_inventory', args=[department_id]),
    })

@login_required
def department_warehouse_element_detail(request, department_id, element_id):
    """View details of an inventory element in department warehouse"""
    user = request.user
    
    # Check if user is a supervisor
    if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
        messages.error(request, _('شما اجازه دسترسی به این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get department and verify access
    department = get_object_or_404(Department, id=department_id, has_warehouse=True)
    
    # Verify user is supervisor of this department
    supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
    if department not in supervised_depts and user.department != department:
        messages.error(request, _('شما اجازه دسترسی به انبار این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get department warehouse
    warehouse = get_department_warehouse(department)
    if not warehouse:
        messages.error(request, _('انبار این بخش یافت نشد.'))
        return redirect('tickets:warehouse_management')
    
    # Get element and verify it belongs to this warehouse
    element = get_object_or_404(InventoryElement, id=element_id)
    
    # Verify element is in this warehouse (warehouse itself or sub-element)
    if element.id != warehouse.id and element.parent_element != warehouse:
        # Check if it's a sub-element of warehouse (recursive check)
        is_sub_element = False
        parent = element.parent_element
        while parent:
            if parent.id == warehouse.id:
                is_sub_element = True
                break
            parent = parent.parent_element
        
        if not is_sub_element:
            messages.error(request, _('این عنصر به انبار این بخش تعلق ندارد.'))
            return redirect('tickets:department_warehouse_inventory', department_id=department_id)
    
    specifications = element.specifications.all().order_by('key')
    sub_elements = element.sub_elements.filter(is_active=True).order_by('name')
    is_warehouse = (element.id == warehouse.id)
    
    context = {
        'element': element,
        'specifications': specifications,
        'sub_elements': sub_elements,
        'is_warehouse': is_warehouse,
        'department': department,
        'warehouse': warehouse,
        'back_url': reverse('tickets:department_warehouse_inventory', args=[department_id]),
    }
    
    return render(request, 'tickets/inventory_element_detail.html', context)

@login_required
def department_warehouse_element_edit(request, department_id, element_id):
    """Edit an existing inventory element in department warehouse"""
    user = request.user
    
    # Check if user is a supervisor
    if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
        messages.error(request, _('شما اجازه دسترسی به این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get department and verify access
    department = get_object_or_404(Department, id=department_id, has_warehouse=True)
    
    # Verify user is supervisor of this department
    supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
    if department not in supervised_depts and user.department != department:
        messages.error(request, _('شما اجازه دسترسی به انبار این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get department warehouse
    warehouse = get_department_warehouse(department)
    if not warehouse:
        messages.error(request, _('انبار این بخش یافت نشد.'))
        return redirect('tickets:warehouse_management')
    
    # Get element and verify it belongs to this warehouse
    element = get_object_or_404(InventoryElement, id=element_id)
    
    # Verify element is in this warehouse
    if element.id != warehouse.id and element.parent_element != warehouse:
        messages.error(request, _('این عنصر به انبار این بخش تعلق ندارد.'))
        return redirect('tickets:department_warehouse_inventory', department_id=department_id)
    
    is_warehouse = (element.id == warehouse.id)
    
    if request.method == 'POST':
        form = InventoryElementForm(request.POST, instance=element, user=user, element_id=element_id)
        if form.is_valid():
            # If editing warehouse, ensure it remains assigned to supervisor and has no parent
            if is_warehouse:
                saved_element = form.save(commit=False)
                saved_element.assigned_to = warehouse.assigned_to
                saved_element.parent_element = None
                saved_element.is_active = True
                saved_element.save()
            else:
                saved_element = form.save(commit=False)
                # Ensure parent is warehouse or a sub-element of warehouse
                if saved_element.parent_element:
                    # Check if parent is a sub-element of warehouse
                    parent = saved_element.parent_element
                    is_valid_parent = False
                    while parent:
                        if parent.id == warehouse.id:
                            is_valid_parent = True
                            break
                        parent = parent.parent_element
                    if not is_valid_parent:
                        saved_element.parent_element = warehouse
                else:
                    saved_element.parent_element = warehouse
                saved_element.save()
            messages.success(request, _('عنصر موجودی با موفقیت بروزرسانی شد.'))
            return redirect('tickets:department_warehouse_element_detail', department_id=department_id, element_id=saved_element.id)
    else:
        form = InventoryElementForm(instance=element, user=user, element_id=element_id)
        # Limit parent_element choices to elements in this warehouse
        if not is_warehouse:
            form.fields['parent_element'].queryset = InventoryElement.objects.filter(
                Q(id=warehouse.id) | Q(parent_element=warehouse)
            ).order_by('name')
    
    return render(request, 'tickets/inventory_element_form.html', {
        'form': form,
        'warehouse': warehouse,
        'department': department,
        'is_warehouse': is_warehouse,
        'action': _('ویرایش'),
        'title': _('ویرایش عنصر موجودی'),
        'back_url': reverse('tickets:department_warehouse_element_detail', args=[department_id, element_id]),
    })

@login_required
def department_warehouse_element_delete(request, department_id, element_id):
    """Delete an inventory element from department warehouse"""
    user = request.user
    
    # Check if user is a supervisor
    if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
        messages.error(request, _('شما اجازه دسترسی به این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get department and verify access
    department = get_object_or_404(Department, id=department_id, has_warehouse=True)
    
    # Verify user is supervisor of this department
    supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
    if department not in supervised_depts and user.department != department:
        messages.error(request, _('شما اجازه دسترسی به انبار این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get department warehouse
    warehouse = get_department_warehouse(department)
    if not warehouse:
        messages.error(request, _('انبار این بخش یافت نشد.'))
        return redirect('tickets:warehouse_management')
    
    # Get element and verify it belongs to this warehouse
    element = get_object_or_404(InventoryElement, id=element_id)
    
    # Cannot delete warehouse itself
    if element.id == warehouse.id:
        messages.error(request, _('نمی‌توان انبار را حذف کرد.'))
        return redirect('tickets:department_warehouse_inventory', department_id=department_id)
    
    # Verify element is in this warehouse
    if element.parent_element != warehouse:
        messages.error(request, _('این عنصر به انبار این بخش تعلق ندارد.'))
        return redirect('tickets:department_warehouse_inventory', department_id=department_id)
    
    if request.method == 'POST':
        element_name = element.name
        element.delete()
        messages.success(request, _('عنصر "{}" با موفقیت حذف شد.').format(element_name))
        return redirect('tickets:department_warehouse_inventory', department_id=department_id)
    
    context = {
        'element': element,
        'department': department,
        'back_url': reverse('tickets:department_warehouse_inventory', args=[department_id]),
    }
    
    return render(request, 'tickets/inventory_element_confirm_delete.html', context)

@login_required
def inventory_element_edit(request, element_id):
    """Edit an existing inventory element"""
    if request.user.role != 'it_manager':
        messages.error(request, _('دسترسی رد شد. فقط مدیر IT میتواند عناصر موجودی را ویرایش کند.'))
        return redirect('tickets:dashboard')
    
    element = get_object_or_404(InventoryElement, id=element_id)
    
    # Check if this is the warehouse element
    warehouse = get_warehouse_element()
    is_warehouse = (element.id == warehouse.id)
    
    if request.method == 'POST':
        form = InventoryElementForm(request.POST, instance=element, user=request.user, element_id=element_id)
        if form.is_valid():
            # If editing warehouse, ensure it remains assigned to IT manager and has no parent
            if is_warehouse:
                saved_element = form.save(commit=False)
                saved_element.assigned_to = warehouse.assigned_to  # Keep original assignment
                saved_element.parent_element = None  # Warehouse has no parent
                saved_element.is_active = True  # Warehouse is always active
                saved_element.save()
            else:
                form.save()
            messages.success(request, _('عنصر موجودی با موفقیت بروزرسانی شد.'))
            return redirect('tickets:inventory_element_detail', element_id=element.id)
    else:
        form = InventoryElementForm(instance=element, user=request.user, element_id=element_id)
        # Preserve the current parent_element value even if it's not in the filtered queryset
        # This allows the form to show the current parent when editing
    
    return render(request, 'tickets/inventory_element_form.html', {
        'form': form,
        'element': element,
        'is_warehouse': is_warehouse,
        'action': _('ویرایش'),
        'title': _('ویرایش عنصر موجودی')
    })

@login_required
def inventory_element_delete(request, element_id):
    """Delete an inventory element"""
    if request.user.role != 'it_manager':
        messages.error(request, _('دسترسی رد شد. فقط مدیر IT میتواند عناصر موجودی را حذف کند.'))
        return redirect('tickets:dashboard')
    
    element = get_object_or_404(InventoryElement, id=element_id)
    
    # Check if this is the warehouse element - prevent deletion
    warehouse = get_warehouse_element()
    is_warehouse = (element.id == warehouse.id)
    
    if is_warehouse:
        messages.error(request, _('نمی‌توانید انبار را حذف کنید. انبار یک بخش پیش‌فرض سیستم است.'))
        return redirect('tickets:inventory_element_detail', element_id=element.id)
    
    if request.method == 'POST':
        element_name = element.name
        element.delete()
        messages.success(request, _('عنصر موجودی "{}" با موفقیت حذف شد.').format(element_name))
        return redirect('tickets:inventory_management')
    
    # Check for sub-elements
    sub_elements_count = element.sub_elements.count()
    
    context = {
        'element': element,
        'sub_elements_count': sub_elements_count,
    }
    
    return render(request, 'tickets/inventory_element_confirm_delete.html', context)

@login_required
def inventory_specification_create(request, element_id):
    """Create a new specification for an element"""
    user = request.user
    element = get_object_or_404(InventoryElement, id=element_id)
    
    # Check if this is a department warehouse element
    is_department_warehouse, department = is_department_warehouse_element(element)
    
    # Access control
    if is_department_warehouse and department:
        # Check if user is supervisor of this department
        if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
            messages.error(request, _('دسترسی رد شد. فقط سرپرست بخش می‌تواند مشخصات عناصر را ایجاد کند.'))
            return redirect('tickets:dashboard')
        
        supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
        if department not in supervised_depts and user.department != department:
            messages.error(request, _('شما اجازه دسترسی به انبار این بخش را ندارید.'))
            return redirect('tickets:dashboard')
    else:
        # IT manager warehouse - only IT managers can access
        if user.role != 'it_manager':
            messages.error(request, _('دسترسی رد شد. فقط مدیر IT میتواند مشخصات عناصر را ایجاد کند.'))
            return redirect('tickets:dashboard')
    
    if request.method == 'POST':
        form = ElementSpecificationForm(request.POST, element=element)
        if form.is_valid():
            specification = form.save(commit=False)
            specification.element = element
            specification.save()
            messages.success(request, _('مشخصه با موفقیت اضافه شد.'))
            if is_department_warehouse and department:
                return redirect('tickets:department_warehouse_element_detail', department_id=department.id, element_id=element.id)
            else:
                return redirect('tickets:inventory_element_detail', element_id=element.id)
    else:
        form = ElementSpecificationForm(element=element)
    
    context = {
        'form': form,
        'element': element,
        'action': _('ایجاد'),
        'title': _('افزودن مشخصه جدید'),
    }
    
    if is_department_warehouse and department:
        context['department'] = department
        context['back_url'] = reverse('tickets:department_warehouse_element_detail', args=[department.id, element.id])
    else:
        context['back_url'] = reverse('tickets:inventory_element_detail', args=[element.id])
    
    return render(request, 'tickets/inventory_specification_form.html', context)

@login_required
def inventory_specification_edit(request, element_id, specification_id):
    """Edit an existing specification"""
    user = request.user
    element = get_object_or_404(InventoryElement, id=element_id)
    specification = get_object_or_404(ElementSpecification, id=specification_id, element=element)
    
    # Check if this is a department warehouse element
    is_department_warehouse, department = is_department_warehouse_element(element)
    
    # Access control
    if is_department_warehouse and department:
        # Check if user is supervisor of this department
        if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
            messages.error(request, _('دسترسی رد شد. فقط سرپرست بخش می‌تواند مشخصات عناصر را ویرایش کند.'))
            return redirect('tickets:dashboard')
        
        supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
        if department not in supervised_depts and user.department != department:
            messages.error(request, _('شما اجازه دسترسی به انبار این بخش را ندارید.'))
            return redirect('tickets:dashboard')
    else:
        # IT manager warehouse - only IT managers can access
        if user.role != 'it_manager':
            messages.error(request, _('دسترسی رد شد. فقط مدیر IT میتواند مشخصات عناصر را ویرایش کند.'))
            return redirect('tickets:dashboard')
    
    if request.method == 'POST':
        form = ElementSpecificationForm(request.POST, instance=specification, element=element)
        if form.is_valid():
            form.save()
            messages.success(request, _('مشخصه با موفقیت بروزرسانی شد.'))
            if is_department_warehouse and department:
                return redirect('tickets:department_warehouse_element_detail', department_id=department.id, element_id=element.id)
            else:
                return redirect('tickets:inventory_element_detail', element_id=element.id)
    else:
        form = ElementSpecificationForm(instance=specification, element=element)
    
    context = {
        'form': form,
        'element': element,
        'specification': specification,
        'action': _('ویرایش'),
        'title': _('ویرایش مشخصه'),
    }
    
    if is_department_warehouse and department:
        context['department'] = department
        context['back_url'] = reverse('tickets:department_warehouse_element_detail', args=[department.id, element.id])
    else:
        context['back_url'] = reverse('tickets:inventory_element_detail', args=[element.id])
    
    return render(request, 'tickets/inventory_specification_form.html', context)

@login_required
@require_POST
def inventory_specification_delete(request, element_id, specification_id):
    """Delete a specification"""
    user = request.user
    element = get_object_or_404(InventoryElement, id=element_id)
    specification = get_object_or_404(ElementSpecification, id=specification_id, element=element)
    
    # Check if this is a department warehouse element
    is_department_warehouse, department = is_department_warehouse_element(element)
    
    # Access control
    if is_department_warehouse and department:
        # Check if user is supervisor of this department
        if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
            messages.error(request, _('دسترسی رد شد. فقط سرپرست بخش می‌تواند مشخصات عناصر را حذف کند.'))
            return redirect('tickets:dashboard')
        
        supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
        if department not in supervised_depts and user.department != department:
            messages.error(request, _('شما اجازه دسترسی به انبار این بخش را ندارید.'))
            return redirect('tickets:dashboard')
    else:
        # IT manager warehouse - only IT managers can access
        if user.role != 'it_manager':
            messages.error(request, _('دسترسی رد شد. فقط مدیر IT میتواند مشخصات عناصر را حذف کند.'))
            return redirect('tickets:dashboard')
    
    spec_key = specification.key
    specification.delete()
    messages.success(request, _('مشخصه "{}" با موفقیت حذف شد.').format(spec_key))
    
    if is_department_warehouse and department:
        return redirect('tickets:department_warehouse_element_detail', department_id=department.id, element_id=element.id)
    else:
        return redirect('tickets:inventory_element_detail', element_id=element.id)

@login_required
def get_parent_elements_for_user(request, user_id):
    """API endpoint to get parent elements for a specific user (excluding self if editing)"""
    if request.user.role != 'it_manager':
        return JsonResponse({'error': _('دسترسی رد شد')}, status=403)
    
    try:
        user = get_object_or_404(User, id=user_id, role__in=['employee', 'technician'], is_active=True)
        
        # Do NOT include warehouse in the list for regular users
        # Warehouse should only appear when warehouse itself is selected
        
        # Get all active elements for this user (allow nested hierarchies)
        elements = InventoryElement.objects.filter(
            assigned_to=user,
            is_active=True
        ).order_by('name')
        
        # Get element_id from request if editing
        element_id = request.GET.get('element_id')
        if element_id:
            try:
                current_element = InventoryElement.objects.get(id=element_id)
                # Exclude self and all its sub-elements
                excluded_ids = [current_element.id] + [sub.id for sub in current_element.get_all_sub_elements()]
                elements = elements.exclude(id__in=excluded_ids)
            except InventoryElement.DoesNotExist:
                pass
        
        elements_data = []
        
        # Add user's elements (NO warehouse for regular users)
        for element in elements:
            # Build hierarchical path for display
            path = element.get_full_path()
            elements_data.append({
                'id': element.id,
                'name': element.name,
                'path': path,
                'element_type': element.element_type,
            })
        
        return JsonResponse({
            'success': True,
            'elements': elements_data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def get_warehouse_sub_elements(request, warehouse_id):
    """API endpoint to get warehouse sub-elements"""
    if request.user.role != 'it_manager':
        return JsonResponse({'error': _('دسترسی رد شد')}, status=403)
    
    try:
        warehouse = get_object_or_404(InventoryElement, id=warehouse_id, name='انبار', parent_element__isnull=True)
        
        # Get all active sub-elements of warehouse (including nested sub-elements)
        # First get direct children
        direct_children = InventoryElement.objects.filter(
            parent_element=warehouse,
            is_active=True
        )
        
        # Then recursively get all nested descendants
        all_descendants = list(direct_children)
        for child in direct_children:
            all_descendants.extend(child.get_all_sub_elements())
        
        # Convert to queryset for filtering
        descendant_ids = [elem.id for elem in all_descendants]
        elements = InventoryElement.objects.filter(
            id__in=descendant_ids,
            is_active=True
        ).order_by('name')
        
        # Get element_id from request if editing
        element_id = request.GET.get('element_id')
        if element_id:
            try:
                current_element = InventoryElement.objects.get(id=element_id)
                # Exclude self and all its sub-elements
                excluded_ids = [current_element.id] + [sub.id for sub in current_element.get_all_sub_elements()]
                elements = elements.exclude(id__in=excluded_ids)
            except InventoryElement.DoesNotExist:
                pass
        
        elements_data = []
        for element in elements:
            # Build hierarchical path for display
            path = element.get_full_path()
            elements_data.append({
                'id': element.id,
                'name': element.name,
                'path': path,
                'element_type': element.element_type,
            })
        
        return JsonResponse({
            'success': True,
            'elements': elements_data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# Ticket Task Views

@login_required
def ticket_task_list(request):
    """List all ticket tasks created by the current user (IT Manager, Supervisor, or delegated task creator)"""
    user = request.user
    
    # Allow IT managers OR supervisors (senior/manager department_role) OR department task creators to access this view
    is_it_manager = user.role == 'it_manager'
    is_supervisor = (user.role == 'employee' and user.department_role in ['senior', 'manager'])
    is_task_creator = False

    try:
        if user.role == 'employee' and user.department and user.department.task_creator_id == user.id:
            is_task_creator = True
    except Exception:
        is_task_creator = False
    
    if not (is_it_manager or is_supervisor or is_task_creator):
        messages.error(request, _('شما اجازه دسترسی به این صفحه را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get filter parameters
    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    
    # Build task queryset based on user role
    # Temporarily defer 'deadline' field until migration is applied
    if is_supervisor:
        # For supervisors: show tasks created by them OR tasks created by task creators in their supervised departments
        supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
        supervised_dept_ids = [dept.id for dept in supervised_depts] if supervised_depts else []
        
        # Get task creators in supervised departments
        task_creators_in_supervised_depts = User.objects.filter(
            department__in=supervised_dept_ids,
            department__task_creator__isnull=False,
            is_active=True
        ).values_list('id', flat=True)
        
        # Tasks created by supervisor OR tasks created by task creators in supervised departments
        if task_creators_in_supervised_depts:
            tasks = TicketTask.objects.filter(
                Q(created_by=user) | Q(created_by__in=task_creators_in_supervised_depts)
            ).defer('deadline').prefetch_related('extension_requests')
        else:
            # No task creators in supervised departments, only show supervisor's own tasks
            tasks = TicketTask.objects.filter(created_by=user).defer('deadline').prefetch_related('extension_requests')
    elif is_task_creator:
        # For task creators: show only tasks they created
        tasks = TicketTask.objects.filter(created_by=user).defer('deadline').prefetch_related('extension_requests')
    else:
        # For IT managers: show all tasks (or tasks they created - keeping current behavior)
        tasks = TicketTask.objects.filter(created_by=user).defer('deadline').prefetch_related('extension_requests')
    
    # Apply filters
    if status_filter:
        tasks = tasks.filter(status=status_filter)
    if priority_filter:
        tasks = tasks.filter(priority=priority_filter)
    
    # Order by creation date (newest first)
    tasks = tasks.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(tasks, 20)
    page_number = request.GET.get('page')
    tasks_page = paginator.get_page(page_number)
    
    # Get choices for filters
    task_status_choices = TicketTask.STATUS_CHOICES
    task_priority_choices = TicketTask.PRIORITY_CHOICES
    
    context = {
        'tasks': tasks_page,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'task_status_choices': task_status_choices,
        'task_priority_choices': task_priority_choices,
    }
    
    return render(request, 'tickets/ticket_task_list.html', context)


@login_required
def ticket_task_create(request):
    """Create a new ticket task (IT Manager or Supervisor)"""
    # #region agent log - Hypothesis B, E: Entry point
    import json
    import os
    from datetime import datetime
    log_path = r'c:\Users\User\Desktop\pticket-main\.cursor\debug.log'
    def log_debug(hypothesis_id, location, message, data):
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            entry = {
                'id': f'log_{int(datetime.now().timestamp() * 1000)}',
                'timestamp': int(datetime.now().timestamp() * 1000),
                'location': location,
                'message': message,
                'data': data,
                'sessionId': 'debug-session',
                'runId': 'run1',
                'hypothesisId': hypothesis_id
            }
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception: pass
    # #endregion
    
    user = request.user
    log_debug('B', 'tickets/views.py:4636', 'ticket_task_create entry', {
        'user_id': user.id,
        'user_role': user.role,
        'department_role': getattr(user, 'department_role', None),
        'user_pk': user.pk
    })
    
    # Allow IT managers OR supervisors (senior/manager department_role) OR department task creators to create tasks
    is_it_manager = user.role == 'it_manager'
    is_supervisor = (user.role == 'employee' and user.department_role in ['senior', 'manager'])
    is_task_creator = False

    try:
        if user.role == 'employee' and user.department and user.department.task_creator_id == user.id:
            is_task_creator = True
    except Exception:
        is_task_creator = False
    log_debug('B', 'tickets/views.py:4648', 'Supervisor check result', {
        'is_supervisor': is_supervisor,
        'is_it_manager': is_it_manager,
        'user_role': user.role,
        'department_role': getattr(user, 'department_role', None)
    })
    
    if not (is_it_manager or is_supervisor or is_task_creator):
        messages.error(request, _('شما اجازه ایجاد تسک را ندارید.'))
        return redirect('tickets:dashboard')
    
    # CRITICAL: Refresh user from database to ensure we have latest relationships
    # This ensures get_supervised_departments() returns up-to-date data
    log_debug('E', 'tickets/views.py:4655', 'Before refresh_from_db', {
        'user_role': user.role,
        'department_role': getattr(user, 'department_role', None)
    })
    user.refresh_from_db()
    log_debug('E', 'tickets/views.py:4658', 'After refresh_from_db', {
        'user_role': user.role,
        'department_role': getattr(user, 'department_role', None),
        'has_get_supervised_departments': hasattr(user, 'get_supervised_departments')
    })
    
    # #region agent log - Hypothesis A: Get supervised departments
    if is_supervisor and hasattr(user, 'get_supervised_departments'):
        supervised_depts_test = user.get_supervised_departments()
        log_debug('A', 'tickets/views.py:4665', 'Supervised departments from view', {
            'supervised_depts_count': len(supervised_depts_test),
            'supervised_dept_ids': [d.id for d in supervised_depts_test],
            'supervised_dept_names': [d.name for d in supervised_depts_test]
        })
    # #endregion
    
    if request.method == 'POST':
        # DEBUG: Log incoming POST data
        log_debug('E', 'tickets/views.py:ticket_task_create', 'POST data received', {
            'post_data': dict(request.POST),
            'deadline_date': request.POST.get('deadline_date', 'NOT PROVIDED'),
            'deadline_date_type': type(request.POST.get('deadline_date', None)).__name__
        })
        
        form = TicketTaskForm(request.POST, user=user)
        # Store user in form for validation
        form._user = user
        
        log_debug('E', 'tickets/views.py:ticket_task_create', 'Form created', {
            'form_data': form.data if hasattr(form, 'data') else 'N/A',
            'deadline_date_in_data': form.data.get('deadline_date', 'NOT FOUND') if hasattr(form, 'data') else 'N/A'
        })
        
        if form.is_valid():
            log_debug('E', 'tickets/views.py:ticket_task_create', 'Form is valid', {
                'cleaned_data': form.cleaned_data,
                'deadline_date_in_cleaned': form.cleaned_data.get('deadline_date', 'NOT FOUND')
            })
            
            task = form.save(commit=False)
            task.created_by = user
            
            log_debug('E', 'tickets/views.py:ticket_task_create', 'Task before final save', {
                'task_deadline': task.deadline,
                'task_deadline_type': type(task.deadline).__name__ if task.deadline else 'None'
            })
            
            task.save()
            
            log_debug('E', 'tickets/views.py:ticket_task_create', 'Task after save', {
                'task_id': task.id,
                'task_deadline': task.deadline,
                'task_deadline_type': type(task.deadline).__name__ if task.deadline else 'None'
            })
            
            messages.success(request, _('تسک با موفقیت ایجاد شد.'))
            return redirect('tickets:ticket_task_detail', task_id=task.id)
        else:
            log_debug('E', 'tickets/views.py:ticket_task_create', 'Form is INVALID', {
                'form_errors': form.errors,
                'deadline_date_errors': form.errors.get('deadline_date', [])
            })
    else:
        form = TicketTaskForm(user=user)
        # Store user in form for validation
        form._user = user
    
    return render(request, 'tickets/ticket_task_form.html', {
        'form': form,
        'title': _('ایجاد تسک جدید')
    })


@login_required
def ticket_task_detail(request, task_id):
    """View details of a ticket task"""
    user = request.user
    
    # CRITICAL: Refresh user from database to ensure we have latest data
    user.refresh_from_db()
    
    # Load task with all fields (including deadline if migration is applied)
    # If migration not applied, this will fail, but that's expected
    try:
        task = get_object_or_404(TicketTask.objects.prefetch_related('extension_requests'), id=task_id)
    except Exception:
        # Fallback: try without deadline field if migration not applied
        task = get_object_or_404(TicketTask.objects.defer('deadline').prefetch_related('extension_requests'), id=task_id)
    
    # CRITICAL: Refresh task from database to ensure we have latest relationships
    task.refresh_from_db()
    
    # Check permissions: ANY creator can view their own tasks, assigned user, or supervisor of task creator's department
    # Use both ID and object comparison for maximum reliability
    is_creator = False
    if hasattr(task, 'created_by_id') and task.created_by_id:
        is_creator = (task.created_by_id == user.id)
    elif task.created_by:
        is_creator = (task.created_by.id == user.id)
    
    is_assigned = False
    if hasattr(task, 'assigned_to_id') and task.assigned_to_id:
        is_assigned = (task.assigned_to_id == user.id)
    elif task.assigned_to:
        is_assigned = (task.assigned_to.id == user.id)
    
    # IMPORTANT: Any user who created the task should be able to view it, regardless of their current permissions
    # This handles cases where a user had task creation permissions when they created the task,
    # but those permissions were later revoked
    
    is_it_manager_creator = (is_creator and user.role == 'it_manager')
    is_supervisor_creator = (is_creator and user.role == 'employee' and user.department_role in ['senior', 'manager'])
    
    # Check if user is currently a task creator (regular employee with task creation permissions)
    # Note: This is for determining edit/delete permissions, not view permissions
    is_task_creator = False
    try:
        if is_creator and user.role == 'employee' and user.department and user.department.task_creator_id == user.id:
            is_task_creator = True
    except Exception:
        pass
    
    # Check if user is a supervisor viewing a task created by ANY employee in their supervised departments
    # CRITICAL: Supervisor access is based on department supervision, NOT on creator's current permissions
    # A supervisor should be able to view ALL tasks created by employees in their supervised departments,
    # regardless of whether the creator currently has task creation permissions or not
    is_supervisor_viewing_task_creator_task = False
    try:
        if not is_creator and not is_assigned and user.role == 'employee' and user.department_role in ['senior', 'manager']:
            # User is a supervisor, check if task was created by ANY employee in their supervised departments
            task_creator_user = task.created_by
            if task_creator_user and task_creator_user.role == 'employee':
                # Get supervisor's supervised departments
                supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
                supervised_dept_ids = [dept.id for dept in supervised_depts] if supervised_depts else []
                
                # CRITICAL FIX: Supervisor can view tasks from ANY employee in their supervised departments
                # Check both: creator's department AND task's department (in case department changed)
                # No need to check if creator currently has task creation permissions - that's irrelevant
                task_creator_dept_in_supervised = False
                task_dept_in_supervised = False
                
                if task_creator_user.department and task_creator_user.department.id in supervised_dept_ids:
                    task_creator_dept_in_supervised = True
                
                if task.department and task.department.id in supervised_dept_ids:
                    task_dept_in_supervised = True
                
                # Supervisor can view if creator's department OR task's department is supervised
                if task_creator_dept_in_supervised or task_dept_in_supervised:
                    is_supervisor_viewing_task_creator_task = True
    except Exception:
        pass
    
    # CRITICAL: Allow ANY creator to view their tasks, regardless of current permissions
    # Also allow assigned users and supervisors viewing task creator tasks
    if not (is_creator or is_assigned or is_supervisor_viewing_task_creator_task):
        messages.error(request, _('شما اجازه مشاهده این تسک را ندارید.'))
        return redirect('tickets:dashboard')
    
    # Get all replies for this task
    replies = task.replies.all().order_by('created_at')
    
    # Check if user is a supervisor (for managing tasks created by task creators)
    is_supervisor = (user.role == 'employee' and user.department_role in ['senior', 'manager'])
    
    # Check if user can update status (creator who is IT manager, supervisor, or task creator, OR supervisor viewing task creator's task)
    can_update_status = is_it_manager_creator or is_supervisor_creator or is_task_creator or (is_supervisor_viewing_task_creator_task and is_supervisor)
    
    # Check if user can edit/delete (creator who is IT manager, supervisor, or task creator, OR supervisor viewing task creator's task)
    can_edit_delete = is_it_manager_creator or is_supervisor_creator or is_task_creator or (is_supervisor_viewing_task_creator_task and is_supervisor)
    
    context = {
        'task': task,
        'replies': replies,
        'can_update_status': can_update_status,
        'can_edit_delete': can_edit_delete,
        'task_status_choices': TicketTask.STATUS_CHOICES,
        'task_priority_choices': TicketTask.PRIORITY_CHOICES,
    }
    
    return render(request, 'tickets/ticket_task_detail.html', context)


@login_required
@require_POST
def ticket_task_update_status(request, task_id):
    """Update status and priority of a ticket task (AJAX endpoint)"""
    user = request.user
    # Temporarily defer 'deadline' field until migration is applied
    task = get_object_or_404(TicketTask.objects.defer('deadline'), id=task_id)
    
    # Only creator (IT manager, supervisor, or task creator) can update task status
    is_it_manager_creator = (task.created_by == user and user.role == 'it_manager')
    is_supervisor_creator = (task.created_by == user and user.role == 'employee' and user.department_role in ['senior', 'manager'])
    
    # Check if user is a task creator
    is_task_creator = False
    try:
        if task.created_by == user and user.role == 'employee' and user.department and user.department.task_creator_id == user.id:
            is_task_creator = True
    except Exception:
        pass
    
    # Check if user is a supervisor viewing a task created by ANY employee in their supervised departments
    # CRITICAL: Supervisor access is based on department supervision, NOT on creator's current permissions
    is_supervisor_viewing_task_creator_task = False
    try:
        if user.role == 'employee' and user.department_role in ['senior', 'manager']:
            task_creator_user = task.created_by
            if task_creator_user and task_creator_user.role == 'employee':
                supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
                supervised_dept_ids = [dept.id for dept in supervised_depts] if supervised_depts else []
                
                # Check both: creator's department AND task's department
                task_creator_dept_in_supervised = False
                task_dept_in_supervised = False
                
                if task_creator_user.department and task_creator_user.department.id in supervised_dept_ids:
                    task_creator_dept_in_supervised = True
                
                if task.department and task.department.id in supervised_dept_ids:
                    task_dept_in_supervised = True
                
                # Supervisor can manage if creator's department OR task's department is supervised
                if task_creator_dept_in_supervised or task_dept_in_supervised:
                    is_supervisor_viewing_task_creator_task = True
    except Exception:
        pass
    
    if not (is_it_manager_creator or is_supervisor_creator or is_task_creator or is_supervisor_viewing_task_creator_task):
        return JsonResponse({
            'success': False,
            'error': _('شما اجازه بروزرسانی این تسک را ندارید.')
        }, status=403)
    
    # Get new status and priority from POST data
    new_status = request.POST.get('status')
    new_priority = request.POST.get('priority')
    
    if new_status:
        if new_status in dict(TicketTask.STATUS_CHOICES):
            task.status = new_status
            # If status is resolved or closed, set resolved_at
            if new_status in ['resolved', 'closed'] and not task.resolved_at:
                task.resolved_at = timezone.now()
            elif new_status not in ['resolved', 'closed']:
                task.resolved_at = None
    
    if new_priority:
        if new_priority in dict(TicketTask.PRIORITY_CHOICES):
            task.priority = new_priority
    
    task.save()
    
    return JsonResponse({
        'success': True,
        'status': task.get_status_display(),
        'priority': task.get_priority_display(),
    })


@login_required
def ticket_task_edit(request, task_id):
    """Edit a ticket task (only creator can edit)"""
    user = request.user
    
    # CRITICAL: Refresh user from database to ensure we have latest relationships
    user.refresh_from_db()
    
    # Temporarily defer 'deadline' field until migration is applied
    task = get_object_or_404(TicketTask.objects.defer('deadline'), id=task_id)
    
    # Only creator (IT manager, supervisor, or task creator) can edit, OR supervisor managing task creator's task
    is_it_manager_creator = (task.created_by == user and user.role == 'it_manager')
    is_supervisor_creator = (task.created_by == user and user.role == 'employee' and user.department_role in ['senior', 'manager'])
    
    # Check if user is a task creator
    is_task_creator = False
    try:
        if task.created_by == user and user.role == 'employee' and user.department and user.department.task_creator_id == user.id:
            is_task_creator = True
    except Exception:
        pass
    
    # Check if user is a supervisor viewing a task created by ANY employee in their supervised departments
    # CRITICAL: Supervisor access is based on department supervision, NOT on creator's current permissions
    is_supervisor_viewing_task_creator_task = False
    try:
        if user.role == 'employee' and user.department_role in ['senior', 'manager']:
            task_creator_user = task.created_by
            if task_creator_user and task_creator_user.role == 'employee':
                supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
                supervised_dept_ids = [dept.id for dept in supervised_depts] if supervised_depts else []
                
                # Check both: creator's department AND task's department
                task_creator_dept_in_supervised = False
                task_dept_in_supervised = False
                
                if task_creator_user.department and task_creator_user.department.id in supervised_dept_ids:
                    task_creator_dept_in_supervised = True
                
                if task.department and task.department.id in supervised_dept_ids:
                    task_dept_in_supervised = True
                
                # Supervisor can manage if creator's department OR task's department is supervised
                if task_creator_dept_in_supervised or task_dept_in_supervised:
                    is_supervisor_viewing_task_creator_task = True
    except Exception:
        pass
    
    if not (is_it_manager_creator or is_supervisor_creator or is_task_creator or is_supervisor_viewing_task_creator_task):
        messages.error(request, _('شما اجازه ویرایش این تسک را ندارید.'))
        return redirect('tickets:ticket_task_detail', task_id=task.id)
    
    if request.method == 'POST':
        form = TicketTaskForm(request.POST, instance=task, user=user)
        form._user = user
        if form.is_valid():
            task = form.save(commit=False)
            # created_by should not change, keep original
            task.save()
            messages.success(request, _('تسک با موفقیت بروزرسانی شد.'))
            return redirect('tickets:ticket_task_detail', task_id=task.id)
    else:
        form = TicketTaskForm(instance=task, user=user)
        form._user = user
    
    return render(request, 'tickets/ticket_task_form.html', {
        'form': form,
        'task': task,
        'title': _('ویرایش تسک')
    })


@login_required
def ticket_task_delete(request, task_id):
    """Delete a ticket task (only creator can delete)"""
    user = request.user
    # Temporarily defer 'deadline' field until migration is applied
    task = get_object_or_404(TicketTask.objects.defer('deadline'), id=task_id)
    
    # Only creator (IT manager, supervisor, or task creator) can delete, OR supervisor managing task creator's task
    is_it_manager_creator = (task.created_by == user and user.role == 'it_manager')
    is_supervisor_creator = (task.created_by == user and user.role == 'employee' and user.department_role in ['senior', 'manager'])
    
    # Check if user is a task creator
    is_task_creator = False
    try:
        if task.created_by == user and user.role == 'employee' and user.department and user.department.task_creator_id == user.id:
            is_task_creator = True
    except Exception:
        pass
    
    # Check if user is a supervisor viewing a task created by ANY employee in their supervised departments
    # CRITICAL: Supervisor access is based on department supervision, NOT on creator's current permissions
    is_supervisor_viewing_task_creator_task = False
    try:
        if user.role == 'employee' and user.department_role in ['senior', 'manager']:
            task_creator_user = task.created_by
            if task_creator_user and task_creator_user.role == 'employee':
                supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
                supervised_dept_ids = [dept.id for dept in supervised_depts] if supervised_depts else []
                
                # Check both: creator's department AND task's department
                task_creator_dept_in_supervised = False
                task_dept_in_supervised = False
                
                if task_creator_user.department and task_creator_user.department.id in supervised_dept_ids:
                    task_creator_dept_in_supervised = True
                
                if task.department and task.department.id in supervised_dept_ids:
                    task_dept_in_supervised = True
                
                # Supervisor can manage if creator's department OR task's department is supervised
                if task_creator_dept_in_supervised or task_dept_in_supervised:
                    is_supervisor_viewing_task_creator_task = True
    except Exception:
        pass
    
    if not (is_it_manager_creator or is_supervisor_creator or is_task_creator or is_supervisor_viewing_task_creator_task):
        messages.error(request, _('شما اجازه حذف این تسک را ندارید.'))
        return redirect('tickets:ticket_task_detail', task_id=task.id)
    
    if request.method == 'POST':
        task.delete()
        messages.success(request, _('تسک با موفقیت حذف شد.'))
        return redirect('tickets:ticket_task_list')
    
    return render(request, 'tickets/ticket_task_delete_confirm.html', {
        'task': task
    })


@login_required
def ticket_task_reply(request, task_id):
    """Reply to a ticket task"""
    user = request.user
    # Temporarily defer 'deadline' field until migration is applied
    task = get_object_or_404(TicketTask.objects.defer('deadline'), id=task_id)
    
    # Assigned user or creator (IT manager, supervisor, or task creator) can reply, OR supervisor managing task creator's task
    # Use ID comparison for more reliable checking
    is_creator = (task.created_by_id == user.id) if task.created_by_id else False
    is_assigned = (task.assigned_to_id == user.id) if task.assigned_to_id else False
    is_it_manager_creator = (is_creator and user.role == 'it_manager')
    is_supervisor_creator = (is_creator and user.role == 'employee' and user.department_role in ['senior', 'manager'])
    
    # Check if user is a task creator
    is_task_creator = False
    try:
        if is_creator and user.role == 'employee' and user.department and user.department.task_creator_id == user.id:
            is_task_creator = True
    except Exception:
        pass
    
    # Check if user is a supervisor viewing a task created by ANY employee in their supervised departments
    # CRITICAL: Supervisor access is based on department supervision, NOT on creator's current permissions
    is_supervisor_viewing_task_creator_task = False
    try:
        if not is_creator and not is_assigned and user.role == 'employee' and user.department_role in ['senior', 'manager']:
            task_creator_user = task.created_by
            if task_creator_user and task_creator_user.role == 'employee':
                supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
                supervised_dept_ids = [dept.id for dept in supervised_depts] if supervised_depts else []
                
                # Check both: creator's department AND task's department
                task_creator_dept_in_supervised = False
                task_dept_in_supervised = False
                
                if task_creator_user.department and task_creator_user.department.id in supervised_dept_ids:
                    task_creator_dept_in_supervised = True
                
                if task.department and task.department.id in supervised_dept_ids:
                    task_dept_in_supervised = True
                
                # Supervisor can manage if creator's department OR task's department is supervised
                if task_creator_dept_in_supervised or task_dept_in_supervised:
                    is_supervisor_viewing_task_creator_task = True
    except Exception:
        pass
    
    if not (is_assigned or is_it_manager_creator or is_supervisor_creator or is_task_creator or is_supervisor_viewing_task_creator_task):
        messages.error(request, _('شما اجازه پاسخ به این تسک را ندارید.'))
        return redirect('tickets:dashboard')
    
    if request.method == 'POST':
        form = TaskReplyForm(request.POST, request.FILES)
        if form.is_valid():
            reply = form.save(commit=False)
            reply.task = task
            reply.author = user
            reply.save()
            
            # Optionally update task status to "in_progress" if it's still "open"
            if task.status == 'open':
                task.status = 'in_progress'
                task.save()
            
            messages.success(request, _('پاسخ با موفقیت ارسال شد.'))
            return redirect('tickets:ticket_task_detail', task_id=task.id)
    else:
        form = TaskReplyForm()
    
    return render(request, 'tickets/task_reply_form.html', {
        'form': form,
        'task': task
    })


@login_required
def my_ticket_tasks(request):
    """View tasks assigned to current user OR created by current user (if task creator)"""
    user = request.user
    
    # Get filter parameters
    status_filter = request.GET.get('status', '')
    
    # Check if user is a task creator
    is_task_creator_for_tasks = False
    try:
        if user.role == 'employee' and user.department and user.department.task_creator_id == user.id:
            is_task_creator_for_tasks = True
    except Exception:
        pass
    
    # For task creators: separate into two sections
    if is_task_creator_for_tasks:
        # My Tasks: tasks assigned to this user (from team leader)
        my_tasks_queryset = TicketTask.objects.filter(assigned_to=user).defer('deadline').prefetch_related('extension_requests')
        
        # Department Tasks: tasks created by this user (for others)
        department_tasks_queryset = TicketTask.objects.filter(created_by=user).defer('deadline').prefetch_related('extension_requests')
        
        # Apply status filter to both
        if status_filter:
            my_tasks_queryset = my_tasks_queryset.filter(status=status_filter)
            department_tasks_queryset = department_tasks_queryset.filter(status=status_filter)
        
        # Order by creation date (newest first)
        my_tasks_queryset = my_tasks_queryset.order_by('-created_at')
        department_tasks_queryset = department_tasks_queryset.order_by('-created_at')
        
        # Pagination for both sections
        my_tasks_paginator = Paginator(my_tasks_queryset, 20)
        department_tasks_paginator = Paginator(department_tasks_queryset, 20)
        page_number = request.GET.get('page', 1)
        section = request.GET.get('section', 'my_tasks')  # 'my_tasks' or 'department_tasks'
        
        # Get paginated pages for both sections
        my_tasks_page = my_tasks_paginator.get_page(page_number if section == 'my_tasks' else 1)
        department_tasks_page = department_tasks_paginator.get_page(page_number if section == 'department_tasks' else 1)
        
        # Get status choices for filter
        task_status_choices = TicketTask.STATUS_CHOICES
        
        context = {
            'is_task_creator': True,
            'my_tasks': my_tasks_page,
            'department_tasks': department_tasks_page,
            'current_section': section,
            'status_filter': status_filter,
            'task_status_choices': task_status_choices,
        }
    else:
        # Regular employees only see tasks assigned to them
        tasks = TicketTask.objects.filter(assigned_to=user).defer('deadline').prefetch_related('extension_requests')
        
        # Apply status filter
        if status_filter:
            tasks = tasks.filter(status=status_filter)
        
        # Order by creation date (newest first)
        tasks = tasks.order_by('-created_at')
        
        # Pagination
        paginator = Paginator(tasks, 20)
        page_number = request.GET.get('page')
        tasks_page = paginator.get_page(page_number)
        
        # Get status choices for filter
        task_status_choices = TicketTask.STATUS_CHOICES
        
        context = {
            'is_task_creator': False,
            'tasks': tasks_page,
            'status_filter': status_filter,
            'task_status_choices': task_status_choices,
        }
    
    return render(request, 'tickets/my_ticket_tasks.html', context)


@login_required
def request_deadline_extension(request, task_id):
    """View for employees to request deadline extension"""
    try:
        task = TicketTask.objects.get(id=task_id)
    except TicketTask.DoesNotExist:
        messages.error(request, _('تسک یافت نشد.'))
        return redirect('tickets:my_ticket_tasks')
    
    # Check if user is assigned to this task and is an employee
    if task.assigned_to != request.user or request.user.department_role != 'employee':
        messages.error(request, _('شما مجاز به درخواست تمدید مهلت برای این تسک نیستید.'))
        return redirect('tickets:my_ticket_tasks')
    
    # Check if deadline is expired
    if not task.is_deadline_expired():
        messages.warning(request, _('مهلت این تسک هنوز به پایان نرسیده است.'))
        return redirect('tickets:my_ticket_tasks')
    
    # Check if there's already a pending request
    pending_request = DeadlineExtensionRequest.objects.filter(
        task=task,
        requested_by=request.user,
        status='pending'
    ).first()
    
    if pending_request:
        messages.info(request, _('شما قبلاً یک درخواست تمدید مهلت در حال بررسی دارید.'))
        return redirect('tickets:my_ticket_tasks')
    
    if request.method == 'POST':
        from .forms import DeadlineExtensionRequestForm
        form = DeadlineExtensionRequestForm(request.POST)
        if form.is_valid():
            extension_request = form.save(commit=False)
            extension_request.task = task
            extension_request.requested_by = request.user
            extension_request.save()
            
            # Notify task creator
            Notification.objects.create(
                recipient=task.created_by,
                title=_('درخواست تمدید مهلت'),
                message=_('کارمند {} برای تسک "{}" درخواست تمدید مهلت داده است.').format(
                    request.user.get_full_name(),
                    task.title
                ),
                notification_type='ticket_created',
                category='tickets'
            )
            
            messages.success(request, _('درخواست تمدید مهلت شما با موفقیت ثبت شد.'))
            return redirect('tickets:ticket_task_detail', task_id=task.id)
    else:
        from .forms import DeadlineExtensionRequestForm
        form = DeadlineExtensionRequestForm()
    
    context = {
        'form': form,
        'task': task,
    }
    return render(request, 'tickets/request_deadline_extension.html', context)


@login_required
def handle_extension_request(request, request_id, action):
    """View for task creators/supervisors to approve/reject extension requests"""
    try:
        extension_request = DeadlineExtensionRequest.objects.get(id=request_id)
    except DeadlineExtensionRequest.DoesNotExist:
        messages.error(request, _('درخواست یافت نشد.'))
        return redirect('tickets:ticket_task_list')
    
    # Check if user can review this request (task creator or supervisor)
    task = extension_request.task
    can_review = False
    
    if task.created_by == request.user:
        can_review = True
    elif request.user.department_role in ['senior', 'manager']:
        if task.department and request.user.is_supervisor_of(task.department):
            can_review = True
    
    if not can_review:
        messages.error(request, _('شما مجاز به بررسی این درخواست نیستید.'))
        return redirect('tickets:ticket_task_list')
    
    if extension_request.status != 'pending':
        messages.warning(request, _('این درخواست قبلاً بررسی شده است.'))
        return redirect('tickets:ticket_task_list')
    
    if request.method == 'POST':
        if action == 'approve':
            extension_request.status = 'approved'
            extension_request.reviewed_by = request.user
            extension_request.reviewed_at = timezone.now()
            extension_request.review_comment = request.POST.get('comment', '')
            extension_request.save()
            
            # Update task deadline
            task.deadline = extension_request.requested_deadline
            task.save()
            
            # Notify requester
            Notification.objects.create(
                recipient=extension_request.requested_by,
                title=_('درخواست تمدید مهلت تایید شد'),
                message=_('درخواست تمدید مهلت شما برای تسک "{}" تایید شد.').format(task.title),
                notification_type='status_done',
                category='tickets'
            )
            
            messages.success(request, _('درخواست تمدید مهلت تایید شد.'))
        elif action == 'reject':
            extension_request.status = 'rejected'
            extension_request.reviewed_by = request.user
            extension_request.reviewed_at = timezone.now()
            extension_request.review_comment = request.POST.get('comment', '')
            extension_request.save()
            
            # Notify requester
            Notification.objects.create(
                recipient=extension_request.requested_by,
                title=_('درخواست تمدید مهلت رد شد'),
                message=_('درخواست تمدید مهلت شما برای تسک "{}" رد شد.').format(task.title),
                notification_type='status_done',
                category='tickets'
            )
            
            messages.success(request, _('درخواست تمدید مهلت رد شد.'))
    
    # Redirect based on referer - if coming from task extension requests page, go back there
    # Otherwise go to general extension requests list
    referer = request.META.get('HTTP_REFERER', '')
    if referer and f'/tasks/{task.id}/extension-requests/' in referer:
        return redirect('tickets:task_extension_requests', task_id=task.id)
    return redirect('tickets:extension_requests_list')


@login_required
def task_extension_requests(request, task_id):
    """View to display and manage extension requests for a specific task"""
    try:
        task = TicketTask.objects.prefetch_related('extension_requests', 'extension_requests__requested_by', 'extension_requests__reviewed_by').get(id=task_id)
    except TicketTask.DoesNotExist:
        messages.error(request, _('تسک یافت نشد.'))
        return redirect('tickets:ticket_task_list')
    
    user = request.user
    
    # Check if user can review extension requests for this task
    can_review = False
    
    if task.created_by == user:
        can_review = True
    elif user.role == 'it_manager':
        can_review = True
    elif user.department_role in ['senior', 'manager']:
        if task.department and user.is_supervisor_of(task.department):
            can_review = True
    
    if not can_review:
        messages.error(request, _('شما مجاز به مشاهده درخواست‌های تمدید مهلت این تسک نیستید.'))
        return redirect('tickets:ticket_task_list')
    
    # Get extension requests for this task
    extension_requests = task.extension_requests.all().select_related('requested_by', 'reviewed_by').order_by('-created_at')
    
    context = {
        'task': task,
        'extension_requests': extension_requests,
        'status_choices': DeadlineExtensionRequest.STATUS_CHOICES,
    }
    
    return render(request, 'tickets/task_extension_requests.html', context)


@login_required
def extension_requests_list(request):
    """View for task creators/supervisors to see pending extension requests"""
    user = request.user
    
    # Get filter parameters
    status_filter = request.GET.get('status', '')  # No default - show all if not specified
    
    # Get extension requests that user can review
    extension_requests = DeadlineExtensionRequest.objects.select_related(
        'task', 'requested_by', 'reviewed_by', 'task__assigned_to', 'task__created_by', 'task__department'
    ).all()
    
    # Filter based on user permissions
    if user.role == 'it_manager':
        # IT managers can see all extension requests for tasks they created
        extension_requests = extension_requests.filter(task__created_by=user)
    elif user.department_role in ['senior', 'manager']:
        # Supervisors can see extension requests for tasks in their supervised departments
        supervised_depts = user.get_supervised_departments()
        if supervised_depts:
            extension_requests = extension_requests.filter(
                task__department__in=[d.id for d in supervised_depts]
            )
        else:
            extension_requests = extension_requests.none()
    elif user.role == 'employee' and user.department and user.department.task_creator_id == user.id:
        # Task creators can see extension requests for tasks they created
        extension_requests = extension_requests.filter(task__created_by=user)
    else:
        # Regular employees can't see extension requests
        extension_requests = extension_requests.none()
    
    # Apply status filter
    if status_filter:
        extension_requests = extension_requests.filter(status=status_filter)
    
    # Order by creation date (newest first)
    extension_requests = extension_requests.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(extension_requests, 20)
    page_number = request.GET.get('page')
    requests_page = paginator.get_page(page_number)
    
    context = {
        'extension_requests': requests_page,
        'status_filter': status_filter,
        'status_choices': DeadlineExtensionRequest.STATUS_CHOICES,
    }
    
    return render(request, 'tickets/extension_requests_list.html', context)


@login_required
def calendar_api_view(request):
    """API endpoint to get calendar data for a specific year/month"""
    year = request.GET.get('year')
    month = request.GET.get('month')
    
    if not year or not month:
        return JsonResponse({
            'success': False,
            'error': _('سال و ماه الزامی است')
        }, status=400)
    
    try:
        year = int(year)
        month = int(month)
        
        # Validate month range
        if month < 1 or month > 12:
            return JsonResponse({
                'success': False,
                'error': _('ماه باید بین 1 تا 12 باشد')
            }, status=400)
        
        # Get calendar data from service layer
        from .calendar_services.calendar_service import get_or_fetch_month_data
        
        calendar_data = get_or_fetch_month_data(year, month)
        
        return JsonResponse({
            'success': True,
            'year': year,
            'month': month,
            'days': calendar_data
        })
        
    except ValueError:
        return JsonResponse({
            'success': False,
            'error': _('سال و ماه باید عدد باشند')
        }, status=400)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error fetching calendar data: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': _('خطا در دریافت اطلاعات تقویم')
        }, status=500)


@login_required
def get_current_jalali_date_api(request):
    """API endpoint to get the current Jalali date from server"""
    try:
        from .calendar_services.jalali_calendar import JalaliCalendarService
        current_date = JalaliCalendarService.get_current_jalali_date()
        return JsonResponse({
            'success': True,
            'year': current_date['year'],
            'month': current_date['month'],
            'day': current_date['day'],
            'hour': current_date['hour'],
            'minute': current_date['minute']
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting current Jalali date: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': _('خطا در دریافت تاریخ فعلی')
        }, status=500)


@login_required
def get_employees_for_department(request, department_id):
    """API endpoint to get employees for a department (for task assignment)"""
    # #region agent log - Hypothesis D: API endpoint entry
    import json
    import os
    from datetime import datetime
    log_path = r'c:\Users\User\Desktop\pticket-main\.cursor\debug.log'
    def log_debug(hypothesis_id, location, message, data):
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            entry = {
                'id': f'log_{int(datetime.now().timestamp() * 1000)}',
                'timestamp': int(datetime.now().timestamp() * 1000),
                'location': location,
                'message': message,
                'data': data,
                'sessionId': 'debug-session',
                'runId': 'run1',
                'hypothesisId': hypothesis_id
            }
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception: pass
    log_debug('D', 'tickets/views.py:4890', 'get_employees_for_department entry', {
        'user_id': request.user.id,
        'department_id': department_id,
        'user_role': request.user.role
    })
    # #endregion
    
    try:
        user = request.user
        
        # CRITICAL: Refresh user from database to ensure we have latest relationships
        user.refresh_from_db()
        
        department = get_object_or_404(Department, id=department_id, is_active=True)
        
        # Check if user is a supervisor
        is_supervisor = (user.role == 'employee' and user.department_role in ['senior', 'manager'])
        is_it_manager = user.role == 'it_manager'
        
        # Task creator: check if user is a task creator for ANY department
        task_creator_departments = Department.objects.filter(
            task_creator=user,
            is_active=True,
            department_type='employee'
        ) if user.role == 'employee' else Department.objects.none()
        is_task_creator = user.role == 'employee' and task_creator_departments.exists()
        
        log_debug('D', 'tickets/views.py:4908', 'API supervisor/task_creator check', {
            'is_supervisor': is_supervisor,
            'is_it_manager': is_it_manager,
            'is_task_creator': is_task_creator,
            'task_creator_dept_ids': list(task_creator_departments.values_list('id', flat=True)),
            'requested_dept_id': department.id
        })
        
        # Check authorization: user must be supervisor, task creator, or IT manager
        if not (is_supervisor or is_task_creator or is_it_manager):
            # User is not authorized to access employees
            log_debug('D', 'tickets/views.py:unauthorized', 'User not authorized to access employees', {
                'user_role': user.role,
                'department_role': getattr(user, 'department_role', None)
            })
            return JsonResponse({
                'success': False,
                'error': 'Unauthorized access'
            }, status=403)
        
        # For supervisors: verify they manage this department
        if is_supervisor:
            # CRITICAL: Call get_supervised_departments() which queries database directly
            supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
            supervised_dept_ids = [dept.id for dept in supervised_depts]
            log_debug('D', 'tickets/views.py:4916', 'API supervised departments check', {
                'supervised_dept_ids': supervised_dept_ids,
                'requested_dept_id': department.id,
                'dept_in_supervised': department.id in supervised_dept_ids
            })
            
            if department.id not in supervised_dept_ids:
                # Supervisor doesn't manage this department - return empty list
                log_debug('D', 'tickets/views.py:4923', 'Department not supervised - returning empty', {})
                return JsonResponse({
                    'success': True,
                    'employees': []
                })
        
        # For task creators: verify department is one of their task_creator departments
        if is_task_creator:
            allowed_dept_ids = list(task_creator_departments.values_list('id', flat=True))
            log_debug('D', 'tickets/views.py:task_creator_api', 'Task creator department check', {
                'allowed_dept_ids': allowed_dept_ids,
                'requested_dept_id': department.id,
                'dept_in_allowed': department.id in allowed_dept_ids
            })
            if department.id not in allowed_dept_ids:
                log_debug('D', 'tickets/views.py:task_creator_api_empty', 'Department not allowed for task creator - returning empty', {
                    'allowed_dept_ids': allowed_dept_ids,
                    'requested_dept_id': department.id
                })
                return JsonResponse({
                    'success': True,
                    'employees': []
                })
        
        # Get employees from this department (filtered by permissions above)
        employees = User.objects.filter(
            department=department,
            is_active=True,
            role='employee'
        )

        # Exclude department heads (supervisors) - users with senior/manager role
        employees = employees.exclude(department_role__in=['senior', 'manager'])
        
        # Exclude the FK supervisor of this department if exists
        if department.supervisor:
            employees = employees.exclude(id=department.supervisor.id)
        
        # Exclude users who supervise this department via M2M relationship
        supervisors_of_dept = User.objects.filter(
            supervised_departments=department,
            is_active=True
        ).values_list('id', flat=True)
        if supervisors_of_dept:
            employees = employees.exclude(id__in=supervisors_of_dept)

        # Supervisors and task creators must not be able to assign tasks to themselves
        if (is_supervisor or is_task_creator) and user and user.id:
            employees = employees.exclude(id=user.id)

        employees = employees.order_by('first_name', 'last_name')
        log_debug('D', 'tickets/views.py:4934', 'API employees query result', {
            'employee_count': employees.count(),
            'employee_ids': list(employees.values_list('id', flat=True))
        })
        
        employees_data = []
        for employee in employees:
            employees_data.append({
                'id': employee.id,
                'name': employee.get_full_name(),
                'is_senior': employee.department_role == 'senior'
            })
        
        return JsonResponse({
            'success': True,
            'employees': employees_data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def get_departments_without_team_lead(request):
    """API endpoint to get departments without a Team Lead (for Team Lead assignment)"""
    try:
        if not is_admin_superuser(request.user):
            return JsonResponse({
                'success': False,
                'error': _('دسترسی رد شد')
            }, status=403)
        
        # Get current user ID if editing (to include their current department)
        current_user_id = request.GET.get('user_id', None)
        current_dept_id = None
        
        if current_user_id:
            try:
                current_user = User.objects.get(id=current_user_id, role='employee')
                current_dept_id = current_user.department_id
            except User.DoesNotExist:
                pass
        
        # Use the same comprehensive filtering logic as SupervisorAssignmentForm
        # Method 1: Exclude departments with active FK supervisor
        depts_with_fk_supervisor = list(Department.objects.filter(
            is_active=True,
            department_type='employee',
            supervisor__isnull=False,
            supervisor__is_active=True
        ).values_list('id', flat=True))
        
        # Method 2: Exclude departments with active M2M supervisors
        depts_with_m2m_supervisor = list(Department.objects.filter(
            is_active=True,
            department_type='employee',
            supervisors__is_active=True
        ).values_list('id', flat=True))
        
        # Method 3: Exclude departments with active users having department_role='senior' or 'manager'
        depts_with_role_based_leads = list(
            User.objects.filter(
                role='employee',
                department_role__in=['senior', 'manager'],
                is_active=True,
                department__isnull=False,
                department__is_active=True,
                department__department_type='employee'
            ).exclude(
                id=current_user_id if current_user_id else None
            ).values_list('department_id', flat=True).distinct()
        )
        
        # Combine all excluded department IDs
        all_excluded_dept_ids = set(depts_with_fk_supervisor) | set(depts_with_m2m_supervisor) | set(depts_with_role_based_leads)
        
        # CRITICAL: For edit form, include current user's department even if it has a Team Lead
        if current_dept_id:
            all_excluded_dept_ids.discard(current_dept_id)
        
        # Get all active employee departments EXCEPT those with any type of Team Lead
        if all_excluded_dept_ids:
            departments = Department.objects.filter(
                is_active=True,
                department_type='employee'
            ).exclude(id__in=all_excluded_dept_ids).distinct().order_by('name')
        else:
            departments = Department.objects.filter(
                is_active=True,
                department_type='employee'
            ).distinct().order_by('name')
        
        departments_data = [{
            'id': dept.id,
            'name': dept.name
        } for dept in departments]
        
        return JsonResponse({
            'success': True,
            'departments': departments_data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def get_all_employee_departments(request):
    """API endpoint to get all active employee departments (for non-Team Lead users)"""
    try:
        if not is_admin_superuser(request.user):
            return JsonResponse({
                'success': False,
                'error': _('دسترسی رد شد')
            }, status=403)
        
        departments = Department.objects.filter(
            is_active=True,
            department_type='employee'
        ).order_by('name')
        
        departments_data = [{
            'id': dept.id,
            'name': dept.name
        } for dept in departments]
        
        return JsonResponse({
            'success': True,
            'departments': departments_data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
