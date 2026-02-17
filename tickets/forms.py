from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.db.models import Q, Count
from .models import Ticket, Reply, User, Department, EmailConfig, Branch, InventoryElement, ElementSpecification, TicketTask, TaskReply, TicketCategory, DeadlineExtensionRequest
from .validators import validate_iranian_national_id, validate_iranian_mobile_number
from .utils import normalize_national_id, normalize_employee_code, log_authentication_attempt
import os
import mimetypes
import logging

logger = logging.getLogger(__name__)


class WarehouseAwareModelChoiceField(forms.ModelChoiceField):
    """Custom ModelChoiceField that allows 'warehouse' as a special value"""
    
    def to_python(self, value):
        # Allow 'warehouse' to pass through without queryset validation
        if value == 'warehouse' or value == 'warehouse':
            return 'warehouse'
        return super().to_python(value)
    
    def validate(self, value):
        # Skip validation if value is 'warehouse'
        if value == 'warehouse':
            return
        super().validate(value)

class CustomAuthenticationForm(AuthenticationForm):
    """Custom authentication form using national ID and employee code"""
    national_id = forms.CharField(
        label=_('کد ملی'),
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('کد ملی خود را وارد کنید'),
            'required': True
        })
    )
    employee_code = forms.CharField(
        label=_('کد کارمندی'),
        max_length=4,
        min_length=4,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('کد کارمندی خود را وارد کنید'),
            'required': True,
            'pattern': '\\d{4}',
            'inputmode': 'numeric',
            'maxlength': '4',
        })
    )
    username = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )
    password = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )
    
    def clean(self):
        national_id = self.cleaned_data.get('national_id')
        employee_code = self.cleaned_data.get('employee_code')
        
        if national_id and employee_code:
            # Normalize identifiers to handle Persian/Arabic numerals
            normalized_national_id = normalize_national_id(national_id)
            normalized_employee_code = normalize_employee_code(employee_code)
            
            # Log normalization if conversion occurred
            if national_id != normalized_national_id or employee_code != normalized_employee_code:
                logger.debug(
                    f"Login form: Normalized National ID from '{national_id}' to '{normalized_national_id}', "
                    f"Employee Code from '{employee_code}' to '{normalized_employee_code}'"
                )
            
            # Update cleaned_data with normalized values
            self.cleaned_data['national_id'] = normalized_national_id
            self.cleaned_data['employee_code'] = normalized_employee_code
            
            # Try to authenticate using normalized national_id and employee_code
            user = authenticate(request=self.request, national_id=normalized_national_id, employee_code=normalized_employee_code)
            if user is None:
                # Log authentication failure
                log_authentication_attempt(
                    national_id=normalized_national_id,
                    employee_code=normalized_employee_code,
                    success=False,
                    error_type='invalid_credentials',
                    error_message='Incorrect National ID or Employee Code'
                )
                raise ValidationError(_('کد ملی یا کد کارمندی اشتباه است.'))
            if not user.is_active:
                # Log inactive user attempt
                log_authentication_attempt(
                    national_id=normalized_national_id,
                    employee_code=normalized_employee_code,
                    success=False,
                    error_type='inactive_user',
                    error_message='User account is inactive',
                    user_id=user.id
                )
                raise ValidationError(_('این حساب کاربری غیرفعال است.'))
            self.user_cache = user
        return self.cleaned_data

class TicketForm(forms.ModelForm):
    """Form for creating and editing tickets"""
    class Meta:
        model = Ticket
        fields = ['title', 'description', 'category', 'ticket_category', 'priority', 'target_department', 'branch', 'attachment']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('عنوان تیکت را وارد کنید')
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': _('توضیحات تیکت را وارد کنید')
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'ticket_category': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_ticket_category'
            }),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'target_department': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_target_department'
            }),
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'attachment': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,.pdf,.doc,.docx'})
        }
        labels = {
            'title': _('عنوان'),
            'description': _('توضیحات'),
            'category': _('دسته‌بندی (قدیمی)'),
            'ticket_category': _('دسته‌بندی'),
            'priority': _('اولویت'),
            'target_department': _('بخش هدف'),
            'branch': _('شعبه'),
            'attachment': _('فایل پیوست')
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filter departments to only show those that can receive tickets
        if 'target_department' in self.fields:
            self.fields['target_department'].queryset = Department.objects.filter(
                is_active=True,
                can_receive_tickets=True
            ).order_by('name')
        
        # Filter branches to only show active ones
        if 'branch' in self.fields:
            self.fields['branch'].queryset = Branch.objects.filter(is_active=True).order_by('name')
        
        # Pre-fill branch, department, and category based on user's department (only for new tickets)
        if user and not self.instance.pk and not self.data:
            user_dept = getattr(user, 'department', None)
            if user_dept:
                # Pre-fill branch if user's department has a branch
                if user_dept.branch and 'branch' in self.fields:
                    self.initial['branch'] = user_dept.branch.id
                
                # Pre-fill department if user's department can receive tickets
                if user_dept.can_receive_tickets and 'target_department' in self.fields:
                    self.initial['target_department'] = user_dept.id
        
        # Initialize ticket_category field
        if 'ticket_category' in self.fields:
            # Determine which department to use for category queryset
            target_dept = None
            
            # For POST requests: use department from form data, or when editing from instance (department field may be hidden)
            if self.data and 'target_department' in self.data:
                target_department_id = self.data.get('target_department')
                if target_department_id:
                    try:
                        target_department_id = int(target_department_id)
                        target_dept = Department.objects.get(id=target_department_id, can_receive_tickets=True)
                    except (Department.DoesNotExist, ValueError, TypeError):
                        pass
            # When editing: use ticket's department (for GET, or for POST when department field is hidden)
            if not target_dept and self.instance and self.instance.pk:
                ticket_dept = getattr(self.instance, 'target_department', None)
                if ticket_dept and getattr(ticket_dept, 'can_receive_tickets', False):
                    target_dept = ticket_dept
            # For GET (new ticket creation), use user's department if available
            if not target_dept and not self.data and user:
                user_dept = getattr(user, 'department', None)
                if user_dept and user_dept.can_receive_tickets:
                    target_dept = user_dept
            
            # Set queryset and initial value based on target department
            current_cat = getattr(self.instance, 'ticket_category', None) if self.instance and self.instance.pk else None
            
            if target_dept:
                # Base: all active categories for this department
                qs = TicketCategory.objects.filter(
                    department=target_dept,
                    is_active=True
                )
                # When editing: always include current ticket's category so the choice is valid
                # (e.g. if it was deactivated, or belongs to another department)
                if current_cat:
                    qs = TicketCategory.objects.filter(
                        Q(department=target_dept, is_active=True) | Q(pk=current_cat.pk)
                    )
                    # Order: current category first, then others by sort_order and name
                    from django.db.models import Case, When, IntegerField
                    qs = qs.annotate(
                        is_current=Case(
                            When(pk=current_cat.pk, then=0),
                            default=1,
                            output_field=IntegerField()
                        )
                    ).order_by('is_current', 'sort_order', 'name')
                else:
                    # For new tickets, just order by sort_order and name
                    qs = qs.order_by('sort_order', 'name')
                self.fields['ticket_category'].queryset = qs
                self.fields['ticket_category'].required = True
                
                # Pre-fill with first available category (only for new tickets)
                if not self.instance.pk and not self.data:
                    first_category = self.fields['ticket_category'].queryset.first()
                    if first_category:
                        self.initial['ticket_category'] = first_category.id
            else:
                # No target department: when editing, show at least current category so choice is valid
                if current_cat:
                    self.fields['ticket_category'].queryset = TicketCategory.objects.filter(
                        pk=current_cat.pk
                    ).order_by('sort_order', 'name')
                    self.fields['ticket_category'].required = False
                else:
                    self.fields['ticket_category'].queryset = TicketCategory.objects.none()
                    self.fields['ticket_category'].required = False
            
            # Remove disabled attribute - fields should be editable from start
            if 'disabled' in self.fields['ticket_category'].widget.attrs:
                del self.fields['ticket_category'].widget.attrs['disabled']
            
            # Show "Requires Supervisor Approval" on creation screen for each category option
            def ticket_category_label(obj):
                if getattr(obj, 'requires_supervisor_approval', False):
                    return f"{obj.name} ({_('نیاز به تایید سرپرست')})"
                return obj.name
            self.fields['ticket_category'].label_from_instance = ticket_category_label
    
    def clean_ticket_category(self):
        """Dynamically validate ticket_category based on selected department"""
        ticket_category = self.cleaned_data.get('ticket_category')
        
        # If no category selected, check if it should be required
        if not ticket_category:
            target_department_id = self.data.get('target_department')
            if target_department_id:
                try:
                    target_department_id = int(target_department_id)
                    dept = Department.objects.get(id=target_department_id, can_receive_tickets=True)
                    # Check if department has categories - if yes, category should be required
                    if TicketCategory.objects.filter(department=dept, is_active=True).exists():
                        raise forms.ValidationError(_('لطفاً دسته‌بندی را انتخاب کنید.'))
                except (Department.DoesNotExist, ValueError, TypeError):
                    pass
            return None
        
        # Category object is already validated by ModelChoiceField (queryset was updated in __init__)
        # Additional validation (category belongs to department) is done in clean() method
        return ticket_category
    
    def clean(self):
        cleaned_data = super().clean()
        target_department = cleaned_data.get('target_department')
        ticket_category = cleaned_data.get('ticket_category')
        
        # Validate category belongs to selected department
        if ticket_category and target_department:
            if ticket_category.department != target_department:
                raise forms.ValidationError({
                    'ticket_category': _(
                        'دسته‌بندی انتخاب شده متعلق به بخش انتخاب شده نیست. '
                        'لطفاً دسته‌بندی مناسب را انتخاب کنید.'
                    )
                })
        
        # Validate department can receive tickets (if category is provided)
        if ticket_category and target_department:
            if not target_department.can_receive_tickets:
                raise forms.ValidationError({
                    'target_department': _(
                        'بخش انتخاب شده نمی‌تواند تیکت دریافت کند.'
                    )
                })
        
        return cleaned_data

class TaskTicketForm(forms.ModelForm):
    """Form for creating task tickets (IT Manager only)"""
    class Meta:
        model = Ticket
        fields = ['title', 'description', 'category', 'priority', 'assigned_to', 'attachment']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('عنوان تیکت را وارد کنید')
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': _('توضیحات تیکت را وارد کنید')
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'assigned_to': forms.Select(attrs={'class': 'form-select'}),
            'attachment': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,.pdf,.doc,.docx'})
        }
        labels = {
            'title': _('عنوان'),
            'description': _('توضیحات'),
            'category': _('دسته‌بندی'),
            'priority': _('اولویت'),
            'assigned_to': _('تخصیص به'),
            'attachment': _('فایل پیوست')
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filter assigned_to to only show technicians
        if 'assigned_to' in self.fields:
                self.fields['assigned_to'].queryset = User.objects.filter(
                role='technician',
                is_active=True
                ).order_by('first_name', 'last_name')

class ReplyForm(forms.ModelForm):
    """Form for replying to tickets"""
    class Meta:
        model = Reply
        fields = ['content', 'is_private', 'attachment']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': _('پاسخ خود را وارد کنید')
            }),
            'is_private': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'attachment': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,.pdf,.doc,.docx'})
        }
        labels = {
            'content': _('پاسخ'),
            'is_private': _('پاسخ محرمانه'),
            'attachment': _('فایل پیوست')
        }

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        if attachment:
            # Check file size (max 10MB)
            if attachment.size > 10 * 1024 * 1024:
                raise ValidationError(_('حجم فایل نباید بیشتر از 10 مگابایت باشد.'))
            
            # Check file type
            allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'application/pdf', 
                           'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
            file_type, _ = mimetypes.guess_type(attachment.name)
            if file_type not in allowed_types:
                raise ValidationError(_('نوع فایل مجاز نیست. فقط تصاویر، PDF و Word مجاز است.'))
        
        return attachment
    
    def save(self, commit=True):
        """Override save to track user for activity logging"""
        instance = super().save(commit=False)
        # Set user for activity logging (will be set by view)
        if hasattr(self, 'user') and self.user:
            instance._activity_user = self.user
        if commit:
            instance.save()
        return instance

class TicketStatusForm(forms.ModelForm):
    """Form for updating ticket status and assignment"""
    class Meta:
        model = Ticket
        fields = ['status', 'assigned_to', 'priority']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'assigned_to': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'})
        }
        labels = {
            'status': _('وضعیت'),
            'assigned_to': _('تخصیص به'),
            'priority': _('اولویت')
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        ticket = kwargs.pop('ticket', None)
        super().__init__(*args, **kwargs)
        
        # Make priority optional - it will default to current value if not provided
        if 'priority' in self.fields:
            self.fields['priority'].required = False
            # Set initial value to current instance priority if available
            if self.instance and hasattr(self.instance, 'priority') and self.instance.priority:
                self.fields['priority'].initial = self.instance.priority
        
        # Exclude admin superuser from assignment
        from .admin_security import get_admin_superuser_queryset_filter
        admin_filter = get_admin_superuser_queryset_filter()
        
        # Filter assigned_to based on user role
        if 'assigned_to' in self.fields:
            if user and user.role == 'it_manager':
                # IT managers can assign to technicians
                self.fields['assigned_to'].queryset = User.objects.filter(
                    role='technician',
                    is_active=True
                ).filter(admin_filter).order_by('first_name', 'last_name')
            elif user and user.role == 'technician':
                # Technicians can only see themselves
                self.fields['assigned_to'].queryset = User.objects.filter(id=user.id)
            else:
                # For other roles, show empty queryset (will be hidden if needed)
                self.fields['assigned_to'].queryset = User.objects.none()
        
        # Check if user is ticket_responder - they can change status but not reassign
        # Use self.instance if ticket parameter is not provided (instance is set by ModelForm.__init__)
        try:
            ticket_obj = ticket if ticket else getattr(self, 'instance', None)
            if user and user.role == 'employee' and ticket_obj and user.department:
                # Check if user is a ticket responder for the ticket's target department OR assigned to them
                is_ticket_responder_for_target = (hasattr(ticket_obj, 'target_department') and 
                                                  ticket_obj.target_department and 
                                                  hasattr(ticket_obj.target_department, 'ticket_responder') and
                                                  ticket_obj.target_department.ticket_responder == user)
                is_ticket_responder_for_assigned = (hasattr(ticket_obj, 'assigned_to') and 
                                                    ticket_obj.assigned_to == user and
                                                    user.department.can_receive_tickets and
                                                    user.department.ticket_responder == user)
                
                if is_ticket_responder_for_target or is_ticket_responder_for_assigned:
                    # Ticket responder can change status but not reassign or change priority
                    if 'assigned_to' in self.fields:
                        self.fields['assigned_to'].widget = forms.HiddenInput()
                        self.fields['assigned_to'].required = False
                        # Set the queryset to include the current assigned_to value to avoid validation errors
                        if ticket_obj and hasattr(ticket_obj, 'assigned_to') and ticket_obj.assigned_to:
                            self.fields['assigned_to'].queryset = User.objects.filter(id=ticket_obj.assigned_to.id)
                    # Hide priority field for ticket responders - they should only change status
                    if 'priority' in self.fields:
                        self.fields['priority'].widget = forms.HiddenInput()
                        self.fields['priority'].required = False
        except (AttributeError, TypeError):
            # Silently handle any attribute errors
            pass
    
    def save(self, commit=True):
        """Override save to preserve priority and assigned_to if not provided"""
        instance = super().save(commit=False)
        # If priority is not provided in cleaned_data or is empty, keep the current value
        if 'priority' in self.fields and ('priority' not in self.cleaned_data or not self.cleaned_data.get('priority')):
            if self.instance and hasattr(self.instance, 'priority') and self.instance.priority:
                instance.priority = self.instance.priority
        # If assigned_to is not provided in cleaned_data or is empty, keep the current value
        if 'assigned_to' in self.fields and ('assigned_to' not in self.cleaned_data or not self.cleaned_data.get('assigned_to')):
            if self.instance and hasattr(self.instance, 'assigned_to'):
                instance.assigned_to = self.instance.assigned_to
        
        # Set user for activity logging
        if hasattr(self, 'user') and self.user:
            instance._activity_user = self.user
        
        if commit:
            instance.save()
        return instance

class TicketTaskForm(forms.ModelForm):
    """Form for creating ticket tasks (IT Manager or Supervisor)
    
    For Supervisors: Departments and employees are filtered to only show
    departments they manage and employees from those departments.
    """
    # Deadline field (Jalali date and time combined: "YYYY/MM/DD HH:MM")
    deadline_date = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('برای انتخاب تاریخ و زمان کلیک کنید'),
            'id': 'deadline-date-input',
            'readonly': True,  # Will be set by date picker
            'autocomplete': 'off',  # Prevent browser autocomplete
        }),
        label=_('تاریخ و زمان مهلت انجام')
    )
    
    class Meta:
        model = TicketTask
        fields = ['title', 'description', 'priority', 'department', 'assigned_to']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('عنوان تسک را وارد کنید')
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': _('توضیحات تسک را وارد کنید')
            }),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'assigned_to': forms.Select(attrs={'class': 'form-select'})
        }
        labels = {
            'title': _('عنوان'),
            'description': _('توضیحات'),
            'priority': _('اولویت'),
            'department': _('بخش'),
            'assigned_to': _('تخصیص به')
        }

    def __init__(self, *args, **kwargs):
        # #region agent log - Hypothesis E: Form init entry
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
        
        user = kwargs.pop('user', None)
        log_debug('E', 'tickets/forms.py:321', 'TicketTaskForm __init__ entry', {
            'has_user': user is not None,
            'user_id': user.id if user else None,
            'user_pk': user.pk if user else None
        })
        
        super().__init__(*args, **kwargs)
        
        # CRITICAL: Ensure user object is fresh from database to get latest relationships
        if user and user.pk:
            log_debug('E', 'tickets/forms.py:332', 'Before refresh_from_db', {
                'user_role': user.role,
                'department_role': getattr(user, 'department_role', None)
            })
            user.refresh_from_db()
            log_debug('E', 'tickets/forms.py:335', 'After refresh_from_db', {
                'user_role': user.role,
                'department_role': getattr(user, 'department_role', None)
            })
            # Prefetch M2M relationships to ensure they're loaded
            if hasattr(user, 'supervised_departments'):
                # Force evaluation of M2M relationship
                m2m_list = list(user.supervised_departments.all())
                log_debug('E', 'tickets/forms.py:340', 'M2M prefetch result', {
                    'm2m_count': len(m2m_list),
                    'm2m_ids': [d.id for d in m2m_list]
                })
        
        # Determine if user is a supervisor (senior/manager)
        is_supervisor = user and user.role == 'employee' and user.department_role in ['senior', 'manager']
        is_it_manager = user and user.role == 'it_manager'
        
        # Task creator: any department that has this user as task_creator (may be different from user.department)
        task_creator_departments = Department.objects.filter(
            task_creator=user,
            is_active=True,
            department_type='employee'
        ) if user else Department.objects.none()
        is_task_creator = user and user.role == 'employee' and task_creator_departments.exists()
        
        log_debug('B', 'tickets/forms.py:345', 'Form supervisor check', {
            'is_supervisor': is_supervisor,
            'is_it_manager': is_it_manager,
            'is_task_creator': is_task_creator,
            'task_creator_dept_ids': list(task_creator_departments.values_list('id', flat=True)) if is_task_creator else [],
            'user_role': user.role if user else None,
            'department_role': getattr(user, 'department_role', None) if user else None
        })
        
        # Make deadline fields mandatory for supervisors
        if is_supervisor:
            self.fields['deadline_date'].required = True
            # Deadline field is already combined (date + time), no separate time field
        
        # Initialize deadline fields from existing deadline if editing
        if self.instance and hasattr(self.instance, 'pk') and self.instance.pk:
            try:
                # Safely get deadline attribute (might not exist if migration not run)
                if hasattr(self.instance, 'deadline'):
                    deadline = self.instance.deadline
                    if deadline:
                        from .calendar_services.jalali_calendar import JalaliCalendarService
                        jalali_components = JalaliCalendarService.gregorian_to_jalali(deadline)
                        # Format as combined date and time: "YYYY/MM/DD HH:MM"
                        date_str = JalaliCalendarService.format_jalali_date(
                            jalali_components['year'],
                            jalali_components['month'],
                            jalali_components['day']
                        )
                        time_str = f"{jalali_components['hour']:02d}:{jalali_components['minute']:02d}"
                        self.initial['deadline_date'] = f"{date_str} {time_str}"
            except (AttributeError, TypeError, ValueError, ImportError) as e:
                # If deadline conversion fails or module not available, just skip initialization
                # This prevents crashes if calendar service is unavailable or deadline field doesn't exist yet
                pass
        
        # Filter departments based on user role/permissions
        if 'department' in self.fields:
            if is_supervisor:
                # For supervisors: only show departments they manage
                # CRITICAL: Call get_supervised_departments() which queries database directly
                supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
                log_debug('A', 'tickets/forms.py:352', 'Supervised departments in form', {
                    'supervised_depts_count': len(supervised_depts),
                    'supervised_dept_ids': [d.id for d in supervised_depts],
                    'supervised_dept_names': [d.name for d in supervised_depts]
                })
                if supervised_depts:
                    # Get department IDs from supervised departments
                    supervised_dept_ids = [dept.id for dept in supervised_depts]
                    dept_queryset = Department.objects.filter(
                        id__in=supervised_dept_ids,
                        is_active=True,
                        department_type='employee'
                    ).order_by('name')
                    log_debug('A', 'tickets/forms.py:361', 'Department queryset result', {
                        'queryset_count': dept_queryset.count(),
                        'queryset_ids': list(dept_queryset.values_list('id', flat=True)),
                        'queryset_names': list(dept_queryset.values_list('name', flat=True))
                    })
                    self.fields['department'].queryset = dept_queryset
                else:
                    # Supervisor has no assigned departments - show empty queryset
                    log_debug('A', 'tickets/forms.py:368', 'No supervised departments - empty queryset', {})
                    self.fields['department'].queryset = Department.objects.none()
            elif is_it_manager:
                # For IT managers: show all active employee departments
                self.fields['department'].queryset = Department.objects.filter(
                    is_active=True,
                    department_type='employee'
                ).order_by('name')
            elif is_task_creator:
                # For task creators: show only departments where they are explicitly task_creator
                log_debug('A', 'tickets/forms.py:task_creator', 'Task creator departments in form', {
                    'task_creator_dept_ids': list(task_creator_departments.values_list('id', flat=True)),
                    'task_creator_dept_names': list(task_creator_departments.values_list('name', flat=True))
                })
                self.fields['department'].queryset = task_creator_departments.order_by('name')
            else:
                # Other users: show empty (shouldn't reach here due to view restriction)
                self.fields['department'].queryset = Department.objects.none()
        
        # Determine which department to use for employee queryset
        department = None
        
        # If editing an existing task, use its department
        if self.instance and self.instance.pk and self.instance.department:
            department = self.instance.department
        # For POST requests, use the selected department
        elif self.data and 'department' in self.data:
            department_id = self.data.get('department')
            if department_id:
                try:
                    department = Department.objects.get(id=department_id, is_active=True)
                except Department.DoesNotExist:
                    department = None
        
        # Update assigned_to queryset based on department AND supervisor restrictions
        if 'assigned_to' in self.fields:
            if department:
                # Start with employees from the selected department (including supervisors/senior/manager)
                employee_queryset = User.objects.filter(
                    department=department,
                    is_active=True,
                    role='employee'
                )
                # Allow assigning to department supervisor (سرپرست بخش) - no exclusion of senior/manager

                # Supervisors and task creators must not be able to assign tasks to themselves
                if (is_supervisor or is_task_creator) and user and user.id:
                    employee_queryset = employee_queryset.exclude(id=user.id)

                # Additional restriction for supervisors: ensure department is in their managed departments
                if is_supervisor:
                    # CRITICAL: Query fresh from database to ensure we have latest relationships
                    supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
                    supervised_dept_ids = [dept.id for dept in supervised_depts]
                    log_debug('C', 'tickets/forms.py:395', 'Employee filtering check', {
                        'selected_dept_id': department.id,
                        'supervised_dept_ids': supervised_dept_ids,
                        'dept_in_supervised': department.id in supervised_dept_ids,
                        'employee_count_before_filter': employee_queryset.count()
                    })
                    if department.id in supervised_dept_ids:
                        # Department is supervised by this user - show employees (excluding the supervisor themselves)
                        final_employee_queryset = employee_queryset.order_by('first_name', 'last_name')
                        log_debug('C', 'tickets/forms.py:402', 'Employee queryset result', {
                            'employee_count': final_employee_queryset.count(),
                            'employee_ids': list(final_employee_queryset.values_list('id', flat=True))
                        })
                        self.fields['assigned_to'].queryset = final_employee_queryset
                    else:
                        # Department not supervised - show empty (shouldn't happen due to department filter, but safety check)
                        log_debug('C', 'tickets/forms.py:408', 'Department not in supervised - empty queryset', {
                            'selected_dept_id': department.id,
                            'supervised_dept_ids': supervised_dept_ids
                        })
                        self.fields['assigned_to'].queryset = User.objects.none()
                elif is_task_creator:
                    # For task creators: allow employees only in departments where they are task_creator
                    allowed_dept_ids = list(task_creator_departments.values_list('id', flat=True))
                    log_debug('C', 'tickets/forms.py:task_creator_employee', 'Task creator employee filtering check', {
                        'selected_dept_id': department.id,
                        'allowed_dept_ids': allowed_dept_ids,
                        'dept_allowed': department.id in allowed_dept_ids,
                        'employee_count_before_filter': employee_queryset.count()
                    })
                    if department.id in allowed_dept_ids:
                        final_employee_queryset = employee_queryset.order_by('first_name', 'last_name')
                        log_debug('C', 'tickets/forms.py:task_creator_employee_result', 'Task creator employee queryset result', {
                            'employee_count': final_employee_queryset.count(),
                            'employee_ids': list(final_employee_queryset.values_list('id', flat=True))
                        })
                        self.fields['assigned_to'].queryset = final_employee_queryset
                    else:
                        log_debug('C', 'tickets/forms.py:task_creator_employee_empty', 'Department not allowed for task creator - empty queryset', {
                            'selected_dept_id': department.id,
                            'allowed_dept_ids': allowed_dept_ids
                        })
                        self.fields['assigned_to'].queryset = User.objects.none()
                else:
                    # IT manager - show all employees from selected department
                    self.fields['assigned_to'].queryset = employee_queryset.order_by('first_name', 'last_name')
            else:
                # Initially empty - will be populated via JavaScript based on department selection
                self.fields['assigned_to'].queryset = User.objects.none()
            self.fields['assigned_to'].required = True
    
    def clean_assigned_to(self):
        """Validate that the assigned user is from the selected department and supervisor has access"""
        assigned_to = self.cleaned_data.get('assigned_to')
        department = self.cleaned_data.get('department')
        
        if assigned_to and department:
            # Check if the assigned user is actually from the selected department
            if assigned_to.department != department:
                raise ValidationError(_('کاربر انتخاب شده باید از بخش انتخاب شده باشد.'))
            
            # Check if the user is an active employee
            if assigned_to.role != 'employee' or not assigned_to.is_active:
                raise ValidationError(_('کاربر انتخاب شده باید یک کارمند فعال باشد.'))
        
        return assigned_to
    
    def clean(self):
        """Cross-field validation and deadline validation/conversion"""
        cleaned_data = super().clean()
        assigned_to = cleaned_data.get('assigned_to')
        department = cleaned_data.get('department')
        
        # Get user from form instance if available (set by view)
        user = getattr(self, '_user', None)
        is_supervisor = user and user.role == 'employee' and user.department_role in ['senior', 'manager']
        
        # Task creator in clean(): any active employee department that has this user as task_creator
        is_task_creator = False
        task_creator_departments = Department.objects.filter(
            task_creator=user,
            is_active=True,
            department_type='employee'
        ) if user else Department.objects.none()
        if user and user.role == 'employee' and task_creator_departments.exists():
            is_task_creator = True
        
        if is_supervisor:
            # Supervisors are not allowed to assign tasks to themselves
            if assigned_to and assigned_to.id == user.id:
                raise ValidationError({
                    'assigned_to': _('سرپرست نمی‌تواند تسک را به خود اختصاص دهد. لطفاً یکی از کارمندان زیرمجموعه را انتخاب کنید.')
                })

            # Supervisor validation: ensure department is in their supervised departments
            if department:
                supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
                supervised_dept_ids = [dept.id for dept in supervised_depts]
                
                if department.id not in supervised_dept_ids:
                    raise ValidationError({
                        'department': _('شما فقط می‌توانید تسک‌ها را به بخش‌های تحت سرپرستی خود اختصاص دهید.')
                    })
            
            # Ensure assigned employee is from a supervised department
            if assigned_to and assigned_to.department:
                supervised_depts = user.get_supervised_departments() if hasattr(user, 'get_supervised_departments') else []
                supervised_dept_ids = [dept.id for dept in supervised_depts]
                
                if assigned_to.department.id not in supervised_dept_ids:
                    raise ValidationError({
                        'assigned_to': _('شما فقط می‌توانید تسک‌ها را به کارمندان بخش‌های تحت سرپرستی خود اختصاص دهید.')
                    })
        
        elif is_task_creator:
            # Task creators are not allowed to assign tasks to themselves
            if assigned_to and assigned_to.id == user.id:
                raise ValidationError({
                    'assigned_to': _('شما نمی‌توانید تسک را به خود اختصاص دهید. لطفاً یکی از کارمندان بخش را انتخاب کنید.')
                })
            
            # Task creator validation: ensure department is one of their task_creator departments
            allowed_dept_ids = list(task_creator_departments.values_list('id', flat=True))
            if department and department.id not in allowed_dept_ids:
                raise ValidationError({
                    'department': _('شما فقط می‌توانید برای بخش‌هایی که به عنوان ایجادکننده تسک آن‌ها تعیین شده‌اید تسک ایجاد کنید.')
                })
            
            # Ensure assigned employee is from an allowed department
            if assigned_to and assigned_to.department and assigned_to.department.id not in allowed_dept_ids:
                raise ValidationError({
                    'assigned_to': _('شما فقط می‌توانید تسک‌ها را به کارمندان بخش‌هایی که برای آن‌ها ایجادکننده تسک هستید اختصاص دهید.')
                })
        
        # Validate deadline field (combined date and time: "YYYY/MM/DD HH:MM")
        deadline_date = cleaned_data.get('deadline_date')
        
        # Get user from form instance if available (set by view)
        user = getattr(self, '_user', None)
        is_supervisor = user and user.role == 'employee' and user.department_role in ['senior', 'manager']
        
        # For supervisors: deadline is mandatory
        if is_supervisor and not deadline_date:
            raise ValidationError({
                'deadline_date': _('برای سرپرستان، تعیین مهلت انجام تسک الزامی است.')
            })
        
        # Normalize, validate, and convert deadline if provided
        if deadline_date:
            from .calendar_services.jalali_calendar import JalaliCalendarService
            try:
                raw_value = str(deadline_date).strip()
                # Handle empty strings
                if not raw_value:
                    return cleaned_data
                
                # Collapse multiple spaces and normalize
                normalized = ' '.join(raw_value.split())
                parts = normalized.split(' ')
                if len(parts) < 1:
                    raise ValidationError({
                        'deadline_date': _('فرمت تاریخ و زمان صحیح نیست. از فرمت YYYY/MM/DD HH:MM استفاده کنید.')
                    })
                
                date_str = parts[0]
                time_str = parts[1] if len(parts) > 1 else '09:00'  # Default time if not provided
                
                # Parse date (Jalali format: YYYY/MM/DD)
                date_parts = date_str.split('/')
                if len(date_parts) != 3:
                    raise ValidationError({
                        'deadline_date': _('فرمت تاریخ صحیح نیست. از فرمت YYYY/MM/DD استفاده کنید (مثال: 1403/09/25).')
                    })
                
                try:
                    year = int(date_parts[0])
                    month = int(date_parts[1])
                    day = int(date_parts[2])
                except (ValueError, TypeError) as e:
                    raise ValidationError({
                        'deadline_date': _('تاریخ باید شامل اعداد باشد. از فرمت YYYY/MM/DD استفاده کنید (مثال: 1403/09/25).')
                    }) from e
                
                # Validate Jalali date ranges and format
                if year < 1300 or year > 1500 or month < 1 or month > 12 or day < 1 or day > 31:
                    raise ValidationError({
                        'deadline_date': _('محدوده تاریخ معتبر نیست. سال بین 1300-1500، ماه 1-12، روز 1-31.')
                    })
                
                # Validate Jalali date using service
                if not JalaliCalendarService.validate_jalali_date(year, month, day):
                    raise ValidationError({
                        'deadline_date': _('تاریخ وارد شده معتبر نیست. لطفاً تاریخ شمسی صحیح را وارد کنید.')
                    })
                
                # Parse time (format: HH:MM, 24-hour)
                time_parts = time_str.split(':')
                if len(time_parts) != 2:
                    raise ValidationError({
                        'deadline_date': _('فرمت زمان صحیح نیست. از فرمت HH:MM استفاده کنید (مثال: 14:30).')
                    })
                
                try:
                    hour = int(time_parts[0])
                    minute = int(time_parts[1])
                except (ValueError, TypeError) as e:
                    raise ValidationError({
                        'deadline_date': _('زمان باید شامل اعداد باشد. از فرمت HH:MM استفاده کنید (مثال: 14:30).')
                    }) from e
                
                # Validate time range (24-hour format)
                if hour < 0 or hour > 23:
                    raise ValidationError({
                        'deadline_date': _('ساعت باید بین 00 تا 23 باشد.')
                    })
                if minute < 0 or minute > 59:
                    raise ValidationError({
                        'deadline_date': _('دقیقه باید بین 00 تا 59 باشد.')
                    })
                
                # Convert Jalali to Gregorian once and store the datetime in cleaned_data
                converted_deadline = JalaliCalendarService.jalali_to_gregorian(
                    year, month, day, hour, minute
                )
                # Minimum allowed date is start of today (yesterday and before are not allowed)
                from django.utils import timezone
                now = timezone.now()
                start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
                if converted_deadline < start_of_today:
                    raise ValidationError({
                        'deadline_date': _('تاریخ و زمان مهلت نمی‌تواند قبل از امروز باشد. لطفاً از امروز به بعد را انتخاب کنید.')
                    })
                # If deadline is today, time must not be before now
                if converted_deadline.date() == now.date() and converted_deadline < now:
                    raise ValidationError({
                        'deadline_date': _('برای امروز نمی‌توانید ساعتی قبل از ساعت الان انتخاب کنید. لطفاً زمان فعلی یا بعد از آن را انتخاب کنید.')
                    })
                cleaned_data['deadline_converted'] = converted_deadline
            except ValidationError:
                # Re-raise ValidationError as-is
                raise
            except (ValueError, IndexError, AttributeError, TypeError) as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f'Error parsing deadline_date: {deadline_date}, error: {str(e)}')
                raise ValidationError({
                    'deadline_date': _('فرمت تاریخ و زمان صحیح نیست. از فرمت YYYY/MM/DD HH:MM استفاده کنید (مثال: 1403/09/25 14:30).')
                }) from e
        
        return cleaned_data
    
    def save(self, commit=True):
        """Override save to apply already-converted deadline datetime"""
        import logging
        logger = logging.getLogger(__name__)
        
        instance = super().save(commit=False)
        
        converted_deadline = self.cleaned_data.get('deadline_converted', None)
        logger.info('=== TICKET TASK FORM SAVE DEBUG (normalized) ===')
        logger.info(f'instance.pk (is editing?): {self.instance.pk}')
        logger.info(f'converted_deadline from cleaned_data: {converted_deadline}')
        logger.info(f'converted_deadline type: {type(converted_deadline)}')
        
        if converted_deadline is not None:
            # A valid deadline was provided and parsed
            instance.deadline = converted_deadline
            logger.info(f'Set instance.deadline to: {instance.deadline}')
        else:
            # No new deadline provided in this submission
            if not self.instance.pk:
                # New task with no deadline
                instance.deadline = None
                logger.info('No deadline provided for new task, setting deadline to None')
            else:
                # Editing existing task with no new deadline value: preserve current deadline
                logger.info('No new deadline provided on edit; preserving existing instance.deadline')
        
        logger.info(f'Final instance.deadline before save: {instance.deadline}')
        
        if commit:
            instance.save()
            logger.info(f'Instance saved. Final deadline in database: {instance.deadline}')
        
        logger.info('=== TICKET TASK FORM SAVE COMPLETED ===')
        return instance

class TaskReplyForm(forms.ModelForm):
    """Form for replying to ticket tasks"""
    class Meta:
        model = TaskReply
        fields = ['content', 'attachment']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': _('پاسخ خود را وارد کنید')
            }),
            'attachment': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,.pdf,.doc,.docx'})
        }
        labels = {
            'content': _('پاسخ'),
            'attachment': _('فایل پیوست')
        }

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        if attachment:
            # Check file size (max 10MB)
            if attachment.size > 10 * 1024 * 1024:
                raise ValidationError(_('حجم فایل نباید بیشتر از 10 مگابایت باشد.'))
            
            # Check file type
            allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'application/pdf', 
                           'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
            file_type, _ = mimetypes.guess_type(attachment.name)
            if file_type not in allowed_types:
                raise ValidationError(_('نوع فایل مجاز نیست. فقط تصاویر، PDF و Word مجاز است.'))
        
        return attachment

class DeadlineExtensionRequestForm(forms.ModelForm):
    """Form for requesting deadline extension"""
    deadline_date = forms.CharField(
        label=_('تاریخ مهلت جدید'),
        help_text=_('فرمت: YYYY/MM/DD HH:MM (مثال: 1403/09/25 14:30)'),
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('1403/09/25 14:30')
        })
    )
    
    class Meta:
        model = DeadlineExtensionRequest
        fields = ['reason']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
        }
        labels = {
            'reason': _('دلیل درخواست'),
        }
    
    def clean_deadline_date(self):
        """Convert Jalali date to Gregorian datetime"""
        deadline_date = self.cleaned_data.get('deadline_date')
        if not deadline_date:
            return None
        
        try:
            from .calendar_services.jalali_calendar import JalaliCalendarService
            
            # Parse date and time (format: YYYY/MM/DD HH:MM)
            parts = deadline_date.strip().split()
            if len(parts) != 2:
                raise ValidationError(_('فرمت تاریخ و زمان صحیح نیست. از فرمت YYYY/MM/DD HH:MM استفاده کنید.'))
            
            date_str = parts[0]
            time_str = parts[1]
            
            # Parse date
            date_parts = date_str.split('/')
            if len(date_parts) != 3:
                raise ValidationError(_('فرمت تاریخ صحیح نیست. از فرمت YYYY/MM/DD استفاده کنید.'))
            
            year = int(date_parts[0])
            month = int(date_parts[1])
            day = int(date_parts[2])
            
            # Parse time
            time_parts = time_str.split(':')
            if len(time_parts) != 2:
                raise ValidationError(_('فرمت زمان صحیح نیست. از فرمت HH:MM استفاده کنید.'))
            
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            
            # Validate time range
            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                raise ValidationError(_('زمان باید در محدوده معتبر باشد.'))
            
            # Convert Jalali to Gregorian
            converted_deadline = JalaliCalendarService.jalali_to_gregorian(year, month, day, hour, minute)
            # Minimum allowed date is start of today
            from django.utils import timezone
            now = timezone.now()
            start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if converted_deadline < start_of_today:
                raise ValidationError(_('تاریخ و زمان مهلت نمی‌تواند قبل از امروز باشد. لطفاً از امروز به بعد را انتخاب کنید.'))
            # If deadline is today, time must not be before now
            if converted_deadline.date() == now.date() and converted_deadline < now:
                raise ValidationError(_('برای امروز نمی‌توانید ساعتی قبل از ساعت الان انتخاب کنید. لطفاً زمان فعلی یا بعد از آن را انتخاب کنید.'))
            return converted_deadline
            
        except ValueError as e:
            raise ValidationError(_('فرمت تاریخ و زمان صحیح نیست. از فرمت YYYY/MM/DD HH:MM استفاده کنید.'))
        except Exception as e:
            raise ValidationError(_('خطا در تبدیل تاریخ. لطفاً تاریخ را بررسی کنید.'))
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        converted_deadline = self.cleaned_data.get('deadline_date')
        if converted_deadline:
            instance.requested_deadline = converted_deadline
        if commit:
            instance.save()
        return instance

class TaskStatusForm(forms.ModelForm):
    """Form for updating task status and priority (IT Manager only)"""
    class Meta:
        model = TicketTask
        fields = ['status', 'priority']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'})
        }
        labels = {
            'status': _('وضعیت'),
            'priority': _('اولویت')
        }

class DepartmentForm(forms.ModelForm):
    """Form for creating and editing departments"""
    class Meta:
        model = Department
        fields = ['name', 'department_type', 'description', 'is_active', 'branch', 'can_receive_tickets']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'department_type': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'can_receive_tickets': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }
        labels = {
            'name': _('نام بخش'),
            'department_type': _('نوع بخش'),
            'description': _('توضیحات'),
            'is_active': _('فعال'),
            'branch': _('شعبه'),
            'can_receive_tickets': _('می‌تواند تیکت دریافت کند')
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filter branches to only show active ones
        if 'branch' in self.fields:
            self.fields['branch'].queryset = Branch.objects.filter(is_active=True).order_by('name')
        
        # Prevent creating IT department type
        if 'department_type' in self.fields:
            # Remove 'technician' option if creating new department
            if not self.instance.pk:
                choices = list(self.fields['department_type'].choices)
                choices = [choice for choice in choices if choice[0] != 'technician']
                self.fields['department_type'].choices = choices

class SupervisorChoiceField(forms.ModelChoiceField):
    """Choice field that displays only the user's full name."""
    def label_from_instance(self, obj):
        return obj.get_full_name() or obj.username


class SupervisorAssignmentForm(forms.Form):
    """Form for assigning supervisors to departments"""
    supervisor = SupervisorChoiceField(
        label=_('سرپرست'),
        queryset=User.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text=_('کاربری که می‌خواهید به عنوان سرپرست انتخاب کنید (باید نقش سرپرست داشته باشد)')
    )
    departments = forms.ModelMultipleChoiceField(
        label=_('بخش‌ها'),
        queryset=Department.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        help_text=_('بخش‌هایی که می‌خواهید به این سرپرست اختصاص دهید (فقط بخش‌هایی که سرپرست ندارند نمایش داده می‌شوند)')
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
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
            except: pass
        log_debug('ENTRY', 'tickets/forms.py:479', 'SupervisorAssignmentForm.__init__ called', {})
        # #endregion
        
        # Filter supervisors - only users with senior role
        # IMPORTANT: Do NOT filter by department - a supervisor can be assigned to multiple departments
        # Query should be evaluated fresh each time to ensure latest data
        supervisor_queryset = User.objects.filter(
            role='employee',
            department_role='senior',
            is_active=True
        ).order_by('first_name', 'last_name')
        
        # Force evaluation to ensure fresh data (no caching issues)
        # The queryset will be re-evaluated when the form field accesses it
        
        # #region agent log - Bug 2: Form supervisor queryset
        log_debug('BUG2', 'tickets/forms.py:490', 'Form supervisor queryset', {
            'total_count': supervisor_queryset.count(),
            'supervisor_ids': list(supervisor_queryset.values_list('id', flat=True)[:20]),
            'supervisor_details': [
                {
                    'id': s.id,
                    'name': s.get_full_name(),
                    'department_id': s.department_id,
                    'department_name': s.department.name if s.department else None,
                    'department_role': s.department_role,
                    'is_active': s.is_active
                } for s in supervisor_queryset[:10]
            ]
        })
        # #endregion
        
        self.fields['supervisor'].queryset = supervisor_queryset
        
        # Filter departments - only show departments with no supervisor (Team Lead)
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
        # Query from User side to avoid reverse relationship caching issues and ensure latest data
        # Use values_list with distinct to get fresh department IDs directly from database
        # This ensures we get the latest committed data without any object caching
        depts_with_role_based_leads = list(
            User.objects.filter(
                role='employee',
                department_role__in=['senior', 'manager'],
                is_active=True,
                department__isnull=False,
                department__is_active=True,
                department__department_type='employee'
            ).values_list('department_id', flat=True).distinct()
        )
        
        # Combine all excluded department IDs
        all_excluded_dept_ids = set(depts_with_fk_supervisor) | set(depts_with_m2m_supervisor) | set(depts_with_role_based_leads)
        
        # Final queryset: All active employee departments EXCEPT those with any type of Team Lead
        if all_excluded_dept_ids:
            dept_queryset = Department.objects.filter(
                is_active=True,
                department_type='employee'
            ).exclude(id__in=all_excluded_dept_ids).distinct().order_by('name')
        else:
            dept_queryset = Department.objects.filter(
                is_active=True,
                department_type='employee'
            ).distinct().order_by('name')
        
        # Set the queryset for the form field
        self.fields['departments'].queryset = dept_queryset
        
        # Add class for JS disabling/enabling
        self.fields['departments'].widget.attrs.update({'class': 'dept-checkbox'})

class BranchForm(forms.ModelForm):
    """Form for creating and editing branches"""
    class Meta:
        model = Branch
        fields = ['name', 'branch_code', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'branch_code': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }
        labels = {
            'name': _('نام شعبه'),
            'branch_code': _('کد شعبه'),
            'description': _('توضیحات'),
            'is_active': _('فعال')
        }

class SuperAdminProfileForm(forms.ModelForm):
    """Form for SuperAdmin to update their national_id and employee_code"""
    
    class Meta:
        model = User
        fields = ['national_id', 'employee_code']
        widgets = {
            'national_id': forms.TextInput(attrs={'class': 'form-control', 'required': True}),
            'employee_code': forms.TextInput(attrs={'class': 'form-control', 'required': True})
        }
        labels = {
            'national_id': _('کد ملی'),
            'employee_code': _('کد پرسنلی'),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make fields required
        self.fields['national_id'].required = True
        self.fields['employee_code'].required = True
    
    def clean_national_id(self):
        """Validate national_id uniqueness (excluding current user)"""
        national_id = self.cleaned_data.get('national_id')
        if national_id:
            # Normalize before validation to match database format
            national_id = normalize_national_id(national_id.strip())
            # Check if another user (excluding current instance) has this national_id
            existing_user = User.objects.filter(national_id=national_id).exclude(
                id=self.instance.id if self.instance and self.instance.pk else None
            ).first()
            if existing_user:
                raise ValidationError(_('کاربری با این کد ملی قبلاً ثبت شده است.'))
        return national_id
    
    def clean_employee_code(self):
        """Validate employee_code uniqueness (excluding current user)"""
        employee_code = self.cleaned_data.get('employee_code')
        if employee_code:
            # Normalize before validation to match database format
            employee_code = normalize_employee_code(employee_code.strip())
            # Check if another user (excluding current instance) has this employee_code
            existing_user = User.objects.filter(employee_code=employee_code).exclude(
                id=self.instance.id if self.instance and self.instance.pk else None
            ).first()
            if existing_user:
                raise ValidationError(_('کاربری با این کد پرسنلی قبلاً ثبت شده است.'))
        return employee_code
    
    def save(self, commit=True):
        """Save the user with updated national_id and employee_code"""
        user = super().save(commit=False)
        if commit:
            user.save()
        return user

class ITManagerProfileForm(forms.ModelForm):
    """Form for IT Manager to update their profile and IT department settings"""
    it_department_name = forms.CharField(
        label=_('نام بخش IT'),
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    it_department_branch = forms.ModelChoiceField(
        label=_('شعبه بخش IT'),
        queryset=Branch.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'it_department_name', 'it_department_branch']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'})
        }
        labels = {
            'first_name': _('نام'),
            'last_name': _('نام خانوادگی'),
            'phone': _('تلفن')
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user:
            # Get IT department
            from .views import get_it_department
            it_dept = get_it_department()
            if it_dept:
                self.fields['it_department_name'].initial = it_dept.name
                if it_dept.branch:
                    self.fields['it_department_branch'].initial = it_dept.branch

class UserCreationByManagerForm(forms.ModelForm):
    """Form for creating users by IT Manager"""
    password = forms.CharField(
        label=_('رمز عبور'),
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )

    class Meta:
        model = User
        fields = ['national_id', 'employee_code', 'first_name', 'last_name', 'phone', 'role', 'department', 'department_role', 'password']
        widgets = {
            'national_id': forms.TextInput(attrs={'class': 'form-control'}),
            'employee_code': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'department_role': forms.Select(attrs={'class': 'form-select'})
        }
        labels = {
            'national_id': _('کد ملی'),
            'employee_code': _('کد کارمندی'),
            'first_name': _('نام'),
            'last_name': _('نام خانوادگی'),
            'phone': _('تلفن'),
            'role': _('نقش'),
            'department': _('بخش'),
            'department_role': _('نقش در بخش')
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .admin_security import get_admin_superuser_queryset_filter
        admin_filter = get_admin_superuser_queryset_filter()
        
        # Filter departments
        if 'department' in self.fields:
            self.fields['department'].queryset = Department.objects.filter(is_active=True).order_by('name')

class EmployeeCreationForm(forms.ModelForm):
    """Form for creating employees"""
    password1 = forms.CharField(
        label=_('رمز عبور'),
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )
    password2 = forms.CharField(
        label=_('تکرار رمز عبور'),
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )
    
    class Meta:
        model = User
        fields = ['national_id', 'employee_code', 'first_name', 'last_name', 'email', 'phone', 'department', 'department_role']
        widgets = {
            'national_id': forms.TextInput(attrs={'class': 'form-control'}),
            'employee_code': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'department_role': forms.Select(attrs={'class': 'form-select'})
        }
        labels = {
            'national_id': _('کد ملی'),
            'employee_code': _('کد کارمندی'),
            'first_name': _('نام'),
            'last_name': _('نام خانوادگی'),
            'email': _('ایمیل'),
            'phone': _('تلفن'),
            'department': _('بخش'),
            'department_role': _('نقش در بخش')
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .admin_security import get_admin_superuser_queryset_filter
        admin_filter = get_admin_superuser_queryset_filter()
        
        # Filter departments based on whether user is being created as Team Lead
        if 'department' in self.fields:
            # Check if department_role is 'senior' or 'manager' (Team Lead)
            # Check both initial data and form data (for POST requests)
            is_team_lead = False
            dept_role = None
            
            # Check form data first (POST request or form re-validation)
            # This is the most reliable way to detect Team Lead status
            if self.data and 'department_role' in self.data:
                dept_role = self.data.get('department_role')
                # Handle both string and list (for RadioSelect/CheckboxSelect)
                if isinstance(dept_role, list):
                    dept_role = dept_role[0] if dept_role else None
                is_team_lead = dept_role in ['senior', 'manager']
            # Check initial data (GET request or form initialization)
            elif 'department_role' in self.fields:
                # Try multiple ways to get the initial value
                if hasattr(self.fields['department_role'], 'initial') and self.fields['department_role'].initial:
                    dept_role = self.fields['department_role'].initial
                    is_team_lead = dept_role in ['senior', 'manager']
                elif hasattr(self, 'initial') and 'department_role' in self.initial:
                    dept_role = self.initial.get('department_role')
                    is_team_lead = dept_role in ['senior', 'manager']
            
            if is_team_lead:
                # For Supervisors (Team Leaders/Group Managers), disable/hide the department field
                # Department assignment must be done exclusively on the 'Assign to Team Leader' page
                if 'department' in self.fields:
                    self.fields['department'].required = False
                    self.fields['department'].widget = forms.HiddenInput()
                    self.fields['department'].initial = None
            else:
                # Not a Team Lead - show all active employee departments and make department required
                if 'department' in self.fields:
                    all_depts_queryset = Department.objects.filter(
                        is_active=True,
                        department_type='employee'
                    ).order_by('name')
                    self.fields['department'].queryset = all_depts_queryset
                    self.fields['department'].required = True
    
    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2:
            if password1 != password2:
                raise ValidationError(_('رمزهای عبور مطابقت ندارند.'))
        return password2
    
    def clean_department(self):
        """Validate department - must be None for supervisors"""
        department = self.cleaned_data.get('department')
        # department_role may not be in cleaned_data yet (field order: department before department_role)
        department_role = self.cleaned_data.get('department_role')
        if department_role is None and self.data and 'department_role' in self.data:
            dept_role = self.data.get('department_role')
            if isinstance(dept_role, list):
                dept_role = dept_role[0] if dept_role else None
            department_role = dept_role
        
        # If creating a supervisor (senior or manager), department is optional - must be None/empty
        if department_role in ['senior', 'manager']:
            if department is not None:
                from django.core.exceptions import ValidationError
                raise ValidationError(_('برای سرپرستان، بخش نباید انتخاب شود. اختصاص بخش باید از صفحه "اختصاص سرپرست به بخش‌ها" انجام شود.'))
            return None
        
        # For regular employees, department is required
        if not department_role or department_role == 'employee':
            if not department:
                from django.core.exceptions import ValidationError
                raise ValidationError(_('لطفاً یک بخش انتخاب کنید.'))
        
        return department
    
    def save(self, commit=True):
        user = super().save(commit=False)
        
        # CRITICAL: For supervisors (senior/manager), ensure department is None
        department_role = self.cleaned_data.get('department_role')
        if department_role in ['senior', 'manager']:
            user.department = None
        
        password = self.cleaned_data.get('password1')
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user
        
class TechnicianCreationForm(forms.ModelForm):
    """Form for creating technicians"""
    password1 = forms.CharField(
        label=_('رمز عبور'),
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )
    password2 = forms.CharField(
        label=_('تکرار رمز عبور'),
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )
    
    class Meta:
        model = User
        fields = ['national_id', 'employee_code', 'first_name', 'last_name', 'email', 'phone', 'department']
        widgets = {
            'national_id': forms.TextInput(attrs={'class': 'form-control'}),
            'employee_code': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.Select(attrs={'class': 'form-select'})
        }
        labels = {
            'national_id': _('کد ملی'),
            'employee_code': _('کد کارمندی'),
            'first_name': _('نام'),
            'last_name': _('نام خانوادگی'),
            'email': _('ایمیل'),
            'phone': _('تلفن'),
            'department': _('بخش')
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter departments to show only active IT departments
        if 'department' in self.fields:
            from .models import Department
            it_depts_queryset = Department.objects.filter(
                is_active=True,
                department_type='technician'
            ).order_by('name')
            self.fields['department'].queryset = it_depts_queryset
            self.fields['department'].required = True
            # Set default department to IT department
            if not self.instance.pk:  # Only for new technicians, not when editing
                from .views import get_it_department
                it_department = get_it_department()
                if it_department:
                    self.fields['department'].initial = it_department.id
    
    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2:
            if password1 != password2:
                raise ValidationError(_('رمزهای عبور مطابقت ندارند.'))
        return password2
    
    def clean_department(self):
        """Validate department - required for technicians"""
        department = self.cleaned_data.get('department')
        if not department:
            raise ValidationError(_('بخش برای کارشناسان فنی الزامی است.'))
        return department
    
    def save(self, commit=True, assigned_by=None):
        user = super().save(commit=False)
        # Set role to technician
        user.role = 'technician'
        # Set assigned_by if provided (IT manager who created this technician)
        if assigned_by:
            user.assigned_by = assigned_by
        # Ensure department is set - if not set, use IT department as default
        if not user.department:
            from .views import get_it_department
            it_department = get_it_department()
            if it_department:
                user.department = it_department
        password = self.cleaned_data.get('password1')
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user

class ITManagerCreationForm(forms.ModelForm):
    """Form for creating IT managers"""
    password1 = forms.CharField(
        label=_('رمز عبور'),
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )
    password2 = forms.CharField(
        label=_('تکرار رمز عبور'),
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )
    
    class Meta:
        model = User
        fields = ['national_id', 'employee_code', 'first_name', 'last_name', 'email', 'phone']
        widgets = {
            'national_id': forms.TextInput(attrs={'class': 'form-control'}),
            'employee_code': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'})
        }
        labels = {
            'national_id': _('کد ملی'),
            'employee_code': _('کد کارمندی'),
            'first_name': _('نام'),
            'last_name': _('نام خانوادگی'),
            'email': _('ایمیل'),
            'phone': _('تلفن')
        }
    
    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2:
            if password1 != password2:
                raise ValidationError(_('رمزهای عبور مطابقت ندارند.'))
        return password2
    
    def save(self, commit=True):
        user = super().save(commit=False)
        # Set role to IT manager
        user.role = 'it_manager'
        # IT managers don't have a department
        user.department = None
        # Set staff and superuser permissions
        user.is_staff = True
        user.is_superuser = True
        password = self.cleaned_data.get('password1')
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user

class EmployeeEditForm(forms.ModelForm):
    """Form for editing employees"""
    class Meta:
        model = User
        fields = ['national_id', 'employee_code', 'first_name', 'last_name', 'email', 'phone', 'department', 'department_role', 'is_active']
        widgets = {
            'national_id': forms.TextInput(attrs={'class': 'form-control'}),
            'employee_code': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'department_role': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }
        labels = {
            'national_id': _('کد ملی'),
            'employee_code': _('کد کارمندی'),
            'first_name': _('نام'),
            'last_name': _('نام خانوادگی'),
            'email': _('ایمیل'),
            'phone': _('تلفن'),
            'department': _('بخش'),
            'department_role': _('نقش در بخش'),
            'is_active': _('فعال')
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Determine if user is/will be a Team Lead
        is_team_lead = False
        current_dept_id = None
        
        # Check if editing existing user
        if self.instance and self.instance.pk:
            current_dept_id = self.instance.department_id
            is_team_lead = self.instance.department_role in ['senior', 'manager']
        
        # Check form data (POST request) - user might be changing to Team Lead
        if self.data and 'department_role' in self.data:
            dept_role = self.data.get('department_role')
            # Handle both string and list (for RadioSelect widget)
            if isinstance(dept_role, list):
                dept_role = dept_role[0] if dept_role else None
            if dept_role in ['senior', 'manager']:
                is_team_lead = True
        
        # Filter departments based on Team Lead status
        if 'department' in self.fields:
            if is_team_lead:
                # For Supervisors (Team Leaders/Group Managers), disable the department field
                # Department assignment must be done exclusively on the 'Assign to Team Leader' page
                self.fields['department'].required = False
                self.fields['department'].disabled = True
                self.fields['department'].widget.attrs['readonly'] = True
                self.fields['department'].widget.attrs['style'] = 'pointer-events: none; opacity: 0.6;'
                # Still set the queryset to include current department for display purposes
                if current_dept_id:
                    self.fields['department'].queryset = Department.objects.filter(
                        id=current_dept_id
                    )
                else:
                    self.fields['department'].queryset = Department.objects.none()
            else:
                # Not a Team Lead - show all active employee departments
                self.fields['department'].queryset = Department.objects.filter(
                    is_active=True,
                    department_type='employee'
                ).order_by('name')
        
        # Ensure department_role has a default value and is not required when editing
        if 'department_role' in self.fields:
            # Set default to 'employee' if instance exists and doesn't have a value
            if self.instance and self.instance.pk:
                if not self.instance.department_role:
                    self.fields['department_role'].initial = 'employee'
                # Make it not required for editing (it has a default in the model)
                self.fields['department_role'].required = False
    
    def clean_department(self):
        """Validate department selection based on department_role"""
        # If department field is disabled (for supervisors), preserve the original value
        if 'department' in self.fields and self.fields['department'].disabled:
            # For disabled fields, Django doesn't include them in cleaned_data
            # We need to get the original value from the instance
            if self.instance and self.instance.pk:
                return self.instance.department
            return None
        
        department = self.cleaned_data.get('department')
        department_role = self.cleaned_data.get('department_role')
        
        # Handle RadioSelect widget (returns list)
        if isinstance(department_role, list):
            department_role = department_role[0] if department_role else None
        
        # If user is/will be a Team Lead, validate department is vacant (except current dept)
        if department_role in ['senior', 'manager'] and department:
            current_dept_id = self.instance.department_id if (self.instance and self.instance.pk) else None
            
            # Check if department already has a Team Lead (excluding current user)
            has_fk_supervisor = (
                department.supervisor_id is not None and 
                department.supervisor.is_active and
                department.supervisor_id != self.instance.id if (self.instance and self.instance.pk) else True
            )
            has_m2m_supervisor = department.supervisors.filter(is_active=True).exclude(
                id=self.instance.id if (self.instance and self.instance.pk) else None
            ).exists()
            has_role_based_lead = User.objects.filter(
                role='employee',
                department_role__in=['senior', 'manager'],
                is_active=True,
                department=department
            ).exclude(id=self.instance.id if (self.instance and self.instance.pk) else None).exists()
            
            # Allow current department (for edit form self-referencing)
            if department.id != current_dept_id and (has_fk_supervisor or has_m2m_supervisor or has_role_based_lead):
                raise ValidationError(_('این بخش قبلاً یک سرپرست دارد. لطفاً بخش دیگری انتخاب کنید.'))
        
        return department
    
    def clean(self):
        """Normalize national_id and employee_code (Persian/Arabic to English digits) for User Management edits."""
        cleaned_data = super().clean()
        from .utils import normalize_national_id, normalize_employee_code
        if cleaned_data.get('national_id'):
            cleaned_data['national_id'] = normalize_national_id(cleaned_data['national_id'].strip())
        if cleaned_data.get('employee_code'):
            cleaned_data['employee_code'] = normalize_employee_code(cleaned_data['employee_code'].strip())
        return cleaned_data
    
    def save(self, commit=True):
        """Override save to preserve department_role and critical authentication fields"""
        # #region agent log - Form save entry
        import json
        import os
        from datetime import datetime
        log_path = r'c:\Users\User\Desktop\pticket-main\.cursor\debug.log'
        def log_form(hypothesis_id, location, message, data):
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
            except:
                pass
        # #endregion
        
        # CRITICAL: Capture ALL critical fields BEFORE calling super().save()
        # This ensures authentication and role fields are never corrupted
        original_fields = {}
        if self.instance and self.instance.pk:
            # Capture critical authentication and role fields
            original_fields = {
                'department_role': self.instance.department_role,
                'role': self.instance.role,
                'is_active': self.instance.is_active,
                'national_id': self.instance.national_id,
                'employee_code': self.instance.employee_code,
                'password': self.instance.password,  # Preserve password hash
                'department': self.instance.department,  # Preserve department for disabled field
            }
            log_form('FORM_SAVE', 'tickets/forms.py:1060', 'BEFORE super().save() - Original fields captured', {
                'instance_pk': self.instance.pk,
                'original_fields': {k: (v[:20] if k == 'password' and v else v) for k, v in original_fields.items()}
            })
        else:
            log_form('FORM_SAVE', 'tickets/forms.py:1060', 'WARNING - No instance.pk, cannot preserve fields', {
                'has_instance': self.instance is not None,
                'instance_pk': self.instance.pk if self.instance else None
            })
        
        user = super().save(commit=False)
        
        log_form('FORM_SAVE', 'tickets/forms.py:1071', 'AFTER super().save(commit=False) - Check if fields corrupted', {
            'user_id': user.id if user.id else None,
            'is_active_after_super': user.is_active,
            'national_id_after_super': user.national_id,
            'employee_code_after_super': user.employee_code,
            'role_after_super': user.role,
            'department_role_after_super': user.department_role
        })
        
        # CRITICAL: Preserve critical fields; allow national_id/employee_code when admin explicitly edits them
        if self.instance and self.instance.pk and original_fields:
            # Use is_active from form data (admin can toggle user status)
            user.is_active = self.cleaned_data.get('is_active', original_fields['is_active'])
            user.role = original_fields['role']  # Preserve role (employee, technician, it_manager)
            # Use cleaned_data for national_id/employee_code when admin submitted new values (identity sync in User.save())
            if self.cleaned_data.get('national_id'):
                user.national_id = self.cleaned_data['national_id']
            else:
                user.national_id = original_fields['national_id']
            if self.cleaned_data.get('employee_code'):
                user.employee_code = self.cleaned_data['employee_code']
            else:
                user.employee_code = original_fields['employee_code']
            
            # Preserve password hash if not explicitly changed
            if not hasattr(self, '_password_changed') or not self._password_changed:
                user.password = original_fields['password']
            
            # Preserve department_role if it's not explicitly changed
            new_dept_role = self.cleaned_data.get('department_role')
            if not new_dept_role or new_dept_role == '' or new_dept_role == original_fields['department_role']:
                # Preserve existing department_role - critical for Team Leads
                if original_fields['department_role'] in ['senior', 'manager']:
                    user.department_role = original_fields['department_role']
            else:
                # User explicitly changed the role
                user.department_role = new_dept_role
            
            # Preserve department if field is disabled (for supervisors)
            if 'department' in self.fields and self.fields['department'].disabled:
                user.department = original_fields.get('department')
            
            log_form('FORM_SAVE', 'tickets/forms.py:1093', 'AFTER restoration - Fields before user.save()', {
                'user_id': user.id if user.id else None,
                'is_active_restored': user.is_active,
                'national_id_restored': user.national_id,
                'employee_code_restored': user.employee_code,
                'role_restored': user.role,
                'department_role_restored': user.department_role,
                'will_save': commit
            })
        
        if commit:
            user.save()
            log_form('FORM_SAVE', 'tickets/forms.py:1094', 'AFTER user.save() - Fields saved to database', {
                'user_id': user.id if user.id else None,
                'save_completed': True
            })
        return user
        # #endregion

class TechnicianEditForm(forms.ModelForm):
    """Form for editing technicians"""
    class Meta:
        model = User
        fields = ['national_id', 'employee_code', 'first_name', 'last_name', 'email', 'phone', 'is_active']
        widgets = {
            'national_id': forms.TextInput(attrs={'class': 'form-control'}),
            'employee_code': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }
        labels = {
            'national_id': _('کد ملی'),
            'employee_code': _('کد کارمندی'),
            'first_name': _('نام'),
            'last_name': _('نام خانوادگی'),
            'email': _('ایمیل'),
            'phone': _('تلفن'),
            'is_active': _('فعال')
        }

    def clean(self):
        """Normalize national_id and employee_code (Persian/Arabic to English digits)."""
        cleaned_data = super().clean()
        from .utils import normalize_national_id, normalize_employee_code
        if cleaned_data.get('national_id'):
            cleaned_data['national_id'] = normalize_national_id(cleaned_data['national_id'].strip())
        if cleaned_data.get('employee_code'):
            cleaned_data['employee_code'] = normalize_employee_code(cleaned_data['employee_code'].strip())
        return cleaned_data

class ITManagerEditForm(forms.ModelForm):
    """Form for editing IT managers"""
    class Meta:
        model = User
        fields = ['national_id', 'employee_code', 'first_name', 'last_name', 'email', 'phone', 'is_active']
        widgets = {
            'national_id': forms.TextInput(attrs={'class': 'form-control'}),
            'employee_code': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }
        labels = {
            'national_id': _('کد ملی'),
            'employee_code': _('کد کارمندی'),
            'first_name': _('نام'),
            'last_name': _('نام خانوادگی'),
            'email': _('ایمیل'),
            'phone': _('تلفن'),
            'is_active': _('فعال')
        }

    def clean(self):
        """Normalize national_id and employee_code (Persian/Arabic to English digits)."""
        cleaned_data = super().clean()
        from .utils import normalize_national_id, normalize_employee_code
        if cleaned_data.get('national_id'):
            cleaned_data['national_id'] = normalize_national_id(cleaned_data['national_id'].strip())
        if cleaned_data.get('employee_code'):
            cleaned_data['employee_code'] = normalize_employee_code(cleaned_data['employee_code'].strip())
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        # Ensure role remains IT manager
        user.role = 'it_manager'
        # IT managers don't have a department
        user.department = None
        # Ensure staff and superuser permissions remain
        user.is_staff = True
        user.is_superuser = True
        if commit:
            user.save()
        return user

class EmailConfigForm(forms.ModelForm):
    """Form for email configuration"""
    class Meta:
        model = EmailConfig
        fields = ['host', 'port', 'use_tls', 'use_ssl', 'username', 'password']
        widgets = {
            'host': forms.TextInput(attrs={'class': 'form-control'}),
            'port': forms.NumberInput(attrs={'class': 'form-control'}),
            'use_tls': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'use_ssl': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'password': forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'})
        }
        labels = {
            'host': _('هاست SMTP'),
            'port': _('پورت'),
            'use_tls': _('استفاده از TLS'),
            'use_ssl': _('استفاده از SSL'),
            'username': _('نام کاربری'),
            'password': _('رمز عبور')
        }

class InventoryElementForm(forms.ModelForm):
    """Form for creating and editing inventory elements"""
    
    class Meta:
        model = InventoryElement
        fields = ['name', 'element_type', 'assigned_to', 'parent_element', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('نام عنصر')
            }),
            'element_type': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('نوع عنصر')
            }),
            'assigned_to': WarehouseAwareModelChoiceField(queryset=User.objects.none(), required=False).widget,
            'parent_element': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('توضیحات (اختیاری)')
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }
        labels = {
            'name': _('نام'),
            'element_type': _('نوع عنصر'),
            'assigned_to': _('تخصیص به'),
            'parent_element': _('عنصر والد (زیرمجموعه)'),
            'description': _('توضیحات'),
            'is_active': _('فعال')
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        element_id = kwargs.pop('element_id', None)
        super().__init__(*args, **kwargs)
        
        # Get warehouse element
        from .views import get_warehouse_element
        warehouse = get_warehouse_element()
        
        # Check if editing warehouse
        is_warehouse = False
        if self.instance and self.instance.pk:
            is_warehouse = (self.instance.id == warehouse.id)
        
        # If editing warehouse, hide assigned_to and parent_element
        if is_warehouse:
            if 'assigned_to' in self.fields:
                self.fields['assigned_to'].widget = forms.HiddenInput()
                self.fields['assigned_to'].required = False
            if 'parent_element' in self.fields:
                self.fields['parent_element'].widget = forms.HiddenInput()
                self.fields['parent_element'].required = False
        
        # Setup assigned_to field
        if 'assigned_to' in self.fields and not is_warehouse:
            from .admin_security import get_admin_superuser_queryset_filter
            admin_filter = get_admin_superuser_queryset_filter()
            
            # Get all active users (employees and technicians) excluding IT managers and admin superuser
            users = User.objects.filter(
                Q(role='employee') | Q(role='technician'),
                is_active=True
            ).filter(admin_filter).order_by('first_name', 'last_name')
            
            # Use WarehouseAwareModelChoiceField
            self.fields['assigned_to'] = WarehouseAwareModelChoiceField(
                queryset=users,
                required=False,
                label=_('تخصیص به'),
                empty_label=_('انتخاب کاربر یا انبار'),
                widget=forms.Select(attrs={'class': 'form-select'})
            )
        
        # Setup parent_element field
        if 'parent_element' in self.fields and not is_warehouse:
            # Use a more lenient queryset that includes all active elements
            # This allows JavaScript-populated values to pass validation
            # We'll restrict the actual options in the template via JavaScript
            self.fields['parent_element'].queryset = InventoryElement.objects.filter(is_active=True)
            self.fields['parent_element'].required = False
            self.fields['parent_element'].empty_label = _('انتخاب عنصر والد (اختیاری)')
            
            # Set initial value if editing
            if self.instance and self.instance.pk and self.instance.parent_element:
                self.fields['parent_element'].initial = self.instance.parent_element

    def clean_assigned_to(self):
        assigned_to_value = self.cleaned_data.get('assigned_to')
        
        # Handle warehouse assignment
        if assigned_to_value == 'warehouse':
            from .views import get_warehouse_element
            warehouse = get_warehouse_element()
            return warehouse.assigned_to if warehouse else None
        
        return assigned_to_value

    def clean_parent_element(self):
        """Validate parent_element - ensure it exists and is active"""
        parent_element = self.cleaned_data.get('parent_element')
        
        if parent_element:
            # Verify the element exists and is active
            if not parent_element.is_active:
                raise ValidationError(_('عنصر والد انتخاب شده فعال نیست.'))
            # Additional validation: ensure it's not the same as current element (for editing)
            if self.instance and self.instance.pk and parent_element.id == self.instance.id:
                raise ValidationError(_('نمی‌توانید یک عنصر را به عنوان والد خودش انتخاب کنید.'))
        
        return parent_element
    
    def clean(self):
        cleaned_data = super().clean()
        assigned_to = cleaned_data.get('assigned_to')
        parent_element = cleaned_data.get('parent_element')
        
        # Handle warehouse assignment
        if assigned_to == 'warehouse':
            from .views import get_warehouse_element
            warehouse = get_warehouse_element()
            if warehouse:
                cleaned_data['assigned_to'] = warehouse.assigned_to
        
        # Prevent circular references
        if parent_element:
            # If editing, check for circular references
            if self.instance and self.instance.pk:
                current = parent_element
                while current:
                    if current.id == self.instance.id:
                        raise ValidationError(_('نمی‌توانید یک عنصر را به عنوان والد خودش انتخاب کنید.'))
                    current = current.parent_element
            # If creating new, ensure parent element is valid and active
            elif not parent_element.is_active:
                raise ValidationError(_('عنصر والد انتخاب شده فعال نیست.'))
        
        return cleaned_data

class ElementSpecificationForm(forms.ModelForm):
    """Form for creating and editing element specifications"""

    class Meta:
        model = ElementSpecification
        fields = ['key', 'value', 'description']
        widgets = {
            'key': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('نام مشخصه (مثال: IP، MAC، شماره سریال)')
            }),
            'value': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('مقدار مشخصه')
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': _('توضیحات (اختیاری)')
            }),
        }
        labels = {
            'key': _('کلید'),
            'value': _('مقدار'),
            'description': _('توضیحات'),
        }

    def __init__(self, *args, **kwargs):
        self.element = kwargs.pop('element', None)
        super().__init__(*args, **kwargs)
        if self.element:
            self.fields['key'].help_text = _('نام مشخصه (مثال: IP، MAC، شماره سریال)')
    
    def clean_key(self):
        key = self.cleaned_data.get('key')
        if key:
            # Check for duplicate key for the same element
            if self.element:
                existing = ElementSpecification.objects.filter(
                    element=self.element,
                    key=key
                )
                if self.instance and self.instance.pk:
                    existing = existing.exclude(pk=self.instance.pk)
                if existing.exists():
                    raise ValidationError(_('این کلید قبلاً برای این عنصر تعریف شده است.'))
        return key

class TicketCategoryForm(forms.ModelForm):
    """Form for creating and editing ticket categories"""
    
    class Meta:
        model = TicketCategory
        fields = ['name', 'description', 'is_active', 'sort_order', 'requires_supervisor_approval']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('نام دسته‌بندی (مثال: سخت‌افزار، شبکه)')
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('توضیحات اختیاری')
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'sort_order': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': _('ترتیب نمایش')
            }),
            'requires_supervisor_approval': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
        labels = {
            'name': _('نام دسته‌بندی'),
            'description': _('توضیحات'),
            'is_active': _('فعال'),
            'sort_order': _('ترتیب نمایش'),
            'requires_supervisor_approval': _('نیاز به تایید سرپرست'),
        }
        help_texts = {
            'sort_order': _('اعداد کمتر در ابتدا نمایش داده می‌شوند'),
            'requires_supervisor_approval': _('در صورت فعال بودن، تیکت‌های این دسته‌بندی نیاز به تایید سرپرست بخش ایجادکننده دارند'),
        }
    
    def __init__(self, *args, **kwargs):
        """Initialize form - department is excluded for security"""
        super().__init__(*args, **kwargs)
        # Department field is intentionally excluded from the form
        # It will be set by the view based on the supervisor's department