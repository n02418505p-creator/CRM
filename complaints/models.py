import re
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

REFERENCE_PATTERN = re.compile(r"^CMP-\d{8}-[0-9A-F]{6}$")
ENQUIRY_REFERENCE_PATTERN = re.compile(r"^ENQ-\d{8}-[0-9A-F]{6}$")
REFERENCE_SEARCH = re.compile(r"(?:CMP|ENQ)-\d{8}-[0-9A-F]{6}", re.IGNORECASE)


def generate_reference():
    """e.g. CMP-20261118-7F3A9C. The website generates the same format."""
    return f"CMP-{timezone.localdate():%Y%m%d}-{secrets.token_hex(3).upper()}"


def generate_enquiry_reference():
    """e.g. ENQ-20261118-7F3A9C"""
    return "ENQ-" + generate_reference()[4:]


class Complaint(models.Model):
    """One case in the CRM: a complaint, or an enquiry (a client question)."""

    class CaseType(models.TextChoices):
        COMPLAINT = "complaint", "Complaint"
        ENQUIRY = "enquiry", "Enquiry"

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

    case_type = models.CharField("type", max_length=20, choices=CaseType.choices, default=CaseType.COMPLAINT, db_index=True)
    reference = models.CharField(max_length=32, unique=True, default=generate_reference, editable=False)
    date_received = models.DateTimeField("date received", default=timezone.now, db_index=True)
    client_name = models.CharField("client name", max_length=150)
    phone_number = models.CharField("phone number", max_length=40, blank=True)
    email_address = models.EmailField("email address", blank=True)
    subject = models.CharField(max_length=200, blank=True)
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
        permissions = [
            ("handle_complaints", "Can work on complaints"),
            ("handle_enquiries", "Can work on enquiries"),
        ]

    def __str__(self):
        return f"{self.reference} – {self.client_name}"

    @property
    def is_enquiry(self):
        return self.case_type == self.CaseType.ENQUIRY

    @property
    def noun(self):
        return "enquiry" if self.is_enquiry else "complaint"

    @property
    def noun_title(self):
        return self.noun.capitalize()

    @property
    def details_label(self):
        return "Message" if self.is_enquiry else "Nature of the complaint"

    @property
    def is_open(self):
        return self.status in (self.Status.NEW, self.Status.IN_PROGRESS)

    def days_open(self):
        if not self.date_received:
            return None
        start = timezone.localtime(self.date_received).date()
        end = self.resolution_date or timezone.localdate()
        return max((end - start).days, 0)

    @property
    def is_overdue(self):
        return self.is_open and (self.days_open() or 0) > settings.COMPLAINT_TARGET_DAYS

    def save(self, *args, **kwargs):
        if self.is_enquiry and self._state.adding and self.reference.startswith("CMP-"):
            self.reference = "ENQ-" + self.reference[4:]
        # Stamp the resolution date automatically when a complaint is resolved/closed.
        if not self.is_open and self.resolution_date is None:
            self.resolution_date = timezone.localdate()
        super().save(*args, **kwargs)


class ComplaintEvent(models.Model):
    """One entry on a complaint's timeline."""

    class Kind(models.TextChoices):
        CREATED = "created", "Created"
        STATUS = "status", "Status change"
        ASSIGNED = "assigned", "Assignment"
        NOTE = "note", "Note"
        UPDATED = "updated", "Update"
        CLIENT = "client", "Emailed to client"
        REPLY = "reply", "Client reply"

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    message = models.TextField()
    # For client replies: the sender and the email's Message-ID (to ignore duplicates).
    sender = models.CharField(max_length=254, blank=True)
    external_id = models.CharField(max_length=255, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.complaint.reference}: {self.message[:50]}"


class Notification(models.Model):
    """An in-portal notification for one staff member."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="complaint_notifications"
    )
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.message
