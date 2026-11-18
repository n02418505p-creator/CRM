from django.conf import settings


def portal(request):
    context = {
        "brand_logo_url": settings.BRAND_LOGO_URL,
        "target_days": settings.COMPLAINT_TARGET_DAYS,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
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
