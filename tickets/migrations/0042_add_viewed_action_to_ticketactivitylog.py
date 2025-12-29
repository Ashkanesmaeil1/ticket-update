from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0041_rename_tickets_tic_ticket__idx_tickets_tic_ticket__3a1c22_idx_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ticketactivitylog',
            name='action',
            field=models.CharField(
                choices=[
                    ('created', 'ایجاد شد'),
                    ('status_changed', 'تغییر وضعیت'),
                    ('priority_changed', 'تغییر اولویت'),
                    ('assigned', 'تخصیص داده شد'),
                    ('unassigned', 'تخصیص حذف شد'),
                    ('replied', 'پاسخ اضافه شد'),
                    ('updated', 'بروزرسانی شد'),
                    ('access_approved', 'دسترسی تایید شد'),
                    ('access_rejected', 'دسترسی رد شد'),
                    ('attachment_added', 'پیوست اضافه شد'),
                    ('viewed', 'مشاهده شد')
                ],
                max_length=50,
                verbose_name='عمل'
            ),
        ),
    ]





