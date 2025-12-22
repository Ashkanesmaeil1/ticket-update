from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator
from django.contrib.auth import get_user_model

User = get_user_model()


class DepartmentWarehouse(models.Model):
    """Main warehouse entity for a department - one per department"""
    department = models.OneToOneField(
        'tickets.Department',
        on_delete=models.CASCADE,
        related_name='dwms_warehouse',
        verbose_name=_('بخش'),
        unique=True
    )
    name = models.CharField(
        max_length=200,
        verbose_name=_('نام انبار'),
        help_text=_('نام انبار این بخش')
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('توضیحات')
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('فعال')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('تاریخ ایجاد')
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('تاریخ بروزرسانی')
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_dwms_warehouses',
        verbose_name=_('ایجاد شده توسط')
    )

    class Meta:
        verbose_name = _('انبار بخش')
        verbose_name_plural = _('انبارهای بخش')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.department.name})"

    def get_authorized_supervisors(self):
        """Get all supervisors authorized to manage this warehouse"""
        supervisors = []
        if self.department.supervisor:
            supervisors.append(self.department.supervisor)
        # Add M2M supervisors
        if hasattr(self.department, 'supervisors'):
            supervisors.extend(self.department.supervisors.all())
        return list(set(supervisors))  # Remove duplicates


class StorageLocation(models.Model):
    """Physical or logical storage locations within a warehouse"""
    warehouse = models.ForeignKey(
        DepartmentWarehouse,
        on_delete=models.CASCADE,
        related_name='locations',
        verbose_name=_('انبار')
    )
    name = models.CharField(
        max_length=200,
        verbose_name=_('نام محل')
    )
    code = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_('کد محل'),
        help_text=_('کد کوتاه برای شناسایی محل')
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('توضیحات')
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('فعال')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('تاریخ ایجاد')
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('تاریخ بروزرسانی')
    )

    class Meta:
        verbose_name = _('محل نگهداری')
        verbose_name_plural = _('محل‌های نگهداری')
        ordering = ['name']
        unique_together = [['warehouse', 'code']]  # Code must be unique per warehouse

    def __str__(self):
        return f"{self.name} ({self.warehouse.name})"


class ItemCategory(models.Model):
    """Category for organizing items"""
    warehouse = models.ForeignKey(
        DepartmentWarehouse,
        on_delete=models.CASCADE,
        related_name='categories',
        verbose_name=_('انبار')
    )
    name = models.CharField(
        max_length=100,
        verbose_name=_('نام دسته‌بندی')
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('توضیحات')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('تاریخ ایجاد')
    )

    class Meta:
        verbose_name = _('دسته‌بندی')
        verbose_name_plural = _('دسته‌بندی‌ها')
        ordering = ['name']
        unique_together = [['warehouse', 'name']]

    def __str__(self):
        return f"{self.name} ({self.warehouse.name})"


class Item(models.Model):
    """Catalog item definition - what can be stored"""
    warehouse = models.ForeignKey(
        DepartmentWarehouse,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('انبار')
    )
    name = models.CharField(
        max_length=200,
        verbose_name=_('نام کالا')
    )
    category = models.ForeignKey(
        ItemCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='items',
        verbose_name=_('دسته‌بندی')
    )
    unit = models.CharField(
        max_length=50,
        default='عدد',
        verbose_name=_('واحد'),
        help_text=_('مثال: عدد، متر، بسته')
    )
    sku = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('کد کالا'),
        help_text=_('کد داخلی کالا')
    )
    is_serialized = models.BooleanField(
        default=False,
        verbose_name=_('سریال‌دار'),
        help_text=_('اگر فعال باشد، هر واحد به صورت جداگانه ردیابی می‌شود')
    )
    min_stock_threshold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_('حداقل موجودی'),
        help_text=_('هشدار کمبود موجودی در این مقدار فعال می‌شود')
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('توضیحات')
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('فعال')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('تاریخ ایجاد')
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('تاریخ بروزرسانی')
    )

    class Meta:
        verbose_name = _('کالا')
        verbose_name_plural = _('کالاها')
        ordering = ['name']
        indexes = [
            models.Index(fields=['warehouse', 'is_active']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return f"{self.name} ({self.warehouse.name})"

    def get_total_stock(self):
        """Calculate total stock across all locations"""
        from django.db.models import Sum
        try:
            # Use the correct related_name from StockBatch model
            result = self.stock_batches.aggregate(total=Sum('quantity'))
            return result['total'] or 0
        except Exception:
            return 0

    def is_low_stock(self):
        """Check if item is below threshold"""
        try:
            if self.min_stock_threshold is None or self.min_stock_threshold == 0:
                return False
            return self.get_total_stock() < self.min_stock_threshold
        except Exception:
            return False


class StockBatch(models.Model):
    """Stock batch - quantity of an item at a specific location"""
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='stock_batches',
        verbose_name=_('کالا')
    )
    location = models.ForeignKey(
        StorageLocation,
        on_delete=models.CASCADE,
        related_name='stock_batches',
        verbose_name=_('محل نگهداری')
    )
    batch_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('کد بچ'),
        help_text=_('کد بچ خرید یا شماره فاکتور')
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_('مقدار')
    )
    expiry_date = models.DateField(
        blank=True,
        null=True,
        verbose_name=_('تاریخ انقضا')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('تاریخ ایجاد')
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('تاریخ بروزرسانی')
    )

    class Meta:
        verbose_name = _('بچ موجودی')
        verbose_name_plural = _('بچ‌های موجودی')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['item', 'location']),
        ]

    def __str__(self):
        return f"{self.item.name} - {self.location.name} ({self.quantity} {self.item.unit})"


class StockMovement(models.Model):
    """Immutable log of all stock movements"""
    MOVEMENT_TYPE_CHOICES = [
        ('IN', _('ورود')),
        ('OUT', _('خروج')),
        ('ADJUSTMENT', _('اصلاح')),
    ]

    REASON_CHOICES = [
        ('INITIAL_STOCK', _('موجودی اولیه')),
        ('PURCHASE', _('خرید')),
        ('LEND', _('امانت')),
        ('RETURN', _('بازگشت از امانت')),
        ('CONSUMPTION', _('مصرف')),
        ('TRANSFER', _('انتقال')),
        ('CORRECTION', _('اصلاح')),
        ('OTHER', _('سایر')),
    ]

    warehouse = models.ForeignKey(
        DepartmentWarehouse,
        on_delete=models.CASCADE,
        related_name='movements',
        verbose_name=_('انبار')
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='movements',
        verbose_name=_('کالا')
    )
    batch = models.ForeignKey(
        StockBatch,
        on_delete=models.CASCADE,
        related_name='movements',
        verbose_name=_('بچ')
    )
    location = models.ForeignKey(
        StorageLocation,
        on_delete=models.CASCADE,
        related_name='movements',
        verbose_name=_('محل نگهداری')
    )
    movement_type = models.CharField(
        max_length=20,
        choices=MOVEMENT_TYPE_CHOICES,
        verbose_name=_('نوع حرکت')
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_('مقدار')
    )
    movement_date = models.DateTimeField(
        default=timezone.now,
        verbose_name=_('تاریخ حرکت')
    )
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='dwms_movements',
        verbose_name=_('انجام شده توسط')
    )
    reason = models.CharField(
        max_length=50,
        choices=REASON_CHOICES,
        default='OTHER',
        verbose_name=_('دلیل')
    )
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('یادداشت')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('تاریخ ایجاد')
    )

    class Meta:
        verbose_name = _('حرکت موجودی')
        verbose_name_plural = _('حرکت‌های موجودی')
        ordering = ['-movement_date', '-created_at']
        indexes = [
            models.Index(fields=['warehouse', 'movement_date']),
            models.Index(fields=['item', 'movement_date']),
            models.Index(fields=['performed_by', 'movement_date']),
        ]

    def __str__(self):
        return f"{self.item.name} - {self.get_movement_type_display()} - {self.quantity} ({self.movement_date.strftime('%Y-%m-%d')})"


class LendRecord(models.Model):
    """Asset lending tracking"""
    STATUS_CHOICES = [
        ('OUT', _('امانت داده شده')),
        ('RETURNED', _('بازگردانده شده')),
        ('OVERDUE', _('تأخیر در بازگشت')),
    ]

    warehouse = models.ForeignKey(
        DepartmentWarehouse,
        on_delete=models.CASCADE,
        related_name='lend_records',
        verbose_name=_('انبار')
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='lend_records',
        verbose_name=_('کالا')
    )
    batch = models.ForeignKey(
        StockBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lend_records',
        verbose_name=_('بچ')
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1,
        validators=[MinValueValidator(0)],
        verbose_name=_('مقدار')
    )
    borrower = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='borrowed_items',
        verbose_name=_('امانت‌گیرنده')
    )
    issued_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='issued_lends',
        verbose_name=_('امانت داده شده توسط')
    )
    issue_date = models.DateTimeField(
        default=timezone.now,
        verbose_name=_('تاریخ امانت')
    )
    due_date = models.DateField(
        verbose_name=_('تاریخ موعد بازگشت')
    )
    return_date = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_('تاریخ بازگشت')
    )
    received_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_returns',
        verbose_name=_('دریافت شده توسط')
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='OUT',
        verbose_name=_('وضعیت')
    )
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('یادداشت')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('تاریخ ایجاد')
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('تاریخ بروزرسانی')
    )

    class Meta:
        verbose_name = _('سابقه امانت')
        verbose_name_plural = _('سوابق امانت')
        ordering = ['-issue_date']
        indexes = [
            models.Index(fields=['warehouse', 'status']),
            models.Index(fields=['borrower', 'status']),
            models.Index(fields=['due_date']),
        ]

    def __str__(self):
        item_name = self.item.name if self.item else "کالای حذف شده"
        borrower_name = self.borrower.get_full_name() if self.borrower else "نامشخص"
        status = self.get_status_display() if self.status else "نامشخص"
        return f"{item_name} - {borrower_name} ({status})"

    def is_overdue(self):
        """Check if lend is overdue"""
        if self.status == 'RETURNED':
            return False
        # Handle None due_date gracefully
        if not self.due_date:
            return False
        try:
            return timezone.now().date() > self.due_date
        except (TypeError, AttributeError):
            return False

    def save(self, *args, **kwargs):
        """Auto-update status based on dates"""
        if self.is_overdue() and self.status != 'RETURNED':
            self.status = 'OVERDUE'
        super().save(*args, **kwargs)


class ItemCode(models.Model):
    """QR/Barcode codes for items"""
    CODE_TYPE_CHOICES = [
        ('QR', _('QR Code')),
        ('BARCODE128', _('Barcode 128')),
        ('EAN13', _('EAN-13')),
    ]

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='codes',
        verbose_name=_('کالا')
    )
    code_type = models.CharField(
        max_length=20,
        choices=CODE_TYPE_CHOICES,
        default='QR',
        verbose_name=_('نوع کد')
    )
    code_value = models.CharField(
        max_length=200,
        unique=True,
        verbose_name=_('مقدار کد'),
        help_text=_('کد یکتا برای اسکن')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('تاریخ ایجاد')
    )

    class Meta:
        verbose_name = _('کد کالا')
        verbose_name_plural = _('کدهای کالا')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['code_value']),
        ]

    def __str__(self):
        return f"{self.item.name} - {self.code_value}"


class LowStockAlert(models.Model):
    """Low stock alerts tracking"""
    STATUS_CHOICES = [
        ('OPEN', _('باز')),
        ('ACKNOWLEDGED', _('تأیید شده')),
        ('RESOLVED', _('حل شده')),
    ]

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='low_stock_alerts',
        verbose_name=_('کالا')
    )
    warehouse = models.ForeignKey(
        DepartmentWarehouse,
        on_delete=models.CASCADE,
        related_name='low_stock_alerts',
        verbose_name=_('انبار')
    )
    current_stock = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('موجودی فعلی')
    )
    threshold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('حد آستانه')
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='OPEN',
        verbose_name=_('وضعیت')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('تاریخ ایجاد')
    )
    resolved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_('تاریخ حل شدن')
    )

    class Meta:
        verbose_name = _('هشدار کمبود موجودی')
        verbose_name_plural = _('هشدارهای کمبود موجودی')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['warehouse', 'status']),
        ]

    def __str__(self):
        return f"{self.item.name} - {self.current_stock}/{self.threshold} ({self.get_status_display()})"
