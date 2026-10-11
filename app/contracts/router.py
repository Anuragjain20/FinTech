from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from .. import billing, db
from ..auth import Principal, require
from . import compare, docx_export, risk, templates

router = APIRouter(prefix="/contracts", tags=["contracts"])
KIND = "contract"


class GenerateIn(BaseModel):
    template_id: str
    answers: dict


class TextIn(BaseModel):
    text: str


class EditIn(BaseModel):
    text: str
    note: str | None = None


class ApproveIn(BaseModel):
    acknowledge_risks: bool = False


@router.get("/templates")
def list_templates(p: Principal = Depends(require("viewer"))):
    return [{"id": k, "name": v["name"], "description": v["description"], "lawyer_reviewed": v["lawyer_reviewed"]}
            for k, v in templates.TEMPLATES.items()]


@router.get("/templates/{template_id}")
def template_detail(template_id: str, p: Principal = Depends(require("viewer"))):
    t = templates.TEMPLATES.get(template_id)
    if not t:
        raise HTTPException(404, "Unknown template")
    return {"id": template_id, "name": t["name"], "description": t["description"],
            "lawyer_reviewed": t["lawyer_reviewed"], "questions": t["questions"], "clauses": t["clauses"]}


@router.post("/review")
def review_text(body: TextIn, p: Principal = Depends(require("viewer"))):
    """Screen any contract text (e.g. a counterparty's draft) for missing clauses and risky terms."""
    return risk.review(body.text)


@router.post("", status_code=201)
def generate(body: GenerateIn, p: Principal = Depends(require("operator"))):
    try:
        doc = templates.render(body.template_id, body.answers)
    except templates.TemplateError as e:
        raise HTTPException(422, str(e)) from e
    billing.consume(p.tenant_id, "contracts")
    text = templates.to_text(doc)
    data = {"title": doc["title"], "template_id": body.template_id, "lawyer_reviewed": doc["lawyer_reviewed"],
            "answers": body.answers, "versions": [{"text": text, "by": p.actor, "at": db.now_iso(), "note": "generated"}]}
    cid = db.put(p.tenant_id, KIND, data, "draft")
    db.audit(p.tenant_id, p.actor, "contract.generated", KIND, cid, {"template": body.template_id})
    return {"id": cid, "status": "draft", "title": doc["title"], "text": text,
            "lawyer_reviewed": doc["lawyer_reviewed"], "review": risk.review(text)}


def _load(p: Principal, cid: str) -> dict:
    d = db.get(p.tenant_id, KIND, cid)
    if not d:
        raise HTTPException(404, "Contract not found")
    return d


@router.get("")
def list_contracts(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), p: Principal = Depends(require("viewer"))):
    return {"total": db.count(p.tenant_id, KIND), "items": [
        {"id": d["id"], "title": d["data"]["title"], "status": d["status"], "versions": len(d["data"]["versions"])}
        for d in db.list_(p.tenant_id, KIND, None, limit, offset)]}


@router.get("/{cid}")
def get_contract(cid: str, p: Principal = Depends(require("viewer"))):
    d = _load(p, cid)
    text = d["data"]["versions"][-1]["text"]
    return {"id": cid, "status": d["status"], "title": d["data"]["title"], "text": text,
            "version": len(d["data"]["versions"]), "lawyer_reviewed": d["data"]["lawyer_reviewed"],
            "review": risk.review(text), "audit": db.audit_log(p.tenant_id, cid)}


@router.put("/{cid}")
def edit(cid: str, body: EditIn, p: Principal = Depends(require("operator"))):
    d = _load(p, cid)
    if d["status"] != "draft":
        raise HTTPException(409, f"Contract is {d['status']}; only drafts can be edited")
    d["data"]["versions"].append({"text": body.text, "by": p.actor, "at": db.now_iso(), "note": body.note or "edited"})
    db.put(p.tenant_id, KIND, d["data"], "draft", cid)
    db.audit(p.tenant_id, p.actor, "contract.edited", KIND, cid, {"version": len(d["data"]["versions"])})
    return {"id": cid, "version": len(d["data"]["versions"]), "review": risk.review(body.text)}


@router.get("/{cid}/compare")
def compare_versions(cid: str, v1: int = 1, v2: int | None = None, p: Principal = Depends(require("viewer"))):
    vs = _load(p, cid)["data"]["versions"]
    v2 = v2 or len(vs)
    if not (1 <= v1 <= len(vs) and 1 <= v2 <= len(vs)):
        raise HTTPException(404, "Version out of range")
    return {"from": v1, "to": v2, "changes": compare.compare(vs[v1 - 1]["text"], vs[v2 - 1]["text"])}


@router.post("/{cid}/submit")
def submit(cid: str, p: Principal = Depends(require("operator"))):
    d = _load(p, cid)
    if d["status"] != "draft":
        raise HTTPException(409, f"Only drafts can be submitted (status: {d['status']})")
    db.put(p.tenant_id, KIND, d["data"], "in_review", cid)
    db.audit(p.tenant_id, p.actor, "contract.submitted", KIND, cid)
    return {"id": cid, "status": "in_review"}


@router.post("/{cid}/approve")
def approve(cid: str, body: ApproveIn, p: Principal = Depends(require("approver"))):
    d = _load(p, cid)
    if d["status"] != "in_review":
        raise HTTPException(409, "Only contracts in review can be approved")
    r = risk.review(d["data"]["versions"][-1]["text"])
    if r["high_risk_count"] and not body.acknowledge_risks:
        raise HTTPException(409, {"message": "High-risk findings present; set acknowledge_risks=true to approve", "review": r})
    db.put(p.tenant_id, KIND, d["data"], "approved", cid)
    db.audit(p.tenant_id, p.actor, "contract.approved", KIND, cid, {"acknowledged_high_risks": r["high_risk_count"]})
    return {"id": cid, "status": "approved"}


@router.post("/{cid}/reject")
def reject(cid: str, p: Principal = Depends(require("approver"))):
    d = _load(p, cid)
    if d["status"] != "in_review":
        raise HTTPException(409, "Only contracts in review can be sent back")
    db.put(p.tenant_id, KIND, d["data"], "draft", cid)
    db.audit(p.tenant_id, p.actor, "contract.returned_to_draft", KIND, cid)
    return {"id": cid, "status": "draft"}


@router.get("/{cid}/docx")
def docx(cid: str, p: Principal = Depends(require("viewer"))):
    d = _load(p, cid)
    blob = docx_export.to_docx(d["data"]["title"], d["data"]["versions"][-1]["text"])
    return Response(blob, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{cid}.docx"'})
