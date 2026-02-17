from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django import forms
from django.utils.translation import gettext_lazy as _
from .models import User, Ticket, Reply, Branch, Department, InventoryElement, ElementSpecification
from .utils import normalize_national_id, normalize_employee_code
import logging

logger = logging.getLogger(__name__)

class CustomUserCreationForm(forms.ModelForm):
    """Custom form for creating users in admin with proper department choices"""
    
    # Department choices will be populated dynamically from database
    
    class Meta:
        model = User
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Get current role from instance or data
        current_role = None
        if self.instance and self.instance.pk:
            current_role = self.instance.role
        elif 'role' in self.data:
            current_role = self.data.get('role')
        elif 'role' in self.initial:
            current_role = self.initial['role']
        
        # Get active departments from database based on role
        from .models import Department
        
        if current_role == 'technician':
            # Get active technician departments
            technician_departments = Department.objects.filter(
                department_type='technician', 
                is_active=True
            ).order_by('name')
            department_choices = [('', '---------')]
            department_choices.extend([(dept.id, dept.name) for dept in technician_departments])
        else:
            # Get active employee departments for 'employee' and 'it_manager' roles
            employee_departments = Department.objects.filter(
                department_type='employee', 
                is_active=True
            ).order_by('name')
            department_choices = [('', '---------')]
            department_choices.extend([(dept.id, dept.name) for dept in employee_departments])
        
        # Delete the existing field first, then recreate it
        if 'department' in self.fields:
            del self.fields['department']
        
        self.fields['department'] = forms.ChoiceField(
            label=_('بخش'),
            choices=department_choices,
            required=False,
            help_text=_('بخش این کاربر را انتخاب کنید'),
            widget=forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_department'
            })
        )
        
        # Also override the department_role field to ensure it's properly configured
        if 'department_role' in self.fields:
            self.fields['department_role'] = forms.ChoiceField(
                label=_('نقش در بخش'),
                choices=User.DEPARTMENT_ROLE_CHOICES,
                required=False,
                widget=forms.RadioSelect(attrs={
                    'class': 'form-check-input',
                    'onchange': 'toggleDepartmentField()'
                })
            )
        
        # Add role field onchange event to update departments dynamically
        if 'role' in self.fields:
            self.fields['role'].widget.attrs.update({
                'onchange': 'updateDepartmentChoices()'
            })
    
    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        department_role = cleaned_data.get('department_role')
        department = cleaned_data.get('department')
        
        # Normalization guard (Docker/locale): strictly convert Persian/Arabic digits to English
        # and strip whitespace before commit, so login query (English digits) finds the match.
        if 'national_id' in cleaned_data and cleaned_data.get('national_id'):
            raw_nid = (cleaned_data['national_id'] or '').strip()
            cleaned_data['national_id'] = normalize_national_id(raw_nid)
            if raw_nid != cleaned_data['national_id']:
                logger.debug(f"Admin form: National ID normalized from '{raw_nid}' to '{cleaned_data['national_id']}'")
        
        if 'employee_code' in cleaned_data and cleaned_data.get('employee_code'):
            raw_ec = (cleaned_data['employee_code'] or '').strip()
            cleaned_data['employee_code'] = normalize_employee_code(raw_ec)
            if raw_ec != cleaned_data['employee_code']:
                logger.debug(f"Admin form: Employee Code normalized from '{raw_ec}' to '{cleaned_data['employee_code']}'")
        
        # For managers, clear the department
        if department_role == 'manager':
            cleaned_data['department'] = None
        
        # Validate department requirements
        if role == 'employee' and not department_role == 'manager' and not department:
            raise forms.ValidationError(_('بخش برای کارمندان (به جز مدیران) الزامی است'))
        elif role == 'technician' and not department:
            raise forms.ValidationError(_('بخش برای کارشناسان فنی الزامی است'))
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        
        # Set department_role for employees if not already set
        if user.role == 'employee' and not user.department_role:
            user.department_role = self.cleaned_data.get('department_role', 'employee')
        
        # Handle department assignment
        department_id = self.cleaned_data.get('department')
        if department_id and department_id != '':
            try:
                from .models import Department
                user.department = Department.objects.get(id=department_id)
            except Department.DoesNotExist:
                user.department = None
        else:
            user.department = None
        
        if commit:
            user.save()
        return user

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'department_role', 'national_id', 'employee_code', 'department')
    list_filter = ('role', 'department_role', 'department', 'is_active')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'national_id', 'employee_code')
    ordering = ('username',)
    
    def get_queryset(self, request):
        """Exclude admin superuser from the list (only visible to itself)"""
        qs = super().get_queryset(request)
        # Only show admin superuser to itself
        from .admin_security import is_admin_superuser
        if not is_admin_superuser(request.user):
            from .admin_security import get_admin_superuser_queryset_filter
            qs = qs.filter(get_admin_superuser_queryset_filter())
        return qs
    
    class Media:
        js = ('admin/js/user_admin.js',)
    
    fieldsets = UserAdmin.fieldsets + (
        ('اطلاعات سیستم تیکت', {
            'fields': ('national_id', 'employee_code', 'role', 'department_role', 'phone', 'department', 'assigned_by')
        }),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('اطلاعات سیستم تیکت', {
            'fields': ('national_id', 'employee_code', 'role', 'department_role', 'phone', 'department', 'assigned_by')
        }),
    )

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'created_by', 'category', 'priority', 'status', 'assigned_to', 'created_at')
    list_filter = ('status', 'priority', 'category', 'assigned_to', 'created_at')
    search_fields = ('title', 'description', 'created_by__username', 'created_by__first_name', 'created_by__last_name')
    list_editable = ('status', 'priority', 'assigned_to')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('اطلاعات پایه', {
            'fields': ('title', 'description', 'category', 'priority', 'status')
        }),
        ('روابط', {
            'fields': ('created_by', 'assigned_to', 'branch', 'target_department')
        }),
        ('زمان‌بندی', {
            'fields': ('created_at', 'updated_at', 'resolved_at'),
            'classes': ('collapse',)
        }),
        ('پیوست‌ها', {
            'fields': ('attachment',),
            'classes': ('collapse',)
        }),
    )

@admin.register(Reply)
class ReplyAdmin(admin.ModelAdmin):
    list_display = ('id', 'ticket', 'author', 'is_private', 'created_at')
    list_filter = ('created_at', 'author__role', 'is_private')
    search_fields = ('content', 'ticket__title', 'author__username')
    readonly_fields = ('created_at',)
    
    fieldsets = (
        ('اطلاعات پاسخ', {
            'fields': ('ticket', 'author', 'content', 'is_private')
        }),
        ('زمان‌بندی', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
        ('پیوست‌ها', {
            'fields': ('attachment',),
            'classes': ('collapse',)
        }),
    )

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'get_departments_count', 'branch_code', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'branch_code')
    readonly_fields = ('created_at', 'updated_at', 'get_departments_list')
    
    fieldsets = (
        ('اطلاعات پایه', {
            'fields': ('name', 'branch_code', 'description', 'is_active')
        }),
        ('بخش‌ها', {
            'fields': ('get_departments_list',),
            'classes': ('collapse',)
        }),
        ('زمان‌بندی', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_departments_count(self, obj):
        """Display number of departments in this branch"""
        count = obj.departments.count()
        return f"{count} بخش"
    get_departments_count.short_description = 'تعداد بخش‌ها'
    
    def get_departments_list(self, obj):
        """Display list of departments in this branch"""
        if obj.pk:
            departments = obj.departments.all()
            if departments.exists():
                return ', '.join([dept.name for dept in departments])
            return "هیچ بخشی اختصاص داده نشده"
        return "ابتدا شعبه را ذخیره کنید"
    get_departments_list.short_description = 'بخش‌های این شعبه'

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'department_type', 'get_branch_info', 'can_receive_tickets', 'is_active', 'created_at')
    list_filter = ('department_type', 'is_active', 'can_receive_tickets', 'branch', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('اطلاعات پایه', {
            'fields': ('name', 'department_type', 'description', 'branch', 'is_active', 'can_receive_tickets')
        }),
        ('زمان‌بندی', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_branch_info(self, obj):
        """Display branch information in admin list"""
        if obj.branch:
            status = "فعال" if obj.branch.is_active else "غیرفعال"
            dept_type = "کارمندی" if obj.department_type == 'employee' else "فنی"
            return f"{obj.branch.name} ({obj.branch.branch_code}) - {status} - {dept_type}"
        return "شعبه پیکربندی نشده"
    get_branch_info.short_description = 'اطلاعات شعبه'

class ElementSpecificationInline(admin.TabularInline):
    """Inline admin for element specifications"""
    model = ElementSpecification
    extra = 1
    fields = ('key', 'value', 'description')

@admin.register(InventoryElement)
class InventoryElementAdmin(admin.ModelAdmin):
    list_display = ('name', 'element_type', 'assigned_to', 'get_parent_name', 'is_active', 'created_at')
    list_filter = ('element_type', 'is_active', 'created_at', 'assigned_to')
    search_fields = ('name', 'description', 'element_type', 'assigned_to__first_name', 'assigned_to__last_name')
    readonly_fields = ('created_at', 'updated_at', 'created_by')
    inlines = [ElementSpecificationInline]
    
    fieldsets = (
        ('اطلاعات پایه', {
            'fields': ('name', 'element_type', 'description', 'assigned_to', 'parent_element', 'is_active')
        }),
        ('زمان‌بندی', {
            'fields': ('created_at', 'updated_at', 'created_by'),
            'classes': ('collapse',)
        }),
    )
    
    def get_parent_name(self, obj):
        """Display parent element name"""
        if obj.parent_element:
            return obj.parent_element.name
        return "-"
    get_parent_name.short_description = 'عنصر والد'
    
    def save_model(self, request, obj, form, change):
        """Set created_by when creating new element"""
        if not change:  # Only for new objects
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(ElementSpecification)
class ElementSpecificationAdmin(admin.ModelAdmin):
    list_display = ('element', 'key', 'value', 'updated_at')
    list_filter = ('element', 'updated_at')
    search_fields = ('key', 'value', 'element__name')
    readonly_fields = ('created_at', 'updated_at') 