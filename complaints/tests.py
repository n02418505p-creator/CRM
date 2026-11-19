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


def make_handler(username, group="Complaint handlers", **extra):
    call_command("setup_complaints", stdout=open("/dev/null", "w"))
    user = get_user_model().objects.create_user(username, f"{username}@example.com", "pw-very-long-123", **extra)
    groups = [group] if isinstance(group, str) else group
    for name in groups:
        user.groups.add(Group.objects.get(name=name))
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
            "case_type": "complaint",
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
            "case_type": "complaint",
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
        self.assertContains(self.client.get(reverse("portal:conversation", args=[self.c.reference])), "Please call me.")
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


@override_settings(COMPLAINTS_API_KEY=API_KEY)
class EnquiryTests(TestCase):
    PAYLOAD = {
        "reference": "ENQ-20261118-ABC123",
        "submitted_at": "2026-11-18T11:30:00+02:00",
        "client_name": "Rudo",
        "email_address": "rudo@example.com",
        "subject": "Opening a trading account",
        "message": "How do I open a CDS account?",
    }

    def post(self, data, url="/api/enquiries/"):
        return self.client.post(url, data=json.dumps(data), content_type="application/json", HTTP_X_API_KEY=API_KEY)

    def test_enquiry_from_contact_form(self):
        handler = make_handler("thapelo", group="Client service")
        resp = self.post(self.PAYLOAD)
        self.assertEqual(resp.status_code, 201)
        e = Complaint.objects.get()
        self.assertEqual(e.case_type, "enquiry")
        self.assertEqual(e.reference, "ENQ-20261118-ABC123")
        self.assertEqual(e.subject, "Opening a trading account")
        self.assertTrue(Notification.objects.filter(recipient=handler, message__startswith="New enquiry").exists())
        self.assertEqual(self.post(self.PAYLOAD).status_code, 200)  # resend is not duplicated
        self.assertEqual(Complaint.objects.count(), 1)

    def test_enquiry_validation(self):
        resp = self.post({"client_name": "", "email_address": "bad", "message": ""})
        self.assertEqual(set(resp.json()["errors"]), {"client_name", "email_address", "message"})

    def test_lists_are_separate_and_reply_matches(self):
        self.post(self.PAYLOAD)
        Complaint.objects.create(client_name="Complainer", phone_number="1", nature_of_complaint="x")
        user = make_handler("monalisa", group=["Complaint handlers", "Client service"])
        self.client.force_login(user)
        enquiries = self.client.get("/enquiries/")
        self.assertContains(enquiries, "Rudo")
        self.assertNotContains(enquiries, "Complainer")
        self.assertEqual(enquiries.context["nav"], "enquiries")
        self.assertNotContains(self.client.get("/complaints/"), "Rudo")
        detail = self.client.get("/complaints/ENQ-20261118-ABC123/")
        self.assertContains(detail, "How do I open a CDS account?")
        self.assertEqual(detail.context["nav"], "enquiries")
        self.client.post("/complaints/ENQ-20261118-ABC123/conversation/", {"message": "Here is how."})
        self.assertIn("Update on your enquiry ENQ-20261118-ABC123", mail.outbox[-1].subject)
        self.post({"from_email": "rudo@example.com", "subject": "Re: Update on your enquiry ENQ-20261118-ABC123",
                   "text": "Thanks!", "message_id": "<e1>"}, url="/api/complaints/inbound/")
        self.assertTrue(Complaint.objects.get(reference="ENQ-20261118-ABC123").events.filter(kind="reply").exists())
        self.assertIn("enquiries-register", self.client.get("/complaints/export.csv?type=enquiry")["Content-Disposition"])

    def test_log_enquiry_in_portal_without_phone(self):
        user = make_handler("monalisa", group="Client service")
        self.client.force_login(user)
        self.client.post("/complaints/new/", {
            "case_type": "enquiry", "date_received": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "source": "email", "client_name": "Asker", "phone_number": "", "email_address": "ask@example.com",
            "subject": "Fees", "nature_of_complaint": "What are your fees?", "staff_member_involved": "", "assigned_to": "",
        })
        e = Complaint.objects.get(client_name="Asker")
        self.assertTrue(e.reference.startswith("ENQ-"))

    def test_login_page_has_password_toggle(self):
        resp = self.client.get("/login/")
        self.assertContains(resp, 'type="password"')
        self.assertContains(resp, 'id="pwToggle"')
        self.assertContains(resp, "MMC CRM")


@override_settings(COMPLAINTS_API_KEY=API_KEY)
class EnquiryDetailTests(TestCase):
    SERVICE_FORM = {
        "client_name": "Chipo",
        "email_address": "chipo@example.com",
        "subject": "[Advisory service request] Capital Raising",
        "message": (
            "Service: Capital Raising\nOrganisation: Acme Holdings\nTelephone: +263 77 123 4567\n"
            "Page: /advisory-services.html\n\nWe want to raise USD 5m for expansion.\n\nConsent to be contacted: yes"
        ),
    }

    def setUp(self):
        self.user = make_handler("service", group="Client service")
        self.client.force_login(self.user)

    def post(self, data):
        return self.client.post("/api/enquiries/", data=json.dumps(data), content_type="application/json", HTTP_X_API_KEY=API_KEY)

    def test_service_request_form_is_unpacked(self):
        self.post(self.SERVICE_FORM)
        e = Complaint.objects.get()
        self.assertEqual(e.enquiry_type, "service")
        self.assertEqual(e.division, "advisory")
        self.assertEqual(e.service, "Capital Raising")
        self.assertEqual(e.organisation, "Acme Holdings")
        self.assertEqual(e.phone_number, "+263 77 123 4567")
        self.assertEqual(e.source_page, "/advisory-services.html")
        self.assertEqual(e.nature_of_complaint, "We want to raise USD 5m for expansion.")
        self.assertEqual(e.subject, "Service request: Capital Raising")
        page = self.client.get(reverse("portal:detail", args=[e.reference]))
        self.assertContains(page, "We structure and facilitate bespoke financing solutions")
        self.assertContains(page, "Acme Holdings")
        listing = self.client.get("/enquiries/?service=Capital+Raising&enquiry_type=service")
        self.assertEqual(listing.context["total"], 1)
        self.assertEqual(self.client.get("/enquiries/?service=Securities+Trading").context["total"], 0)
        self.assertContains(self.client.get("/"), "Enquiries by service")

    def test_contact_form_topic(self):
        self.post({"client_name": "Tino", "email_address": "t@example.com", "subject": "Account",
                   "message": "How do I start?", "enquiry_about": "stockbroking|Opening a trading account",
                   "organisation": "Self", "phone_number": "0772"})
        e = Complaint.objects.get()
        self.assertEqual((e.division, e.service, e.enquiry_type, e.organisation), ("stockbroking", "Opening a trading account", "service", "Self"))

    def test_plain_contact_message_is_general(self):
        self.post({"client_name": "Pat", "email_address": "p@example.com", "subject": "Hello", "message": "Question"})
        self.assertEqual(Complaint.objects.get().enquiry_type, "general")

    def test_log_enquiry_with_service_in_portal(self):
        self.client.post("/complaints/new/", {
            "case_type": "enquiry", "date_received": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "source": "phone", "client_name": "Caller", "phone_number": "0771", "email_address": "",
            "organisation": "Big Co", "service": "Securities Trading", "enquiry_type": "",
            "subject": "", "nature_of_complaint": "Wants to buy shares", "staff_member_involved": "", "assigned_to": "",
        })
        e = Complaint.objects.get(client_name="Caller")
        self.assertEqual((e.division, e.enquiry_type, e.organisation), ("stockbroking", "service", "Big Co"))
        email = self.client.get(reverse("portal:detail", args=[e.reference]))
        self.assertContains(email, "We provide trade execution")


class ReportTests(TestCase):
    def setUp(self):
        from datetime import date as _date
        self.service = make_handler("service", group="Client service")
        self.handler = make_handler("handler", group="Complaint handlers", first_name="Thapelo")
        self.boss = make_handler("boss", group="Administrators")
        now = timezone.now()
        self.c1 = Complaint.objects.create(client_name="Old", phone_number="1", nature_of_complaint="x",
                                           date_received=now - timedelta(days=40), assigned_to=self.handler)
        self.c2 = Complaint.objects.create(client_name="Recent", phone_number="1", nature_of_complaint="Slow service",
                                           staff_member_involved="J. Banda", assigned_to=self.handler)
        self.c2.status = "resolved"
        self.c2.save()
        Complaint.objects.create(case_type="enquiry", client_name="Asker", email_address="a@example.com",
                                 nature_of_complaint="?", service="Capital Raising", division="advisory", enquiry_type="service")

    def test_periods(self):
        from datetime import date as _date
        from .reports import period_bounds
        start, end, label = period_bounds("weekly", "2026-11-19")
        self.assertEqual((start, end), (_date(2026, 11, 16), _date(2026, 11, 23)))
        start, end, label = period_bounds("monthly", "2026-02")
        self.assertEqual((start, end, label), (_date(2026, 2, 1), _date(2026, 3, 1), "February 2026"))
        start, end, _ = period_bounds("monthly", "2026-12")
        self.assertEqual(end, _date(2027, 1, 1))

    def test_monthly_complaints_report(self):
        from .reports import build
        report = build("complaint", "monthly", timezone.localdate().strftime("%Y-%m"))
        self.assertEqual(report["stats"]["received"], 1)
        self.assertEqual(report["stats"]["resolved"], 1)
        self.assertEqual(report["stats"]["open_at_end"], 1)  # the 40-day-old one
        self.assertEqual(report["stats"]["overdue"], 1)
        self.assertEqual(report["by_handler"][0]["label"], "Thapelo")
        self.assertEqual(report["extra"][0][1][0]["label"], "J. Banda")

    def test_report_pages_pdf_and_csv(self):
        self.client.force_login(self.handler)
        page = self.client.get("/reports/?period=monthly")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Complaints report")
        self.assertContains(page, "logo.png")
        self.assertContains(page, 'id="previewBtn"')
        self.assertContains(page, "<title>Reports · MMC CRM</title>", html=False)
        self.assertEqual(page.content.decode().count('id="pdfPreview"'), 1)
        pdf = self.client.get("/reports/report.pdf?period=weekly")
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertTrue(pdf["Content-Disposition"].startswith("inline"))      # preview in the browser
        self.assertEqual(pdf["X-Frame-Options"], "SAMEORIGIN")               # can be shown inside the page
        download = self.client.get("/reports/report.pdf?period=weekly&download=1")
        self.assertTrue(download["Content-Disposition"].startswith("attachment"))
        csv_resp = self.client.get("/reports/report.csv?period=monthly&value=" + timezone.localdate().strftime("%Y-%m"))
        self.assertIn("Recent", csv_resp.content.decode("utf-8-sig"))

    def test_report_follows_role(self):
        self.client.force_login(self.service)
        page = self.client.get("/reports/?type=complaint")
        self.assertEqual(page.context["report"]["case_type"], "enquiry")  # complaints not allowed, falls back
        self.assertContains(page, "By service")
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get("/reports/?type=complaint").context["report"]["case_type"], "complaint")
        self.assertEqual(len(self.client.get("/reports/").context["types"]), 2)
        pdf = self.client.get("/reports/report.pdf?type=enquiry&period=monthly")
        self.assertTrue(pdf.content.startswith(b"%PDF"))


class RoleTests(TestCase):
    def setUp(self):
        self.complaint = Complaint.objects.create(client_name="Complainer", phone_number="1", nature_of_complaint="x")
        self.enquiry = Complaint.objects.create(
            case_type="enquiry", client_name="Asker", email_address="a@example.com", nature_of_complaint="Q?"
        )
        self.handler = make_handler("handler", group="Complaint handlers")
        self.service = make_handler("service", group="Client service")
        self.boss = make_handler("boss", group="Administrators")

    def detail(self, case):
        return reverse("portal:detail", args=[case.reference])

    def test_complaint_handler_sees_only_complaints(self):
        self.client.force_login(self.handler)
        self.assertEqual(self.client.get("/complaints/").status_code, 200)
        self.assertEqual(self.client.get("/enquiries/").status_code, 403)
        self.assertEqual(self.client.get(self.detail(self.enquiry)).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:conversation", args=[self.enquiry.reference])).status_code, 403)
        dash = self.client.get("/")
        self.assertNotContains(dash, "Asker")
        self.assertNotContains(dash, 'href="/enquiries/"')
        self.assertNotContains(dash, "Manage staff")
        self.assertNotIn("Asker", self.client.get("/complaints/export.csv").content.decode("utf-8-sig"))
        self.assertEqual(self.client.get("/complaints/export.csv?type=enquiry").status_code, 403)

    def test_client_service_sees_only_enquiries(self):
        self.client.force_login(self.service)
        self.assertEqual(self.client.get("/enquiries/").status_code, 200)
        self.assertEqual(self.client.get("/complaints/").status_code, 403)
        self.assertEqual(self.client.get(self.detail(self.complaint)).status_code, 403)
        self.assertEqual(self.client.get(self.detail(self.enquiry)).status_code, 200)
        form = self.client.get("/complaints/new/").context["form"]
        self.assertEqual([c[0] for c in form.fields["case_type"].choices], ["enquiry"])
        resp = self.client.post("/complaints/new/", {
            "case_type": "complaint", "date_received": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "source": "phone", "client_name": "Sneaky", "phone_number": "1", "email_address": "",
            "subject": "", "nature_of_complaint": "x", "staff_member_involved": "", "assigned_to": "",
        })
        self.assertFalse(Complaint.objects.filter(client_name="Sneaky").exists())
        self.assertEqual(self.client.get("/").context["role_label"], "Client service")

    def test_administrator_sees_everything(self):
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.is_staff)  # set automatically when added to Administrators
        self.client.force_login(self.boss)
        for url in ["/complaints/", "/enquiries/", self.detail(self.complaint), self.detail(self.enquiry), "/admin/auth/user/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get("/"), "Manage staff")

    def test_new_case_notifications_go_to_the_right_team(self):
        from . import services
        services.record_new(Complaint.objects.create(case_type="enquiry", client_name="N", email_address="n@example.com", nature_of_complaint="?"))
        recipients = set(Notification.objects.filter(kind="new").values_list("recipient__username", flat=True))
        self.assertEqual(recipients, {"service", "boss"})

    def test_sidebar_highlight_for_client_service(self):
        self.client.force_login(self.service)
        self.assertEqual(self.client.get("/enquiries/?status=overdue").context["nav"], "overdue")
        self.assertEqual(self.client.get("/enquiries/?assigned=me&status=open").context["nav"], "mine")
        self.assertEqual(self.client.get("/enquiries/").context["nav"], "enquiries")
        page = self.client.get("/").content.decode()
        self.assertIn('href="/enquiries/?status=overdue"', page)
        self.assertIn('id="menuBtn"', page)
        self.assertIn('id="drawerBackdrop"', page)
        self.assertIn('class="nav-label"', page)

    def test_assignment_list_matches_case_type(self):
        self.client.force_login(self.boss)
        staff = {u.username for u in self.client.get(self.detail(self.enquiry)).context["staff"]}
        self.assertIn("service", staff)
        self.assertNotIn("handler", staff)


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
