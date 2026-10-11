"""Shared Celery application. Modules define their own tasks in `<module>/tasks.py` using `celery` from here;
`app/worker.py` imports those task modules so a worker process registers them all."""
from celery import Celery

from app.core.config import settings

celery = Celery("fintech", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_always_eager=settings.celery_eager,
    task_acks_late=True, worker_prefetch_multiplier=1, task_time_limit=300,
    broker_connection_retry_on_startup=True,
    beat_schedule={"poll-mailbox": {"task": "fintech.poll_mailbox", "schedule": 120.0}} if settings.imap_host else {},
)
