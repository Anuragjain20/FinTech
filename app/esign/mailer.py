"""Outbound email. SMTP when configured; otherwise captured in `outbox` (development and tests)."""
import smtplib
import ssl
from email.message import EmailMessage

from ..config import settings

outbox: list[dict] = []


def send(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        outbox.append({"to": to, "subject": subject, "body": body})
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
        if settings.smtp_starttls:
            s.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)
