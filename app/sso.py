"""OpenID Connect single sign-on (authorization-code flow + PKCE) and invite-only user management.

Works with any standards-compliant IdP (Keycloak, Authentik, Azure AD, Okta, Google Workspace ...).
Authlib validates the id_token (signature via JWKS, issuer, audience, expiry, nonce). We additionally require
a *verified* email that matches an invited user; there is no auto-provisioning, so SSO can never create access
to a tenant by itself.
"""
import re

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import insert, select, update

from . import auth, db
from .config import settings

router = APIRouter(tags=["sso"])
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_oauth: OAuth | None = None
_oauth_key: tuple | None = None


def enabled() -> bool:
    return bool(settings.oidc_issuer and settings.oidc_client_id)


def client():
    global _oauth, _oauth_key
    key = (settings.oidc_issuer, settings.oidc_client_id, settings.oidc_client_secret)
    if _oauth is None or _oauth_key != key:
        _oauth = OAuth()
        _oauth.register(
            "oidc", client_id=settings.oidc_client_id, client_secret=settings.oidc_client_secret,
            server_metadata_url=settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
            client_kwargs={"scope": settings.oidc_scopes, "code_challenge_method": "S256"})
        _oauth_key = key
    return _oauth.oidc


@router.get("/auth/config")
def sso_config():
    return {"sso": enabled(), "provider": settings.oidc_provider_name if enabled() else None}


@router.get("/auth/login")
async def login(request: Request):
    if not enabled():
        raise HTTPException(404, "SSO is not configured")
    return await client().authorize_redirect(request, settings.public_base_url.rstrip("/") + "/auth/callback")


@router.get("/auth/callback")
async def callback(request: Request):
    if not enabled():
        raise HTTPException(404, "SSO is not configured")
    try:
        token = await client().authorize_access_token(request)
    except OAuthError:
        return RedirectResponse("/?sso_error=login_failed")
    claims = token.get("userinfo") or {}
    email = str(claims.get("email", "")).strip().lower()
    if not _EMAIL.match(email) or claims.get("email_verified") is not True:
        return RedirectResponse("/?sso_error=email_not_verified")
    with db.engine().connect() as c:
        user = c.execute(select(db.users).where(db.users.c.email == email)).first()
    if not user or not user.active:
        return RedirectResponse("/?sso_error=not_invited")
    with db.engine().begin() as c:
        c.execute(update(db.users).where(db.users.c.id == user.id).values(last_login=db.now()))
    db.audit(user.tenant_id, email, "auth.sso_login", "user", user.id)
    resp = RedirectResponse("/")
    resp.set_cookie(auth.SESSION_COOKIE, auth.create_session(user.id), httponly=True, samesite="lax",
                    secure=settings.secure_cookies, max_age=settings.session_ttl_hours * 3600, path="/")
    return resp


@router.post("/auth/logout")
def logout(request: Request):
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        auth.delete_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.SESSION_COOKIE, path="/")
    return resp


class UserIn(BaseModel):
    email: str
    role: str
    name: str | None = None


@router.post("/users", status_code=201)
def invite_user(body: UserIn, p: auth.Principal = Depends(auth.require("admin"))):
    email = body.email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(422, "Invalid email")
    if body.role not in auth.ROLES:
        raise HTTPException(422, f"role must be one of {auth.ROLES}")
    with db.engine().connect() as c:
        if c.execute(select(db.users.c.id).where(db.users.c.email == email)).first():
            raise HTTPException(409, "A user with this email already exists")
    uid = db.new_id()
    with db.engine().begin() as c:
        c.execute(insert(db.users).values(id=uid, tenant_id=p.tenant_id, email=email, name=body.name, role=body.role,
                                          active=1, created_at=db.now()))
    db.audit(p.tenant_id, p.actor, "user.invited", "user", uid, {"email": email, "role": body.role})
    return {"id": uid, "email": email, "role": body.role}


@router.get("/users")
def list_users(p: auth.Principal = Depends(auth.require("admin"))):
    with db.engine().connect() as c:
        rows = c.execute(select(db.users).where(db.users.c.tenant_id == p.tenant_id).order_by(db.users.c.created_at)).all()
    return [{"id": r.id, "email": r.email, "name": r.name, "role": r.role, "active": bool(r.active),
             "last_login": r.last_login.isoformat() if r.last_login else None} for r in rows]


@router.delete("/users/{user_id}")
def deactivate_user(user_id: str, p: auth.Principal = Depends(auth.require("admin"))):
    with db.engine().begin() as c:
        res = c.execute(update(db.users).where(db.users.c.id == user_id, db.users.c.tenant_id == p.tenant_id).values(active=0))
    if not res.rowcount:
        raise HTTPException(404, "No such user")
    db.audit(p.tenant_id, p.actor, "user.deactivated", "user", user_id)
    return {"deactivated": user_id}
