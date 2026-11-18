"""Runs on every deploy (see build.sh). Safe to run repeatedly.

- Creates/updates the "Complaint handlers" group: can view, add and edit
  complaints, but not delete them.
- Creates the first administrator from ADMIN_USERNAME / ADMIN_PASSWORD /
  ADMIN_EMAIL if that user does not exist yet.
"""
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

HANDLER_GROUP = "Complaint handlers"
HANDLER_PERMISSIONS = ["view_complaint", "add_complaint", "change_complaint"]


class Command(BaseCommand):
    help = "Set up the complaint handlers group and the first administrator."

    def handle(self, *args, **options):
        group, _ = Group.objects.get_or_create(name=HANDLER_GROUP)
        perms = Permission.objects.filter(
            content_type__app_label="complaints", codename__in=HANDLER_PERMISSIONS
        )
        group.permissions.set(perms)
        self.stdout.write(f'Group "{HANDLER_GROUP}" has {perms.count()} permissions.')

        username = os.environ.get("ADMIN_USERNAME", "").strip()
        password = os.environ.get("ADMIN_PASSWORD", "")
        email = os.environ.get("ADMIN_EMAIL", "").strip()
        if not (username and password):
            self.stdout.write("ADMIN_USERNAME/ADMIN_PASSWORD not set; skipping administrator setup.")
            return

        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(f'Administrator "{username}" already exists.')
            return
        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f'Created administrator "{username}".'))
