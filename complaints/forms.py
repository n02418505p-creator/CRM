from django import forms
from django.utils import timezone

from . import services
from .models import Complaint

DATETIME_FORMAT = "%Y-%m-%dT%H:%M"


class StaffChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return services.display_name(obj)


class ComplaintCreateForm(forms.ModelForm):
    """Used by staff to log a complaint received by phone, email or in person."""

    assigned_to = StaffChoiceField(queryset=None, required=False, empty_label="Unassigned", label="Assign to")

    class Meta:
        model = Complaint
        fields = [
            "case_type",
            "date_received",
            "source",
            "client_name",
            "phone_number",
            "email_address",
            "subject",
            "nature_of_complaint",
            "staff_member_involved",
            "assigned_to",
        ]
        labels = {"nature_of_complaint": "Details", "case_type": "This is a"}
        widgets = {
            "date_received": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_FORMAT),
            "nature_of_complaint": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, allowed_types=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed_types = allowed_types or list(Complaint.CaseType.values)
        self.fields["case_type"].choices = [c for c in Complaint.CaseType.choices if c[0] in allowed_types]
        # Only people who can work on this type of case can be assigned it.
        wanted = self.data.get("case_type") or self.initial.get("case_type") or allowed_types[0]
        self.fields["assigned_to"].queryset = services.handlers(wanted if wanted in allowed_types else allowed_types[0])
        self.fields["date_received"].input_formats = [DATETIME_FORMAT, "%Y-%m-%d %H:%M"]
        self.fields["source"].choices = [c for c in Complaint.Source.choices if c[0] != Complaint.Source.WEBSITE]

    def clean(self):
        data = super().clean()
        if data.get("case_type") == Complaint.CaseType.COMPLAINT and not data.get("phone_number"):
            self.add_error("phone_number", "A phone number is needed for complaints.")
        if not data.get("phone_number") and not data.get("email_address"):
            self.add_error("email_address", "Give at least a phone number or an email address.")
        return data
        if not self.is_bound:
            self.initial.setdefault("date_received", timezone.localtime().strftime(DATETIME_FORMAT))
            self.initial.setdefault("source", Complaint.Source.PHONE)


class HandlingForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ["action_taken", "resolution_date", "remarks"]
        widgets = {
            "action_taken": forms.Textarea(attrs={"rows": 4}),
            "resolution_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }


class DetailsForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ["client_name", "phone_number", "email_address", "subject", "nature_of_complaint", "staff_member_involved"]
        widgets = {"nature_of_complaint": forms.Textarea(attrs={"rows": 5})}
        labels = {"nature_of_complaint": "Details"}
