# Generated migration for notification performance optimization
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0044_department_is_service_provider_and_more'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['-created_at'], name='tickets_not_created_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['is_read'], name='tickets_not_is_read_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['recipient', '-created_at'], name='tickets_not_recip_creat_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['category', 'is_read'], name='tickets_not_cat_read_idx'),
        ),
    ]


