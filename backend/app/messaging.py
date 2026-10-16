"""Sending email and text messages. Nothing is sent unless SMTP / ClickSend are set up in .env."""
import logging
import smtplib
from email.message import EmailMessage

from . import config

log = logging.getLogger(__name__)
_test_outbox: list[dict] | None = None  # tests capture messages here instead of sending


def capture_for_tests() -> list[dict]:
    global _test_outbox
    _test_outbox = []
    return _test_outbox


class NotConfigured(Exception):
    pass


def email_ready() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_FROM) or _test_outbox is not None


def sms_ready() -> bool:
    return bool(config.CLICKSEND_USERNAME and config.CLICKSEND_API_KEY) or _test_outbox is not None


def send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    if _test_outbox is not None:
        _test_outbox.append({"channel": "email", "to": to, "subject": subject, "body": text})
        return
    if not email_ready():
        raise NotConfigured("Email isn't set up yet (SMTP_HOST in .env)")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, to, subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
        s.starttls()
        if config.SMTP_USER:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
        s.send_message(msg)


def send_sms(to: str, text: str) -> None:
    if _test_outbox is not None:
        _test_outbox.append({"channel": "sms", "to": to, "body": text})
        return
    if not sms_ready():
        raise NotConfigured("Text messages aren't set up yet (CLICKSEND_USERNAME in .env)")
    import httpx

    r = httpx.post("https://rest.clicksend.com/v3/sms/send", auth=(config.CLICKSEND_USERNAME, config.CLICKSEND_API_KEY), timeout=30,
                   json={"messages": [{"source": "peak", "from": config.SMS_FROM, "to": to, "body": text}]})
    if r.status_code >= 300:
        raise RuntimeError(f"ClickSend said {r.status_code}: {r.text[:200]}")
