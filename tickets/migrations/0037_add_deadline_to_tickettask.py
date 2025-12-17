# Generated migration for adding deadline field to TicketTask

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0036_department_supervisor_user_supervised_departments_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tickettask',
            name='deadline',
            field=models.DateTimeField(blank=True, help_text='تاریخ و زمان مهلت انجام تسک', null=True, verbose_name='مهلت انجام'),
        ),
    ]





