from django.db import migrations
from django.contrib.auth.hashers import make_password


def set_it_manager_email_password(apps, schema_editor):
    User = apps.get_model('tickets', 'User')
    # Try to find IT manager by role
    it_managers = User.objects.filter(role='it_manager')
    if it_managers.exists():
        for u in it_managers:
            u.email = 'itss@pargasiran.com'
            u.password = make_password('rV23mWq4b')
            u.save(update_fields=['email', 'password'])


def revert_it_manager_email_password(apps, schema_editor):
    # No-op, cannot safely revert password
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0010_alter_ticket_category_alter_user_department_role'),
    ]

    operations = [
        migrations.RunPython(set_it_manager_email_password, revert_it_manager_email_password),
    ]