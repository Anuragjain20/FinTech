import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.invoice.gst import checksum_char


def make_gstin(state: str, pan: str, entity: str = "1") -> str:
    base = f"{state}{pan}{entity}Z"
    return base + checksum_char(base)


SUPPLIER = make_gstin("27", "AAPFU0939F")
BUYER_SAME = make_gstin("27", "AABCT1332L")
BUYER_OTHER = make_gstin("29", "AABCT1332L")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    db.reset()
    from app.main import app
    with TestClient(app) as c:
        yield c
    db.reset()


def _tenant(client, name):
    r = client.post("/tenants", json={"name": name}, headers={"X-Admin-Token": config.ADMIN_TOKEN})
    assert r.status_code == 201
    return r.json()["api_key"]


@pytest.fixture
def admin(client):
    return {"X-API-Key": _tenant(client, "acme")}


@pytest.fixture
def other_admin(client):
    return {"X-API-Key": _tenant(client, "globex")}


@pytest.fixture
def role_headers(client, admin):
    def make(role):
        r = client.post("/keys", json={"role": role, "label": role}, headers=admin)
        return {"X-API-Key": r.json()["api_key"]}
    return make
