from tests.conftest import SUPPLIER


def test_requires_api_key(client):
    assert client.get("/invoices").status_code == 401
    assert client.get("/invoices", headers={"X-API-Key": "nope"}).status_code == 401


def test_tenant_creation_needs_admin_token(client):
    assert client.post("/tenants", json={"name": "x"}, headers={"X-Admin-Token": "bad"}).status_code == 401


def test_rbac_viewer_cannot_write(client, role_headers):
    viewer = role_headers("viewer")
    assert client.post("/invoices", json={"supplier_gstin": SUPPLIER}, headers=viewer).status_code == 403
    assert client.get("/invoices", headers=viewer).status_code == 200


def test_tenant_isolation(client, admin, other_admin):
    inv = client.post("/invoices", json={"invoice_number": "A1", "supplier_gstin": SUPPLIER}, headers=admin).json()
    assert client.get(f"/invoices/{inv['id']}", headers=other_admin).status_code == 404
    assert client.get("/invoices", headers=other_admin).json() == {"total": 0, "items": []}
    assert client.post(f"/invoices/{inv['id']}/approve", json={"override_reason": "x"}, headers=other_admin).status_code == 404


def test_audit_requires_admin(client, role_headers, admin):
    assert client.get("/audit", headers=role_headers("operator")).status_code == 403
    assert client.get("/audit", headers=admin).status_code == 200
