"""Runs on every deploy (see build.sh). Safe to run repeatedly.

Creates/updates the three staff groups:
- Complaint handlers: complaints only
- Client service: enquiries only
- Administrators: everything, including staff accounts

Also creates the first administrator from ADMIN_USERNAME / ADMIN_PASSWORD /
ADMIN_EMAIL if that user does not exist yet.
"""
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db.models import Q

from complaints.roles import ADMIN_GROUP, CLIENT_SERVICE_GROUP, COMPLAINTS_GROUP

BASE = ["view_complaint", "add_complaint", "change_complaint"]

GROUPS = {
    COMPLAINTS_GROUP: Q(content_type__app_label="complaints", codename__in=BASE + ["handle_complaints"]),
    CLIENT_SERVICE_GROUP: Q(content_type__app_label="complaints", codename__in=BASE + ["handle_enquiries"]),
    ADMIN_GROUP: Q(content_type__app_label="complaints")
    | Q(content_type__app_label="auth", codename__in=[
        "view_user", "add_user", "change_user", "delete_user", "view_group", "change_group",
    ]),
}


class Command(BaseCommand):
    help = "Set up the staff groups and the first administrator."

    def handle(self, *args, **options):
        for name, query in GROUPS.items():
            group, _ = Group.objects.get_or_create(name=name)
            perms = Permission.objects.filter(query)
            group.permissions.set(perms)
            self.stdout.write(f'Group "{name}" has {perms.count()} permissions.')

        # Administrators need "staff status" to open the staff-account screens.
        User = get_user_model()
        User.objects.filter(groups__name=ADMIN_GROUP, is_staff=False).update(is_staff=True)

        username = os.environ.get("ADMIN_USERNAME", "").strip()
        password = os.environ.get("ADMIN_PASSWORD", "")
        email = os.environ.get("ADMIN_EMAIL", "").strip()
        if not (username and password):
            self.stdout.write("ADMIN_USERNAME/ADMIN_PASSWORD not set; skipping administrator setup.")
            return
        if User.objects.filter(username=username).exists():
            self.stdout.write(f'Administrator "{username}" already exists.')
            return
        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f'Created administrator "{username}".'))
