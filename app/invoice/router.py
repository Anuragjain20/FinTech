from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import billing, db, storage
from ..auth import Principal, require
from ..uploads import read_limited
from . import export, extract, service

router = APIRouter(prefix="/invoices", tags=["invoices"])
KIND = service.KIND
UPLOAD_TYPES = (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".txt")


class InvoiceIn(BaseModel):
    """Structured submission (e.g. from an API client or a corrected extraction)."""
    supplier_name: str | None = None
    supplier_gstin: str | None = None
    buyer_gstin: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    taxable_value: float | None = None
    cgst: float | None = None
    sgst: float | None = None
    igst: float | None = None
    total: float | None = None
    line_items: list[dict] = []


class TextIn(BaseModel):
    text: str


class ApproveIn(BaseModel):
    override_reason: str | None = None


@router.post("/upload", status_code=202)
async def upload(file: UploadFile = File(...), p: Principal = Depends(require("operator"))):
    """Store the original and queue OCR/extraction. Poll GET /invoices/{id} until status != 'processing'."""
    from ..worker import process_invoice
    name, data = await read_limited(file, UPLOAD_TYPES)
    billing.consume(p.tenant_id, "invoices")
    doc_id = service.create_pending(p.tenant_id, p.actor, name, data, f"upload:{name}")
    process_invoice.delay(p.tenant_id, doc_id)
    d = db.get(p.tenant_id, KIND, doc_id)
    return {"id": doc_id, "status": d["status"], **d["data"]}


@router.post("/text", status_code=201)
def from_text(body: TextIn, p: Principal = Depends(require("operator"))):
    billing.consume(p.tenant_id, "invoices")
    parsed = extract.parse_invoice_text(body.text)
    inv = {**parsed["fields"], "line_items": parsed["line_items"]}
    return service.save(p.tenant_id, p.actor, inv, parsed["confidence"], "text")


@router.post("", status_code=201)
def create(body: InvoiceIn, p: Principal = Depends(require("operator"))):
    billing.consume(p.tenant_id, "invoices")
    return service.save(p.tenant_id, p.actor, body.model_dump(), {}, "api")


def _summary(d: dict) -> dict:
    return {"id": d["id"], "status": d["status"], "created_at": d["created_at"], **d["data"]}


@router.get("")
def list_invoices(status: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  p: Principal = Depends(require("viewer"))):
    return {"total": db.count(p.tenant_id, KIND, status), "items":
            [_summary(d) for d in db.list_(p.tenant_id, KIND, status, limit, offset)]}


@router.get("/review-queue")
def review_queue(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), p: Principal = Depends(require("viewer"))):
    return list_invoices("needs_review", limit, offset, p)


def _all_approved(p: Principal) -> list[dict]:
    rows, off = [], 0
    while chunk := db.list_(p.tenant_id, KIND, "approved", 500, off):
        rows += chunk
        off += 500
    return rows


@router.get("/export/csv", response_class=PlainTextResponse)
def export_csv(p: Principal = Depends(require("viewer"))):
    return export.to_csv(_all_approved(p))


@router.get("/export/tally", response_class=PlainTextResponse)
def export_tally(company: str = "My Company", p: Principal = Depends(require("viewer"))):
    return PlainTextResponse(export.to_tally_xml(_all_approved(p), company=company), media_type="application/xml")


@router.get("/{invoice_id}")
def get_invoice(invoice_id: str, p: Principal = Depends(require("viewer"))):
    d = db.get(p.tenant_id, KIND, invoice_id)
    if not d:
        raise HTTPException(404, "Invoice not found")
    return {**_summary(d), "audit": db.audit_log(p.tenant_id, invoice_id)}


@router.get("/{invoice_id}/file")
def original_file(invoice_id: str, p: Principal = Depends(require("viewer"))):
    from fastapi.responses import Response
    d = db.get(p.tenant_id, KIND, invoice_id)
    if not d or not d["data"].get("file_key"):
        raise HTTPException(404, "No original file")
    return Response(storage.get(d["data"]["file_key"]), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{d["data"].get("filename", "invoice")}"'})


@router.put("/{invoice_id}")
def correct(invoice_id: str, body: InvoiceIn, p: Principal = Depends(require("operator"))):
    """Human correction: re-validates; corrected fields are treated as confidence 1.0."""
    d = db.get(p.tenant_id, KIND, invoice_id)
    if not d:
        raise HTTPException(404, "Invoice not found")
    if d["status"] == "approved":
        raise HTTPException(409, "Approved invoices are immutable")
    if d["status"] == "processing":
        raise HTTPException(409, "Invoice is still being processed")
    inv = body.model_dump()
    conf = {k: 1.0 for k, v in inv.items() if v not in (None, "", [])}
    before = d["data"]["invoice"]
    r = service.save(p.tenant_id, p.actor, inv, conf, d["data"]["source"], invoice_id, d["data"].get("file_key"), "invoice.corrected")
    db.audit(p.tenant_id, p.actor, "invoice.diff", KIND, invoice_id, {"before": before, "after": inv})
    return {"id": invoice_id, "status": r["status"], "invoice": inv, "issues": r["issues"]}


@router.post("/{invoice_id}/approve")
def approve(invoice_id: str, body: ApproveIn, p: Principal = Depends(require("approver"))):
    d = db.get(p.tenant_id, KIND, invoice_id)
    if not d:
        raise HTTPException(404, "Invoice not found")
    if d["status"] in ("processing", "failed"):
        raise HTTPException(409, f"Invoice is {d['status']}; it cannot be approved")
    errors = [i for i in d["data"]["issues"] if i["severity"] == "error"]
    if errors and not body.override_reason:
        raise HTTPException(409, {"message": "Invoice has blocking errors; fix them or supply override_reason", "errors": errors})
    db.put(p.tenant_id, KIND, d["data"], "approved", invoice_id)
    db.audit(p.tenant_id, p.actor, "invoice.approved", KIND, invoice_id, {"override_reason": body.override_reason})
    return {"id": invoice_id, "status": "approved"}
