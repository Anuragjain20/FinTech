"""Invoice creation/processing shared by the API, the Celery worker and the mailbox poller."""
from app.core import db, storage
from app.modules.invoices import extract, validate

KIND = "invoice"


def candidates(tenant_id: str, inv: dict, exclude_id: str | None = None) -> list[dict]:
    if not inv.get("supplier_gstin"):
        return []
    return [d for d in db.list_(tenant_id, KIND, ref=inv["supplier_gstin"]) if d["id"] != exclude_id]


def save(tenant_id: str, actor: str, inv: dict, conf: dict, source: str, doc_id: str | None = None,
         file_key: str | None = None, action: str = "invoice.created") -> dict:
    issues = validate.validate(inv, conf, candidates(tenant_id, inv, doc_id))
    status = validate.status_for(issues)
    doc = {"invoice": inv, "confidence": conf, "issues": issues, "source": source, "file_key": file_key}
    doc_id = db.put(tenant_id, KIND, doc, status, doc_id, ref=inv.get("supplier_gstin"))
    db.audit(tenant_id, actor, action, KIND, doc_id, {"issues": len(issues), "source": source})
    return {"id": doc_id, "status": status, **doc}


def create_pending(tenant_id: str, actor: str, filename: str, data: bytes, source: str) -> str:
    """Persist the original file and a placeholder record; processing happens in the worker."""
    doc_id = db.new_id()
    key = storage.key_for(tenant_id, doc_id, filename)
    storage.put(key, data)
    db.put(tenant_id, KIND, {"invoice": {}, "confidence": {}, "issues": [], "source": source, "file_key": key,
                             "filename": filename}, "processing", doc_id)
    db.audit(tenant_id, actor, "invoice.uploaded", KIND, doc_id, {"filename": filename, "source": source})
    return doc_id


def process(tenant_id: str, doc_id: str) -> dict:
    """OCR + extraction + validation for a previously uploaded file (idempotent)."""
    d = db.get(tenant_id, KIND, doc_id)
    if d is None:
        raise LookupError(doc_id)
    meta = d["data"]
    try:
        text = extract.extract_text(meta["filename"], storage.get(meta["file_key"]))
    except Exception as e:  # OCR missing, corrupt file, ...: surface to the reviewer instead of losing the upload
        failed = {**meta, "error": str(e)}
        db.put(tenant_id, KIND, failed, "failed", doc_id)
        db.audit(tenant_id, "worker", "invoice.failed", KIND, doc_id, {"error": str(e)})
        return {"id": doc_id, "status": "failed", "error": str(e)}
    parsed = extract.parse_invoice_text(text)
    inv = {**parsed["fields"], "line_items": parsed["line_items"]}
    return save(tenant_id, "worker", inv, parsed["confidence"], meta["source"], doc_id, meta["file_key"], "invoice.processed")
