from app.core.jobs import celery
from app.modules.invoices import service


@celery.task(name="fintech.process_invoice", bind=True, max_retries=3, default_retry_delay=30)
def process_invoice(self, tenant_id: str, doc_id: str):
    try:
        return service.process(tenant_id, doc_id)
    except LookupError:
        return None
    except OSError as e:  # storage hiccup: retry
        raise self.retry(exc=e) from e


@celery.task(name="fintech.poll_mailbox")
def poll_mailbox():
    from app.modules.invoices import mailbox
    return mailbox.poll()
