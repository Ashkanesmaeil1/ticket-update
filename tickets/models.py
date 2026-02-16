from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinLengthValidator, RegexValidator
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from .validators import validate_iranian_national_id, validate_iranian_mobile_number
from .utils import normalize_national_id, normalize_employee_code
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

def validate_employee_code(value):
    """Validate that employee code is exactly 4 digits (normalizes Persian/Arabic numerals)"""
    # Normalize Persian/Arabic numerals to English
    normalized_value = normalize_employee_code(value)
    
    if len(normalized_value) != 4:
        raise ValidationError(_('کد کارمندی باید دقیقاً ۴ رقم باشد.'))
    if not normalized_value.isdigit():
        raise ValidationError(_('کد کارمندی باید فقط شامل اعداد باشد.'))

class Branch(models.Model):
    """Branch (position/location) model - branch_code must be globally unique. A branch can have multiple departments."""
    name = models.CharField(_('نام شعبه'), max_length=100)
    branch_code = models.CharField(_('کد شعبه'), max_length=50, unique=True, help_text=_('کد یکتا برای شعبه (باید در تمام سیستم یکتا باشد)'))
    description = models.TextField(_('توضیحات'), blank=True, null=True)
    is_active = models.BooleanField(_('فعال'), default=True)
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    updated_at = models.DateTimeField(_('تاریخ بروزرسانی'), auto_now=True)
    
    class Meta:
        verbose_name = _("شعبه")
        verbose_name_plural = _("شعبه‌ها")
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def clean(self):
        """Validate that branch_code is globally unique"""
        if self.branch_code:
            existing = Branch.objects.filter(branch_code=self.branch_code)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError({
                    'branch_code': _('کد شعبه باید در تمام سیستم یکتا باشد.')
                })

class Department(models.Model):
    """Department model for organizational units"""
    DEPARTMENT_TYPE_CHOICES = [
        ('employee', _('بخش کارمندی')),
        ('technician', _('بخش فنی')),
    ]
    
    name = models.CharField(_('نام بخش'), max_length=100, unique=True, 
                           error_messages={'unique': 'بخشی با این نام قبلاً وجود دارد.'})
    department_type = models.CharField(_('نوع بخش'), max_length=20, choices=DEPARTMENT_TYPE_CHOICES, default='employee')
    description = models.TextField(_('توضیحات'), blank=True, null=True)
    
    # Multi-tenant categorization support
    is_service_provider = models.BooleanField(
        _('ارائه‌دهنده خدمات'),
        default=False,
        help_text=_('در صورتی که این بخش می‌تواند تیکت‌های پشتیبانی دریافت کند، این گزینه را فعال کنید')
    )
    service_provider_since = models.DateTimeField(
        _('ارائه خدمات از تاریخ'),
        null=True,
        blank=True,
        help_text=_('تاریخ فعال‌سازی این بخش به عنوان ارائه‌دهنده خدمات')
    )
    is_active = models.BooleanField(_('فعال'), default=True)
    can_receive_tickets = models.BooleanField(_('می‌تواند تیکت دریافت کند'), default=False, 
                                             help_text=_('اگر فعال باشد، این بخش می‌تواند تیکت‌ها را مستقیماً از کاربران دریافت کند'))
    has_warehouse = models.BooleanField(_('انبار'), default=False,
                                       help_text=_('اگر فعال باشد، سرپرست این بخش می‌تواند به ماژول انبار دسترسی داشته باشد'))
    supervisor = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='departments_as_supervisor',
        verbose_name=_('سرپرست'),
        help_text=_('کاربری که سرپرست این بخش است (فقط یک سرپرست برای هر بخش)'),
        limit_choices_to={'department_role': 'senior', 'role': 'employee'}
    )
    ticket_responder = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='departments_as_responder',
        verbose_name=_('پاسخ‌دهنده تیکت'),
        help_text=_('کارمندی که می‌تواند به تیکت‌های دریافتی این بخش پاسخ دهد و وضعیت آن‌ها را تغییر دهد')
    )
    task_creator = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='departments_as_task_creator',
        verbose_name=_('ایجادکننده تسک'),
        help_text=_('کارمندی که می‌تواند برای این بخش تسک ایجاد کرده و به سایر کارمندان این بخش تخصیص دهد')
    )
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, 
                              related_name='departments', verbose_name=_('شعبه'),
                              help_text=_('شعبه این بخش (الزامی)'))
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    updated_at = models.DateTimeField(_('تاریخ بروزرسانی'), auto_now=True)
    
    class Meta:
        verbose_name = _("بخش")
        verbose_name_plural = _("بخش‌ها")
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def get_user_count(self):
        """Get the number of users in this department"""
        return self.users.count()

class User(AbstractUser):
    """Custom User model with role-based access control"""
    ROLE_CHOICES = [
        ('employee', _('کارمند')),
        ('technician', _('کارشناس فنی')),
        ('it_manager', _('مدیر IT')),
    ]
    DEPARTMENT_ROLE_CHOICES = [
        ('employee', _('کارمند')),
        ('senior', _('سرپرست')),
        ('manager', _('مدیر')),
    ]
    
    # Override username field to be non-unique since we use national_id for authentication
    username = models.CharField(_('نام کاربری'), max_length=150, unique=False, blank=True, null=True)
    
    national_id = models.CharField(_('کد ملی'), max_length=20, unique=True, validators=[validate_iranian_national_id], 
                                  error_messages={'unique': 'کاربر با این کد ملی وجود دارد.'})
    employee_code = models.CharField(_('کد کارمندی'), max_length=10, unique=True, validators=[validate_employee_code],
                                    error_messages={'unique': 'کاربر با این کد کارمندی وجود دارد.'})
    role = models.CharField(_('نقش'), max_length=20, choices=ROLE_CHOICES, default='employee')
    phone = models.CharField(_('تلفن'), max_length=15, blank=True, null=True, validators=[validate_iranian_mobile_number])
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='users', verbose_name=_('بخش اصلی'))
    department_role = models.CharField(_('نقش در بخش'), max_length=10, choices=DEPARTMENT_ROLE_CHOICES, default='employee')
    
    # For supervisors - can supervise multiple departments
    supervised_departments = models.ManyToManyField(Department, related_name='supervisors', blank=True, 
                                                   verbose_name=_('بخش‌های تحت سرپرستی'),
                                                   help_text=_('بخش‌هایی که این کاربر سرپرست آن‌ها است'))
    
    # For technicians - assigned by IT Manager
    assigned_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_technicians', verbose_name=_('تخصیص داده شده توسط'))
    
    # Set USERNAME_FIELD to national_id for authentication
    USERNAME_FIELD = 'national_id'
    REQUIRED_FIELDS = ['employee_code', 'first_name', 'last_name']
    
    def save(self, *args, **kwargs):
        """
        Override save to normalize national_id and employee_code before saving.
        This ensures consistency regardless of input format (Persian/Arabic vs English numerals).
        """
        # Normalize identifiers if they are set
        if self.national_id:
            original_national_id = self.national_id
            self.national_id = normalize_national_id(self.national_id)
            if original_national_id != self.national_id:
                logger.info(
                    f"User {self.pk or 'new'}: National ID normalized from '{original_national_id}' to '{self.national_id}'"
                )
        
        if self.employee_code:
            original_employee_code = self.employee_code
            self.employee_code = normalize_employee_code(self.employee_code)
            if original_employee_code != self.employee_code:
                logger.info(
                    f"User {self.pk or 'new'}: Employee Code normalized from '{original_employee_code}' to '{self.employee_code}'"
                )
        
        # Forced identity synchronization: username must always match national_id (login identifier).
        # This ensures Admin panel / User Management edits to National ID are reflected in the Auth
        # User record used by AdminModelBackend and login.
        if self.national_id and self.username != self.national_id:
            logger.info(
                f"User {self.pk or 'new'}: Syncing username to national_id (was '{self.username}', now '{self.national_id}')"
            )
            self.username = self.national_id
            # When save(update_fields=...) is used, include username so the sync is persisted
            if kwargs.get('update_fields') is not None and 'username' not in kwargs['update_fields']:
                kwargs['update_fields'] = list(kwargs['update_fields']) + ['username']
        
        # Call parent save
        super().save(*args, **kwargs)
    
    def get_full_name(self):
        """Override to return Administrator for admin superuser"""
        try:
            from .admin_security import is_admin_superuser
            if is_admin_superuser(self):
                return "Administrator"
        except (ImportError, AttributeError):
            # Fallback if admin_security is not available (e.g., during migrations)
            pass
        return super().get_full_name() or f"{self.first_name} {self.last_name}".strip() or self.username
    
    def __str__(self):
        # Check if this is the admin superuser
        try:
            from .admin_security import is_admin_superuser
            if is_admin_superuser(self):
                return "Administrator"
        except (ImportError, AttributeError):
            # Fallback if admin_security is not available (e.g., during migrations)
            pass
        return f"{self.get_full_name()} ({self.get_role_display()})"
    
    def get_department_display(self):
        """Get department name for display"""
        if self.department:
            return self.department.name
        return "بدون بخش"
    
    def is_supervisor_of(self, department):
        """Check if this user is a supervisor of the given department"""
        if not department:
            return False
        
        # User must be a senior/manager to be a supervisor
        if self.department_role not in ['senior', 'manager']:
            return False
        
        try:
            # Check if user is supervisor via ManyToMany relationship
            if hasattr(self, 'supervised_departments'):
                if department in self.supervised_departments.all():
                    return True
            
            # Check ForeignKey relationship (department.supervisor)
            if hasattr(department, 'supervisor') and department.supervisor == self:
                return True
            
            # Check if user is supervisor of their own department
            # This handles the case where user.department == department and user is a senior/manager
            if self.department == department and self.department_role in ['senior', 'manager']:
                return True
            
            return False
        except (AttributeError, Exception):
            # Return False if there's any error (e.g., during migration or if relationship doesn't exist yet)
            return False
    
    def get_supervised_departments(self):
        """Get all departments this user supervises
        
        CRITICAL: This method queries the database directly to ensure we always
        get fresh data, even if the user object is stale or cached.
        """
        # #region agent log - Hypothesis A: Method entry
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
        try:
            log_debug('A', 'tickets/models.py:166', 'get_supervised_departments entry', {
                'user_id': getattr(self, 'id', None),
                'user_pk': self.pk if hasattr(self, 'pk') else None,
                'department_role': getattr(self, 'department_role', None)
            })
        except Exception:
            pass  # Don't fail if logging fails
        # #endregion
        
        # Check for both seniors and managers
        department_role = getattr(self, 'department_role', None)
        if department_role not in ['senior', 'manager']:
            try:
                log_debug('A', 'tickets/models.py:201', 'Not senior/manager - returning empty', {
                    'department_role': department_role
                })
            except Exception:
                pass
            return []
        
        try:
            supervised = []
            
            # CRITICAL FIX: Query M2M relationship directly from database
            # Don't rely on cached user object relationships
            if hasattr(self, 'supervised_departments') and self.pk:
                try:
                    # Query M2M table directly to ensure fresh data
                    from django.db import connection
                    m2m_table = User.supervised_departments.through._meta.db_table
                    try:
                        log_debug('A', 'tickets/models.py:217', 'Querying M2M table', {
                            'm2m_table': m2m_table,
                            'user_id': self.pk
                        })
                    except Exception:
                        pass
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"SELECT department_id FROM {m2m_table} WHERE user_id = %s",
                            [self.pk]
                        )
                        m2m_dept_ids = [row[0] for row in cursor.fetchall()]
                    try:
                        log_debug('A', 'tickets/models.py:227', 'M2M query result', {
                            'm2m_dept_ids': m2m_dept_ids,
                            'm2m_count': len(m2m_dept_ids)
                        })
                    except Exception:
                        pass
                    
                    if m2m_dept_ids:
                        # Get department objects from database
                        m2m_depts = Department.objects.filter(
                            id__in=m2m_dept_ids,
                            is_active=True
                        )
                        try:
                            log_debug('A', 'tickets/models.py:238', 'M2M departments found', {
                                'm2m_depts_count': m2m_depts.count(),
                                'm2m_dept_names': list(m2m_depts.values_list('name', flat=True))
                            })
                        except Exception:
                            pass
                        supervised.extend(m2m_depts)
                except (AttributeError, ValueError, Exception) as e:
                    # Fallback to standard M2M access if direct query fails
                    try:
                        m2m_depts = self.supervised_departments.all()
                        supervised.extend([d for d in m2m_depts if d.is_active])
                    except:
                        pass
            
            # Also check if any department has this user as supervisor via ForeignKey
            # This queries the database directly, so it's always fresh
            try:
                fk_depts = Department.objects.filter(
                    supervisor_id=self.pk,
                    is_active=True
                )
                try:
                    log_debug('A', 'tickets/models.py:262', 'FK departments query result', {
                        'fk_depts_count': fk_depts.count(),
                        'fk_dept_ids': list(fk_depts.values_list('id', flat=True)),
                        'fk_dept_names': list(fk_depts.values_list('name', flat=True))
                    })
                except Exception:
                    pass
                supervised.extend(fk_depts)
            except (AttributeError, ValueError):
                pass
            
            # Include the user's own department FK if set (legacy/old workflow assignment)
            # Refresh from database to ensure we have the latest value
            try:
                if self.pk:
                    # Refresh department FK from database
                    from django.db import connection
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT department_id FROM tickets_user WHERE id = %s",
                            [self.pk]
                        )
                        row = cursor.fetchone()
                        if row and row[0]:
                            dept_id = row[0]
                            try:
                                dept = Department.objects.get(id=dept_id, is_active=True)
                                if dept not in supervised:
                                    supervised.append(dept)
                            except Department.DoesNotExist:
                                pass
            except (AttributeError, ValueError, Exception):
                pass
            
            # Remove duplicates (preserve order by converting to dict keys then back to list)
            seen = set()
            result = []
            for dept in supervised:
                if dept.id not in seen:
                    seen.add(dept.id)
                    result.append(dept)
            try:
                log_debug('A', 'tickets/models.py:305', 'Final supervised departments result', {
                    'result_count': len(result),
                    'result_ids': [d.id for d in result],
                    'result_names': [d.name for d in result]
                })
            except Exception:
                pass
            return result
        except Exception as e:
            # Return empty list if there's any error (e.g., during migration or if relationship doesn't exist yet)
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error getting supervised departments for user {self.id}: {e}")
            import traceback
            logger.warning(traceback.format_exc())
            return []
    
    def get_department_and_role_display(self):
        """Get department and role for display"""
        try:
            if self.department_role == 'manager':
                return "مدیر کل"
            elif self.department_role == 'senior':
                supervised = self.get_supervised_departments()
                if supervised:
                    dept_names = ', '.join([d.name for d in supervised[:3]])
                    if len(supervised) > 3:
                        dept_names += f' و {len(supervised) - 3} بخش دیگر'
                    return f"سرپرست • {dept_names}"
                elif self.department:
                    return f"سرپرست • {self.department.name}"
                else:
                    return "سرپرست"
            else:
                if self.department:
                    return f"{self.get_role_display()} • {self.department.name}"
                else:
                    return self.get_role_display()
        except Exception:
            # Fallback to simple display if there's any error
            if self.department:
                return f"{self.get_role_display()} • {self.department.name}"
            else:
                return self.get_role_display()
    
    class Meta:
        verbose_name = _("کاربر")
        verbose_name_plural = _("کاربران")

class Ticket(models.Model):
    """Ticket model for support requests"""
    PRIORITY_CHOICES = [
        ('low', _('کم')),
        ('medium', _('متوسط')),
        ('high', _('زیاد')),
        ('urgent', _('فوری')),
    ]
    
    STATUS_CHOICES = [
        ('open', _('باز')),
        ('in_progress', _('در حال انجام')),
        ('waiting_for_user', _('در انتظار کاربر')),
        ('resolved', _('انجام شده')),
        ('closed', _('بسته')),
    ]
    
    CATEGORY_CHOICES = [
        ('hardware', _('سخت‌افزار')),
        ('software', _('نرم‌افزار')),
        ('network', _('شبکه')),
        ('access', _('دسترسی شبکه')),
        ('other', _('سایر')),
    ]
    # Approval flow for access tickets
    ACCESS_APPROVAL_CHOICES = [
        ('not_required', _('بدون نیاز به تایید')),
        ('pending', _('در انتظار تایید سرپرست')),
        ('approved', _('تایید شده')),
        ('rejected', _('رد شده')),
    ]
    
    title = models.CharField(_('عنوان'), max_length=200)
    description = models.TextField(_('توضیحات'))
    category = models.CharField(_('دسته‌بندی'), max_length=20, choices=CATEGORY_CHOICES, default='other')
    
    # New department-specific category (multi-tenant)
    ticket_category = models.ForeignKey(
        'TicketCategory',
        on_delete=models.PROTECT,
        related_name='tickets',
        verbose_name=_('دسته‌بندی جدید'),
        null=True,
        blank=True,
        help_text=_('دسته‌بندی تیکت بر اساس بخش مقصد (سیستم جدید)')
    )
    priority = models.CharField(_('اولویت'), max_length=20, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(_('وضعیت'), max_length=20, choices=STATUS_CHOICES, default='open')
    access_approval_status = models.CharField(
        _('وضعیت تایید دسترسی شبکه'), max_length=20, choices=ACCESS_APPROVAL_CHOICES, default='not_required'
    )
    
    # Relationships
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_tickets', verbose_name=_('ایجاد شده توسط'))
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tickets', verbose_name=_('تخصیص داده شده به'))
    
    # Branch and target department for multi-department ticket system
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, 
                              related_name='tickets', verbose_name=_('شعبه'))
    target_department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='received_tickets', verbose_name=_('بخش هدف'),
                                         help_text=_('بخشی که تیکت برای آن ارسال شده است'))
    
    # Timestamps
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    updated_at = models.DateTimeField(_('تاریخ بروزرسانی'), auto_now=True)
    resolved_at = models.DateTimeField(_('تاریخ انجام'), null=True, blank=True)
    
    # File attachments
    attachment = models.FileField(_('فایل پیوست'), upload_to='ticket_attachments/', blank=True, null=True)
    
    def __str__(self):
        return f"#{self.id} - {self.title} ({self.get_status_display()})"
    
    def get_category_display(self):
        """
        Return the category display name.
        Priority: ticket_category (new system) > category (old system fallback)
        """
        if self.ticket_category:
            # New department-specific category system
            return self.ticket_category.name
        elif self.category:
            # Fallback to old category system
            return dict(self.CATEGORY_CHOICES).get(self.category, self.category)
        else:
            # No category set - return default
            return dict(self.CATEGORY_CHOICES).get('other', _('سایر'))
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = _("تیکت")
        verbose_name_plural = _("تیکت‌ها")

class Reply(models.Model):
    """Reply model for ticket conversations"""
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='replies', verbose_name=_('تیکت'))
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='replies', verbose_name=_('نویسنده'))
    content = models.TextField(_('محتوا'))
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    
    # Private reply functionality
    is_private = models.BooleanField(_('پاسخ محرمانه'), default=False, help_text=_('این پاسخ فقط برای کارمند دریافت‌کننده قابل مشاهده است'))
    
    # File attachments for replies
    attachment = models.FileField(_('فایل پیوست'), upload_to='reply_attachments/', blank=True, null=True)
    
    def __str__(self):
        return f"پاسخ {self.author} در {self.ticket}"
    
    class Meta:
        ordering = ['created_at']
        verbose_name = _("پاسخ")
        verbose_name_plural = _("پاسخ‌ها")

class TicketTask(models.Model):
    """Ticket Task model for IT manager to assign tasks to employees"""
    PRIORITY_CHOICES = [
        ('low', _('کم')),
        ('medium', _('متوسط')),
        ('high', _('زیاد')),
        ('urgent', _('فوری')),
    ]
    
    STATUS_CHOICES = [
        ('open', _('باز')),
        ('in_progress', _('در حال انجام')),
        ('waiting_for_user', _('در انتظار کاربر')),
        ('resolved', _('انجام شده')),
        ('closed', _('بسته')),
    ]
    
    title = models.CharField(_('عنوان'), max_length=200)
    description = models.TextField(_('توضیحات'))
    priority = models.CharField(_('اولویت'), max_length=20, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(_('وضعیت'), max_length=20, choices=STATUS_CHOICES, default='open')
    
    # Relationships
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_tasks', verbose_name=_('ایجاد شده توسط'))
    assigned_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='assigned_tasks', verbose_name=_('تخصیص داده شده به'))
    department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks', verbose_name=_('بخش'))
    
    # Timestamps
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    updated_at = models.DateTimeField(_('تاریخ بروزرسانی'), auto_now=True)
    resolved_at = models.DateTimeField(_('تاریخ انجام'), null=True, blank=True)
    deadline = models.DateTimeField(_('مهلت انجام'), null=True, blank=True, help_text=_('تاریخ و زمان مهلت انجام تسک'))
    deadline_reminder_8h_sent = models.BooleanField(
        _('یادآور ۸ ساعت ارسال شده'), default=False, editable=False,
        help_text=_('آیا ایمیل یادآور ۸ ساعت مانده به مهلت ارسال شده است')
    )
    deadline_reminder_2h_sent = models.BooleanField(
        _('یادآور ۲ ساعت ارسال شده'), default=False, editable=False,
        help_text=_('آیا ایمیل یادآور ۲ ساعت مانده به مهلت ارسال شده است')
    )
    
    def save(self, *args, **kwargs):
        if self.pk and self.deadline is not None:
            try:
                old = TicketTask.objects.get(pk=self.pk)
                if old.deadline != self.deadline:
                    self.deadline_reminder_8h_sent = False
                    self.deadline_reminder_2h_sent = False
            except TicketTask.DoesNotExist:
                pass
        super().save(*args, **kwargs)
    
    def is_deadline_expired(self):
        """Check if the task deadline has expired"""
        if not self.deadline:
            return False
        return timezone.now() > self.deadline
    
    def has_pending_extension_request(self, user):
        """Check if user has a pending extension request for this task"""
        return self.extension_requests.filter(
            requested_by=user,
            status='pending'
        ).exists()
    
    def __str__(self):
        return f"Task #{self.id} - {self.title} ({self.get_status_display()})"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = _("تسک تیکت")
        verbose_name_plural = _("تسک‌های تیکت")

class TaskReply(models.Model):
    """Reply model for ticket task conversations"""
    task = models.ForeignKey(TicketTask, on_delete=models.CASCADE, related_name='replies', verbose_name=_('تسک'))
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_replies', verbose_name=_('نویسنده'))
    content = models.TextField(_('محتوا'))
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    
    # File attachments for replies
    attachment = models.FileField(_('فایل پیوست'), upload_to='task_reply_attachments/', blank=True, null=True)
    
    def __str__(self):
        return f"پاسخ {self.author} در {self.task}"
    
    class Meta:
        ordering = ['created_at']
        verbose_name = _("پاسخ تسک")
        verbose_name_plural = _("پاسخ‌های تسک")


class DeadlineExtensionRequest(models.Model):
    """Model for deadline extension requests from employees"""
    STATUS_CHOICES = [
        ('pending', _('در انتظار بررسی')),
        ('approved', _('تایید شده')),
        ('rejected', _('رد شده')),
    ]
    
    task = models.ForeignKey(TicketTask, on_delete=models.CASCADE, related_name='extension_requests', verbose_name=_('تسک'))
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='extension_requests', verbose_name=_('درخواست‌دهنده'))
    requested_deadline = models.DateTimeField(_('مهلت درخواستی'), help_text=_('مهلت جدید مورد درخواست'))
    reason = models.TextField(_('دلیل درخواست'), help_text=_('توضیح دلیل درخواست تمدید مهلت'))
    status = models.CharField(_('وضعیت'), max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_extensions', verbose_name=_('بررسی کننده'))
    review_comment = models.TextField(_('نظر بررسی'), blank=True, null=True)
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    reviewed_at = models.DateTimeField(_('تاریخ بررسی'), null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = _("درخواست تمدید مهلت")
        verbose_name_plural = _("درخواست‌های تمدید مهلت")
    
    def __str__(self):
        return f"Extension Request for Task #{self.task.id} - {self.get_status_display()}"


class Notification(models.Model):
    """Notification model for user alerts (initially for IT manager)."""
    TYPE_CHOICES = [
        ('ticket_urgent', _('تیکت فوری')),
        ('ticket_created', _('تیکت جدید')),
        ('access_approved', _('تایید دسترسی شبکه')),
        ('access_pending_approval', _('در انتظار تایید دسترسی شبکه')),
        ('access_rejected', _('رد دسترسی شبکه')),
        ('user_created', _('ایجاد کاربر')),
        ('login', _('ورود')),
        ('status_done', _('انجام شد')),
    ]
    
    CATEGORY_CHOICES = [
        ('tickets', _('تیکت‌ها')),
        ('users', _('کاربران')),
        ('system', _('سیستم')),
        ('access', _('دسترسی شبکه')),
        ('team_leader_access', _('درخواست‌های دسترسی شبکه')),
    ]

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', verbose_name=_('دریافت‌کننده'))
    title = models.CharField(_('عنوان'), max_length=255)
    message = models.TextField(_('پیام'), blank=True)
    notification_type = models.CharField(_('نوع'), max_length=50, choices=TYPE_CHOICES)
    category = models.CharField(_('دسته‌بندی'), max_length=20, choices=CATEGORY_CHOICES, default='system')
    ticket = models.ForeignKey('Ticket', on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications', verbose_name=_('تیکت'))
    user_actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications', verbose_name=_('کاربر ایجاد کننده'))
    is_read = models.BooleanField(_('خوانده شده'), default=False)
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('اعلان')
        verbose_name_plural = _('اعلان‌ها')
        indexes = [
            models.Index(fields=['-created_at'], name='tickets_not_created_idx'),
            models.Index(fields=['is_read'], name='tickets_not_is_read_idx'),
            models.Index(fields=['recipient', '-created_at'], name='tickets_not_recip_creat_idx'),
            models.Index(fields=['category', 'is_read'], name='tickets_not_cat_read_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.title} - {self.recipient.get_full_name()}"


class TicketActivityLog(models.Model):
    """Activity log model for tracking all changes to tickets"""
    ACTION_CHOICES = [
        ('created', _('ایجاد شد')),
        ('status_changed', _('تغییر وضعیت')),
        ('priority_changed', _('تغییر اولویت')),
        ('assigned', _('تخصیص داده شد')),
        ('unassigned', _('تخصیص حذف شد')),
        ('replied', _('پاسخ اضافه شد')),
        ('updated', _('بروزرسانی شد')),
        ('access_approved', _('دسترسی تایید شد')),
        ('access_rejected', _('دسترسی رد شد')),
        ('attachment_added', _('پیوست اضافه شد')),
        ('viewed', _('مشاهده شد')),
    ]
    
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='activity_logs', verbose_name=_('تیکت'))
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ticket_activities', verbose_name=_('کاربر'))
    action = models.CharField(_('عمل'), max_length=50, choices=ACTION_CHOICES)
    description = models.TextField(_('توضیحات'), help_text=_('توضیحات تغییرات'))
    old_value = models.CharField(_('مقدار قبلی'), max_length=255, blank=True, null=True)
    new_value = models.CharField(_('مقدار جدید'), max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    
    # Optional reference to related objects
    reply = models.ForeignKey(Reply, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_logs', verbose_name=_('پاسخ مرتبط'))
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = _("لاگ فعالیت تیکت")
        verbose_name_plural = _("لاگ‌های فعالیت تیکت")
        indexes = [
            models.Index(fields=['ticket', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_action_display()} - تیکت #{self.ticket.id} - {self.created_at}"

# SMTP/Email configuration managed in-app by IT Manager
class EmailConfig(models.Model):
    """Holds SMTP configuration for sending system emails, editable by IT Manager."""
    host = models.CharField(_('هاست SMTP'), max_length=255, default='')
    port = models.PositiveIntegerField(_('پورت'), default=587)
    use_tls = models.BooleanField(_('استفاده از TLS'), default=True)
    use_ssl = models.BooleanField(_('استفاده از SSL'), default=False)
    username = models.EmailField(_('ایمیل فرستنده'), blank=True, null=True)
    password = models.CharField(_('رمز عبور ایمیل'), max_length=255, blank=True, null=True)
    from_name = models.CharField(_('نام نمایشی فرستنده'), max_length=255, blank=True, null=True)
    updated_at = models.DateTimeField(_('آخرین بروزرسانی'), auto_now=True)

    class Meta:
        verbose_name = _('تنظیمات ایمیل')
        verbose_name_plural = _('تنظیمات ایمیل')

    def __str__(self) -> str:
        return self.username or 'Email Config'

    @classmethod
    def get_active(cls):
        """Return the single active config or a default unsaved instance."""
        cfg = cls.objects.first()
        if cfg:
            return cfg
        return cls(host='', port=587, use_tls=True, use_ssl=False)

# Signal removed: Manual State Control - Status changes must be explicit user actions
# Assignment operations no longer automatically change ticket status

class TicketCategory(models.Model):
    """
    Department-specific ticket categories.
    Each service provider department can define its own categories.
    """
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name='ticket_categories',
        verbose_name=_('بخش'),
        help_text=_('بخش ارائه‌دهنده خدمات مربوطه')
    )
    
    name = models.CharField(
        _('نام دسته‌بندی'),
        max_length=100,
        help_text=_('نام دسته‌بندی تیکت (مثال: سخت‌افزار، شبکه، درخواست دسترسی)')
    )
    
    description = models.TextField(
        _('توضیحات'),
        blank=True,
        null=True,
        help_text=_('توضیحات اختیاری برای این دسته‌بندی')
    )
    
    is_active = models.BooleanField(
        _('فعال'),
        default=True,
        help_text=_('در صورت غیرفعال بودن، این دسته‌بندی در فرم ایجاد تیکت نمایش داده نمی‌شود')
    )
    
    sort_order = models.IntegerField(
        _('ترتیب نمایش'),
        default=0,
        help_text=_('ترتیب نمایش دسته‌بندی در لیست (اعداد کمتر در ابتدا نمایش داده می‌شوند)')
    )
    
    requires_supervisor_approval = models.BooleanField(
        _('نیاز به تایید سرپرست'),
        default=False,
        help_text=_('در صورت فعال بودن، تیکت‌های این دسته‌بندی نیاز به تایید سرپرست بخش ایجادکننده دارند')
    )
    
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    updated_at = models.DateTimeField(_('تاریخ بروزرسانی'), auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_categories',
        verbose_name=_('ایجاد شده توسط')
    )
    
    class Meta:
        verbose_name = _("دسته‌بندی تیکت")
        verbose_name_plural = _("دسته‌بندی‌های تیکت")
        ordering = ['department', 'sort_order', 'name']
        unique_together = [['department', 'name']]
        indexes = [
            models.Index(fields=['department', 'is_active']),
            models.Index(fields=['department', 'sort_order']),
        ]
    
    def __str__(self):
        # Safely access department to avoid RelatedObjectDoesNotExist during form validation
        if self.department_id:
            try:
                return f"{self.department.name} - {self.name}"
            except (AttributeError, ValueError):
                return f"{self.name}"
        return f"{self.name}"
    
    def clean(self):
        """Validate that department is a service provider"""
        # Use department_id to avoid RelatedObjectDoesNotExist when department is not yet set
        # This allows form validation to pass before the view sets the department
        if self.department_id is not None:
            # Only validate if department is set (will be set by view before final save)
            try:
                department = self.department
                if department and not department.can_receive_tickets:
                    raise ValidationError({
                        'department': _('فقط بخش‌هایی که می‌توانند تیکت دریافت کنند می‌توانند دسته‌بندی داشته باشند.')
                    })
            except (AttributeError, ValueError):
                # Department not set yet or invalid - this is OK during form validation
                # The view will set it before final save
                pass
    
    def save(self, *args, **kwargs):
        """Save the category with validation"""
        # Only run full_clean if department_id is set
        # This prevents RelatedObjectDoesNotExist during form.save(commit=False)
        # The view will set department before calling save(), so validation will run then
        if hasattr(self, 'department_id') and self.department_id is not None:
            self.full_clean()  # Run validation (department should be set by view before calling save())
        super().save(*args, **kwargs)

class InventoryElement(models.Model):
    """
    Modular inventory system element model.
    Elements can have specifications and sub-elements (hierarchical structure).
    Example: A computer case (element) with IP/MAC (specifications) and mouse/keyboard (sub-elements).
    """
    name = models.CharField(_('نام'), max_length=200, help_text=_('نام عنصر موجودی (مثال: کیس کامپیوتر)'))
    description = models.TextField(_('توضیحات'), blank=True, null=True, help_text=_('توضیحات اضافی درباره این عنصر'))
    element_type = models.CharField(
        _('نوع عنصر'),
        max_length=100,
        help_text=_('نوع عنصر (مثال: کامپیوتر، مانیتور، ماوس، کیبورد)')
    )
    
    # User association
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='inventory_elements',
        verbose_name=_('اختصاص داده شده به'),
        help_text=_('کاربری که این عنصر به او اختصاص داده شده است')
    )
    
    # Hierarchical structure: elements can have parent elements (sub-elements)
    parent_element = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        related_name='sub_elements',
        null=True,
        blank=True,
        verbose_name=_('عنصر والد'),
        help_text=_('اگر این عنصر زیرمجموعه عنصر دیگری است، آن را انتخاب کنید')
    )
    
    # Status and metadata
    is_active = models.BooleanField(_('فعال'), default=True)
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    updated_at = models.DateTimeField(_('تاریخ بروزرسانی'), auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_inventory_elements',
        verbose_name=_('ایجاد شده توسط')
    )
    
    class Meta:
        verbose_name = _("عنصر موجودی")
        verbose_name_plural = _("عناصر موجودی")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['assigned_to', 'is_active']),
            models.Index(fields=['parent_element']),
        ]
    
    def __str__(self):
        if self.parent_element:
            return f"{self.name} ({self.parent_element.name})"
        return f"{self.name} - {self.assigned_to.get_full_name()}"
    
    def get_full_path(self):
        """Get full hierarchical path of the element"""
        path = [self.name]
        parent = self.parent_element
        while parent:
            path.insert(0, parent.name)
            parent = parent.parent_element
        return " > ".join(path)
    
    def get_all_sub_elements(self):
        """Get all sub-elements recursively"""
        sub_elements = list(self.sub_elements.filter(is_active=True))
        for sub in sub_elements:
            sub_elements.extend(sub.get_all_sub_elements())
        return sub_elements
    
    def clean(self):
        """Validate that element is not its own parent"""
        if self.parent_element and self.parent_element.pk == self.pk:
            raise ValidationError(_('عنصر نمی‌تواند والد خودش باشد.'))

class ElementSpecification(models.Model):
    """
    Specifications/attributes for inventory elements.
    Flexible key-value pairs for storing various properties (IP, MAC, serial number, etc.)
    """
    element = models.ForeignKey(
        InventoryElement,
        on_delete=models.CASCADE,
        related_name='specifications',
        verbose_name=_('عنصر'),
        help_text=_('عنصر موجودی که این مشخصه به آن تعلق دارد')
    )
    key = models.CharField(
        _('کلید'),
        max_length=100,
        help_text=_('نام مشخصه (مثال: IP، MAC، شماره سریال)')
    )
    value = models.TextField(
        _('مقدار'),
        help_text=_('مقدار مشخصه')
    )
    description = models.TextField(
        _('توضیحات'),
        blank=True,
        null=True,
        help_text=_('توضیحات اضافی درباره این مشخصه')
    )
    
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    updated_at = models.DateTimeField(_('تاریخ بروزرسانی'), auto_now=True)
    
    class Meta:
        verbose_name = _("مشخصه عنصر")
        verbose_name_plural = _("مشخصات عناصر")
        ordering = ['key']
        unique_together = [['element', 'key']]  # Each element can only have one specification per key
    
    def __str__(self):
        return f"{self.element.name} - {self.key}: {self.value}"


class CalendarDay(models.Model):
    """Model to cache Jalali calendar data from external API"""
    year = models.IntegerField(_('سال'), db_index=True)
    month = models.IntegerField(_('ماه'), db_index=True)
    day = models.IntegerField(_('روز'), db_index=True)
    solar_date = models.CharField(_('تاریخ شمسی'), max_length=20, help_text=_('فرمت: YYYY/MM/DD'))
    gregorian_date = models.CharField(_('تاریخ میلادی'), max_length=20, help_text=_('فرمت: YYYY-MM-DD'))
    is_holiday = models.BooleanField(_('تعطیل رسمی'), default=False)
    events_json = models.JSONField(_('رویدادها'), default=list, help_text=_('آرایه رویدادهای فارسی برای این روز'))
    created_at = models.DateTimeField(_('تاریخ ایجاد'), auto_now_add=True)
    updated_at = models.DateTimeField(_('تاریخ بروزرسانی'), auto_now=True)
    
    class Meta:
        verbose_name = _("روز تقویم")
        verbose_name_plural = _("روزهای تقویم")
        unique_together = [['year', 'month', 'day']]
        indexes = [
            models.Index(fields=['year', 'month']),
        ]
        ordering = ['year', 'month', 'day']
    
    def __str__(self):
        return f"{self.year}/{self.month:02d}/{self.day:02d}" 