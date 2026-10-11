import os

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.core.config import settings
from app.modules.invoices.gst import checksum_char


def make_gstin(state: str, pan: str, entity: str = "1") -> str:
    base = f"{state}{pan}{entity}Z"
    return base + checksum_char(base)


SUPPLIER = make_gstin("27", "AAPFU0939F")
BUYER_SAME = make_gstin("27", "AABCT1332L")
BUYER_OTHER = make_gstin("29", "AABCT1332L")


@pytest.fixture
def client(tmp_path, monkeypatch):
    # FINTECH_TEST_DATABASE_URL runs the whole suite against PostgreSQL (CI does this).
    monkeypatch.setattr(settings, "database_url", os.environ.get("FINTECH_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_local_dir", str(tmp_path / "up"))
    monkeypatch.setattr(settings, "celery_eager", True)
    db.reset()
    if os.environ.get("FINTECH_TEST_DATABASE_URL"):
        with db.engine().begin() as conn:
            for t in reversed(db.metadata.sorted_tables):
                conn.execute(t.delete())
    from app.main import app
    with TestClient(app) as c:
        yield c
    db.reset()


def _tenant(client, name):
    r = client.post("/tenants", json={"name": name}, headers={"X-Admin-Token": settings.admin_token})
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
