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

from . import roles, services
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
    types = roles.allowed_types(request.user)
    if not types:
        raise PermissionDenied
    everything = Complaint.objects.filter(case_type__in=types)
    # Charts and overdue figures cover whatever this person works on.
    qs = everything
    enquiries = everything.filter(case_type=Complaint.CaseType.ENQUIRY)
    complaints_only = everything.filter(case_type=Complaint.CaseType.COMPLAINT)
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
        "can_complaints": Complaint.CaseType.COMPLAINT in types,
        "can_enquiries": Complaint.CaseType.ENQUIRY in types,
        "stats": {
            "open": complaints_only.filter(status__in=OPEN).count(),
            "new": complaints_only.filter(status=Complaint.Status.NEW).count(),
            "overdue": open_qs.filter(date_received__lt=overdue_cutoff).count(),
            "mine": everything.filter(status__in=OPEN, assigned_to=request.user).count(),
            "open_enquiries": enquiries.filter(status__in=OPEN).count(),
            "new_enquiries": enquiries.filter(status=Complaint.Status.NEW).count(),
            "unassigned": complaints_only.filter(status__in=OPEN, assigned_to__isnull=True).count(),
            "received_month": complaints_only.filter(date_received__gte=_aware(month_start)).count(),
            "resolved_month": complaints_only.filter(resolution_date__gte=month_start).count(),
            "avg_days": avg_days,
        },
        "by_status": by_status,
        "trend": trend,
        "enquiries_by_service": list(
            enquiries.filter(date_received__gte=timezone.now() - timedelta(days=90))
            .exclude(service="")
            .values("service")
            .annotate(n=Count("id"))
            .order_by("-n")[:6]
        ),
        "recent": everything.select_related("assigned_to")[:8],
        "my_open": everything.filter(status__in=OPEN, assigned_to=request.user).select_related("assigned_to")[:6],
    }
    return render(request, "portal/dashboard.html", context)


def _filtered(request, case_type=None):
    qs = Complaint.objects.select_related("assigned_to").filter(case_type__in=roles.allowed_types(request.user))
    case_type = case_type or request.GET.get("type", "")
    if case_type in Complaint.CaseType.values:
        qs = qs.filter(case_type=case_type)
    f = {k: request.GET.get(k, "").strip() for k in ("q", "status", "assigned", "source", "from", "to", "enquiry_type", "division", "service")}
    if f["q"]:
        q = f["q"]
        qs = qs.filter(
            Q(reference__icontains=q) | Q(client_name__icontains=q) | Q(phone_number__icontains=q)
            | Q(email_address__icontains=q) | Q(nature_of_complaint__icontains=q)
            | Q(staff_member_involved__icontains=q) | Q(remarks__icontains=q) | Q(action_taken__icontains=q)
            | Q(subject__icontains=q) | Q(service__icontains=q) | Q(organisation__icontains=q)
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
    if f["enquiry_type"] in Complaint.EnquiryType.values:
        qs = qs.filter(enquiry_type=f["enquiry_type"])
    if f["division"] in Complaint.Division.values:
        qs = qs.filter(division=f["division"])
    if f["service"]:
        qs = qs.filter(service__iexact=f["service"])
    for key, op in (("from", "gte"), ("to", "lt")):
        try:
            d = date.fromisoformat(f[key])
        except ValueError:
            continue
        if key == "to":
            d += timedelta(days=1)
        qs = qs.filter(**{f"date_received__{op}": _aware(d)})
    return qs, f


def _case_list(request, case_type):
    roles.require(request.user, case_type)
    qs, filters = _filtered(request, case_type)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    export_params = params.copy()
    export_params["type"] = case_type
    is_enquiry = case_type == Complaint.CaseType.ENQUIRY
    context = {
        "page": page,
        "filters": filters,
        "querystring": params.urlencode(),
        "export_querystring": export_params.urlencode(),
        "statuses": Complaint.Status.choices,
        "sources": Complaint.Source.choices,
        "staff": services.handlers(case_type),
        "total": page.paginator.count,
        "case_type": case_type,
        "is_enquiry": is_enquiry,
        "list_title": "Enquiries" if is_enquiry else "Complaints",
        "list_url": reverse("portal:enquiries" if is_enquiry else "portal:list"),
        "enquiry_types": Complaint.EnquiryType.choices,
        "divisions": Complaint.Division.choices,
        "service_groups": [(label, [name for name, _ in items]) for label, items in _service_groups()],
    }
    return render(request, "portal/complaint_list.html", context)


def _service_groups():
    from .enquiries import DIVISION_LABELS, SERVICES

    return [(DIVISION_LABELS[d], items) for d, items in SERVICES.items()]


@login_required
@view_required
def complaint_list(request):
    return _case_list(request, Complaint.CaseType.COMPLAINT)


@login_required
@view_required
def enquiry_list(request):
    return _case_list(request, Complaint.CaseType.ENQUIRY)


@login_required
@view_required
def export_csv(request):
    if request.GET.get("type") in Complaint.CaseType.values:
        roles.require(request.user, request.GET["type"])
    qs, _ = _filtered(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    kind = "enquiries" if request.GET.get("type") == "enquiry" else "complaints"
    response["Content-Disposition"] = f'attachment; filename="{kind}-register-{timezone.localdate():%Y-%m-%d}.csv"'
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow([name for name, _ in EXPORT_COLUMNS])
    for complaint in qs.order_by("date_received"):
        writer.writerow([_safe_cell(get(complaint)) for _, get in EXPORT_COLUMNS])
    return response


def _email_client(request, complaint, message, acknowledgement=False):
    sent, error = services.email_client(complaint, message, request.user, acknowledgement=acknowledgement)
    if sent:
        messages.success(request, f"Email sent to {complaint.email_address}.")
    else:
        messages.error(request, error)
    return sent


@login_required
@permission_required("complaints.add_complaint", raise_exception=True)
def complaint_new(request):
    types = roles.allowed_types(request.user)
    if not types:
        raise PermissionDenied
    wanted = request.GET.get("type")
    initial = {"case_type": wanted if wanted in types else types[0]}
    form = ComplaintCreateForm(request.POST or None, initial=initial, allowed_types=types)
    if request.method == "POST" and form.is_valid():
        complaint = form.save()
        services.record_new(complaint, actor=request.user)
        messages.success(request, f"{complaint.noun_title} {complaint.reference} has been logged.")
        if request.POST.get("send_acknowledgement") == "yes" and complaint.email_address:
            _email_client(request, complaint, services.acknowledgement_message(complaint), acknowledgement=True)
        return redirect("portal:detail", reference=complaint.reference)
    from .enquiries import SERVICES

    descriptions = {name: desc for items in SERVICES.values() for name, desc in items if desc}
    return render(request, "portal/complaint_form.html", {"form": form, "service_descriptions": descriptions})


@login_required
@view_required
def complaint_detail(request, reference):
    complaint = get_object_or_404(Complaint.objects.select_related("assigned_to"), reference=reference)
    roles.require(request.user, complaint.case_type)
    can_change = request.user.has_perm("complaints.change_complaint")
    handling_form = HandlingForm(instance=complaint)
    details_form = DetailsForm(instance=complaint)

    if request.method == "POST":
        if not can_change:
            raise PermissionDenied
        action = request.POST.get("action")
        done = False
        notify_client = request.POST.get("notify_client") == "yes"
        if action == "status":
            note = request.POST.get("note", "").strip()
            done = services.change_status(complaint, request.POST.get("status", ""), request.user, note)
            if done:
                messages.success(request, f"Status changed to {complaint.get_status_display()}.")
                if notify_client:
                    _email_client(request, complaint, services.status_message(complaint, note))
        elif action == "assign":
            user_id = request.POST.get("assigned_to", "")
            user = services.handlers(complaint.case_type).filter(pk=user_id).first() if user_id else None
            done = services.assign(complaint, user, request.user)
            if done:
                messages.success(request, f"Assigned to {services.display_name(user)}." if user else "Complaint unassigned.")
                if notify_client and user:
                    _email_client(request, complaint, services.assignment_message(complaint))
        elif action == "client":
            done = _email_client(request, complaint, request.POST.get("message", ""))
            if not done:
                return redirect("portal:detail", reference=complaint.reference)
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
        "staff": services.handlers(complaint.case_type),
        "nav": "enquiries" if complaint.is_enquiry else "list",
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
    if note.kind == "reply":
        return redirect(reverse("portal:conversation", args=[note.complaint.reference]) + "#latest")
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


CONVERSATION_KINDS = ["client", "reply"]


@login_required
@view_required
def conversation(request, reference):
    complaint = get_object_or_404(Complaint.objects.select_related("assigned_to"), reference=reference)
    roles.require(request.user, complaint.case_type)
    can_change = request.user.has_perm("complaints.change_complaint")
    if request.method == "POST":
        if not can_change:
            raise PermissionDenied
        _email_client(request, complaint, request.POST.get("message", ""))
        return redirect(reverse("portal:conversation", args=[complaint.reference]) + "#latest")

    Notification.objects.filter(recipient=request.user, complaint=complaint, is_read=False).update(is_read=True)
    messages_qs = complaint.events.filter(kind__in=CONVERSATION_KINDS).select_related("actor").order_by("created_at", "id")
    thread = [
        {
            "mine": False,
            "who": complaint.client_name,
            "when": complaint.date_received,
            "text": complaint.nature_of_complaint,
            "label": (f"{complaint.noun_title} received via {complaint.get_source_display()}"
                      + (f" · {complaint.subject}" if complaint.subject else "")),
        }
    ]
    for e in messages_qs:
        from_client = e.kind == "reply"
        thread.append(
            {
                "mine": not from_client,
                "who": complaint.client_name if from_client else services.display_name(e.actor),
                "when": e.created_at,
                "text": services.clean_message(e.message),
                "label": (f"from {e.sender}" if from_client and e.sender and e.sender != complaint.email_address.lower() else ""),
            }
        )
    latest = messages_qs.last()
    context = {
        "c": complaint,
        "thread": thread,
        "can_change": can_change,
        "latest_event_id": latest.pk if latest else 0,
    }
    return render(request, "portal/conversation.html", context)


@login_required
@view_required
def conversation_feed(request, reference):
    complaint = get_object_or_404(Complaint, reference=reference)
    roles.require(request.user, complaint.case_type)
    latest = complaint.events.filter(kind__in=CONVERSATION_KINDS).order_by("-id").values_list("pk", flat=True).first()
    return JsonResponse({"latest": latest or 0})


@login_required
@view_required
def conversations(request):
    """Every complaint with email correspondence, most recent first."""
    from .models import ComplaintEvent

    show = request.GET.get("show", "")
    seen, rows = set(), []
    events = ComplaintEvent.objects.filter(
        kind__in=CONVERSATION_KINDS, complaint__case_type__in=roles.allowed_types(request.user)
    ).select_related("complaint", "complaint__assigned_to", "actor")
    for e in events.order_by("-created_at", "-id")[:500]:
        if e.complaint_id in seen:
            continue
        seen.add(e.complaint_id)
        waiting = e.kind == "reply"
        if show == "waiting" and not waiting:
            continue
        if show == "mine" and e.complaint.assigned_to_id != request.user.pk:
            continue
        rows.append(
            {
                "c": e.complaint,
                "last": e,
                "waiting": waiting,
                "who": e.complaint.client_name if waiting else services.display_name(e.actor),
                "count": e.complaint.events.filter(kind__in=CONVERSATION_KINDS).count(),
                "snippet": services.clean_message(e.message),
            }
        )
    waiting_count = sum(1 for r in rows if r["waiting"]) if show != "waiting" else len(rows)
    return render(request, "portal/conversations.html", {"rows": rows, "show": show, "waiting_count": waiting_count})


def _report_params(request):
    from . import reports as report_lib

    types = roles.allowed_types(request.user)
    if not types:
        raise PermissionDenied
    case_type = request.GET.get("type") if request.GET.get("type") in types else types[0]
    period = "monthly" if request.GET.get("period") == "monthly" else "weekly"
    return report_lib.build(case_type, period, request.GET.get("value") or None), types


@login_required
@view_required
def reports(request):
    from . import reports as report_lib

    report, types = _report_params(request)
    params = {"type": report["case_type"], "period": report["period"], "value": report["value"]}
    from urllib.parse import urlencode

    context = {
        "report": report,
        "types": [(t, "Complaints" if t == Complaint.CaseType.COMPLAINT else "Enquiries") for t in types],
        "quick": [
            {"label": lbl, "url": "?" + urlencode({"type": report["case_type"], "period": p, "value": v}),
             "active": p == report["period"] and report_lib.period_bounds(p, v)[0] == report["start"]}
            for p, v, lbl in report_lib.quick_periods()
        ],
        "query": urlencode(params),
        "month_value": report["start"].strftime("%Y-%m"),
        "week_value": report["start"].isoformat(),
    }
    return render(request, "portal/reports.html", context)


@login_required
@view_required
def report_pdf(request):
    from . import report_pdf as pdf

    report, _ = _report_params(request)
    content = pdf.render(report, request.user)
    name = f"MMC-{report['noun_plural'].lower()}-{report['period']}-report-{report['start']:%Y-%m-%d}.pdf"
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


@login_required
@view_required
def report_csv(request):
    report, _ = _report_params(request)
    name = f"MMC-{report['noun_plural'].lower()}-{report['period']}-report-{report['start']:%Y-%m-%d}.csv"
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow([f"MMC Capital – {report['period_name']} {report['noun_plural'].lower()} report – {report['label']}"])
    writer.writerow([])
    writer.writerow([name for name, _ in EXPORT_COLUMNS])
    for case in report["cases"]:
        writer.writerow([_safe_cell(get(case)) for _, get in EXPORT_COLUMNS])
    return response
