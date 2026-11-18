import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Complaint, ComplaintEvent, Notification

API_KEY = "test-key-123"
PAYLOAD = {
    "reference": "CMP-20261118-ABC123",
    "submitted_at": "2026-11-18T09:15:00+02:00",
    "client_name": "Tendai Moyo",
    "phone_number": "+263 77 123 4567",
    "email_address": "tendai@example.com",
    "nature_of_complaint": "My trade was not executed on the day I instructed.",
    "staff_member_involved": "",
}


def make_handler(username, **extra):
    call_command("setup_complaints", stdout=open("/dev/null", "w"))
    user = get_user_model().objects.create_user(username, f"{username}@example.com", "pw-very-long-123", **extra)
    user.groups.add(Group.objects.get(name="Complaint handlers"))
    return user


@override_settings(COMPLAINTS_API_KEY=API_KEY)
class ApiTests(TestCase):
    def post(self, data, key=API_KEY):
        return self.client.post(
            "/api/complaints/", data=json.dumps(data), content_type="application/json", HTTP_X_API_KEY=key
        )

    def test_rejects_wrong_key(self):
        self.assertEqual(self.post(PAYLOAD, key="nope").status_code, 401)
        self.assertEqual(Complaint.objects.count(), 0)

    def test_creates_complaint_event_and_notifications(self):
        handler = make_handler("thapelo")
        resp = self.post(PAYLOAD)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["reference"], PAYLOAD["reference"])
        c = Complaint.objects.get()
        self.assertEqual(c.client_name, "Tendai Moyo")
        self.assertEqual(c.status, Complaint.Status.NEW)
        self.assertEqual(c.source, Complaint.Source.WEBSITE)
        self.assertEqual(timezone.localtime(c.date_received).hour, 9)
        self.assertEqual(c.events.get().kind, ComplaintEvent.Kind.CREATED)
        self.assertEqual(Notification.objects.get().recipient, handler)

    def test_resend_is_not_duplicated(self):
        self.post(PAYLOAD)
        resp = self.post(PAYLOAD)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["duplicate"])
        self.assertEqual(Complaint.objects.count(), 1)

    def test_validation(self):
        resp = self.post({**PAYLOAD, "client_name": "", "email_address": "bad", "reference": "x"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(set(resp.json()["errors"]), {"client_name", "email_address", "reference"})

    def test_generates_reference_when_missing(self):
        resp = self.post({k: v for k, v in PAYLOAD.items() if k != "reference"})
        self.assertRegex(resp.json()["reference"], r"^CMP-\d{8}-[0-9A-F]{6}$")


class ModelTests(TestCase):
    def test_resolution_date_set_when_resolved(self):
        c = Complaint.objects.create(client_name="A", phone_number="1", nature_of_complaint="x")
        self.assertIsNone(c.resolution_date)
        c.status = Complaint.Status.RESOLVED
        c.save()
        self.assertEqual(c.resolution_date, timezone.localdate())

    def test_days_open_and_overdue(self):
        c = Complaint.objects.create(
            client_name="A", phone_number="1", nature_of_complaint="x",
            date_received=timezone.now() - timedelta(days=20),
        )
        self.assertEqual(c.days_open(), 20)
        self.assertTrue(c.is_overdue)


class PortalTests(TestCase):
    def setUp(self):
        self.me = make_handler("monalisa", first_name="Monalisa")
        self.other = make_handler("thapelo", first_name="Thapelo")
        self.client.force_login(self.me)
        self.c = Complaint.objects.create(
            client_name="Rudo Chari", phone_number="0772000000", email_address="rudo@example.com",
            nature_of_complaint="Statement shows the wrong balance.",
        )

    def detail_url(self):
        return reverse("portal:detail", args=[self.c.reference])

    def test_login_required(self):
        self.client.logout()
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])
        self.assertEqual(self.client.get("/login/").status_code, 200)

    def test_user_without_permission_gets_403(self):
        stranger = get_user_model().objects.create_user("stranger", password="pw-very-long-123")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get("/").status_code, 403)

    def test_pages_render(self):
        for url in ["/", "/complaints/", "/complaints/?status=open&assigned=me&q=rudo", "/complaints/?status=overdue",
                    "/complaints/new/", self.detail_url(), "/notifications/"]:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)
        self.assertContains(self.client.get("/complaints/?q=rudo"), "Rudo Chari")
        self.assertNotContains(self.client.get("/complaints/?q=nobody"), "Rudo Chari")

    def test_assign_notifies_assignee_and_logs(self):
        self.client.post(self.detail_url(), {"action": "assign", "assigned_to": self.other.pk})
        self.c.refresh_from_db()
        self.assertEqual(self.c.assigned_to, self.other)
        self.assertTrue(Notification.objects.filter(recipient=self.other, kind="assigned").exists())
        self.assertTrue(self.c.events.filter(kind=ComplaintEvent.Kind.ASSIGNED).exists())

    def test_status_change_and_note(self):
        self.client.post(self.detail_url(), {"action": "status", "status": "resolved", "note": "Refund processed."})
        self.c.refresh_from_db()
        self.assertEqual(self.c.status, "resolved")
        self.assertEqual(self.c.resolution_date, timezone.localdate())
        self.client.post(self.detail_url(), {"action": "note", "note": "Called the client."})
        self.assertEqual(self.c.events.filter(kind=ComplaintEvent.Kind.NOTE).count(), 1)

    def test_handling_and_details_forms(self):
        resp = self.client.post(self.detail_url(), {"action": "handling", "action_taken": "Reviewed statement.", "resolution_date": "", "remarks": "OK"})
        self.assertEqual(resp.status_code, 302)
        self.c.refresh_from_db()
        self.assertEqual(self.c.action_taken, "Reviewed statement.")
        resp = self.client.post(self.detail_url(), {
            "action": "details", "client_name": "Rudo Chari-Moyo", "phone_number": "0772000000",
            "email_address": "rudo@example.com", "nature_of_complaint": "Updated text", "staff_member_involved": "",
        })
        self.assertEqual(resp.status_code, 302)
        self.c.refresh_from_db()
        self.assertEqual(self.c.client_name, "Rudo Chari-Moyo")

    def test_log_new_complaint(self):
        resp = self.client.post("/complaints/new/", {
            "date_received": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "source": "phone", "client_name": "Walk In", "phone_number": "0771111111",
            "email_address": "", "nature_of_complaint": "Long wait at reception.",
            "staff_member_involved": "", "assigned_to": self.other.pk,
        })
        created = Complaint.objects.get(client_name="Walk In")
        self.assertRedirects(resp, reverse("portal:detail", args=[created.reference]))
        self.assertEqual(created.source, "phone")
        self.assertTrue(Notification.objects.filter(recipient=self.other, complaint=created).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.me, complaint=created).exists())

    def test_notifications_feed_and_read(self):
        n = Notification.objects.create(recipient=self.me, complaint=self.c, kind="new", message="New complaint")
        data = self.client.get("/notifications/feed.json?since=0").json()
        self.assertEqual(data["unread"], 1)
        self.assertEqual(data["items"][0]["id"], n.pk)
        self.client.get(reverse("portal:notification_open", args=[n.pk]))
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_csv_export_is_safe(self):
        Complaint.objects.create(client_name="=HYPERLINK(1)", phone_number="1", nature_of_complaint="x")
        body = self.client.get("/complaints/export.csv").content.decode("utf-8-sig")
        self.assertIn("Nature of the Complaint", body)
        self.assertIn("'=HYPERLINK(1)", body)


class AdminTests(TestCase):
    def test_admin_still_works(self):
        admin = get_user_model().objects.create_superuser("boss", "b@example.com", "pw-very-long-123")
        self.client.force_login(admin)
        self.assertEqual(self.client.get("/admin/complaints/complaint/").status_code, 200)
