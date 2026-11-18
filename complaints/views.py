"""The MMC complaints portal (staff-facing)."""
import csv
from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .admin import EXPORT_COLUMNS, _safe_cell
from .forms import ComplaintCreateForm, DetailsForm, HandlingForm
from .models import Complaint, Notification

OPEN = [Complaint.Status.NEW, Complaint.Status.IN_PROGRESS]
view_required = permission_required("complaints.view_complaint", raise_exception=True)


def _month_start(d, months_back=0):
    year, month = d.year, d.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return date(year, month, 1)


def _aware(d):
    return timezone.make_aware(datetime.combine(d, datetime.min.time()))


@login_required
@view_required
def dashboard(request):
    today = timezone.localdate()
    month_start = _month_start(today)
    qs = Complaint.objects.all()
    open_qs = qs.filter(status__in=OPEN)
    overdue_cutoff = timezone.now() - timedelta(days=settings.COMPLAINT_TARGET_DAYS)

    resolved_recent = qs.filter(resolution_date__isnull=False, resolution_date__gte=today - timedelta(days=90))
    durations = [c.days_open() for c in resolved_recent]
    avg_days = round(sum(durations) / len(durations), 1) if durations else None

    status_counts = dict(qs.values_list("status").annotate(n=Count("id")))
    total = sum(status_counts.values()) or 1
    by_status = [
        {"key": key, "label": label, "count": status_counts.get(key, 0), "pct": round(100 * status_counts.get(key, 0) / total)}
        for key, label in Complaint.Status.choices
    ]

    trend = []
    for back in range(5, -1, -1):
        start = _month_start(today, back)
        end = _month_start(today, back - 1)
        trend.append(
            {
                "label": start.strftime("%b"),
                "received": qs.filter(date_received__gte=_aware(start), date_received__lt=_aware(end)).count(),
                "resolved": qs.filter(resolution_date__gte=start, resolution_date__lt=end).count(),
            }
        )
    peak = max([max(t["received"], t["resolved"]) for t in trend] + [1])
    for t in trend:
        t["received_pct"] = round(100 * t["received"] / peak)
        t["resolved_pct"] = round(100 * t["resolved"] / peak)

    hour = timezone.localtime().hour
    context = {
        "greeting": "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening",
        "stats": {
            "open": open_qs.count(),
            "new": qs.filter(status=Complaint.Status.NEW).count(),
            "overdue": open_qs.filter(date_received__lt=overdue_cutoff).count(),
            "mine": open_qs.filter(assigned_to=request.user).count(),
            "unassigned": open_qs.filter(assigned_to__isnull=True).count(),
            "received_month": qs.filter(date_received__gte=_aware(month_start)).count(),
            "resolved_month": qs.filter(resolution_date__gte=month_start).count(),
            "avg_days": avg_days,
        },
        "by_status": by_status,
        "trend": trend,
        "recent": qs.select_related("assigned_to")[:8],
        "my_open": open_qs.filter(assigned_to=request.user).select_related("assigned_to")[:6],
    }
    return render(request, "portal/dashboard.html", context)


def _filtered(request):
    qs = Complaint.objects.select_related("assigned_to")
    f = {k: request.GET.get(k, "").strip() for k in ("q", "status", "assigned", "source", "from", "to")}
    if f["q"]:
        q = f["q"]
        qs = qs.filter(
            Q(reference__icontains=q) | Q(client_name__icontains=q) | Q(phone_number__icontains=q)
            | Q(email_address__icontains=q) | Q(nature_of_complaint__icontains=q)
            | Q(staff_member_involved__icontains=q) | Q(remarks__icontains=q) | Q(action_taken__icontains=q)
        )
    if f["status"] == "open":
        qs = qs.filter(status__in=OPEN)
    elif f["status"] == "overdue":
        qs = qs.filter(status__in=OPEN, date_received__lt=timezone.now() - timedelta(days=settings.COMPLAINT_TARGET_DAYS))
    elif f["status"] in Complaint.Status.values:
        qs = qs.filter(status=f["status"])
    if f["assigned"] == "me":
        qs = qs.filter(assigned_to=request.user)
    elif f["assigned"] == "none":
        qs = qs.filter(assigned_to__isnull=True)
    elif f["assigned"].isdigit():
        qs = qs.filter(assigned_to_id=int(f["assigned"]))
    if f["source"] in Complaint.Source.values:
        qs = qs.filter(source=f["source"])
    for key, op in (("from", "gte"), ("to", "lt")):
        try:
            d = date.fromisoformat(f[key])
        except ValueError:
            continue
        if key == "to":
            d += timedelta(days=1)
        qs = qs.filter(**{f"date_received__{op}": _aware(d)})
    return qs, f


@login_required
@view_required
def complaint_list(request):
    qs, filters = _filtered(request)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    context = {
        "page": page,
        "filters": filters,
        "querystring": params.urlencode(),
        "statuses": Complaint.Status.choices,
        "sources": Complaint.Source.choices,
        "staff": services.handlers(),
        "total": page.paginator.count,
    }
    return render(request, "portal/complaint_list.html", context)


@login_required
@view_required
def export_csv(request):
    qs, _ = _filtered(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="complaints-register-{timezone.localdate():%Y-%m-%d}.csv"'
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow([name for name, _ in EXPORT_COLUMNS])
    for complaint in qs.order_by("date_received"):
        writer.writerow([_safe_cell(get(complaint)) for _, get in EXPORT_COLUMNS])
    return response


@login_required
@permission_required("complaints.add_complaint", raise_exception=True)
def complaint_new(request):
    form = ComplaintCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        complaint = form.save()
        services.record_new(complaint, actor=request.user)
        messages.success(request, f"Complaint {complaint.reference} has been logged.")
        return redirect("portal:detail", reference=complaint.reference)
    return render(request, "portal/complaint_form.html", {"form": form})


@login_required
@view_required
def complaint_detail(request, reference):
    complaint = get_object_or_404(Complaint.objects.select_related("assigned_to"), reference=reference)
    can_change = request.user.has_perm("complaints.change_complaint")
    handling_form = HandlingForm(instance=complaint)
    details_form = DetailsForm(instance=complaint)

    if request.method == "POST":
        if not can_change:
            raise PermissionDenied
        action = request.POST.get("action")
        done = False
        if action == "status":
            done = services.change_status(complaint, request.POST.get("status", ""), request.user, request.POST.get("note", "").strip())
            if done:
                messages.success(request, f"Status changed to {complaint.get_status_display()}.")
        elif action == "assign":
            user_id = request.POST.get("assigned_to", "")
            user = services.handlers().filter(pk=user_id).first() if user_id else None
            done = services.assign(complaint, user, request.user)
            if done:
                messages.success(request, f"Assigned to {services.display_name(user)}." if user else "Complaint unassigned.")
        elif action == "note":
            done = services.add_note(complaint, request.POST.get("note", ""), request.user)
            if done:
                messages.success(request, "Note added.")
        elif action == "handling":
            handling_form = HandlingForm(request.POST, instance=complaint)
            if handling_form.is_valid():
                labels = [str(handling_form.fields[f].label) for f in handling_form.changed_data]
                handling_form.save()
                done = services.record_update(complaint, labels, request.user)
                messages.success(request, "Handling details saved.")
        elif action == "details":
            details_form = DetailsForm(request.POST, instance=complaint)
            if details_form.is_valid():
                labels = [str(details_form.fields[f].label) for f in details_form.changed_data]
                details_form.save()
                done = services.record_update(complaint, labels, request.user)
                messages.success(request, "Complaint details saved.")
        if done or (action in ("handling", "details") and not (handling_form.errors or details_form.errors)):
            return redirect("portal:detail", reference=complaint.reference)
        if action in ("status", "assign", "note") and not done:
            messages.info(request, "Nothing changed.")
            return redirect("portal:detail", reference=complaint.reference)

    # Opening a complaint marks its notifications as read.
    Notification.objects.filter(recipient=request.user, complaint=complaint, is_read=False).update(is_read=True)

    context = {
        "c": complaint,
        "events": complaint.events.select_related("actor"),
        "can_change": can_change,
        "handling_form": handling_form,
        "details_form": details_form,
        "statuses": Complaint.Status.choices,
        "staff": services.handlers(),
    }
    return render(request, "portal/complaint_detail.html", context)


@login_required
def notifications(request):
    items = request.user.complaint_notifications.select_related("complaint")[:100]
    return render(request, "portal/notifications.html", {"items": items})


@login_required
def notification_open(request, pk):
    note = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not note.is_read:
        note.is_read = True
        note.save(update_fields=["is_read"])
    return redirect("portal:detail", reference=note.complaint.reference)


@login_required
@require_POST
def notifications_read_all(request):
    request.user.complaint_notifications.filter(is_read=False).update(is_read=True)
    return redirect(request.POST.get("next") or "portal:notifications")


@login_required
def notifications_feed(request):
    """Polled by the portal every minute to update the bell and show pop-ups."""
    notes = request.user.complaint_notifications.select_related("complaint")
    since = request.GET.get("since", "0")
    since = int(since) if since.isdigit() else 0
    fresh = notes.filter(pk__gt=since, is_read=False)[:5]
    return JsonResponse(
        {
            "unread": notes.filter(is_read=False).count(),
            "latest_id": notes.values_list("pk", flat=True).first() or since,
            "items": [
                {
                    "id": n.pk,
                    "message": n.message,
                    "url": reverse("portal:notification_open", args=[n.pk]),
                    "kind": n.kind,
                }
                for n in fresh
            ],
        }
    )
