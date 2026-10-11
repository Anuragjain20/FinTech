from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import insert, text
from starlette.middleware.sessions import SessionMiddleware

from app.core import auth, billing, db, observability
from app.core.config import settings
from app.modules.contracts.api import router as contracts_router
from app.modules.esign.api import router as esign_router
from app.modules.identity import api as identity_api
from app.modules.invoices.api import router as invoice_router
from app.modules.legal.api import router as rag_router
from app.modules.reconciliation.api import router as brs_router

app = FastAPI(title="FinTech Suite", version="0.2.0",
              description="Invoice automation, bank reconciliation and contract drafting for Indian SMBs")


def _rate_key(request: Request) -> str:
    return request.headers.get("x-api-key") or (request.client.host if request.client else "anon")


limiter = Limiter(key_func=_rate_key, default_limits=[settings.rate_limit],
                  storage_uri=None if settings.celery_eager else settings.redis_url)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax", https_only=settings.secure_cookies,
                   max_age=600, session_cookie="fk_login")  # only holds the OIDC state/nonce during login
observability.setup(app)


@app.exception_handler(RateLimitExceeded)
def _rate_limited(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)


class TenantIn(BaseModel):
    name: str


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}


@app.get("/ready", include_in_schema=False)
def ready():
    try:
        with db.engine().connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "database unavailable") from None
    return {"ok": True}


@app.post("/tenants", status_code=201, dependencies=[Depends(auth.admin_token)])
def create_tenant(body: TenantIn):
    """Provision a tenant and its first admin key (shown once). Requires X-Admin-Token."""
    tid = db.new_id()
    with db.engine().begin() as c:
        c.execute(insert(db.tenants).values(id=tid, name=body.name, plan="free", created_at=db.now()))
    return {"tenant_id": tid, "api_key": auth.create_key(tid, "admin", "owner")}


class KeyIn(BaseModel):
    role: str
    label: str


@app.post("/keys", status_code=201)
def create_key(body: KeyIn, p: auth.Principal = Depends(auth.require("admin"))):
    if body.role not in auth.ROLES:
        raise HTTPException(422, f"role must be one of {auth.ROLES}")
    db.audit(p.tenant_id, p.actor, "key.created", "api_key", "", {"role": body.role, "label": body.label})
    return {"api_key": auth.create_key(p.tenant_id, body.role, body.label)}


@app.get("/keys")
def list_keys(p: auth.Principal = Depends(auth.require("admin"))):
    return auth.list_keys(p.tenant_id)


@app.delete("/keys/{label}")
def revoke_key(label: str, p: auth.Principal = Depends(auth.require("admin"))):
    if label == p.label:
        raise HTTPException(409, "Cannot revoke the key you are using")
    if not auth.revoke_key(p.tenant_id, label):
        raise HTTPException(404, "No such key")
    db.audit(p.tenant_id, p.actor, "key.revoked", "api_key", "", {"label": label})
    return {"revoked": label}


@app.get("/me")
def me(p: auth.Principal = Depends(auth.principal)):
    return {"tenant_id": p.tenant_id, "role": p.role, "label": p.label, "plan": billing.tenant_plan(p.tenant_id)}


@app.get("/audit")
def audit(entity_id: str | None = None, p: auth.Principal = Depends(auth.require("admin"))):
    return db.audit_log(p.tenant_id, entity_id)


app.include_router(invoice_router)
app.include_router(brs_router)
app.include_router(contracts_router)
app.include_router(esign_router)
app.include_router(rag_router)
app.include_router(billing.router)
app.include_router(identity_api.router)

_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    @app.get("/s/{token}", include_in_schema=False)
    def signing_page(token: str):  # SPA entry for the public signing page
        return FileResponse(_dist / "index.html")
  # serve the built SPA from the same origin (no CORS needed)
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
