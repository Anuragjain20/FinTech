from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import db
from ..auth import Principal, require
from . import export, extract, validate

router = APIRouter(prefix="/invoices", tags=["invoices"])
KIND = "invoice"


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


def _store(p: Principal, inv: dict, conf: dict, source: str) -> dict:
    existing = db.list_(p.tenant_id, KIND)
    issues = validate.validate(inv, conf, existing)
    doc = {"invoice": inv, "confidence": conf, "issues": issues, "source": source}
    doc_id = db.put(p.tenant_id, KIND, doc, status=validate.status_for(issues))
    db.audit(p.tenant_id, p.actor, "invoice.created", KIND, doc_id, {"issues": len(issues), "source": source})
    return {"id": doc_id, "status": validate.status_for(issues), **doc}


@router.post("/upload", status_code=201)
async def upload(file: UploadFile = File(...), p: Principal = Depends(require("operator"))):
    data = await file.read()
    try:
        text = extract.extract_text(file.filename or "", data)
    except extract.OcrUnavailable as e:
        raise HTTPException(422, str(e))
    parsed = extract.parse_invoice_text(text)
    inv = {**parsed["fields"], "line_items": parsed["line_items"]}
    return _store(p, inv, parsed["confidence"], f"upload:{file.filename}")


@router.post("/text", status_code=201)
def from_text(body: TextIn, p: Principal = Depends(require("operator"))):
    parsed = extract.parse_invoice_text(body.text)
    inv = {**parsed["fields"], "line_items": parsed["line_items"]}
    return _store(p, inv, parsed["confidence"], "text")


@router.post("", status_code=201)
def create(body: InvoiceIn, p: Principal = Depends(require("operator"))):
    inv = body.model_dump()
    return _store(p, inv, {}, "api")


@router.get("")
def list_invoices(status: str | None = None, p: Principal = Depends(require("viewer"))):
    return [{"id": d["id"], "status": d["status"], **d["data"]} for d in db.list_(p.tenant_id, KIND, status)]


@router.get("/review-queue")
def review_queue(p: Principal = Depends(require("viewer"))):
    return list_invoices("needs_review", p)


@router.get("/export/csv", response_class=PlainTextResponse)
def export_csv(p: Principal = Depends(require("viewer"))):
    return export.to_csv(db.list_(p.tenant_id, KIND, "approved"))


@router.get("/export/tally", response_class=PlainTextResponse)
def export_tally(company: str = "My Company", p: Principal = Depends(require("viewer"))):
    return PlainTextResponse(export.to_tally_xml(db.list_(p.tenant_id, KIND, "approved"), company=company),
                             media_type="application/xml")


@router.get("/{invoice_id}")
def get_invoice(invoice_id: str, p: Principal = Depends(require("viewer"))):
    d = db.get(p.tenant_id, KIND, invoice_id)
    if not d:
        raise HTTPException(404, "Invoice not found")
    return {"id": d["id"], "status": d["status"], **d["data"], "audit": db.audit_log(p.tenant_id, invoice_id)}


@router.put("/{invoice_id}")
def correct(invoice_id: str, body: InvoiceIn, p: Principal = Depends(require("operator"))):
    """Human correction: re-validates; corrected fields are treated as confidence 1.0."""
    d = db.get(p.tenant_id, KIND, invoice_id)
    if not d:
        raise HTTPException(404, "Invoice not found")
    if d["status"] == "approved":
        raise HTTPException(409, "Approved invoices are immutable")
    inv = body.model_dump()
    conf = {k: 1.0 for k, v in inv.items() if v not in (None, "", [])}
    others = [x for x in db.list_(p.tenant_id, KIND) if x["id"] != invoice_id]
    issues = validate.validate(inv, conf, others)
    status = validate.status_for(issues)
    db.put(p.tenant_id, KIND, {**d["data"], "invoice": inv, "confidence": conf, "issues": issues}, status, invoice_id)
    db.audit(p.tenant_id, p.actor, "invoice.corrected", KIND, invoice_id, {"before": d["data"]["invoice"], "after": inv})
    return {"id": invoice_id, "status": status, "invoice": inv, "issues": issues}


@router.post("/{invoice_id}/approve")
def approve(invoice_id: str, body: ApproveIn, p: Principal = Depends(require("approver"))):
    d = db.get(p.tenant_id, KIND, invoice_id)
    if not d:
        raise HTTPException(404, "Invoice not found")
    errors = [i for i in d["data"]["issues"] if i["severity"] == "error"]
    if errors and not body.override_reason:
        raise HTTPException(409, {"message": "Invoice has blocking errors; fix them or supply override_reason", "errors": errors})
    db.put(p.tenant_id, KIND, d["data"], "approved", invoice_id)
    db.audit(p.tenant_id, p.actor, "invoice.approved", KIND, invoice_id, {"override_reason": body.override_reason})
    return {"id": invoice_id, "status": "approved"}
