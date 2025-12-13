from django.db import migrations


def noop_forward(apps, schema_editor):
    # Label is taken from code; no DB change required
    pass


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0012_alter_ticket_resolved_at_alter_ticket_status'),
    ]

    operations = [
        migrations.RunPython(noop_forward, noop_reverse),
    ]