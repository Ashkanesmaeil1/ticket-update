from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0042_add_viewed_action_to_ticketactivitylog'),
    ]

    operations = [
        migrations.AddField(
            model_name='department',
            name='has_warehouse',
            field=models.BooleanField(default=False, help_text='اگر فعال باشد، سرپرست این بخش می‌تواند به ماژول انبار دسترسی داشته باشد', verbose_name='انبار'),
        ),
    ]

