"""The staff portal: Django's admin, set up as a complaints register."""
import csv

from django.contrib import admin, messages
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import Truncator

from .models import Complaint

admin.site.site_header = "MMC Capital · CRM"
admin.site.site_title = "MMC CRM"
admin.site.index_title = "Administration (staff accounts and raw records)"
admin.site.site_url = "/"  # "View site" goes back to the complaints portal

STATUS_COLOURS = {
    Complaint.Status.NEW: ("#b42318", "#fef3f2"),
    Complaint.Status.IN_PROGRESS: ("#b54708", "#fffaeb"),
    Complaint.Status.RESOLVED: ("#067647", "#ecfdf3"),
    Complaint.Status.CLOSED: ("#475467", "#f2f4f7"),
}

# Column order matches the existing paper/Excel register.
EXPORT_COLUMNS = [
    ("Reference", lambda c: c.reference),
    ("Type", lambda c: c.get_case_type_display()),
    ("Date Received", lambda c: timezone.localtime(c.date_received).strftime("%Y-%m-%d %H:%M")),
    ("Client Name", lambda c: c.client_name),
    ("Phone Number", lambda c: c.phone_number),
    ("Email Address", lambda c: c.email_address),
    ("Nature of the Complaint", lambda c: c.nature_of_complaint),
    ("Enquiry Type", lambda c: c.get_enquiry_type_display()),
    ("Division", lambda c: c.get_division_display()),
    ("Service", lambda c: c.service),
    ("Organisation", lambda c: c.organisation),
    ("Subject", lambda c: c.subject),
    ("Staff Member Involved", lambda c: c.staff_member_involved),
    ("Action Taken", lambda c: c.action_taken),
    ("Resolution Date", lambda c: c.resolution_date.isoformat() if c.resolution_date else ""),
    ("Status", lambda c: c.get_status_display()),
    ("Remarks", lambda c: c.remarks),
    ("Assigned To", lambda c: (c.assigned_to.get_full_name() or c.assigned_to.get_username()) if c.assigned_to else ""),
    ("Source", lambda c: c.get_source_display()),
    ("Days Open", lambda c: c.days_open()),
]


def _safe_cell(value):
    """Stop text typed by the public being run as a formula when the CSV is opened in Excel."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


class OpenFilter(admin.SimpleListFilter):
    title = "open / closed"
    parameter_name = "open"

    def lookups(self, request, model_admin):
        return [("open", "Open (New or In progress)"), ("done", "Resolved or Closed")]

    def queryset(self, request, queryset):
        open_statuses = [Complaint.Status.NEW, Complaint.Status.IN_PROGRESS]
        if self.value() == "open":
            return queryset.filter(status__in=open_statuses)
        if self.value() == "done":
            return queryset.exclude(status__in=open_statuses)
        return queryset


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "case_type",
        "date_received",
        "client_name",
        "phone_number",
        "email_address",
        "nature_short",
        "staff_member_involved",
        "status_badge",
        "assigned_to",
        "resolution_date",
        "days_open_display",
    )
    list_display_links = ("reference", "client_name")
    list_filter = ("case_type", OpenFilter, "status", "assigned_to", "source", "date_received")
    search_fields = (
        "reference",
        "client_name",
        "phone_number",
        "email_address",
        "nature_of_complaint",
        "staff_member_involved",
        "action_taken",
        "remarks",
    )
    date_hierarchy = "date_received"
    list_per_page = 50
    list_select_related = ("assigned_to",)
    show_facets = admin.ShowFacets.ALWAYS
    readonly_fields = ("reference", "days_open_display", "created_at", "updated_at")
    fieldsets = (
        ("Case", {"fields": ("case_type", "reference", "date_received", "source", "status", "assigned_to")}),
        ("Client details", {"fields": ("client_name", "phone_number", "email_address")}),
        ("Details", {"fields": ("subject", "nature_of_complaint", "staff_member_involved")}),
        ("Enquiry", {"fields": ("enquiry_type", "division", "service", "organisation", "source_page"), "classes": ("collapse",)}),
        (
            "Handling",
            {
                "fields": ("action_taken", "resolution_date", "remarks", "days_open_display"),
                "description": "The resolution date fills in automatically when the status is set to Resolved or Closed.",
            },
        ),
        ("Record", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    actions = ("export_csv", "mark_in_progress", "mark_resolved", "mark_closed")

    @admin.display(description="Nature of the complaint")
    def nature_short(self, obj):
        return Truncator(obj.nature_of_complaint).chars(80)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        fg, bg = STATUS_COLOURS.get(obj.status, ("#344054", "#f2f4f7"))
        return format_html(
            '<span style="color:{};background:{};padding:2px 8px;border-radius:10px;'
            'font-weight:600;white-space:nowrap">{}</span>',
            fg,
            bg,
            obj.get_status_display(),
        )

    @admin.display(description="Days open")
    def days_open_display(self, obj):
        if obj is None or obj.pk is None:
            return "–"
        return obj.days_open()

    def save_model(self, request, obj, form, change):
        # Manually captured complaints (phone, walk-in) default to "assigned to me".
        if not change and obj.assigned_to is None and obj.source != Complaint.Source.WEBSITE:
            obj.assigned_to = request.user
        super().save_model(request, obj, form, change)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault("source", Complaint.Source.PHONE)
        return initial

    @admin.action(description="Export selected complaints to Excel (CSV)")
    def export_csv(self, request, queryset):
        filename = f"complaints-register-{timezone.localdate():%Y-%m-%d}.csv"
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("﻿")  # lets Excel detect UTF-8
        writer = csv.writer(response)
        writer.writerow([name for name, _ in EXPORT_COLUMNS])
        for complaint in queryset.select_related("assigned_to").order_by("date_received"):
            writer.writerow([_safe_cell(get(complaint)) for _, get in EXPORT_COLUMNS])
        return response

    def _set_status(self, request, queryset, status):
        count = 0
        for complaint in queryset:
            if complaint.status != status:
                complaint.status = status
                complaint.save()
                self.log_change(request, complaint, [{"changed": {"fields": ["Status"]}}])
                count += 1
        label = Complaint.Status(status).label
        self.message_user(request, f"{count} complaint(s) marked as {label}.", messages.SUCCESS)

    @admin.action(description="Mark selected as In progress")
    def mark_in_progress(self, request, queryset):
        self._set_status(request, queryset, Complaint.Status.IN_PROGRESS)

    @admin.action(description="Mark selected as Resolved")
    def mark_resolved(self, request, queryset):
        self._set_status(request, queryset, Complaint.Status.RESOLVED)

    @admin.action(description="Mark selected as Closed")
    def mark_closed(self, request, queryset):
        self._set_status(request, queryset, Complaint.Status.CLOSED)
