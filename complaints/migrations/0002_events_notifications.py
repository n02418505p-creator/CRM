import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def add_created_events(apps, schema_editor):
    """Give complaints that already exist a 'received' entry on their timeline."""
    Complaint = apps.get_model("complaints", "Complaint")
    ComplaintEvent = apps.get_model("complaints", "ComplaintEvent")
    sources = dict(
        [("website", "Website form"), ("phone", "Phone"), ("email", "Email"), ("in_person", "In person"), ("other", "Other")]
    )
    for complaint in Complaint.objects.all():
        ComplaintEvent.objects.create(
            complaint=complaint,
            kind="created",
            message=f"Complaint received via {sources.get(complaint.source, complaint.source)}.",
            created_at=complaint.date_received,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("complaints", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ComplaintEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("created", "Created"), ("status", "Status change"), ("assigned", "Assignment"), ("note", "Note"), ("updated", "Update")], max_length=20)),
                ("message", models.TextField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("complaint", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="complaints.complaint")),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(max_length=20)),
                ("message", models.CharField(max_length=255)),
                ("is_read", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("complaint", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to="complaints.complaint")),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="complaint_notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.RunPython(add_created_events, migrations.RunPython.noop),
    ]
