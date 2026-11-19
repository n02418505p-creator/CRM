"""Weekly and monthly reports for complaints and enquiries."""
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta

from django.conf import settings
from django.utils import timezone

from . import services
from .models import Complaint

OPEN = [Complaint.Status.NEW, Complaint.Status.IN_PROGRESS]


def _aware(d):
    return timezone.make_aware(datetime.combine(d, datetime.min.time()))


def _add_months(d, months):
    month = d.month - 1 + months
    return date(d.year + month // 12, month % 12 + 1, 1)


def period_bounds(period, value=None, today=None):
    """Return (start, end, label) — end is exclusive — for a weekly or monthly report.

    period: "weekly" or "monthly"
    value:  for weekly, any date in the week (YYYY-MM-DD); for monthly, YYYY-MM.
            Defaults to the last complete week or month.
    """
    today = today or timezone.localdate()
    if period == "monthly":
        try:
            start = datetime.strptime(value, "%Y-%m").date().replace(day=1) if value else None
        except (TypeError, ValueError):
            start = None
        start = start or _add_months(today.replace(day=1), -1)
        end = _add_months(start, 1)
        return start, end, start.strftime("%B %Y")
    try:
        day = date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        day = None
    day = day or (today - timedelta(days=7))
    start = day - timedelta(days=day.weekday())  # Monday
    end = start + timedelta(days=7)
    last = end - timedelta(days=1)
    label = f"Week of {start.day} {start:%b} – {last.day} {last:%b %Y}"
    return start, end, label


def quick_periods(today=None):
    today = today or timezone.localdate()
    this_month = today.replace(day=1)
    return [
        ("weekly", today.isoformat(), "This week"),
        ("weekly", (today - timedelta(days=7)).isoformat(), "Last week"),
        ("monthly", this_month.strftime("%Y-%m"), "This month"),
        ("monthly", _add_months(this_month, -1).strftime("%Y-%m"), "Last month"),
    ]


def _counter_rows(counter, total, limit=None):
    rows = [{"label": k or "Not given", "count": n, "pct": round(100 * n / total) if total else 0}
            for k, n in counter.most_common(limit)]
    return rows


def _change(now, before):
    if before == 0:
        return None if now == 0 else 100
    return round(100 * (now - before) / before)


def build(case_type, period, value=None):
    start, end, label = period_bounds(period, value)
    target = settings.COMPLAINT_TARGET_DAYS
    is_enquiry = case_type == Complaint.CaseType.ENQUIRY
    cases = Complaint.objects.filter(case_type=case_type).select_related("assigned_to")
    received = list(cases.filter(date_received__gte=_aware(start), date_received__lt=_aware(end)).order_by("date_received"))
    resolved = list(cases.filter(resolution_date__gte=start, resolution_date__lt=end))
    # Still open at the end of the period: received before the end and not resolved by then.
    open_at_end = [
        c for c in cases.filter(date_received__lt=_aware(end))
        if c.resolution_date is None or c.resolution_date >= end
    ]
    overdue_cutoff = _aware(end) - timedelta(days=target)
    overdue = [c for c in open_at_end if c.date_received < overdue_cutoff]

    durations = [c.days_open() for c in resolved]
    avg_days = round(sum(durations) / len(durations), 1) if durations else None
    within = sum(1 for d in durations if d <= target)
    within_pct = round(100 * within / len(durations)) if durations else None

    length = end - start
    prev_start = _add_months(start, -1) if period == "monthly" else start - length
    previous = cases.filter(date_received__gte=_aware(prev_start), date_received__lt=_aware(start)).count()

    n = len(received)
    status_counts = Counter(c.get_status_display() for c in received)
    by_status = [{"label": lbl, "count": status_counts.get(lbl, 0), "pct": round(100 * status_counts.get(lbl, 0) / n) if n else 0}
                 for _, lbl in Complaint.Status.choices]
    by_source = _counter_rows(Counter(c.get_source_display() for c in received), n)

    people = OrderedDict()
    for c in received:
        name = services.display_name(c.assigned_to) if c.assigned_to else "Unassigned"
        row = people.setdefault(name, {"label": name, "received": 0, "resolved": 0, "open": 0})
        row["received"] += 1
        row["open" if c.is_open else "resolved"] += 1
    by_handler = sorted(people.values(), key=lambda r: -r["received"])

    extra = []
    if is_enquiry:
        extra.append(("By service", _counter_rows(Counter(c.service or "Not given" for c in received), n)))
        extra.append(("By enquiry type", _counter_rows(Counter(c.get_enquiry_type_display() or "Not given" for c in received), n)))
        extra.append(("By division", _counter_rows(Counter(c.get_division_display() or "Not given" for c in received), n)))
    else:
        named = Counter(c.staff_member_involved.strip() for c in received if c.staff_member_involved.strip())
        if named:
            extra.append(("Staff members named in complaints", _counter_rows(named, n, limit=8)))

    return {
        "case_type": case_type,
        "is_enquiry": is_enquiry,
        "noun_plural": "Enquiries" if is_enquiry else "Complaints",
        "period": period,
        "period_name": "Monthly" if period == "monthly" else "Weekly",
        "value": value or start.isoformat(),
        "start": start,
        "end_inclusive": end - timedelta(days=1),
        "label": label,
        "target": target,
        "stats": {
            "received": n,
            "previous": previous,
            "change": _change(n, previous),
            "resolved": len(resolved),
            "open_at_end": len(open_at_end),
            "overdue": len(overdue),
            "avg_days": avg_days,
            "within_pct": within_pct,
        },
        "by_status": by_status,
        "by_source": by_source,
        "by_handler": by_handler,
        "extra": extra,
        "cases": received,
        "generated_at": timezone.localtime(),
    }
