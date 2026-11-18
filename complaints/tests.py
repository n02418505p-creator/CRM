import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
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


class ClientEmailTests(TestCase):
    def setUp(self):
        self.me = make_handler("garikayi", first_name="Garikayi", last_name="Gomwe")
        self.other = make_handler("thapelo", first_name="Thapelo")
        self.client.force_login(self.me)
        self.c = Complaint.objects.create(
            client_name="Takudzwa Murombedzi", phone_number="0772000000", email_address="client@example.com",
            nature_of_complaint="Slow service at the trading desk.",
        )
        self.url = reverse("portal:detail", args=[self.c.reference])

    def test_message_client(self):
        self.client.post(self.url, {"action": "client", "message": "We have sent your case to the relevant team."})
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["client@example.com"])
        self.assertIn(self.c.reference, email.subject)
        self.assertIn("has been updated with the following comments", email.body)
        self.assertIn("Garikayi Gomwe", email.body)
        self.assertIn("We have sent your case", email.body)
        self.assertIn("Status:      New", email.body)
        self.assertEqual(self.c.events.filter(kind=ComplaintEvent.Kind.CLIENT).count(), 1)

    def test_history_included_in_later_updates(self):
        self.client.post(self.url, {"action": "client", "message": "First update."})
        self.client.post(self.url, {"action": "client", "message": "Second update."})
        self.assertIn("Previous updates", mail.outbox[1].body)
        self.assertIn("First update.", mail.outbox[1].body)

    def test_status_and_assignment_notify_client(self):
        self.client.post(self.url, {"action": "assign", "assigned_to": self.other.pk, "notify_client": "yes"})
        self.assertIn("assigned to Thapelo", mail.outbox[-1].body)
        self.client.post(self.url, {"action": "status", "status": "resolved", "note": "Refund paid.", "notify_client": "yes"})
        self.assertIn("Your complaint has been resolved.", mail.outbox[-1].body)
        self.assertIn("Refund paid.", mail.outbox[-1].body)
        self.assertIn("Handled by:  Thapelo", mail.outbox[-1].body)
        self.assertEqual(len(mail.outbox), 2)

    def test_no_email_when_unticked(self):
        self.client.post(self.url, {"action": "status", "status": "in_progress"})
        self.assertEqual(len(mail.outbox), 0)

    def test_no_email_address(self):
        self.c.email_address = ""
        self.c.save()
        self.client.post(self.url, {"action": "client", "message": "Hello"})
        self.assertEqual(len(mail.outbox), 0)

    def test_acknowledgement_for_logged_complaint(self):
        self.client.post("/complaints/new/", {
            "date_received": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "source": "phone",
            "client_name": "Caller", "phone_number": "0771111111", "email_address": "caller@example.com",
            "nature_of_complaint": "Could not reach my broker.", "staff_member_involved": "",
            "assigned_to": "", "send_acknowledgement": "yes",
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("We've received your complaint", mail.outbox[0].subject)
        self.assertIn("Your reference number is CMP-", mail.outbox[0].body)


@override_settings(COMPLAINTS_API_KEY=API_KEY)
class ClientReplyTests(TestCase):
    def setUp(self):
        self.handler = make_handler("thapelo")
        self.c = Complaint.objects.create(
            client_name="Tendai Moyo", phone_number="1", email_address="Tendai@Example.com",
            nature_of_complaint="Refund not received.",
        )

    def post(self, **data):
        return self.client.post(
            "/api/complaints/inbound/", data=json.dumps(data), content_type="application/json", HTTP_X_API_KEY=API_KEY
        )

    def test_reply_added_to_timeline_and_notifies(self):
        text = (
            "I still have not received my refund.\n\nTendai\n\n________________________________\n"
            "From: MMC Capital Complaints <research@mmccapitalzim.com>\nDear Tendai,\nYour complaint ..."
        )
        resp = self.post(from_email="tendai@example.com", from_name="Tendai Moyo",
                         subject=f"RE: Update on your complaint {self.c.reference} – MMC Capital", text=text, message_id="<abc@mail>")
        self.assertTrue(resp.json()["matched"])
        event = self.c.events.get(kind=ComplaintEvent.Kind.REPLY)
        self.assertEqual(event.message, "I still have not received my refund.\n\nTendai")
        self.assertTrue(Notification.objects.filter(recipient=self.handler, kind="reply").exists())
        # the same email delivered twice is only added once
        self.post(from_email="tendai@example.com", subject=f"RE: {self.c.reference}", text=text, message_id="<abc@mail>")
        self.assertEqual(self.c.events.filter(kind=ComplaintEvent.Kind.REPLY).count(), 1)

    def test_reply_shows_on_portal_and_in_next_update(self):
        self.post(from_email="tendai@example.com", subject=f"Re: {self.c.reference}", text="Please call me.", message_id="<1@x>")
        self.client.force_login(self.handler)
        url = reverse("portal:detail", args=[self.c.reference])
        self.assertContains(self.client.get(url), "Please call me.")
        self.client.post(url, {"action": "client", "message": "We will call you today."})
        self.assertIn("(your reply)", mail.outbox[-1].body)
        self.assertIn("Please call me.", mail.outbox[-1].body)

    def test_outlook_image_placeholders_removed(self):
        self.post(from_email="tendai@example.com", subject=f"Re: {self.c.reference}",
                  text="Resolve as soon as possible\n\n[cid:7d2685b0-04ea-438a-b908-a636c461ae2c]", message_id="<cid@x>")
        self.assertEqual(self.c.events.get(kind=ComplaintEvent.Kind.REPLY).message, "Resolve as soon as possible")

    def test_unmatched_and_unauthorised(self):
        self.assertFalse(self.post(from_email="x@example.com", subject="Hello", text="hi").json()["matched"])
        resp = self.client.post("/api/complaints/inbound/", data="{}", content_type="application/json", HTTP_X_API_KEY="bad")
        self.assertEqual(resp.status_code, 401)


class ConversationTests(TestCase):
    def setUp(self):
        self.me = make_handler("monalisa", first_name="Monalisa")
        self.client.force_login(self.me)
        self.c = Complaint.objects.create(
            client_name="Takudzwa", phone_number="1", email_address="t@example.com", nature_of_complaint="Original complaint text",
        )
        self.url = reverse("portal:conversation", args=[self.c.reference])

    def test_thread_shows_complaint_messages_and_replies(self):
        from . import services
        self.client.post(self.url, {"message": "We are looking into it."})
        self.assertEqual(len(mail.outbox), 1)
        services.record_reply(self.c, "Okay thank you", "t@example.com", message_id="<m1>")
        resp = self.client.get(self.url)
        self.assertContains(resp, "Original complaint text")
        self.assertContains(resp, "We are looking into it.")
        self.assertContains(resp, "Okay thank you")
        self.assertGreater(self.client.get(self.url.replace("conversation/", "conversation.json")).json()["latest"], 0)

    def test_inbox_and_waiting_filter(self):
        from . import services
        services.record_reply(self.c, "Any news?", "t@example.com", message_id="<m2>")
        self.assertContains(self.client.get("/conversations/"), "Any news?")
        self.assertContains(self.client.get("/conversations/?show=waiting"), "waiting for us")
        n = Notification.objects.get(recipient=self.me, kind="reply")
        resp = self.client.get(reverse("portal:notification_open", args=[n.pk]))
        self.assertIn("/conversation/", resp["Location"])

    def test_sidebar_highlights_filtered_views(self):
        resp = self.client.get("/complaints/?status=overdue")
        self.assertEqual(resp.context["nav"], "overdue")
        self.assertEqual(self.client.get("/complaints/?assigned=me&status=open").context["nav"], "mine")
        self.assertEqual(self.client.get("/complaints/").context["nav"], "list")
        self.assertEqual(self.client.get(self.url).context["nav"], "conversations")


class AdminTests(TestCase):
    def test_admin_still_works(self):
        admin = get_user_model().objects.create_superuser("boss", "b@example.com", "pw-very-long-123")
        self.client.force_login(admin)
        resp = self.client.get("/admin/complaints/complaint/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "favicon-32x32.png")

    def test_dark_theme_switch_and_no_activity_panel(self):
        user = make_handler("dark")
        self.client.force_login(user)
        c = Complaint.objects.create(client_name="A", phone_number="1", nature_of_complaint="x")
        resp = self.client.get(reverse("portal:detail", args=[c.reference]))
        self.assertContains(resp, 'id="themeBtn"')
        self.assertNotContains(resp, "<h3 style=\"margin-bottom:.8rem\">Activity</h3>", html=False)

    def test_portal_pages_have_mmc_icon(self):
        self.assertContains(self.client.get("/login/"), "favicon_io/favicon-32x32.png")
