"""Celery entrypoint:  celery -A app.worker worker -B -l info   (composition root: imports every module's tasks)."""
from app.core.jobs import celery
from app.modules.invoices import tasks as _invoice_tasks  # noqa: F401
from app.modules.legal import tasks as _legal_tasks  # noqa: F401

__all__ = ["celery"]
