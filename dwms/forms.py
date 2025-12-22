from django import forms
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from .models import (
    DepartmentWarehouse, StorageLocation, ItemCategory, Item,
    StockBatch, StockMovement, LendRecord, ItemCode
)

User = get_user_model()


class StorageLocationForm(forms.ModelForm):
    class Meta:
        model = StorageLocation
        fields = ['name', 'code', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('نام محل نگهداری')
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('کد محل (اختیاری)')
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('توضیحات')
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
        labels = {
            'name': _('نام محل'),
            'code': _('کد محل'),
            'description': _('توضیحات'),
            'is_active': _('فعال'),
        }


class ItemCategoryForm(forms.ModelForm):
    class Meta:
        model = ItemCategory
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('نام دسته‌بندی')
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('توضیحات')
            }),
        }
        labels = {
            'name': _('نام دسته‌بندی'),
            'description': _('توضیحات'),
        }


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'category', 'unit', 'sku', 'is_serialized',
                  'min_stock_threshold', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('نام کالا')
            }),
            'category': forms.Select(attrs={
                'class': 'form-select'
            }),
            'unit': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('واحد: عدد، متر، بسته')
            }),
            'sku': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('کد کالا')
            }),
            'is_serialized': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'min_stock_threshold': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('توضیحات')
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
        labels = {
            'name': _('نام کالا'),
            'category': _('دسته‌بندی'),
            'unit': _('واحد'),
            'sku': _('کد کالا'),
            'is_serialized': _('سریال‌دار'),
            'min_stock_threshold': _('حداقل موجودی'),
            'description': _('توضیحات'),
            'is_active': _('فعال'),
        }

    def __init__(self, *args, **kwargs):
        warehouse = kwargs.pop('warehouse', None)
        super().__init__(*args, **kwargs)
        if warehouse:
            self.fields['category'].queryset = ItemCategory.objects.filter(
                warehouse=warehouse
            )


class StockBatchForm(forms.ModelForm):
    class Meta:
        model = StockBatch
        fields = ['item', 'location', 'batch_code', 'quantity', 'expiry_date']
        widgets = {
            'item': forms.Select(attrs={
                'class': 'form-select'
            }),
            'location': forms.Select(attrs={
                'class': 'form-select'
            }),
            'batch_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('کد بچ (اختیاری)')
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            }),
            'expiry_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
        }
        labels = {
            'item': _('کالا'),
            'location': _('محل نگهداری'),
            'batch_code': _('کد بچ'),
            'quantity': _('مقدار'),
            'expiry_date': _('تاریخ انقضا'),
        }

    def __init__(self, *args, **kwargs):
        warehouse = kwargs.pop('warehouse', None)
        super().__init__(*args, **kwargs)
        if warehouse:
            self.fields['item'].queryset = Item.objects.filter(
                warehouse=warehouse,
                is_active=True
            )
            self.fields['location'].queryset = StorageLocation.objects.filter(
                warehouse=warehouse,
                is_active=True
            )


class StockMovementForm(forms.Form):
    """Form for creating stock movements"""
    MOVEMENT_TYPE_CHOICES = [
        ('IN', _('ورود')),
        ('OUT', _('خروج')),
        ('ADJUSTMENT', _('اصلاح')),
    ]

    REASON_CHOICES = [
        ('PURCHASE', _('خرید')),
        ('CONSUMPTION', _('مصرف')),
        ('TRANSFER', _('انتقال')),
        ('CORRECTION', _('اصلاح')),
        ('OTHER', _('سایر')),
    ]

    item = forms.ModelChoiceField(
        queryset=Item.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('کالا')
    )
    batch = forms.ModelChoiceField(
        queryset=StockBatch.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('بچ'),
        required=False
    )
    location = forms.ModelChoiceField(
        queryset=StorageLocation.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('محل نگهداری')
    )
    movement_type = forms.ChoiceField(
        choices=MOVEMENT_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('نوع حرکت')
    )
    quantity = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0'
        }),
        label=_('مقدار')
    )
    reason = forms.ChoiceField(
        choices=REASON_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('دلیل'),
        required=False
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': _('یادداشت (اختیاری)')
        }),
        label=_('یادداشت')
    )

    def __init__(self, *args, **kwargs):
        warehouse = kwargs.pop('warehouse', None)
        item = kwargs.pop('item', None)
        super().__init__(*args, **kwargs)
        if warehouse:
            self.fields['item'].queryset = Item.objects.filter(
                warehouse=warehouse,
                is_active=True
            )
            self.fields['location'].queryset = StorageLocation.objects.filter(
                warehouse=warehouse,
                is_active=True
            )
            if item:
                self.fields['item'].initial = item
                self.fields['item'].widget.attrs['readonly'] = True
                self.fields['batch'].queryset = StockBatch.objects.filter(
                    item=item
                )


class LendRecordForm(forms.ModelForm):
    # Due date field (Jalali date and time combined: "YYYY/MM/DD HH:MM")
    due_date = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('برای انتخاب تاریخ و زمان کلیک کنید'),
            'id': 'due-date-input',
            'readonly': True,  # Will be set by date picker
            'autocomplete': 'off',  # Prevent browser autocomplete
        }),
        label=_('تاریخ موعد بازگشت')
    )
    
    class Meta:
        model = LendRecord
        fields = ['item', 'batch', 'quantity', 'borrower', 'notes']
        widgets = {
            'item': forms.Select(attrs={
                'class': 'form-select'
            }),
            'batch': forms.Select(attrs={
                'class': 'form-select'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0.01'
            }),
            'borrower': forms.Select(attrs={
                'class': 'form-select'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('یادداشت (اختیاری)')
            }),
        }
        labels = {
            'item': _('کالا'),
            'batch': _('بچ'),
            'quantity': _('مقدار'),
            'borrower': _('امانت‌گیرنده'),
            'notes': _('یادداشت'),
        }

    def __init__(self, *args, **kwargs):
        warehouse = kwargs.pop('warehouse', None)
        item = kwargs.pop('item', None)
        super().__init__(*args, **kwargs)
        if warehouse:
            self.fields['item'].queryset = Item.objects.filter(
                warehouse=warehouse,
                is_active=True
            )
            if item:
                self.fields['item'].initial = item
                self.fields['item'].widget.attrs['readonly'] = True
                self.fields['batch'].queryset = StockBatch.objects.filter(
                    item=item
                )
            # Borrower should be employees/technicians
            self.fields['borrower'].queryset = User.objects.filter(
                is_active=True
            ).exclude(role='it_manager').order_by('first_name', 'last_name')
    
    def clean_due_date(self):
        """Validate and convert Jalali due_date to Gregorian date"""
        from django.core.exceptions import ValidationError
        due_date = self.cleaned_data.get('due_date')
        
        if not due_date:
            raise ValidationError(_('تاریخ موعد بازگشت الزامی است.'))
        
        # Use the same validation logic as TicketTaskForm
        from tickets.calendar_services.jalali_calendar import JalaliCalendarService
        try:
            raw_value = str(due_date).strip()
            if not raw_value:
                raise ValidationError(_('تاریخ موعد بازگشت الزامی است.'))
            
            # Collapse multiple spaces and normalize
            normalized = ' '.join(raw_value.split())
            parts = normalized.split(' ')
            if len(parts) < 1:
                raise ValidationError(_('فرمت تاریخ و زمان صحیح نیست. از فرمت YYYY/MM/DD HH:MM استفاده کنید.'))
            
            date_str = parts[0]
            time_str = parts[1] if len(parts) > 1 else '23:59'  # Default to end of day if not provided
            
            # Parse date (Jalali format: YYYY/MM/DD)
            date_parts = date_str.split('/')
            if len(date_parts) != 3:
                raise ValidationError(_('فرمت تاریخ صحیح نیست. از فرمت YYYY/MM/DD استفاده کنید (مثال: 1403/09/25).'))
            
            try:
                year = int(date_parts[0])
                month = int(date_parts[1])
                day = int(date_parts[2])
            except (ValueError, TypeError) as e:
                raise ValidationError(_('تاریخ باید شامل اعداد باشد. از فرمت YYYY/MM/DD استفاده کنید (مثال: 1403/09/25).')) from e
            
            # Validate Jalali date ranges
            if year < 1300 or year > 1500 or month < 1 or month > 12 or day < 1 or day > 31:
                raise ValidationError(_('محدوده تاریخ معتبر نیست. سال بین 1300-1500، ماه 1-12، روز 1-31.'))
            
            # Validate Jalali date using service
            if not JalaliCalendarService.validate_jalali_date(year, month, day):
                raise ValidationError(_('تاریخ وارد شده معتبر نیست. لطفاً تاریخ شمسی صحیح را وارد کنید.'))
            
            # Parse time (format: HH:MM, 24-hour)
            time_parts = time_str.split(':')
            if len(time_parts) != 2:
                raise ValidationError(_('فرمت زمان صحیح نیست. از فرمت HH:MM استفاده کنید (مثال: 14:30).'))
            
            try:
                hour = int(time_parts[0])
                minute = int(time_parts[1])
            except (ValueError, TypeError) as e:
                raise ValidationError(_('زمان باید شامل اعداد باشد. از فرمت HH:MM استفاده کنید (مثال: 14:30).')) from e
            
            # Validate time range (24-hour format)
            if hour < 0 or hour > 23:
                raise ValidationError(_('ساعت باید بین 00 تا 23 باشد.'))
            if minute < 0 or minute > 59:
                raise ValidationError(_('دقیقه باید بین 00 تا 59 باشد.'))
            
            # Convert Jalali to Gregorian date (for due_date, we only need date, not datetime)
            converted_datetime = JalaliCalendarService.jalali_to_gregorian(
                year, month, day, hour, minute
            )
            # Extract date only (due_date is a DateField, not DateTimeField)
            converted_date = converted_datetime.date()
            
            # Store converted date for use in save method
            self.cleaned_data['due_date_converted'] = converted_date
            
            return due_date  # Return original string for display
        except ValidationError:
            raise
        except (ValueError, IndexError, AttributeError, TypeError) as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Error parsing due_date: {due_date}, error: {str(e)}')
            raise ValidationError(_('فرمت تاریخ و زمان صحیح نیست. از فرمت YYYY/MM/DD HH:MM استفاده کنید (مثال: 1403/09/25 14:30).')) from e
    
    def save(self, commit=True):
        """Override save to apply converted due_date"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            instance = super().save(commit=False)
            logger.info(f'Super().save(commit=False) successful, instance={instance}')
            
            # Use converted date if available
            converted_date = self.cleaned_data.get('due_date_converted', None)
            logger.info(f'Converted date from cleaned_data: {converted_date}')
            
            if converted_date:
                instance.due_date = converted_date
                logger.info(f'Set instance.due_date to {converted_date}')
            else:
                logger.warning('No converted_date found in cleaned_data!')
                # This should not happen if clean_due_date was called
                # But we'll raise an error to prevent saving invalid data
                from django.core.exceptions import ValidationError
                raise ValidationError(_('تاریخ موعد بازگشت به درستی تبدیل نشده است. لطفاً دوباره تلاش کنید.'))
            
            if commit:
                logger.info('Committing instance to database...')
                instance.save()
                logger.info(f'Instance saved successfully, ID={instance.id if hasattr(instance, "id") else "N/A"}')
            return instance
        except Exception as e:
            logger.error(f'Error in LendRecordForm.save(): {str(e)}', exc_info=True)
            raise

