from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.db.models import Q, Count
from .models import Ticket, Reply, User, Department, EmailConfig, Branch, InventoryElement, ElementSpecification, TicketTask, TaskReply
from .validators import validate_iranian_national_id, validate_iranian_mobile_number
import os
import mimetypes


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
            # Try to authenticate using national_id and employee_code
            user = authenticate(request=self.request, national_id=national_id, employee_code=employee_code)
            if user is None:
                raise ValidationError(_('کد ملی یا کد کارمندی اشتباه است.'))
            if not user.is_active:
                raise ValidationError(_('این حساب کاربری غیرفعال است.'))
            self.user_cache = user
        return self.cleaned_data

class TicketForm(forms.ModelForm):
    """Form for creating and editing tickets"""
    class Meta:
        model = Ticket
        fields = ['title', 'description', 'category', 'priority', 'target_department', 'branch', 'attachment']
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
            'target_department': forms.Select(attrs={'class': 'form-select'}),
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'attachment': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,.pdf,.doc,.docx'})
        }
        labels = {
            'title': _('عنوان'),
            'description': _('توضیحات'),
            'category': _('دسته‌بندی'),
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
        if commit:
            instance.save()
        return instance

class TicketTaskForm(forms.ModelForm):
    """Form for creating ticket tasks (IT Manager only)"""
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
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filter departments to only show active employee departments
        if 'department' in self.fields:
            self.fields['department'].queryset = Department.objects.filter(
                is_active=True,
                department_type='employee'
            ).order_by('name')
        
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
        
        # Update assigned_to queryset based on department
        if 'assigned_to' in self.fields:
            if department:
                self.fields['assigned_to'].queryset = User.objects.filter(
                    department=department,
                    is_active=True,
                    role='employee'
                ).order_by('first_name', 'last_name')
            else:
                # Initially empty - will be populated via JavaScript based on department selection
                self.fields['assigned_to'].queryset = User.objects.none()
            self.fields['assigned_to'].required = True
    
    def clean_assigned_to(self):
        """Validate that the assigned user is from the selected department"""
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
            
            # DEBUG: Log the detection result (remove in production)
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"EmployeeCreationForm: is_team_lead={is_team_lead}, dept_role={dept_role}, has_data={bool(self.data)}")
            
            if is_team_lead:
                # Filter to only show departments WITHOUT a Team Lead
                # Use the same comprehensive filtering logic as SupervisorAssignmentForm
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
                    filtered_queryset = Department.objects.filter(
                        is_active=True,
                        department_type='employee'
                    ).exclude(id__in=all_excluded_dept_ids).distinct().order_by('name')
                else:
                    filtered_queryset = Department.objects.filter(
                        is_active=True,
                        department_type='employee'
                    ).distinct().order_by('name')
                
                # Store original queryset for potential dynamic updates
                self._team_lead_filtered_queryset = filtered_queryset
                self.fields['department'].queryset = filtered_queryset
            else:
                # Not a Team Lead - show all active employee departments
                all_depts_queryset = Department.objects.filter(
                    is_active=True,
                    department_type='employee'
                ).order_by('name')
                self._team_lead_filtered_queryset = None
                self.fields['department'].queryset = all_depts_queryset
    
    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2:
            if password1 != password2:
                raise ValidationError(_('رمزهای عبور مطابقت ندارند.'))
        return password2
    
    def save(self, commit=True):
        user = super().save(commit=False)
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
                # Filter to only show departments WITHOUT a Team Lead
                # Use the same comprehensive filtering logic as SupervisorAssignmentForm
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
                # CRITICAL: Exclude other users' departments, but include current user's department if editing
                depts_with_role_based_leads = list(
                    User.objects.filter(
                        role='employee',
                        department_role__in=['senior', 'manager'],
                        is_active=True,
                        department__isnull=False,
                        department__is_active=True,
                        department__department_type='employee'
                    ).exclude(
                        id=self.instance.id if (self.instance and self.instance.pk) else None
                    ).values_list('department_id', flat=True).distinct()
                )
                
                # Combine all excluded department IDs
                all_excluded_dept_ids = set(depts_with_fk_supervisor) | set(depts_with_m2m_supervisor) | set(depts_with_role_based_leads)
                
                # CRITICAL: For edit form, include current user's department even if it has a Team Lead
                # This allows saving without changes or reassignment
                if current_dept_id:
                    all_excluded_dept_ids.discard(current_dept_id)  # Remove current dept from excluded list
                
                # Final queryset: All active employee departments EXCEPT those with any type of Team Lead
                # (but including current user's department if editing)
                if all_excluded_dept_ids:
                    self.fields['department'].queryset = Department.objects.filter(
                        is_active=True,
                        department_type='employee'
                    ).exclude(id__in=all_excluded_dept_ids).distinct().order_by('name')
                else:
                    self.fields['department'].queryset = Department.objects.filter(
                        is_active=True,
                        department_type='employee'
                    ).distinct().order_by('name')
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
        
        # CRITICAL: Preserve ALL critical authentication fields
        if self.instance and self.instance.pk and original_fields:
            # Preserve authentication fields - NEVER modify these
            user.is_active = original_fields['is_active']
            user.national_id = original_fields['national_id']
            user.employee_code = original_fields['employee_code']
            user.role = original_fields['role']  # Preserve role (employee, technician, it_manager)
            
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