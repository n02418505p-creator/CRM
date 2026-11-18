from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("complaints", "0006_roles"),
    ]

    operations = [
        migrations.AddField(
            model_name="complaint",
            name="enquiry_type",
            field=models.CharField(
                blank=True,
                choices=[("general", "General enquiry"), ("service", "Service request")],
                max_length=20,
                verbose_name="enquiry type",
            ),
        ),
        migrations.AddField(
            model_name="complaint",
            name="division",
            field=models.CharField(
                blank=True,
                choices=[("advisory", "MMC Capital Advisory"), ("stockbroking", "MMC Stockbrokers"), ("general", "General")],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="complaint",
            name="service",
            field=models.CharField(blank=True, max_length=120, verbose_name="service"),
        ),
        migrations.AddField(
            model_name="complaint",
            name="organisation",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="complaint",
            name="source_page",
            field=models.CharField(blank=True, max_length=200, verbose_name="sent from page"),
        ),
    ]
