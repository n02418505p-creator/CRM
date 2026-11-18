"""Sends portal emails through the website server (complaints-mail.php on
HostGator), which is authorised to send for mmccapitalzim.com."""
import json
import logging
import urllib.request

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class RelayEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            for recipient in message.to:
                payload = {
                    "to": recipient,
                    "subject": message.subject,
                    "body": message.body,
                    "reply_to": (message.reply_to or [None])[0],
                }
                request = urllib.request.Request(
                    settings.MAIL_RELAY_URL,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "X-API-Key": settings.COMPLAINTS_API_KEY,
                        "User-Agent": "MMC-Complaints-Portal/1.0",
                    },
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=25) as response:
                        data = json.loads(response.read() or b"{}")
                    if not data.get("ok"):
                        raise RuntimeError(data.get("error") or "the mail relay refused the message")
                    sent += 1
                except Exception:
                    logger.exception("Could not send email to %s", recipient)
                    if not self.fail_silently:
                        raise
        return sent
