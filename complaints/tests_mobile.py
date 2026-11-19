"""Phone-size check of every portal page (runs in GitHub Actions).

Opens each page in Chromium at phone widths, fails if anything makes the page
wider than the screen, and saves a screenshot of every page to
$MOBILE_SHOTS_DIR for review.
"""
import os
import unittest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # not installed for the normal test run
    sync_playwright = None

from . import services
from .models import Complaint, Notification

SHOTS = os.environ.get("MOBILE_SHOTS_DIR", "/tmp/mobile-shots")
WIDTHS = [390, 360]

OVERFLOW_JS = """() => {
  const w = document.documentElement.clientWidth;
  const offenders = [];
  document.querySelectorAll('body *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    if (el.closest('.table-wrap, .results, .sidebar, .segmented, .chat-body')) return;   // these scroll/slide by design
    if (r.right > w + 1 || r.left < -1) {
      offenders.push((el.tagName + '.' + (el.className || '')).slice(0, 80) + ' right=' + Math.round(r.right));
    }
  });
  return {scroll: document.documentElement.scrollWidth, width: w, offenders: offenders.slice(0, 8)};
}"""


@unittest.skipUnless(sync_playwright, "Playwright is not installed")
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PhoneLayoutTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()
        os.makedirs(SHOTS, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        super().tearDownClass()

    def setUp(self):
        call_command("setup_complaints", stdout=open(os.devnull, "w"))
        User = get_user_model()
        self.admin = User.objects.create_user("boss", "boss@example.com", "pw-very-long-123", first_name="Elizabeth", last_name="Karombo-Longsurname")
        self.admin.groups.add(Group.objects.get(name="Administrators"))
        self.complaint = Complaint.objects.create(
            client_name="Tendai Moyo-Chikwanha", phone_number="+263 77 123 4567", email_address="tendai.moyo.chikwanha@example-long-domain.co.zw",
            nature_of_complaint="My trade instruction of 10 November was not executed and nobody called me back. " * 3,
            staff_member_involved="Thapelo Mashayamombe", date_received=timezone.now() - timedelta(days=20), assigned_to=self.admin,
        )
        services.record_new(self.complaint)
        self.enquiry = Complaint.objects.create(
            case_type="enquiry", client_name="Chipo Nyathi", email_address="chipo@example.com", phone_number="0772 000 000",
            organisation="Acme Holdings (Private) Limited", service="Advisory & Sponsoring Broker Services", division="stockbroking",
            enquiry_type="service", subject="Service request: Advisory & Sponsoring Broker Services",
            nature_of_complaint="We would like to list on the VFEX next year and need a sponsoring broker.", source_page="/stockbroker-services.html",
        )
        services.record_new(self.enquiry)
        services.email_client(self.enquiry, "Dear Valued Client,\n\nThank you for your enquiry. A member of our team will call you this week.", self.admin)
        services.record_reply(self.enquiry, "Thank you, mornings are best for me. " * 4, "chipo@example.com", message_id="<m1>")
        Notification.objects.create(recipient=self.admin, complaint=self.enquiry, kind="reply", message="Chipo Nyathi replied to " + self.enquiry.reference)

    def pages(self):
        c, e = self.complaint.reference, self.enquiry.reference
        return [
            ("dashboard", "/"),
            ("complaints", "/complaints/"),
            ("complaints-filtered", "/complaints/?status=overdue"),
            ("enquiries", "/enquiries/"),
            ("new-complaint", "/complaints/new/?type=complaint"),
            ("new-enquiry", "/complaints/new/?type=enquiry"),
            ("complaint-detail", f"/complaints/{c}/"),
            ("enquiry-detail", f"/complaints/{e}/"),
            ("conversation", f"/complaints/{e}/conversation/"),
            ("conversations", "/conversations/"),
            ("notifications", "/notifications/"),
            ("staff-admin", "/admin/auth/user/"),
            ("staff-edit", f"/admin/auth/user/{self.admin.pk}/change/"),
        ]

    def new_page(self, width, logged_in=True):
        context = self.browser.new_context(viewport={"width": width, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        if logged_in:
            self.client.force_login(self.admin)
            cookie = self.client.cookies["sessionid"]
            context.add_cookies([{"name": "sessionid", "value": cookie.value, "url": self.live_server_url}])
        return context, context.new_page()

    def check(self, page, name, width):
        result = page.evaluate(OVERFLOW_JS)
        page.screenshot(path=os.path.join(SHOTS, f"{width}-{name}.png"), full_page=True)
        self.assertLessEqual(result["scroll"], result["width"] + 1, f"{name} at {width}px is wider than the screen: {result}")
        self.assertEqual(result["offenders"], [], f"{name} at {width}px has content off the screen: {result['offenders']}")

    def test_signed_in_pages(self):
        for width in WIDTHS:
            context, page = self.new_page(width)
            for name, url in self.pages():
                with self.subTest(page=name, width=width):
                    response = page.goto(self.live_server_url + url)
                    self.assertEqual(response.status, 200, f"{name} returned {response.status}")
                    page.wait_for_load_state("networkidle")
                    self.check(page, name, width)
            # The slide-in menu
            page.goto(self.live_server_url + "/")
            page.click("#menuBtn")
            page.wait_for_timeout(400)
            self.assertTrue(page.is_visible("#drawerBackdrop"))
            page.screenshot(path=os.path.join(SHOTS, f"{width}-menu-open.png"))
            box = page.locator(".sidebar").bounding_box()
            self.assertAlmostEqual(box["x"], 0, delta=1)
            page.click("#drawerBackdrop", position={"x": width - 10, "y": 400})
            page.wait_for_timeout(400)
            self.assertFalse(page.locator(".sidebar.open").count())
            # Notifications drop-down
            page.click("#bellBtn")
            page.wait_for_timeout(200)
            page.screenshot(path=os.path.join(SHOTS, f"{width}-bell-open.png"))
            box = page.locator("#bellMenu").bounding_box()
            self.assertLessEqual(box["x"] + box["width"], width + 1)
            context.close()

    def test_lists_show_cards_on_phones(self):
        context, page = self.new_page(390)
        page.goto(self.live_server_url + "/complaints/")
        self.assertFalse(page.is_visible("table.list thead"))
        label = page.evaluate("getComputedStyle(document.querySelector('td[data-label=\"Status\"]'), '::before').content")
        self.assertIn("Status", label)
        self.assertFalse(page.is_visible("#f-status"))
        page.click("#filtersToggle")
        self.assertTrue(page.is_visible("#f-status"))
        context.close()

    def test_sign_in_page(self):
        for width in WIDTHS:
            context, page = self.new_page(width, logged_in=False)
            page.goto(self.live_server_url + "/login/")
            page.wait_for_load_state("networkidle")
            self.assertTrue(page.is_visible(".login-mobile-brand img"), "logo should show on the phone sign-in page")
            self.check(page, "login", width)
            context.close()

    def test_no_access_page(self):
        stranger = get_user_model().objects.create_user("stranger", password="pw-very-long-123")
        context = self.browser.new_context(viewport={"width": 360, "height": 800})
        self.client.force_login(stranger)
        context.add_cookies([{"name": "sessionid", "value": self.client.cookies["sessionid"].value, "url": self.live_server_url}])
        page = context.new_page()
        page.goto(self.live_server_url + "/")
        self.check(page, "no-access", 360)
        context.close()
