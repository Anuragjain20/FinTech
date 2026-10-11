"""API-key auth with per-tenant isolation and simple RBAC.

Roles: admin > approver > operator > viewer. Only a SHA-256 of each key is stored
(keys are 192-bit random, so a fast hash is appropriate). Keys can be revoked.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import delete, insert, select, update

from app.core import db
from app.core.config import settings

ROLES = ["viewer", "operator", "approver", "admin"]


@dataclass
class Principal:
    tenant_id: str
    role: str
    label: str

    @property
    def actor(self) -> str:
        return f"{self.label}({self.role})"


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(tenant_id: str, role: str, label: str) -> str:
    key = "fk_" + secrets.token_urlsafe(24)
    with db.engine().begin() as c:
        c.execute(insert(db.api_keys).values(key_hash=_hash(key), tenant_id=tenant_id, role=role, label=label, revoked=0))
    return key


def revoke_key(tenant_id: str, label: str) -> int:
    with db.engine().begin() as c:
        return c.execute(update(db.api_keys).where(db.api_keys.c.tenant_id == tenant_id, db.api_keys.c.label == label)
                         .values(revoked=1)).rowcount


def list_keys(tenant_id: str) -> list[dict]:
    with db.engine().connect() as c:
        rows = c.execute(select(db.api_keys).where(db.api_keys.c.tenant_id == tenant_id)).all()
    return [{"label": r.label, "role": r.role, "revoked": bool(r.revoked)} for r in rows]


SESSION_COOKIE = "fk_session"


def _session_principal(token: str) -> Principal | None:
    with db.engine().connect() as c:
        row = c.execute(
            select(db.users.c.tenant_id, db.users.c.role, db.users.c.email)
            .join(db.sessions, db.sessions.c.user_id == db.users.c.id)
            .where(db.sessions.c.token_hash == _hash(token), db.sessions.c.expires_at > db.now(), db.users.c.active == 1)
        ).first()
    return Principal(row.tenant_id, row.role, row.email) if row else None


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    with db.engine().begin() as c:
        c.execute(insert(db.sessions).values(token_hash=_hash(token), user_id=user_id, created_at=db.now(),
                                             expires_at=db.now() + timedelta(hours=settings.session_ttl_hours)))
    return token


def delete_session(token: str) -> None:
    with db.engine().begin() as c:
        c.execute(delete(db.sessions).where(db.sessions.c.token_hash == _hash(token)))


def principal(request: Request, x_api_key: str = Header(default="")) -> Principal:
    """API key (machine clients) or session cookie (browser SSO). Cookie-authenticated writes must carry
    an X-Requested-With header, which a cross-site form post cannot set (CSRF defence)."""
    if x_api_key:
        with db.engine().connect() as c:
            row = c.execute(select(db.api_keys).where(db.api_keys.c.key_hash == _hash(x_api_key))).first()
        if row and not row.revoked:
            return Principal(row.tenant_id, row.role, row.label or "key")
        raise HTTPException(401, "Invalid or missing X-API-Key")
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        if request.method not in ("GET", "HEAD", "OPTIONS") and not request.headers.get("x-requested-with"):
            raise HTTPException(403, "Missing X-Requested-With header")
        p = _session_principal(token)
        if p:
            return p
    raise HTTPException(401, "Invalid or missing credentials")


def require(min_role: str):
    def dep(p: Principal = Depends(principal)) -> Principal:
        if ROLES.index(p.role) < ROLES.index(min_role):
            raise HTTPException(403, f"Requires role '{min_role}' or higher")
        return p
    return dep


def admin_token(x_admin_token: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(401, "Invalid admin token")
