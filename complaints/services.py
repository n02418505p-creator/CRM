"""Everything that changes a complaint goes through here, so the timeline and
notifications are always kept up to date."""
from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import Complaint, ComplaintEvent, Notification


def display_name(user):
    if user is None:
        return "System"
    return user.get_full_name() or user.get_username()


def handlers():
    """Active staff who can see complaints."""
    User = get_user_model()
    return (
        User.objects.filter(is_active=True)
        .filter(
            Q(is_superuser=True)
            | Q(groups__permissions__codename="view_complaint")
            | Q(user_permissions__codename="view_complaint")
        )
        .distinct()
        .order_by("first_name", "last_name", "username")
    )


def log(complaint, kind, message, actor=None):
    return ComplaintEvent.objects.create(complaint=complaint, kind=kind, message=message, actor=actor)


def notify(users, complaint, kind, message, exclude=None):
    recipients = [u for u in users if u is not None and (exclude is None or u.pk != exclude.pk)]
    Notification.objects.bulk_create(
        [Notification(recipient=u, complaint=complaint, kind=kind, message=message[:255]) for u in recipients]
    )


def record_new(complaint, actor=None):
    source = complaint.get_source_display()
    if actor is None:
        log(complaint, ComplaintEvent.Kind.CREATED, f"Complaint received via {source}.")
    else:
        log(complaint, ComplaintEvent.Kind.CREATED, f"Complaint logged by {display_name(actor)} ({source}).", actor)
    notify(handlers(), complaint, "new", f"New complaint from {complaint.client_name} ({complaint.reference})", exclude=actor)
    if complaint.assigned_to and (actor is None or complaint.assigned_to.pk != actor.pk):
        notify([complaint.assigned_to], complaint, "assigned", f"You were assigned {complaint.reference} – {complaint.client_name}")


def change_status(complaint, status, actor, note=""):
    if status not in Complaint.Status.values or status == complaint.status:
        return False
    old = complaint.get_status_display()
    complaint.status = status
    complaint.save()
    message = f"Status changed from {old} to {complaint.get_status_display()}."
    if note:
        message += f"\n{note}"
    log(complaint, ComplaintEvent.Kind.STATUS, message, actor)
    notify(
        [complaint.assigned_to], complaint, "status",
        f"{complaint.reference} is now {complaint.get_status_display()} ({display_name(actor)})", exclude=actor,
    )
    return True


def assign(complaint, user, actor):
    old = complaint.assigned_to
    if (old and user and old.pk == user.pk) or (old is None and user is None):
        return False
    complaint.assigned_to = user
    complaint.save()
    if user is None:
        log(complaint, ComplaintEvent.Kind.ASSIGNED, f"Unassigned (was {display_name(old)}).", actor)
    else:
        log(complaint, ComplaintEvent.Kind.ASSIGNED, f"Assigned to {display_name(user)}.", actor)
        notify([user], complaint, "assigned", f"You were assigned {complaint.reference} – {complaint.client_name}", exclude=actor)
    return True


def add_note(complaint, text, actor):
    text = (text or "").strip()
    if not text:
        return False
    log(complaint, ComplaintEvent.Kind.NOTE, text, actor)
    notify([complaint.assigned_to], complaint, "note", f"New note on {complaint.reference} from {display_name(actor)}", exclude=actor)
    return True


def record_update(complaint, changed_labels, actor):
    if not changed_labels:
        return False
    log(complaint, ComplaintEvent.Kind.UPDATED, "Updated " + ", ".join(changed_labels) + ".", actor)
    return True
