import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import complaints.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Complaint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.CharField(default=complaints.models.generate_reference, editable=False, max_length=32, unique=True)),
                ("date_received", models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name="date received")),
                ("client_name", models.CharField(max_length=150, verbose_name="client name")),
                ("phone_number", models.CharField(max_length=40, verbose_name="phone number")),
                ("email_address", models.EmailField(blank=True, max_length=254, verbose_name="email address")),
                ("nature_of_complaint", models.TextField(verbose_name="nature of the complaint")),
                ("staff_member_involved", models.CharField(blank=True, max_length=150, verbose_name="staff member involved")),
                ("action_taken", models.TextField(blank=True, verbose_name="action taken")),
                ("resolution_date", models.DateField(blank=True, null=True, verbose_name="resolution date")),
                ("status", models.CharField(choices=[("new", "New"), ("in_progress", "In progress"), ("resolved", "Resolved"), ("closed", "Closed")], db_index=True, default="new", max_length=20)),
                ("remarks", models.TextField(blank=True)),
                ("source", models.CharField(choices=[("website", "Website form"), ("phone", "Phone"), ("email", "Email"), ("in_person", "In person"), ("other", "Other")], default="website", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_complaints", to=settings.AUTH_USER_MODEL, verbose_name="assigned to")),
            ],
            options={
                "ordering": ["-date_received"],
            },
        ),
    ]
