from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0015_alter_ticket_category'),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255, verbose_name='عنوان')),
                ('message', models.TextField(blank=True, verbose_name='پیام')),
                ('type', models.CharField(choices=[('ticket_urgent', 'تیکت فوری'), ('access_approved', 'تایید دسترسی شبکه'), ('user_created', 'ایجاد کاربر'), ('login', 'ورود'), ('status_done', 'انجام شد')], max_length=50, verbose_name='نوع')),
                ('is_read', models.BooleanField(default=False, verbose_name='خوانده شده')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ایجاد')),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to='tickets.user', verbose_name='دریافت‌کننده')),
                ('ticket', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notifications', to='tickets.ticket', verbose_name='تیکت')),
            ],
            options={
                'verbose_name': 'اعلان',
                'verbose_name_plural': 'اعلان‌ها',
                'ordering': ['-created_at'],
            },
        ),
    ]