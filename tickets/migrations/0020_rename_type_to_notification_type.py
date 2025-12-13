# Generated manually to fix column name mismatch

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0019_add_notification_fields'),
    ]

    operations = [
        migrations.RenameField(
            model_name='notification',
            old_name='type',
            new_name='notification_type',
        ),
    ] 