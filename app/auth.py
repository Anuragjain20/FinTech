"""API-key auth with per-tenant isolation and simple RBAC.

Roles: admin > approver > operator > viewer. Only a SHA-256 of each key is stored
(keys are 192-bit random, so a fast hash is appropriate). Keys can be revoked.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import insert, select, update

from . import db
from .config import settings

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


def principal(x_api_key: str = Header(default="")) -> Principal:
    row = None
    if x_api_key:
        with db.engine().connect() as c:
            row = c.execute(select(db.api_keys).where(db.api_keys.c.key_hash == _hash(x_api_key))).first()
    if not row or row.revoked:
        raise HTTPException(401, "Invalid or missing X-API-Key")
    return Principal(row.tenant_id, row.role, row.label or "key")


def require(min_role: str):
    def dep(p: Principal = Depends(principal)) -> Principal:
        if ROLES.index(p.role) < ROLES.index(min_role):
            raise HTTPException(403, f"Requires role '{min_role}' or higher")
        return p
    return dep


def admin_token(x_admin_token: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(401, "Invalid admin token")
