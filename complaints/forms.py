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
            "date_received",
            "source",
            "client_name",
            "phone_number",
            "email_address",
            "nature_of_complaint",
            "staff_member_involved",
            "assigned_to",
        ]
        widgets = {
            "date_received": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_FORMAT),
            "nature_of_complaint": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = services.handlers()
        self.fields["date_received"].input_formats = [DATETIME_FORMAT, "%Y-%m-%d %H:%M"]
        self.fields["source"].choices = [c for c in Complaint.Source.choices if c[0] != Complaint.Source.WEBSITE]
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
        fields = ["client_name", "phone_number", "email_address", "nature_of_complaint", "staff_member_involved"]
        widgets = {"nature_of_complaint": forms.Textarea(attrs={"rows": 5})}
