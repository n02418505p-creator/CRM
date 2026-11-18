import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Complaint

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


@override_settings(COMPLAINTS_API_KEY=API_KEY)
class ApiTests(TestCase):
    def post(self, data, key=API_KEY):
        return self.client.post(
            "/api/complaints/", data=json.dumps(data), content_type="application/json", HTTP_X_API_KEY=key
        )

    def test_rejects_wrong_key(self):
        self.assertEqual(self.post(PAYLOAD, key="nope").status_code, 401)
        self.assertEqual(Complaint.objects.count(), 0)

    def test_creates_complaint(self):
        resp = self.post(PAYLOAD)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["reference"], PAYLOAD["reference"])
        c = Complaint.objects.get()
        self.assertEqual(c.client_name, "Tendai Moyo")
        self.assertEqual(c.status, Complaint.Status.NEW)
        self.assertEqual(c.source, Complaint.Source.WEBSITE)
        self.assertEqual(timezone.localtime(c.date_received).hour, 9)

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

    def test_days_open(self):
        c = Complaint.objects.create(
            client_name="A", phone_number="1", nature_of_complaint="x",
            date_received=timezone.now() - timedelta(days=3),
        )
        self.assertEqual(c.days_open(), 3)


class PortalTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("boss", "b@example.com", "pw-very-long-123")
        self.client.force_login(self.admin)
        Complaint.objects.create(client_name="=HYPERLINK(1)", phone_number="1", nature_of_complaint="x")

    def test_list_page(self):
        self.assertEqual(self.client.get("/complaints/complaint/").status_code, 200)

    def test_csv_export_is_safe(self):
        ids = list(Complaint.objects.values_list("pk", flat=True))
        resp = self.client.post(
            "/complaints/complaint/", {"action": "export_csv", "_selected_action": ids}
        )
        body = resp.content.decode("utf-8-sig")
        self.assertIn("Nature of the Complaint", body)
        self.assertIn("'=HYPERLINK(1)", body)

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get("/complaints/complaint/").status_code, 302)
