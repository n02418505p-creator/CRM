from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("complaints", "0002_events_notifications"),
    ]

    operations = [
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
                ],
                max_length=20,
            ),
        ),
    ]
