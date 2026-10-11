"""Ingest invoices emailed to a dedicated mailbox (IMAP). One tenant per mailbox.

Every PDF/image/text attachment on an UNSEEN message becomes an invoice upload
that goes through the normal OCR + validation pipeline. Messages are marked Seen
only after all attachments were stored, so a crash re-processes rather than loses mail.
"""
import email
import imaplib
from email.message import Message

from fastapi import HTTPException

from app.core import billing
from app.core.config import settings
from app.modules.invoices import service
from app.modules.invoices.tasks import process_invoice

ALLOWED = (".pdf", ".png", ".jpg", ".jpeg", ".txt")


def attachments(msg: Message):
    for part in msg.walk():
        name = part.get_filename()
        if name and name.lower().endswith(ALLOWED):
            payload = part.get_payload(decode=True)
            if payload and len(payload) <= settings.max_upload_mb * 1024 * 1024:
                yield name, payload


def ingest_message(raw: bytes, tenant_id: str) -> list[str]:
    msg = email.message_from_bytes(raw)
    sender = email.utils.parseaddr(msg.get("From", ""))[1] or "unknown"
    ids = []
    for name, payload in attachments(msg):
        try:
            billing.consume(tenant_id, "invoices")
        except HTTPException:
            break  # quota exhausted: leave remaining attachments unprocessed
        doc_id = service.create_pending(tenant_id, f"email:{sender}", name, payload, f"email:{sender}")
        process_invoice.delay(tenant_id, doc_id)
        ids.append(doc_id)
    return ids


def poll() -> int:
    if not (settings.imap_host and settings.imap_tenant_id):
        return 0
    n = 0
    with imaplib.IMAP4_SSL(settings.imap_host) as imap:
        imap.login(settings.imap_user, settings.imap_password)
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN")
        for num in data[0].split():
            _, parts = imap.fetch(num, "(BODY.PEEK[])")
            n += len(ingest_message(parts[0][1], settings.imap_tenant_id))
            imap.store(num, "+FLAGS", "\\Seen")
    return n
