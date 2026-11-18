import re
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

REFERENCE_PATTERN = re.compile(r"^CMP-\d{8}-[0-9A-F]{6}$")


def generate_reference():
    """e.g. CMP-20261118-7F3A9C. The website generates the same format."""
    return f"CMP-{timezone.localdate():%Y%m%d}-{secrets.token_hex(3).upper()}"


class Complaint(models.Model):
    """One row of the complaints register."""

    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Source(models.TextChoices):
        WEBSITE = "website", "Website form"
        PHONE = "phone", "Phone"
        EMAIL = "email", "Email"
        IN_PERSON = "in_person", "In person"
        OTHER = "other", "Other"

    reference = models.CharField(max_length=32, unique=True, default=generate_reference, editable=False)
    date_received = models.DateTimeField("date received", default=timezone.now, db_index=True)
    client_name = models.CharField("client name", max_length=150)
    phone_number = models.CharField("phone number", max_length=40)
    email_address = models.EmailField("email address", blank=True)
    nature_of_complaint = models.TextField("nature of the complaint")
    staff_member_involved = models.CharField("staff member involved", max_length=150, blank=True)
    action_taken = models.TextField("action taken", blank=True)
    resolution_date = models.DateField("resolution date", null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    remarks = models.TextField(blank=True)

    # Extra fields that help with handling (not on the original paper register)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="assigned to",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_complaints",
    )
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.WEBSITE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_received"]

    def __str__(self):
        return f"{self.reference} – {self.client_name}"

    @property
    def is_open(self):
        return self.status in (self.Status.NEW, self.Status.IN_PROGRESS)

    def days_open(self):
        if not self.date_received:
            return None
        start = timezone.localtime(self.date_received).date()
        end = self.resolution_date or timezone.localdate()
        return max((end - start).days, 0)

    def save(self, *args, **kwargs):
        # Stamp the resolution date automatically when a complaint is resolved/closed.
        if not self.is_open and self.resolution_date is None:
            self.resolution_date = timezone.localdate()
        super().save(*args, **kwargs)
