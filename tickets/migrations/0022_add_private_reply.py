# Generated manually for Private Reply feature

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0021_alter_notification_notification_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='reply',
            name='is_private',
            field=models.BooleanField(
                default=False,
                help_text='این پاسخ فقط برای کارمند دریافت‌کننده قابل مشاهده است',
                verbose_name='پاسخ خصوصی'
            ),
        ),
    ] 