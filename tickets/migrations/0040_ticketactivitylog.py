from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0039_department_task_creator'),
    ]

    operations = [
        migrations.CreateModel(
            name='TicketActivityLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('created', 'ایجاد شد'), ('status_changed', 'تغییر وضعیت'), ('priority_changed', 'تغییر اولویت'), ('assigned', 'تخصیص داده شد'), ('unassigned', 'تخصیص حذف شد'), ('replied', 'پاسخ اضافه شد'), ('updated', 'بروزرسانی شد'), ('access_approved', 'دسترسی تایید شد'), ('access_rejected', 'دسترسی رد شد'), ('attachment_added', 'پیوست اضافه شد')], max_length=50, verbose_name='عمل')),
                ('description', models.TextField(help_text='توضیحات تغییرات', verbose_name='توضیحات')),
                ('old_value', models.CharField(blank=True, max_length=255, null=True, verbose_name='مقدار قبلی')),
                ('new_value', models.CharField(blank=True, max_length=255, null=True, verbose_name='مقدار جدید')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ایجاد')),
                ('reply', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='activity_logs', to='tickets.reply', verbose_name='پاسخ مرتبط')),
                ('ticket', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='activity_logs', to='tickets.ticket', verbose_name='تیکت')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ticket_activities', to=settings.AUTH_USER_MODEL, verbose_name='کاربر')),
            ],
            options={
                'verbose_name': 'لاگ فعالیت تیکت',
                'verbose_name_plural': 'لاگ\u200cهای فعالیت تیکت',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='ticketactivitylog',
            index=models.Index(fields=['ticket', '-created_at'], name='tickets_tic_ticket__idx'),
        ),
        migrations.AddIndex(
            model_name='ticketactivitylog',
            index=models.Index(fields=['user', '-created_at'], name='tickets_tic_user_id_idx'),
        ),
    ]





