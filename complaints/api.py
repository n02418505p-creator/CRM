"""The endpoint the website's submit-complaint.php sends complaints to.

POST /api/complaints/
Header:  X-API-Key: <COMPLAINTS_API_KEY>
Body (JSON): reference, submitted_at, client_name, phone_number,
             email_address, nature_of_complaint, staff_member_involved
"""
import hmac
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import enquiries as enquiry_details
from . import services
from .models import ENQUIRY_REFERENCE_PATTERN, REFERENCE_PATTERN, REFERENCE_SEARCH, Complaint

logger = logging.getLogger(__name__)

TEXT_FIELDS = {
    # field: (required, max length)
    "client_name": (True, 150),
    "phone_number": (True, 40),
    "email_address": (False, 254),
    "nature_of_complaint": (True, 5000),
    "staff_member_involved": (False, 150),
}


def _authorised(request):
    expected = settings.COMPLAINTS_API_KEY
    supplied = request.headers.get("X-API-Key", "")
    return bool(expected) and hmac.compare_digest(supplied.encode(), expected.encode())


def _validate(data):
    clean, errors = {}, {}
    for field, (required, max_len) in TEXT_FIELDS.items():
        value = data.get(field, "")
        if not isinstance(value, str):
            errors[field] = "Must be text."
            continue
        value = value.strip()
        if required and not value:
            errors[field] = "Required."
        elif len(value) > max_len:
            errors[field] = f"Must be at most {max_len} characters."
        clean[field] = value

    if clean.get("email_address"):
        try:
            validate_email(clean["email_address"])
        except ValidationError:
            errors["email_address"] = "Not a valid email address."

    reference = data.get("reference") or ""
    if reference and (not isinstance(reference, str) or not REFERENCE_PATTERN.match(reference)):
        errors["reference"] = "Invalid reference format."
    clean["reference"] = reference

    submitted_at = data.get("submitted_at")
    clean["date_received"] = timezone.now()
    if submitted_at:
        parsed = parse_datetime(submitted_at) if isinstance(submitted_at, str) else None
        if parsed is None:
            errors["submitted_at"] = "Must be an ISO 8601 date-time."
        else:
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            # Queued complaints keep their original time; ignore clocks set in the future.
            if parsed <= timezone.now() + timedelta(minutes=10):
                clean["date_received"] = parsed
    return clean, errors


@csrf_exempt
@require_POST
def create_complaint(request):
    if not _authorised(request):
        return JsonResponse({"ok": False, "error": "unauthorised"}, status=401)

    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid JSON"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"ok": False, "error": "expected a JSON object"}, status=400)

    clean, errors = _validate(data)
    if errors:
        return JsonResponse({"ok": False, "errors": errors}, status=400)

    reference = clean.pop("reference")
    # The website may resend a complaint (e.g. after a timeout). Same reference = same complaint.
    if reference:
        existing = Complaint.objects.filter(reference=reference).first()
        if existing:
            return JsonResponse({"ok": True, "reference": existing.reference, "duplicate": True})

    complaint = Complaint(source=Complaint.Source.WEBSITE, **clean)
    if reference:
        complaint.reference = reference
    try:
        with transaction.atomic():
            complaint.save()
    except IntegrityError:
        existing = Complaint.objects.filter(reference=reference).first()
        if existing:
            return JsonResponse({"ok": True, "reference": existing.reference, "duplicate": True})
        raise

    services.record_new(complaint)
    logger.info("Complaint %s received from website", complaint.reference)
    return JsonResponse({"ok": True, "reference": complaint.reference}, status=201)


@csrf_exempt
@require_POST
def inbound_reply(request):
    """Client replies, forwarded by the website server's inbound-email script.

    Body (JSON): from_email, from_name, subject, text, message_id
    """
    if not _authorised(request):
        return JsonResponse({"ok": False, "error": "unauthorised"}, status=401)
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid JSON"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"ok": False, "error": "expected a JSON object"}, status=400)

    fields = {k: data.get(k) if isinstance(data.get(k), str) else "" for k in ("from_email", "from_name", "subject", "text", "message_id")}
    match = REFERENCE_SEARCH.search(fields["subject"]) or REFERENCE_SEARCH.search(fields["text"])
    complaint = Complaint.objects.filter(reference=match.group(0).upper()).first() if match else None
    if complaint is None:
        logger.info("Inbound email from %s did not match a complaint", fields["from_email"])
        return JsonResponse({"ok": True, "matched": False})
    if not fields["text"].strip():
        return JsonResponse({"ok": True, "matched": True, "reference": complaint.reference, "empty": True})

    event, created = services.record_reply(
        complaint, fields["text"], fields["from_email"], fields["from_name"].strip()[:150], fields["message_id"].strip()
    )
    logger.info("Reply from %s added to %s", fields["from_email"], complaint.reference)
    return JsonResponse({"ok": True, "matched": True, "reference": complaint.reference, "duplicate": not created})


@csrf_exempt
@require_POST
def create_enquiry(request):
    """Questions from the website's Contact Us form.

    Body (JSON): reference, submitted_at, client_name, email_address, phone_number, subject, message
    """
    if not _authorised(request):
        return JsonResponse({"ok": False, "error": "unauthorised"}, status=401)
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid JSON"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"ok": False, "error": "expected a JSON object"}, status=400)

    limits = {"client_name": (True, 150), "email_address": (True, 254), "phone_number": (False, 40),
              "subject": (False, 200), "message": (True, 5000)}
    clean, errors = {}, {}
    for field, (required, max_len) in limits.items():
        value = data.get(field, "")
        value = value.strip() if isinstance(value, str) else ""
        if required and not value:
            errors[field] = "Required."
        elif len(value) > max_len:
            errors[field] = f"Must be at most {max_len} characters."
        clean[field] = value
    if clean.get("email_address"):
        try:
            validate_email(clean["email_address"])
        except ValidationError:
            errors["email_address"] = "Not a valid email address."
    reference = data.get("reference") or ""
    if reference and (not isinstance(reference, str) or not ENQUIRY_REFERENCE_PATTERN.match(reference)):
        errors["reference"] = "Invalid reference format."
    received = timezone.now()
    submitted_at = data.get("submitted_at")
    if isinstance(submitted_at, str) and submitted_at:
        parsed = parse_datetime(submitted_at)
        if parsed is not None:
            parsed = parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
            if parsed <= timezone.now() + timedelta(minutes=10):
                received = parsed
    if errors:
        return JsonResponse({"ok": False, "errors": errors}, status=400)

    if reference:
        existing = Complaint.objects.filter(reference=reference).first()
        if existing:
            return JsonResponse({"ok": True, "reference": existing.reference, "duplicate": True})

    details = enquiry_details.parse(
        clean["subject"], clean["message"], data.get("enquiry_about") if isinstance(data.get("enquiry_about"), str) else ""
    )

    def extra(field, max_len, choices=None):
        value = data.get(field)
        value = value.strip()[:max_len] if isinstance(value, str) else ""
        if choices is not None and value not in choices:
            value = ""
        return value or details.get(field, "")[:max_len]

    enquiry = Complaint(
        case_type=Complaint.CaseType.ENQUIRY,
        source=Complaint.Source.WEBSITE,
        date_received=received,
        client_name=clean["client_name"],
        email_address=clean["email_address"],
        phone_number=clean["phone_number"] or details.get("phone_number", "")[:40],
        subject=details.get("subject", clean["subject"])[:200],
        nature_of_complaint=details.get("message") or clean["message"],
        enquiry_type=extra("enquiry_type", 20, Complaint.EnquiryType.values),
        division=extra("division", 20, Complaint.Division.values),
        service=extra("service", 120),
        organisation=extra("organisation", 160),
        source_page=extra("source_page", 200),
    )
    enquiry.apply_service()
    if reference:
        enquiry.reference = reference
    try:
        with transaction.atomic():
            enquiry.save()
    except IntegrityError:
        existing = Complaint.objects.filter(reference=reference).first()
        if existing:
            return JsonResponse({"ok": True, "reference": existing.reference, "duplicate": True})
        raise
    services.record_new(enquiry)
    logger.info("Enquiry %s received from website", enquiry.reference)
    return JsonResponse({"ok": True, "reference": enquiry.reference}, status=201)
