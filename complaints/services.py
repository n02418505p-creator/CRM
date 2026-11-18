"""Everything that changes a complaint goes through here, so the timeline and
notifications are always kept up to date."""
import re

from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import Complaint, ComplaintEvent, Notification


def display_name(user):
    if user is None:
        return "System"
    return user.get_full_name() or user.get_username()


def handlers(case_type=None):
    """Active staff who can work on this type of case (or on any case)."""
    from .roles import CODENAME_FOR_TYPE

    codenames = [CODENAME_FOR_TYPE[case_type]] if case_type else list(CODENAME_FOR_TYPE.values())
    User = get_user_model()
    return (
        User.objects.filter(is_active=True)
        .filter(
            Q(is_superuser=True)
            | Q(groups__permissions__codename__in=codenames)
            | Q(user_permissions__codename__in=codenames)
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
    noun = complaint.noun_title
    if actor is None:
        log(complaint, ComplaintEvent.Kind.CREATED, f"{noun} received via {source}.")
    else:
        log(complaint, ComplaintEvent.Kind.CREATED, f"{noun} logged by {display_name(actor)} ({source}).", actor)
    notify(handlers(complaint.case_type), complaint, "new", f"New {complaint.noun} from {complaint.client_name} ({complaint.reference})", exclude=actor)
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


# ---------------------------------------------------------------------------
# Emails to the client
# ---------------------------------------------------------------------------

def handler_name(complaint):
    return display_name(complaint.assigned_to) if complaint.assigned_to else "MMC Capital client service team"


def email_client(complaint, message, actor, acknowledgement=False):
    """Email the client an update and record it on the timeline.

    Returns (sent, error_message)."""
    from django.conf import settings
    from django.core.mail import EmailMessage
    from django.template.loader import render_to_string
    from django.utils import timezone

    message = (message or "").strip()
    if not complaint.email_address:
        return False, "There is no email address for this client."
    if not message:
        return False, "Please write a message for the client."

    history = list(
        complaint.events.filter(kind__in=[ComplaintEvent.Kind.CLIENT, ComplaintEvent.Kind.REPLY]).select_related("actor")[:10]
    )
    body = render_to_string(
        "emails/client_update.txt",
        {
            "c": complaint,
            "message": message,
            "staff_name": display_name(actor) if actor else "MMC Capital",
            "sent_at": timezone.localtime(),
            "handler": handler_name(complaint),
            "history": history,
            "acknowledgement": acknowledgement,
        },
    )
    subject = (
        f"We've received your {complaint.noun} – reference {complaint.reference}"
        if acknowledgement
        else f"Update on your {complaint.noun} {complaint.reference} – MMC Capital"
    )
    email = EmailMessage(subject, body, to=[complaint.email_address], reply_to=settings.COMPLAINTS_REPLY_TO)
    try:
        sent = email.send(fail_silently=False)
    except Exception as exc:  # network problems, relay refused, etc.
        log(complaint, ComplaintEvent.Kind.NOTE, f"Email to the client could not be sent ({exc}).", actor)
        return False, "The email to the client could not be sent. Please try again later."
    if not sent:
        return False, "The email to the client could not be sent."
    log(complaint, ComplaintEvent.Kind.CLIENT, message, actor)
    return True, ""


def status_message(complaint, note=""):
    n = complaint.noun
    texts = {
        Complaint.Status.NEW: f"Your {n} has been received and is waiting to be reviewed.",
        Complaint.Status.IN_PROGRESS: f"Your {n} is being looked into by our team.",
        Complaint.Status.RESOLVED: f"Your {n} has been resolved.",
        Complaint.Status.CLOSED: f"Your {n} has been closed.",
    }
    text = texts.get(complaint.status, f"Your {n} is now {complaint.get_status_display()}.")
    return text + (f"\n\n{note}" if note else "")


def assignment_message(complaint):
    return (
        f"Your {complaint.noun} has been assigned to {handler_name(complaint)}, "
        "who will be in touch with you."
    )


def acknowledgement_message(complaint):
    if complaint.is_enquiry:
        return "Your enquiry has been logged and a member of our team will get back to you by email."
    return (
        "Your complaint has been logged in our complaints register. "
        "We will review it and keep you updated on progress by email."
    )


# ---------------------------------------------------------------------------
# Replies from the client (emails to replies@cases.mmccapitalzim.com)
# ---------------------------------------------------------------------------

_QUOTE_STARTS = [
    re.compile(r"^\s*On\s.+wrote:\s*$", re.IGNORECASE),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE),
    re.compile(r"^\s*_{10,}\s*$"),
    re.compile(r"^\s*\*?From:\*?\s.+", re.IGNORECASE),
    re.compile(r"^\s*Dear .+,\s*$"),  # start of our own email quoted without ">" markers
]


CID_PLACEHOLDER = re.compile(r"\[cid:[^\]]*\]", re.IGNORECASE)


def clean_message(text):
    """Remove placeholders Outlook leaves where inline images were."""
    return re.sub(r"\n{3,}", "\n\n", CID_PLACEHOLDER.sub("", text or "")).strip()


def strip_quoted(text):
    """Keep only what the client wrote, not the earlier emails quoted underneath."""
    text = CID_PLACEHOLDER.sub("", text or "")
    lines = text.replace("\r\n", "\n").split("\n")
    kept = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith(">"):
            continue
        if kept and any(p.match(line) for p in _QUOTE_STARTS):
            # "Dear ..." only counts as quoted text if our update wording follows soon after.
            if line.strip().lower().startswith("dear "):
                following = "\n".join(lines[i + 1:i + 6]).lower()
                if "your complaint" not in following:
                    kept.append(line)
                    continue
            break
        # Gmail sometimes wraps "On <date> <name> wrote:" over two lines.
        if line.strip().lower().startswith("on ") and i + 1 < len(lines) and lines[i + 1].strip().lower().endswith("wrote:") and kept:
            break
        kept.append(line)
    result = "\n".join(kept).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result or (text or "").strip()


def record_reply(complaint, text, sender, sender_name="", message_id=""):
    """Add a client's emailed reply to the complaint. Returns the event (or the existing one)."""
    if message_id:
        existing = complaint.events.filter(external_id=message_id).first()
        if existing:
            return existing, False
    body = strip_quoted(text)[:20000]
    sender = (sender or "").strip().lower()
    event = ComplaintEvent.objects.create(
        complaint=complaint,
        kind=ComplaintEvent.Kind.REPLY,
        message=body,
        sender=sender,
        external_id=message_id[:255],
    )
    who = sender_name or complaint.client_name
    note = f"{who} replied to {complaint.reference}"
    if not complaint.is_open:
        note += f" (complaint is {complaint.get_status_display()})"
    recipients = [complaint.assigned_to] if complaint.assigned_to else list(handlers(complaint.case_type))
    notify(recipients, complaint, "reply", note)
    return event, True
