# Dynamic Multi-Tenant Ticket Categorization System
## Technical Architecture Blueprint

---

## Document Purpose

This specification defines the technical architecture for implementing a **Dynamic Multi-Tenant Ticket Categorization System** that enables department-level customization of ticket categories. The system empowers supervisors to manage their own service taxonomies while maintaining data isolation and system integrity.

---

## Executive Summary

**Objective:** Implement a modular sub-system where departments marked as "Service Providers" can define and manage their own unique set of ticket categories. The system dynamically updates the "Create Ticket" form based on the selected destination department.

**Key Features:**
- Department-specific category management (multi-tenant isolation)
- Dynamic form updates via cascading dropdowns
- Supervisor-level category CRUD operations
- Backend validation and security guardrails
- Performance optimization via caching
- Departmental reporting capabilities

---

## 1. Data Architecture & Schema Enhancements

### 1.1 Department Model Extension

**File:** `tickets/models.py`

**Current State:** Verify existing Department model structure

**Required Changes:**

```python
class Department(models.Model):
    # ... existing fields ...
    
    # New field for multi-tenant categorization
    is_service_provider = models.BooleanField(
        _('ارائه‌دهنده خدمات'),
        default=False,
        help_text=_('در صورتی که این بخش می‌تواند تیکت‌های پشتیبانی دریافت کند، این گزینه را فعال کنید')
    )
    
    # Optional: Track when service provider status was enabled
    service_provider_since = models.DateTimeField(
        _('ارائه خدمات از تاریخ'),
        null=True,
        blank=True,
        help_text=_('تاریخ فعال‌سازی این بخش به عنوان ارائه‌دهنده خدمات')
    )
    
    class Meta:
        verbose_name = _("بخش")
        verbose_name_plural = _("بخش‌ها")
        # ... existing meta options ...
```

**Migration Required:**
```python
# tickets/migrations/XXXX_add_service_provider_to_department.py
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('tickets', 'XXXX_previous_migration'),
    ]

    operations = [
        migrations.AddField(
            model_name='department',
            name='is_service_provider',
            field=models.BooleanField(default=False, verbose_name='ارائه‌دهنده خدمات'),
        ),
        migrations.AddField(
            model_name='department',
            name='service_provider_since',
            field=models.DateTimeField(null=True, blank=True, verbose_name='ارائه خدمات از تاریخ'),
        ),
    ]
```

### 1.2 TicketCategory Model (New)

**File:** `tickets/models.py`

**New Model Definition:**

```python
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
        unique_together = [['department', 'name']]  # Prevent duplicate category names per department
        indexes = [
            models.Index(fields=['department', 'is_active']),
            models.Index(fields=['department', 'sort_order']),
        ]
    
    def __str__(self):
        return f"{self.department.name} - {self.name}"
    
    def clean(self):
        """Validate that department is a service provider"""
        from django.core.exceptions import ValidationError
        if self.department and not self.department.is_service_provider:
            raise ValidationError({
                'department': _('فقط بخش‌هایی که به عنوان ارائه‌دهنده خدمات فعال هستند می‌توانند دسته‌بندی داشته باشند.')
            })
    
    def save(self, *args, **kwargs):
        self.full_clean()  # Run validation
        super().save(*args, **kwargs)
```

**Migration Required:**
```python
# tickets/migrations/XXXX_create_ticket_category.py
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('tickets', 'XXXX_add_service_provider_to_department'),
    ]

    operations = [
        migrations.CreateModel(
            name='TicketCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='نام دسته‌بندی')),
                ('description', models.TextField(blank=True, null=True, verbose_name='توضیحات')),
                ('is_active', models.BooleanField(default=True, verbose_name='فعال')),
                ('sort_order', models.IntegerField(default=0, verbose_name='ترتیب نمایش')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ایجاد')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='تاریخ بروزرسانی')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_categories', to=settings.AUTH_USER_MODEL, verbose_name='ایجاد شده توسط')),
                ('department', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ticket_categories', to='tickets.department', verbose_name='بخش')),
            ],
            options={
                'verbose_name': 'دسته‌بندی تیکت',
                'verbose_name_plural': 'دسته‌بندی‌های تیکت',
                'ordering': ['department', 'sort_order', 'name'],
                'unique_together': {('department', 'name')},
            },
        ),
        migrations.AddIndex(
            model_name='ticketcategory',
            index=models.Index(fields=['department', 'is_active'], name='tickets_tick_departm_idx'),
        ),
        migrations.AddIndex(
            model_name='ticketcategory',
            index=models.Index(fields=['department', 'sort_order'], name='tickets_tick_departm_sort_idx'),
        ),
    ]
```

### 1.3 Ticket Model Modification

**File:** `tickets/models.py`

**Required Changes:**

**Option A: Replace Existing Category Field (Breaking Change)**
If the current system uses a simple CharField for category:

```python
class Ticket(models.Model):
    # ... existing fields ...
    
    # Remove old category field:
    # category = models.CharField(...)  # OLD
    
    # Add new foreign key to TicketCategory:
    category = models.ForeignKey(
        TicketCategory,
        on_delete=models.PROTECT,  # Prevent deletion of categories in use
        related_name='tickets',
        verbose_name=_('دسته‌بندی'),
        null=True,  # Allow null during migration
        blank=True,
        help_text=_('دسته‌بندی تیکت بر اساس بخش مقصد')
    )
    
    # Keep old category field for data migration compatibility:
    category_legacy = models.CharField(
        _('دسته‌بندی (قدیمی)'),
        max_length=50,
        blank=True,
        null=True,
        help_text=_('مقدار قدیمی دسته‌بندی (فقط برای سازگاری)')
    )
```

**Option B: Add New Field (Non-Breaking Change)**
If we want to maintain backward compatibility:

```python
class Ticket(models.Model):
    # ... existing fields ...
    
    # Keep existing category field for backward compatibility
    category = models.CharField(...)  # Keep as-is for now
    
    # Add new foreign key field
    ticket_category = models.ForeignKey(
        TicketCategory,
        on_delete=models.PROTECT,
        related_name='tickets',
        verbose_name=_('دسته‌بندی جدید'),
        null=True,
        blank=True,
        help_text=_('دسته‌بندی تیکت بر اساس بخش مقصد (سیستم جدید)')
    )
```

**Recommended Approach:** Option B (non-breaking) for gradual migration.

---

## 2. Access Control and Conditional UI (Supervisor Panel)

### 2.1 Menu Visibility Logic

**File:** `tickets/context_processors.py` or `templates/base.html`

**Implementation:**

```python
# tickets/context_processors.py
def category_management_access(request):
    """Check if user can access category management"""
    if request.user.is_authenticated:
        user = request.user
        if user.role == 'employee' and user.department_role == 'senior':
            # Check if user's department is a service provider
            if user.department and user.department.is_service_provider:
                return {'can_manage_categories': True}
    return {'can_manage_categories': False}
```

**Template Logic (base.html):**

```django
{% if can_manage_categories %}
    <li class="nav-item">
        <a class="nav-link" href="{% url 'tickets:category_list' %}">
            <i class="fas fa-tags"></i>
            {% trans "مدیریت دسته‌بندی‌ها" %}
        </a>
    </li>
{% endif %}
```

### 2.2 Category Management Interface

**Files Required:**
- `tickets/views.py` - Category CRUD views
- `tickets/forms.py` - Category form
- `templates/tickets/category_list.html` - List view
- `templates/tickets/category_form.html` - Create/Edit form

#### A. List View

**View Code:**

```python
# tickets/views.py
@login_required
def category_list(request):
    """List all categories for the supervisor's department"""
    user = request.user
    
    # Permission check
    if not (user.role == 'employee' and user.department_role == 'senior'):
        messages.error(request, _('دسترسی رد شد.'))
        return redirect('tickets:dashboard')
    
    # Ensure user has a department
    if not user.department:
        messages.error(request, _('شما به هیچ بخشی اختصاص داده نشده‌اید.'))
        return redirect('tickets:dashboard')
    
    # Ensure department is a service provider
    if not user.department.is_service_provider:
        messages.error(request, _('بخش شما به عنوان ارائه‌دهنده خدمات فعال نشده است.'))
        return redirect('tickets:dashboard')
    
    # Get categories filtered by department (multi-tenant isolation)
    categories = TicketCategory.objects.filter(
        department=user.department,
        is_active=True
    ).order_by('sort_order', 'name')
    
    # Include inactive categories for management
    all_categories = TicketCategory.objects.filter(
        department=user.department
    ).order_by('sort_order', 'name')
    
    context = {
        'categories': categories,
        'all_categories': all_categories,
        'department': user.department,
    }
    
    return render(request, 'tickets/category_list.html', context)
```

#### B. Create/Edit Views

**View Code:**

```python
@login_required
def category_create(request):
    """Create a new category for supervisor's department"""
    user = request.user
    
    # Permission check (same as list view)
    if not (user.role == 'employee' and user.department_role == 'senior'):
        messages.error(request, _('دسترسی رد شد.'))
        return redirect('tickets:dashboard')
    
    if not user.department or not user.department.is_service_provider:
        messages.error(request, _('دسترسی رد شد.'))
        return redirect('tickets:dashboard')
    
    if request.method == 'POST':
        form = TicketCategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            # Force department to user's department (multi-tenant isolation)
            category.department = user.department
            category.created_by = user
            category.save()
            messages.success(request, _('دسته‌بندی با موفقیت ایجاد شد.'))
            return redirect('tickets:category_list')
    else:
        form = TicketCategoryForm()
        # Pre-set department (read-only)
        form.fields['department'].initial = user.department
        form.fields['department'].widget.attrs['readonly'] = True
    
    context = {
        'form': form,
        'department': user.department,
    }
    return render(request, 'tickets/category_form.html', context)


@login_required
def category_edit(request, category_id):
    """Edit a category (only if belongs to supervisor's department)"""
    user = request.user
    
    # Permission check
    if not (user.role == 'employee' and user.department_role == 'senior'):
        messages.error(request, _('دسترسی رد شد.'))
        return redirect('tickets:dashboard')
    
    if not user.department:
        messages.error(request, _('دسترسی رد شد.'))
        return redirect('tickets:dashboard')
    
    # Get category and verify department ownership (multi-tenant isolation)
    category = get_object_or_404(
        TicketCategory,
        id=category_id,
        department=user.department  # Critical: Filter by department
    )
    
    if request.method == 'POST':
        form = TicketCategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, _('دسته‌بندی با موفقیت بروزرسانی شد.'))
            return redirect('tickets:category_list')
    else:
        form = TicketCategoryForm(instance=category)
        form.fields['department'].widget.attrs['readonly'] = True
    
    context = {
        'form': form,
        'category': category,
        'department': user.department,
    }
    return render(request, 'tickets/category_form.html', context)


@login_required
def category_delete(request, category_id):
    """Delete a category (only if belongs to supervisor's department)"""
    user = request.user
    
    # Permission check
    if not (user.role == 'employee' and user.department_role == 'senior'):
        messages.error(request, _('دسترسی رد شد.'))
        return redirect('tickets:dashboard')
    
    if not user.department:
        messages.error(request, _('دسترسی رد شد.'))
        return redirect('tickets:dashboard')
    
    # Get category and verify department ownership
    category = get_object_or_404(
        TicketCategory,
        id=category_id,
        department=user.department
    )
    
    if request.method == 'POST':
        # Soft delete: Set is_active to False
        category.is_active = False
        category.save()
        messages.success(request, _('دسته‌بندی با موفقیت غیرفعال شد.'))
        return redirect('tickets:category_list')
    
    # Check if category is in use
    tickets_count = category.tickets.count()
    
    context = {
        'category': category,
        'tickets_count': tickets_count,
    }
    return render(request, 'tickets/category_delete_confirm.html', context)
```

#### C. Category Form

**Form Code:**

```python
# tickets/forms.py
class TicketCategoryForm(forms.ModelForm):
    """Form for creating/editing ticket categories"""
    
    class Meta:
        model = TicketCategory
        fields = ['name', 'description', 'is_active', 'sort_order']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('مثال: سخت‌افزار، شبکه، نرم‌افزار')
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
                'min': 0,
                'step': 1
            }),
        }
        labels = {
            'name': _('نام دسته‌بندی'),
            'description': _('توضیحات'),
            'is_active': _('فعال'),
            'sort_order': _('ترتیب نمایش'),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Department field (hidden or readonly, set by view)
        self.fields['department'] = forms.ModelChoiceField(
            queryset=Department.objects.filter(is_service_provider=True),
            required=True,
            widget=forms.HiddenInput() if self.instance.pk else forms.Select(attrs={'class': 'form-control', 'disabled': True}),
            label=_('بخش')
        )
```

---

## 3. Dynamic Form Integration (Cascading Dropdown)

### 3.1 API Endpoint

**File:** `tickets/views.py` or `tickets/api_views.py`

**Endpoint Implementation:**

```python
# tickets/views.py
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.cache import cache

@require_http_methods(["GET"])
def get_department_categories(request, department_id):
    """
    API endpoint to fetch active categories for a department.
    Returns JSON list of categories.
    
    URL: /api/departments/<department_id>/categories/
    """
    try:
        department = get_object_or_404(Department, id=department_id)
        
        # Check if department is a service provider
        if not department.is_service_provider:
            return JsonResponse({
                'error': _('این بخش به عنوان ارائه‌دهنده خدمات فعال نیست.'),
                'categories': []
            }, status=400)
        
        # Cache key
        cache_key = f'dept_categories_{department_id}'
        
        # Try cache first
        categories_data = cache.get(cache_key)
        if categories_data is None:
            # Query database
            categories = TicketCategory.objects.filter(
                department=department,
                is_active=True
            ).order_by('sort_order', 'name').values('id', 'name', 'description')
            
            categories_data = list(categories)
            
            # Cache for 1 hour (categories change infrequently)
            cache.set(cache_key, categories_data, 3600)
        
        return JsonResponse({
            'success': True,
            'categories': categories_data,
            'department_name': department.name
        })
    
    except Department.DoesNotExist:
        return JsonResponse({
            'error': _('بخش مورد نظر یافت نشد.'),
            'categories': []
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'error': _('خطا در دریافت دسته‌بندی‌ها'),
            'categories': []
        }, status=500)
```

**URL Configuration:**

```python
# tickets/urls.py
urlpatterns = [
    # ... existing patterns ...
    path('api/departments/<int:department_id>/categories/', views.get_department_categories, name='department_categories_api'),
]
```

### 3.2 Frontend Implementation (JavaScript)

**File:** `templates/tickets/ticket_form.html` or `static/tickets/js/ticket_form.js`

**JavaScript Implementation:**

```javascript
// Cascading dropdown for department -> category
(function() {
    'use strict';
    
    document.addEventListener('DOMContentLoaded', function() {
        const departmentSelect = document.getElementById('id_target_department'); // Adjust selector
        const categorySelect = document.getElementById('id_ticket_category'); // Adjust selector
        const categoryFieldWrapper = document.getElementById('category-field-wrapper'); // Wrapper for category field
        
        if (!departmentSelect || !categorySelect) {
            return; // Elements not found, exit
        }
        
        // Store original category options (if any)
        const originalCategoryOptions = Array.from(categorySelect.options);
        
        /**
         * Load categories for selected department via AJAX
         */
        function loadCategories(departmentId) {
            if (!departmentId) {
                // No department selected, clear categories
                clearCategorySelect();
                return;
            }
            
            // Show loading state
            categorySelect.disabled = true;
            categorySelect.innerHTML = '<option value="">در حال بارگذاری...</option>';
            
            // Fetch categories from API
            fetch(`/tickets/api/departments/${departmentId}/categories/`, {
                method: 'GET',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'Content-Type': 'application/json',
                },
                credentials: 'same-origin',
            })
            .then(response => response.json())
            .then(data => {
                // Clear existing options
                categorySelect.innerHTML = '';
                
                if (data.success && data.categories && data.categories.length > 0) {
                    // Add default option
                    const defaultOption = document.createElement('option');
                    defaultOption.value = '';
                    defaultOption.textContent = '-- انتخاب دسته‌بندی --';
                    categorySelect.appendChild(defaultOption);
                    
                    // Add category options
                    data.categories.forEach(category => {
                        const option = document.createElement('option');
                        option.value = category.id;
                        option.textContent = category.name;
                        if (category.description) {
                            option.title = category.description; // Tooltip
                        }
                        categorySelect.appendChild(option);
                    });
                    
                    // Show category field
                    if (categoryFieldWrapper) {
                        categoryFieldWrapper.style.display = 'block';
                    }
                    categorySelect.disabled = false;
                } else {
                    // No categories found - show fallback
                    handleNoCategories(data.department_name || 'این بخش');
                }
            })
            .catch(error => {
                console.error('Error loading categories:', error);
                handleCategoryLoadError();
            });
        }
        
        /**
         * Clear category select dropdown
         */
        function clearCategorySelect() {
            categorySelect.innerHTML = '<option value="">-- ابتدا بخش مقصد را انتخاب کنید --</option>';
            categorySelect.disabled = true;
            if (categoryFieldWrapper) {
                categoryFieldWrapper.style.display = 'none';
            }
        }
        
        /**
         * Handle case when no categories are defined
         */
        function handleNoCategories(departmentName) {
            categorySelect.innerHTML = '<option value="">-- این بخش دسته‌بندی تعریف نکرده است --</option>';
            categorySelect.disabled = true;
            
            // Optional: Show info message
            const infoMessage = document.createElement('div');
            infoMessage.className = 'alert alert-info mt-2';
            infoMessage.id = 'category-info-message';
            infoMessage.innerHTML = `
                <i class="fas fa-info-circle"></i>
                بخش "${departmentName}" هنوز دسته‌بندی تعریف نکرده است.
                می‌توانید تیکت را بدون دسته‌بندی ارسال کنید.
            `;
            
            // Remove existing message if any
            const existingMessage = document.getElementById('category-info-message');
            if (existingMessage) {
                existingMessage.remove();
            }
            
            // Insert message after category field
            if (categoryFieldWrapper) {
                categoryFieldWrapper.appendChild(infoMessage);
            }
        }
        
        /**
         * Handle category load error
         */
        function handleCategoryLoadError() {
            categorySelect.innerHTML = '<option value="">-- خطا در بارگذاری دسته‌بندی‌ها --</option>';
            categorySelect.disabled = true;
        }
        
        // Event listener for department selection change
        departmentSelect.addEventListener('change', function() {
            const selectedDepartmentId = this.value;
            loadCategories(selectedDepartmentId);
        });
        
        // Load categories on page load if department is pre-selected
        if (departmentSelect.value) {
            loadCategories(departmentSelect.value);
        }
        
        // Initial state: Disable category if no department selected
        if (!departmentSelect.value) {
            clearCategorySelect();
        }
    });
})();
```

### 3.3 Template Integration

**File:** `templates/tickets/ticket_form.html`

**Template Changes:**

```django
<!-- Department Selection Field (existing) -->
<div class="form-group">
    <label for="id_target_department">{{ form.target_department.label }}</label>
    {{ form.target_department }}
    {% if form.target_department.errors %}
        <div class="text-danger">{{ form.target_department.errors }}</div>
    {% endif %}
</div>

<!-- Category Selection Field (dynamic) -->
<div class="form-group" id="category-field-wrapper">
    <label for="id_ticket_category">
        {{ form.ticket_category.label }}
        <small class="text-muted">(پس از انتخاب بخش مقصد نمایش داده می‌شود)</small>
    </label>
    {{ form.ticket_category }}
    {% if form.ticket_category.errors %}
        <div class="text-danger">{{ form.ticket_category.errors }}</div>
    {% endif %}
    <small class="form-text text-muted">
        دسته‌بندی‌ها بر اساس بخش مقصد انتخاب شده نمایش داده می‌شوند.
    </small>
</div>
```

---

## 4. Engineering Guardrails and Scalability

### 4.1 Data Validation

**File:** `tickets/forms.py` or `tickets/views.py`

**Backend Validation:**

```python
# tickets/forms.py
class TicketForm(forms.ModelForm):
    """Enhanced ticket form with category validation"""
    
    class Meta:
        model = Ticket
        fields = ['title', 'description', 'target_department', 'ticket_category', 'priority', ...]
    
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
        
        # Validate department is a service provider (if category is provided)
        if ticket_category and target_department:
            if not target_department.is_service_provider:
                raise forms.ValidationError({
                    'target_department': _(
                        'بخش انتخاب شده به عنوان ارائه‌دهنده خدمات فعال نیست.'
                    )
                })
        
        return cleaned_data
```

**View-Level Validation:**

```python
# tickets/views.py
@login_required
def ticket_create(request):
    """Create ticket with category validation"""
    if request.method == 'POST':
        form = TicketForm(request.POST, request.FILES)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.created_by = request.user
            
            # Additional validation: Prevent ID injection
            category_id = request.POST.get('ticket_category')
            department_id = request.POST.get('target_department')
            
            if category_id and department_id:
                try:
                    category = TicketCategory.objects.get(id=category_id)
                    department = Department.objects.get(id=department_id)
                    
                    # Critical: Verify category belongs to department
                    if category.department_id != department.id:
                        messages.error(request, _('دسته‌بندی انتخاب شده معتبر نیست.'))
                        return render(request, 'tickets/ticket_form.html', {'form': form})
                    
                except (TicketCategory.DoesNotExist, Department.DoesNotExist):
                    messages.error(request, _('دسته‌بندی یا بخش انتخاب شده معتبر نیست.'))
                    return render(request, 'tickets/ticket_form.html', {'form': form})
            
            ticket.save()
            messages.success(request, _('تیکت با موفقیت ایجاد شد.'))
            return redirect('tickets:ticket_detail', ticket_id=ticket.id)
    else:
        form = TicketForm()
    
    return render(request, 'tickets/ticket_form.html', {'form': form})
```

### 4.2 Performance Optimization

**Caching Strategy:**

```python
# tickets/views.py (or tickets/utils.py)
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

def invalidate_category_cache(department_id):
    """Invalidate category cache when categories change"""
    cache_key = f'dept_categories_{department_id}'
    cache.delete(cache_key)

@receiver(post_save, sender=TicketCategory)
def category_saved(sender, instance, **kwargs):
    """Invalidate cache when category is saved"""
    invalidate_category_cache(instance.department_id)

@receiver(post_delete, sender=TicketCategory)
def category_deleted(sender, instance, **kwargs):
    """Invalidate cache when category is deleted"""
    invalidate_category_cache(instance.department_id)
```

**Database Query Optimization:**

```python
# Use select_related for department lookups
categories = TicketCategory.objects.filter(
    department=department,
    is_active=True
).select_related('department').order_by('sort_order', 'name')
```

### 4.3 Reporting Consistency

**Enhanced Reporting Queries:**

```python
# tickets/views.py (reporting views)
def department_heatmap_report(request):
    """Generate departmental heatmap showing category distribution"""
    # Group tickets by department and category
    from django.db.models import Count
    
    heatmap_data = Ticket.objects.filter(
        ticket_category__isnull=False
    ).values(
        'target_department__name',
        'ticket_category__name',
        'target_department_id',
        'ticket_category_id'
    ).annotate(
        count=Count('id')
    ).order_by('target_department__name', '-count')
    
    context = {
        'heatmap_data': heatmap_data,
    }
    return render(request, 'tickets/reports/heatmap.html', context)
```

---

## 5. URL Configuration

**File:** `tickets/urls.py`

**URL Patterns:**

```python
urlpatterns = [
    # ... existing patterns ...
    
    # Category Management (Supervisor only)
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('categories/<int:category_id>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:category_id>/delete/', views.category_delete, name='category_delete'),
    
    # API Endpoints
    path('api/departments/<int:department_id>/categories/', views.get_department_categories, name='department_categories_api'),
]
```

---

## 6. Verification and Acceptance Criteria (UAT)

### 6.1 Permission Check

**Test Case:** Supervisor of Non-Service Department

**Steps:**
1. Log in as supervisor of a department where `is_service_provider=False`
2. Navigate to dashboard/sidebar
3. Verify "Category Management" menu item is NOT visible

**Expected Result:** Menu item is hidden

**Implementation Verification:**
- Context processor returns `can_manage_categories=False`
- Template conditional check works correctly

### 6.2 Modularity Test

**Test Case:** Category Isolation Between Departments

**Steps:**
1. Log in as supervisor of IT department
2. Create category "Software Issue" in IT department
3. Log in as supervisor of Logistics department
4. Create ticket with destination = IT department
5. Verify "Software Issue" category appears in dropdown
6. Create ticket with destination = Logistics department
7. Verify "Software Issue" category does NOT appear

**Expected Result:** Categories are department-specific

**Implementation Verification:**
- API endpoint filters by department
- Frontend loads correct categories for selected department

### 6.3 End-to-End Flow

**Test Case:** Complete Ticket Creation Flow

**Steps:**
1. User navigates to "Create Ticket" form
2. Selects "IT" as destination department
3. Category dropdown automatically updates (AJAX call)
4. "Software Issue" category appears in dropdown
5. User selects "Software Issue"
6. Submits ticket
7. Ticket is saved with correct `department_id` and `ticket_category_id`

**Expected Result:** Ticket created successfully with correct associations

**Implementation Verification:**
- Cascading dropdown works correctly
- Backend validation passes
- Ticket saved with correct foreign keys

### 6.4 Security Test: ID Injection Prevention

**Test Case:** Attempt to Submit Invalid Category-Department Combination

**Steps:**
1. User selects "IT" department
2. Inspect network request, modify category_id to belong to different department
3. Submit form
4. Verify backend rejects the request

**Expected Result:** Validation error, ticket not created

**Implementation Verification:**
- Form validation checks category.department == target_department
- View-level validation prevents ID injection

---

## 7. Implementation Roadmap

### Phase 1: Database Schema (Week 1)
- [ ] Add `is_service_provider` field to Department model
- [ ] Create TicketCategory model
- [ ] Create and run migrations
- [ ] Add `ticket_category` field to Ticket model (optional, non-breaking)

### Phase 2: Category Management Interface (Week 2)
- [ ] Implement category list view
- [ ] Implement category create/edit/delete views
- [ ] Create category forms
- [ ] Create category management templates
- [ ] Add menu visibility logic

### Phase 3: Dynamic Form Integration (Week 3)
- [ ] Create API endpoint for category fetching
- [ ] Implement JavaScript cascading dropdown
- [ ] Update ticket form template
- [ ] Add caching layer

### Phase 4: Validation and Security (Week 4)
- [ ] Implement form-level validation
- [ ] Implement view-level validation
- [ ] Add ID injection prevention
- [ ] Security testing

### Phase 5: Testing and Documentation (Week 5)
- [ ] Unit tests for models
- [ ] Integration tests for views
- [ ] Frontend testing
- [ ] User acceptance testing
- [ ] Documentation updates

---

## 8. Migration Strategy

### 8.1 Data Migration (If Replacing Existing Category System)

**Migration Script:**

```python
# tickets/migrations/XXXX_migrate_categories.py
from django.db import migrations

def migrate_old_categories_to_new_system(apps, schema_editor):
    """
    Migrate existing category data to new TicketCategory model.
    This assumes existing categories are stored in a CharField.
    """
    Ticket = apps.get_model('tickets', 'Ticket')
    TicketCategory = apps.get_model('tickets', 'TicketCategory')
    Department = apps.get_model('tickets', 'Department')
    
    # Get all unique old category values
    old_categories = Ticket.objects.values_list('category', flat=True).distinct()
    
    # Create default categories for each service provider department
    for department in Department.objects.filter(is_service_provider=True):
        for old_category in old_categories:
            if old_category:  # Skip empty values
                TicketCategory.objects.get_or_create(
                    department=department,
                    name=old_category,
                    defaults={
                        'is_active': True,
                        'sort_order': 0,
                    }
                )

class Migration(migrations.Migration):
    dependencies = [
        ('tickets', 'XXXX_create_ticket_category'),
    ]

    operations = [
        migrations.RunPython(migrate_old_categories_to_new_system),
    ]
```

---

## 9. Performance Considerations

### 9.1 Caching Strategy

**Cache Keys:**
- `dept_categories_{department_id}` - Category list for department (1 hour TTL)

**Cache Invalidation:**
- On category create/update/delete
- On department service provider status change

### 9.2 Database Indexes

**Recommended Indexes:**
- `(department_id, is_active)` - For filtering active categories
- `(department_id, sort_order)` - For ordering categories
- `(department_id, name)` - For unique constraint check

### 9.3 Query Optimization

**Best Practices:**
- Use `select_related('department')` when loading categories
- Limit category queries to active categories only
- Use prefetch_related for bulk operations

---

## 10. Security Considerations

### 10.1 Multi-Tenant Isolation

**Critical Requirements:**
- All category queries MUST filter by `department=user.department`
- Use `get_object_or_404` with department filter
- Never trust user-provided category_id without validation

### 10.2 Input Validation

**Required Validations:**
- Category ID belongs to selected department
- Department is a service provider
- User has permission to create categories
- Category name uniqueness per department

### 10.3 SQL Injection Prevention

**Django ORM Usage:**
- Always use Django ORM (not raw SQL)
- Use parameterized queries via ORM
- Validate all user inputs

---

## 11. Conclusion

This specification provides a comprehensive blueprint for implementing a Dynamic Multi-Tenant Ticket Categorization System. The design emphasizes:

- ✅ **Multi-tenant isolation** - Department-level data segregation
- ✅ **Dynamic UI** - Cascading dropdowns for seamless UX
- ✅ **Security** - Backend validation and ID injection prevention
- ✅ **Performance** - Caching and query optimization
- ✅ **Scalability** - Modular architecture for future extensions
- ✅ **User Experience** - Intuitive category management interface

**Status:** Specification complete and ready for implementation review.

---

**Document Version:** 1.0  
**Last Updated:** 2024  
**Status:** Technical Blueprint Complete


