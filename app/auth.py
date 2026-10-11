"""API-key auth with per-tenant isolation and simple RBAC.

Roles: admin > approver > operator > viewer. Keys are stored hashed.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from . import config, db

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
    c = db.conn()
    c.execute("INSERT INTO api_keys VALUES(?,?,?,?)", (_hash(key), tenant_id, role, label))
    c.commit()
    return key


def principal(x_api_key: str = Header(default="")) -> Principal:
    row = db.conn().execute("SELECT * FROM api_keys WHERE key_hash=?", (_hash(x_api_key),)).fetchone()
    if not x_api_key or not row:
        raise HTTPException(401, "Invalid or missing X-API-Key")
    return Principal(row["tenant_id"], row["role"], row["label"] or "key")


def require(min_role: str):
    def dep(p: Principal = Depends(principal)) -> Principal:
        if ROLES.index(p.role) < ROLES.index(min_role):
            raise HTTPException(403, f"Requires role '{min_role}' or higher")
        return p
    return dep


def admin_token(x_admin_token: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(401, "Invalid admin token")
