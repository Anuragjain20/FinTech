import httpx
import pytest

from app import sso
from app.config import settings
from tests.fake_idp import CLIENT_ID, CLIENT_SECRET, Idp


@pytest.fixture
def idp(monkeypatch):
    i = Idp().start()
    monkeypatch.setattr(settings, "oidc_issuer", i.issuer)
    monkeypatch.setattr(settings, "oidc_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "oidc_client_secret", CLIENT_SECRET)
    monkeypatch.setattr(settings, "public_base_url", "http://testserver")
    sso._oauth = None
    yield i
    i.stop()
    sso._oauth = None


def sso_login(client, idp):
    """Drive the full browser flow: app -> IdP -> app callback. Returns the final callback response."""
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith(idp.issuer + "/authorize")
    assert "code_challenge_method=S256" in r.headers["location"]
    back = httpx.get(r.headers["location"], follow_redirects=False)
    assert back.status_code in (302, 307)
    return client.get(back.headers["location"].replace("http://testserver", ""), follow_redirects=False)


def test_sso_disabled_by_default(client):
    assert client.get("/auth/config").json() == {"sso": False, "provider": None}
    assert client.get("/auth/login").status_code == 404


def test_invited_user_logs_in_and_uses_session(client, admin, idp):
    assert client.get("/auth/config").json()["sso"] is True
    assert client.post("/users", json={"email": "Alice@Acme.test", "role": "approver"}, headers=admin).status_code == 201
    assert client.post("/users", json={"email": "alice@acme.test", "role": "viewer"}, headers=admin).status_code == 409
    r = sso_login(client, idp)
    assert r.status_code in (302, 307) and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    me = client.get("/me").json()  # session cookie only, no API key
    assert me["role"] == "approver" and me["label"] == "alice@acme.test"
    # sees the same tenant data as the API-key client
    client.post("/invoices", json={"invoice_number": "S1"}, headers=admin)
    assert client.get("/invoices").json()["total"] == 1
    # CSRF defence: cookie-authenticated writes need X-Requested-With
    assert client.post("/invoices", json={"invoice_number": "S2"}).status_code == 403
    assert client.post("/invoices", json={"invoice_number": "S2"}, headers={"X-Requested-With": "fetch"}).status_code == 201
    # role enforcement still applies to SSO users (approver is not admin)
    assert client.get("/users").status_code == 403
    assert client.post("/auth/logout", headers={"X-Requested-With": "fetch"}).status_code == 200
    assert client.get("/me").status_code == 401


def test_uninvited_unverified_and_deactivated_are_rejected(client, admin, idp):
    r = sso_login(client, idp)
    assert r.headers["location"] == "/?sso_error=not_invited" and client.get("/me").status_code == 401

    uid = client.post("/users", json={"email": "alice@acme.test", "role": "viewer"}, headers=admin).json()["id"]
    idp.user = {"email": "alice@acme.test", "email_verified": False}
    assert sso_login(client, idp).headers["location"] == "/?sso_error=email_not_verified"

    idp.user = {"email": "alice@acme.test", "email_verified": True}
    assert sso_login(client, idp).headers["location"] == "/"
    assert client.get("/me").status_code == 200
    client.delete(f"/users/{uid}", headers=admin)
    assert client.get("/me").status_code == 401  # existing session dies with deactivation
    assert sso_login(client, idp).headers["location"] == "/?sso_error=not_invited"


def test_tampered_state_rejected(client, admin, idp):
    client.post("/users", json={"email": "alice@acme.test", "role": "viewer"}, headers=admin)
    client.get("/auth/login", follow_redirects=False)
    r = client.get("/auth/callback?code=code0&state=forged", follow_redirects=False)
    assert r.headers["location"] == "/?sso_error=login_failed" and client.get("/me").status_code == 401


def test_user_admin_scoped_to_tenant(client, admin, other_admin):
    uid = client.post("/users", json={"email": "bob@a.test", "role": "viewer"}, headers=admin).json()["id"]
    assert client.delete(f"/users/{uid}", headers=other_admin).status_code == 404
    assert [u["email"] for u in client.get("/users", headers=admin).json()] == ["bob@a.test"]
    assert client.get("/users", headers=other_admin).json() == []
    assert client.post("/users", json={"email": "not-an-email", "role": "viewer"}, headers=admin).status_code == 422
