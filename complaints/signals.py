from django.contrib.auth import get_user_model
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .roles import ADMIN_GROUP

User = get_user_model()


@receiver(m2m_changed, sender=User.groups.through)
def administrators_get_staff_status(sender, instance, action, reverse, pk_set, **kwargs):
    """Adding someone to Administrators lets them open the staff-account screens."""
    if action != "post_add" or reverse:
        return
    if instance.groups.filter(name=ADMIN_GROUP).exists() and not instance.is_staff:
        instance.is_staff = True
        instance.save(update_fields=["is_staff"])
