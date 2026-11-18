from django.conf import settings


def nav_section(request):
    match = getattr(request, "resolver_match", None)
    name = match.url_name if match else ""
    if name == "list":
        status, assigned = request.GET.get("status", ""), request.GET.get("assigned", "")
        if status == "overdue":
            return "overdue"
        if assigned == "me" and status == "open":
            return "mine"
        return "list"
    if name == "detail":
        return "list"
    if name == "enquiries":
        return "enquiries"
    if name in ("conversation", "conversations"):
        return "conversations"
    return name or ""


def portal(request):
    context = {
        "nav": nav_section(request),
        "brand_logo_url": settings.BRAND_LOGO_URL,
        "brand_icon_base": settings.BRAND_ICON_BASE,
        "target_days": settings.COMPLAINT_TARGET_DAYS,
        "reply_to": settings.COMPLAINTS_REPLY_TO[0] if settings.COMPLAINTS_REPLY_TO else "",
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from . import roles
        from .models import Complaint

        types = roles.allowed_types(user)
        context.update(
            {
                "can_complaints": Complaint.CaseType.COMPLAINT in types,
                "can_enquiries": Complaint.CaseType.ENQUIRY in types,
                "is_portal_admin": roles.is_admin(user),
                "role_label": roles.role_label(user),
                "home_list": "portal:list" if Complaint.CaseType.COMPLAINT in types else "portal:enquiries",
            }
        )
        notes = user.complaint_notifications.select_related("complaint")
        recent = list(notes[:6])
        context.update(
            {
                "unread_count": notes.filter(is_read=False).count(),
                "recent_notifications": recent,
                "latest_notification_id": recent[0].pk if recent else 0,
            }
        )
    return context
