from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.core import billing, db, storage
from app.core.auth import Principal, require
from app.core.uploads import read_limited
from app.modules.reconciliation import match, parse, report

router = APIRouter(prefix="/reconciliations", tags=["bank-reconciliation"])
KIND = "reconciliation"
STATEMENT_TYPES = (".csv", ".xlsx", ".xlsm", ".pdf")


class PairIn(BaseModel):
    bank_id: str
    book_id: str


def _load(p: Principal, rec_id: str) -> dict:
    d = db.get(p.tenant_id, KIND, rec_id)
    if not d:
        raise HTTPException(404, "Reconciliation not found")
    return d


def _view(d: dict) -> dict:
    r = d["data"]
    summary = match.summarize(r["bank"], r["book"], r["matches"], r.get("bank_closing"), r.get("book_closing"))
    mb, mo = {m["bank_id"] for m in r["matches"]}, {m["book_id"] for m in r["matches"]}
    classified = match.classify_unmatched(
        [t for t in r["bank"] if t["id"] not in mb], [t for t in r["book"] if t["id"] not in mo], r["bank"], r["book"])
    return {"id": d["id"], "status": d["status"], "name": r.get("name"), "summary": summary,
            "matches": r["matches"], "unmatched_bank": classified["bank"], "unmatched_book": classified["book"]}


@router.post("", status_code=201)
async def create(bank_file: UploadFile = File(...), book_file: UploadFile = File(...),
                 name: str = Form("Reconciliation"), bank_closing_balance: float | None = Form(None),
                 book_closing_balance: float | None = Form(None), date_tolerance_days: int = Form(3),
                 amount_tolerance: float = Form(0.0), p: Principal = Depends(require("operator"))):
    bank_name, bank_raw = await read_limited(bank_file, STATEMENT_TYPES)
    book_name, book_raw = await read_limited(book_file, STATEMENT_TYPES)
    try:
        bank = parse.parse_statement(bank_name, bank_raw, "bank", "B")
        book = parse.parse_statement(book_name, book_raw, "book", "L")
    except parse.ParseError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # corrupt xlsx/pdf etc.
        raise HTTPException(422, "Could not read the uploaded files") from e
    billing.consume(p.tenant_id, "reconciliations")
    matches = match.run_matching(bank, book, date_tolerance_days, amount_tolerance=amount_tolerance)
    data = {"name": name, "bank": bank, "book": book, "matches": matches, "rejected": [],
            "bank_closing": bank_closing_balance, "book_closing": book_closing_balance,
            "params": {"date_tolerance_days": date_tolerance_days, "amount_tolerance": amount_tolerance}}
    rec_id = db.put(p.tenant_id, KIND, data, "open")
    storage.put(storage.key_for(p.tenant_id, rec_id, bank_name), bank_raw)
    storage.put(storage.key_for(p.tenant_id, rec_id, book_name), book_raw)
    db.audit(p.tenant_id, p.actor, "reconciliation.created", KIND, rec_id,
             {"bank": len(bank), "book": len(book), "matches": len(matches)})
    return _view(db.get(p.tenant_id, KIND, rec_id))


@router.get("")
def list_all(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), p: Principal = Depends(require("viewer"))):
    return {"total": db.count(p.tenant_id, KIND), "items": [
        {"id": d["id"], "name": d["data"].get("name"), "status": d["status"], "created_at": d["created_at"]}
        for d in db.list_(p.tenant_id, KIND, None, limit, offset)]}


@router.get("/{rec_id}")
def get(rec_id: str, p: Principal = Depends(require("viewer"))):
    d = _load(p, rec_id)
    return {**_view(d), "audit": db.audit_log(p.tenant_id, rec_id)}


def _find(r: dict, bank_id: str, book_id: str) -> dict | None:
    return next((m for m in r["matches"] if m["bank_id"] == bank_id and m["book_id"] == book_id), None)


def _mutable(d: dict):
    if d["status"] == "finalized":
        raise HTTPException(409, "Reconciliation is finalized")


@router.post("/{rec_id}/confirm")
def confirm(rec_id: str, body: PairIn, p: Principal = Depends(require("operator"))):
    d = _load(p, rec_id); _mutable(d)
    m = _find(d["data"], body.bank_id, body.book_id)
    if not m:
        raise HTTPException(404, "No such match")
    m["status"] = "confirmed"
    db.put(p.tenant_id, KIND, d["data"], d["status"], rec_id)
    db.audit(p.tenant_id, p.actor, "match.confirmed", KIND, rec_id, body.model_dump())
    return _view(db.get(p.tenant_id, KIND, rec_id))


@router.post("/{rec_id}/reject")
def reject(rec_id: str, body: PairIn, p: Principal = Depends(require("operator"))):
    d = _load(p, rec_id); _mutable(d)
    r = d["data"]
    m = _find(r, body.bank_id, body.book_id)
    if not m:
        raise HTTPException(404, "No such match")
    r["matches"].remove(m)
    r["rejected"].append([body.bank_id, body.book_id])
    db.put(p.tenant_id, KIND, r, d["status"], rec_id)
    db.audit(p.tenant_id, p.actor, "match.rejected", KIND, rec_id, body.model_dump())
    return _view(db.get(p.tenant_id, KIND, rec_id))


@router.post("/{rec_id}/manual-match")
def manual(rec_id: str, body: PairIn, p: Principal = Depends(require("operator"))):
    d = _load(p, rec_id); _mutable(d)
    r = d["data"]
    bank = next((t for t in r["bank"] if t["id"] == body.bank_id), None)
    book = next((t for t in r["book"] if t["id"] == body.book_id), None)
    if not bank or not book:
        raise HTTPException(404, "Unknown transaction id")
    if any(m["bank_id"] == body.bank_id or m["book_id"] == body.book_id for m in r["matches"]):
        raise HTTPException(409, "Transaction already matched; reject the existing match first")
    r["matches"].append({"bank_id": body.bank_id, "book_id": body.book_id, "rule": "manual", "confidence": 1.0, "status": "confirmed",
                         "amount_difference": round(bank["amount"] - book["amount"], 2)})
    db.put(p.tenant_id, KIND, r, d["status"], rec_id)
    db.audit(p.tenant_id, p.actor, "match.manual", KIND, rec_id, body.model_dump())
    return _view(db.get(p.tenant_id, KIND, rec_id))


@router.post("/{rec_id}/finalize")
def finalize(rec_id: str, p: Principal = Depends(require("approver"))):
    d = _load(p, rec_id); _mutable(d)
    v = _view(d)
    if v["summary"]["suggested_pending"]:
        raise HTTPException(409, "Confirm or reject all suggested matches before finalizing")
    db.put(p.tenant_id, KIND, d["data"], "finalized", rec_id)
    db.audit(p.tenant_id, p.actor, "reconciliation.finalized", KIND, rec_id, v["summary"])
    return {**v, "status": "finalized"}


@router.get("/{rec_id}/report.xlsx")
def xlsx(rec_id: str, p: Principal = Depends(require("viewer"))):
    d = _load(p, rec_id)
    v = _view(d)
    blob = report.build_xlsx(d["data"], v["summary"], {"bank": v["unmatched_bank"], "book": v["unmatched_book"]})
    return Response(blob, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="brs-{rec_id}.xlsx"'})
