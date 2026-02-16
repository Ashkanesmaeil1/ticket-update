# Generated manually for deadline reminder email flags

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0047_deadlineextensionrequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='tickettask',
            name='deadline_reminder_8h_sent',
            field=models.BooleanField(default=False, editable=False, help_text='آیا ایمیل یادآور ۸ ساعت مانده به مهلت ارسال شده است', verbose_name='یادآور ۸ ساعت ارسال شده'),
        ),
        migrations.AddField(
            model_name='tickettask',
            name='deadline_reminder_2h_sent',
            field=models.BooleanField(default=False, editable=False, help_text='آیا ایمیل یادآور ۲ ساعت مانده به مهلت ارسال شده است', verbose_name='یادآور ۲ ساعت ارسال شده'),
        ),
    ]
