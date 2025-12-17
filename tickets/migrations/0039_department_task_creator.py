from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0038_calendarday'),
    ]

    operations = [
        migrations.AddField(
            model_name='department',
            name='task_creator',
            field=models.ForeignKey(
                on_delete=models.SET_NULL,
                to=settings.AUTH_USER_MODEL,
                null=True,
                blank=True,
                related_name='departments_as_task_creator',
                verbose_name='ایجادکننده تسک',
                help_text='کارمندی که می‌تواند برای این بخش تسک ایجاد کرده و به سایر کارمندان این بخش تخصیص دهد',
            ),
        ),
    ]


