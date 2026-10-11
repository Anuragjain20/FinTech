from fastapi import Depends, FastAPI
from pydantic import BaseModel

from . import auth, db
from .brs.router import router as brs_router
from .contracts.router import router as contracts_router
from .invoice.router import router as invoice_router

app = FastAPI(title="FinTech Suite", version="0.1.0",
              description="Invoice automation, bank reconciliation and contract drafting for Indian SMBs")


class TenantIn(BaseModel):
    name: str


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/tenants", status_code=201, dependencies=[Depends(auth.admin_token)])
def create_tenant(body: TenantIn):
    """Provision a tenant and its first admin key (shown once). Requires X-Admin-Token."""
    tid = db.new_id()
    c = db.conn()
    c.execute("INSERT INTO tenants VALUES(?,?,?)", (tid, body.name, db.now()))
    c.commit()
    return {"tenant_id": tid, "api_key": auth.create_key(tid, "admin", "owner")}


class KeyIn(BaseModel):
    role: str
    label: str


@app.post("/keys", status_code=201)
def create_key(body: KeyIn, p: auth.Principal = Depends(auth.require("admin"))):
    from fastapi import HTTPException
    if body.role not in auth.ROLES:
        raise HTTPException(422, f"role must be one of {auth.ROLES}")
    db.audit(p.tenant_id, p.actor, "key.created", "api_key", "", {"role": body.role, "label": body.label})
    return {"api_key": auth.create_key(p.tenant_id, body.role, body.label)}


@app.get("/audit")
def audit(entity_id: str | None = None, p: auth.Principal = Depends(auth.require("admin"))):
    return db.audit_log(p.tenant_id, entity_id)


app.include_router(invoice_router)
app.include_router(brs_router)
app.include_router(contracts_router)
