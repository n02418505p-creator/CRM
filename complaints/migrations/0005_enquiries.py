from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("complaints", "0004_client_replies"),
    ]

    operations = [
        migrations.AddField(
            model_name="complaint",
            name="case_type",
            field=models.CharField(
                choices=[("complaint", "Complaint"), ("enquiry", "Enquiry")],
                db_index=True,
                default="complaint",
                max_length=20,
                verbose_name="type",
            ),
        ),
        migrations.AddField(
            model_name="complaint",
            name="subject",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="phone_number",
            field=models.CharField(blank=True, max_length=40, verbose_name="phone number"),
        ),
    ]
