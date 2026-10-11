from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core import billing, db
from app.core.auth import Principal, admin_token, require
from app.core.uploads import read_limited
from app.modules.contracts import public as contracts
from app.modules.legal import ingest, store
from app.modules.legal.tasks import legal_review

router = APIRouter(tags=["legal-review"])
KIND = "legal_review"
DOC_TYPES = (".txt", ".md", ".pdf")


class TextIn(BaseModel):
    text: str = Field(min_length=20, max_length=200_000)


def _start(p: Principal, text: str, contract_id: str | None) -> dict:
    billing.consume(p.tenant_id, "ai_reviews")
    rid = db.put(p.tenant_id, KIND, {"contract_id": contract_id, "text": text}, "processing", ref=contract_id)
    db.audit(p.tenant_id, p.actor, "legal_review.requested", KIND, rid, {"contract": contract_id})
    legal_review.delay(p.tenant_id, rid)
    d = db.get(p.tenant_id, KIND, rid)
    return {"id": rid, "status": d["status"], **{k: v for k, v in d["data"].items() if k != "text"}}


@router.post("/legal/review", status_code=202)
def review_text(body: TextIn, p: Principal = Depends(require("operator"))):
    """Grounded review of arbitrary contract text (e.g. a counterparty draft). Poll GET /legal/reviews/{id}."""
    return _start(p, body.text, None)


@router.post("/contracts/{cid}/legal-review", status_code=202)
def review_contract(cid: str, p: Principal = Depends(require("operator"))):
    c = contracts.get_contract(p.tenant_id, cid)
    if not c:
        raise HTTPException(404, "Contract not found")
    return _start(p, c.text, cid)


@router.get("/legal/reviews/{rid}")
def get_review(rid: str, p: Principal = Depends(require("viewer"))):
    d = db.get(p.tenant_id, KIND, rid)
    if not d:
        raise HTTPException(404, "Review not found")
    return {"id": rid, "status": d["status"], "created_at": d["created_at"], **{k: v for k, v in d["data"].items() if k != "text"}}


@router.get("/contracts/{cid}/legal-reviews")
def contract_reviews(cid: str, p: Principal = Depends(require("viewer"))):
    return [{"id": d["id"], "status": d["status"], "created_at": d["created_at"],
             "issue_count": d["data"].get("result", {}).get("issue_count")} for d in db.list_(p.tenant_id, KIND, ref=cid)]


# ---- corpus management ------------------------------------------------------------------

@router.post("/legal/documents", status_code=201)
async def add_private(file: UploadFile = File(...), source: str = Form(..., max_length=300), p: Principal = Depends(require("admin"))):
    """Tenant-private reference material (clause playbook, precedent contracts). Visible only to this tenant."""
    name, data = await read_limited(file, DOC_TYPES)
    n = store.add_document(p.tenant_id, source, ingest.read_text(name, data))
    if not n:
        raise HTTPException(422, "No text could be extracted")
    db.audit(p.tenant_id, p.actor, "legal_corpus.added", "rag", "", {"source": source, "chunks": n})
    return {"source": source, "chunks": n}


@router.get("/legal/documents")
def list_private(p: Principal = Depends(require("viewer"))):
    return {"private": store.stats(p.tenant_id), "shared": store.stats(None)}


@router.delete("/legal/documents")
def delete_private(source: str, p: Principal = Depends(require("admin"))):
    n = store.delete_source(p.tenant_id, source)
    if not n:
        raise HTTPException(404, "No such source")
    db.audit(p.tenant_id, p.actor, "legal_corpus.deleted", "rag", "", {"source": source, "chunks": n})
    return {"deleted_chunks": n}


@router.post("/legal/corpus", status_code=201, dependencies=[Depends(admin_token)])
async def add_shared(file: UploadFile = File(...), source: str = Form(..., max_length=300), replace: bool = Form(False)):
    """Platform operator: load public-law text (bare Acts) into the shared corpus. Requires X-Admin-Token."""
    name, data = await read_limited(file, DOC_TYPES)
    if replace:
        store.delete_source(None, source)
    n = store.add_document(None, source, ingest.read_text(name, data))
    if not n:
        raise HTTPException(422, "No text could be extracted")
    return {"source": source, "chunks": n}
