"""Celery app: OCR/extraction jobs and the periodic mailbox poll.

Run:  celery -A app.worker worker -l info     (and `-B` or a separate beat for the schedule)
"""
from celery import Celery

from .config import settings

celery = Celery("fintech", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_always_eager=settings.celery_eager,
    task_acks_late=True, worker_prefetch_multiplier=1, task_time_limit=300,
    broker_connection_retry_on_startup=True,
    beat_schedule={"poll-mailbox": {"task": "fintech.poll_mailbox", "schedule": 120.0}} if settings.imap_host else {},
)


@celery.task(name="fintech.process_invoice", bind=True, max_retries=3, default_retry_delay=30)
def process_invoice(self, tenant_id: str, doc_id: str):
    from .invoice import service
    try:
        return service.process(tenant_id, doc_id)
    except LookupError:
        return None
    except OSError as e:  # storage hiccup: retry
        raise self.retry(exc=e) from e


@celery.task(name="fintech.legal_review", time_limit=900)
def legal_review(tenant_id: str, review_id: str):
    from . import db
    from .rag import review
    d = db.get(tenant_id, "legal_review", review_id)
    if d is None:
        return None
    try:
        result = review.review(tenant_id, d["data"]["text"])
        db.put(tenant_id, "legal_review", {**d["data"], "result": result}, "completed", review_id)
    except Exception as e:  # keep the request visible to the user instead of failing silently
        db.put(tenant_id, "legal_review", {**d["data"], "error": str(e)}, "failed", review_id)
    return review_id


@celery.task(name="fintech.poll_mailbox")
def poll_mailbox():
    from .invoice import mailbox
    return mailbox.poll()
