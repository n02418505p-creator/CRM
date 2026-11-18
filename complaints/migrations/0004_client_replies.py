from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("complaints", "0003_event_client_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="complaintevent",
            name="sender",
            field=models.CharField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="complaintevent",
            name="external_id",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="complaintevent",
            name="kind",
            field=models.CharField(
                choices=[
                    ("created", "Created"),
                    ("status", "Status change"),
                    ("assigned", "Assignment"),
                    ("note", "Note"),
                    ("updated", "Update"),
                    ("client", "Emailed to client"),
                    ("reply", "Client reply"),
                ],
                max_length=20,
            ),
        ),
    ]
