from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0013_rename_remote_access_label'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='access_approval_status',
            field=models.CharField(
                verbose_name='وضعیت تایید دسترسی شبکه',
                max_length=20,
                choices=[
                    ('not_required', 'بدون نیاز به تایید'),
                    ('pending', 'در انتظار تایید سرگروه'),
                    ('approved', 'تایید شده'),
                    ('rejected', 'رد شده'),
                ],
                default='not_required'
            ),
        ),
    ]