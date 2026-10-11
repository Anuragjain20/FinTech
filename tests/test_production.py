import hashlib
import hmac
import io
import json
from email.message import EmailMessage

import pytest
from moto import mock_aws

from app import billing, storage
from app.config import Settings, settings
from app.invoice import mailbox
from tests.conftest import BUYER_SAME, SUPPLIER
from tests.test_invoice import INVOICE_TEXT


def test_production_settings_guard():
    with pytest.raises(ValueError, match="ADMIN_TOKEN"):
        Settings(env="production", database_url="postgresql+psycopg://x", celery_eager=False)
    with pytest.raises(ValueError, match="SQLite"):
        Settings(env="production", admin_token="x" * 32, celery_eager=False)
    with pytest.raises(ValueError, match="CELERY_EAGER"):
        Settings(env="production", admin_token="x" * 32, database_url="postgresql+psycopg://x")
    Settings(env="production", admin_token="x" * 32, database_url="postgresql+psycopg://x", celery_eager=False)


def test_health_ready_metrics_headers(client):
    assert client.get("/health").json() == {"ok": True}
    r = client.get("/ready")
    assert r.status_code == 200 and r.headers["x-content-type-options"] == "nosniff" and r.headers["x-request-id"]
    assert "http_requests_total" in client.get("/metrics").text


def test_key_revocation(client, admin, role_headers):
    op = role_headers("operator")
    assert client.get("/me", headers=op).json()["role"] == "operator"
    assert client.delete("/keys/operator", headers=admin).status_code == 200
    assert client.get("/me", headers=op).status_code == 401
    assert client.delete("/keys/owner", headers=admin).status_code == 409  # cannot revoke own key
    assert {k["label"] for k in client.get("/keys", headers=admin).json()} == {"owner", "operator"}


def test_quota_enforced_and_plan_upgrade_via_signed_webhook(client, admin, monkeypatch):
    monkeypatch.setitem(billing.PLANS, "free", {**billing.PLANS["free"], "invoices": 2})
    for i in range(2):
        assert client.post("/invoices", json={"invoice_number": f"Q{i}"}, headers=admin).status_code == 201
    assert client.post("/invoices", json={"invoice_number": "Q3"}, headers=admin).status_code == 402
    info = client.get("/billing", headers=admin).json()
    assert info["usage"]["invoices"] == 2 and info["plan"] == "free"

    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec")
    tenant = client.get("/me", headers=admin).json()["tenant_id"]
    body = json.dumps({"event": "subscription.activated", "payload": {"subscription": {"entity": {
        "id": "sub_1", "notes": {"tenant_id": tenant, "plan": "starter"}}}}}).encode()
    assert client.post("/webhooks/razorpay", content=body, headers={"x-razorpay-signature": "bad"}).status_code == 400
    sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    assert client.post("/webhooks/razorpay", content=body, headers={"x-razorpay-signature": sig}).status_code == 200
    assert client.get("/me", headers=admin).json()["plan"] == "starter"
    assert client.post("/invoices", json={"invoice_number": "Q3"}, headers=admin).status_code == 201
    cancel = json.dumps({"event": "subscription.cancelled", "payload": {"subscription": {"entity": {
        "id": "sub_1", "notes": {"tenant_id": tenant}}}}}).encode()
    sig = hmac.new(b"whsec", cancel, hashlib.sha256).hexdigest()
    client.post("/webhooks/razorpay", content=cancel, headers={"x-razorpay-signature": sig})
    assert client.get("/me", headers=admin).json()["plan"] == "free"


def test_webhook_disabled_without_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "")
    assert client.post("/webhooks/razorpay", content=b"{}", headers={"x-razorpay-signature": ""}).status_code == 400


def test_mailbox_ingests_attachments(client, admin):
    tenant = client.get("/me", headers=admin).json()["tenant_id"]
    m = EmailMessage()
    m["From"], m["Subject"] = "Vendor <ap@vendor.in>", "Invoice"
    m.set_content("see attached")
    m.add_attachment(INVOICE_TEXT.encode(), maintype="text", subtype="plain", filename="inv.txt")
    m.add_attachment(b"x", maintype="application", subtype="octet-stream", filename="evil.exe")
    ids = mailbox.ingest_message(m.as_bytes(), tenant)
    assert len(ids) == 1
    inv = client.get(f"/invoices/{ids[0]}", headers=admin).json()
    assert inv["source"] == "email:ap@vendor.in" and inv["invoice"]["invoice_number"] == "INV/2024/0042"


@mock_aws
def test_s3_storage_backend(monkeypatch):
    import boto3
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x"); monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "test-bucket")
    monkeypatch.setattr(settings, "s3_region", "us-east-1")
    storage.clear_cache()
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket")
    key = storage.key_for("t1", "d1", "../../etc/passwd")
    assert key == "t1/d1/passwd"
    storage.put(key, b"hello")
    assert storage.get(key) == b"hello"
    storage.clear_cache()


def test_csv_formula_injection_neutralised(client, admin):
    r = client.post("/invoices", json={"supplier_name": "=HYPERLINK(\"http://evil\")", "supplier_gstin": SUPPLIER, "buyer_gstin": BUYER_SAME,
                                      "invoice_number": "E1", "invoice_date": "2024-01-01", "taxable_value": 100, "cgst": 9, "sgst": 9,
                                      "total": 118}, headers=admin).json()
    assert client.post(f"/invoices/{r['id']}/approve", json={}, headers=admin).status_code == 200
    out = client.get("/invoices/export/csv", headers=admin).text
    assert "'=HYPERLINK" in out and ",=HYPERLINK" not in out


def test_upload_size_limit(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    r = client.post("/invoices/upload", files={"file": ("a.txt", b"x")}, headers=admin)
    assert r.status_code == 413


def test_pdf_bank_statement(client, admin):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
    buf = io.BytesIO()
    rows = [["Date", "Narration", "Chq/Ref No", "Withdrawal Amt", "Deposit Amt"],
            ["01/04/2024", "NEFT ACME", "UTR2002", "", "5000.00"],
            ["02/04/2024", "CHQ PAID", "000456", "1200.00", ""]]
    t = Table(rows); t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(buf, pagesize=A4).build([t])
    book = "Date,Particulars,Voucher No,Debit,Credit\n01/04/2024,Acme receipt,UTR2002,5000,\n02/04/2024,Cheque,456,,1200\n"
    r = client.post("/reconciliations", headers=admin,
                    files={"bank_file": ("stmt.pdf", buf.getvalue()), "book_file": ("book.csv", book.encode())})
    assert r.status_code == 201, r.text
    assert [m["rule"] for m in r.json()["matches"]] == ["reference", "reference"]


def test_recon_quota(client, admin, monkeypatch):
    monkeypatch.setitem(billing.PLANS, "free", {**billing.PLANS["free"], "reconciliations": 0})
    f = {"bank_file": ("b.csv", b"Date,Debit,Credit\n01/01/2024,,5\n"), "book_file": ("l.csv", b"Date,Debit,Credit\n01/01/2024,5,\n")}
    assert client.post("/reconciliations", headers=admin, files=f).status_code == 402


def test_rate_limit_returns_429():
    import os
    import subprocess
    import sys
    import textwrap
    code = textwrap.dedent("""
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        codes = [c.get("/me", headers={"X-API-Key": "nope"}).status_code for _ in range(5)]
        print(codes)
    """)
    env = {**os.environ, "FINTECH_RATE_LIMIT": "3/minute", "FINTECH_DATABASE_URL": "sqlite://"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=os.getcwd()).stdout
    assert "[401, 401, 401, 429, 429]" in out, out
