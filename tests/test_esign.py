import hashlib
import io
import re
from datetime import datetime, timedelta, timezone

import pytest
from pyhanko.pdf_utils.reader import PdfFileReader

from app.core import billing, db, storage
from app.modules.esign import mailer, seal
from tests.test_contracts import NDA


@pytest.fixture(autouse=True)
def _outbox():
    mailer.outbox.clear()


def approved_contract(client, headers):
    cid = client.post("/contracts", json={"template_id": "nda", "answers": NDA}, headers=headers).json()["id"]
    client.post(f"/contracts/{cid}/submit", headers=headers)
    assert client.post(f"/contracts/{cid}/approve", json={}, headers=headers).status_code == 200
    return cid


def links():
    return {m["to"]: re.search(r"/s/(\S+)", m["body"]).group(1) for m in mailer.outbox if "Please sign" in m["subject"]}


def otp_for(email):
    return re.search(r"code .*? is (\d{6})", [m for m in mailer.outbox if m["to"] == email and "code" in m["subject"]][-1]["body"]).group(1)


def sign(client, token, email, name):
    assert client.post(f"/public/sign/{token}/otp").status_code == 200
    return client.post(f"/public/sign/{token}/sign", json={"otp": otp_for(email), "typed_name": name, "consent": True})


SIGNERS = {"signers": [{"name": "Asha Rao", "email": "asha@acme-corp.com"}, {"name": "Bala K", "email": "bala@beta-corp.com"}]}


def test_full_signing_flow_and_seal(client, admin):
    cid = approved_contract(client, admin)
    r = client.post(f"/contracts/{cid}/signing", json=SIGNERS, headers=admin)
    assert r.status_code == 201, r.text
    sid, doc_hash = r.json()["id"], r.json()["sha256"]
    assert client.get(f"/contracts/{cid}", headers=admin).json()["status"] == "out_for_signature"
    assert client.put(f"/contracts/{cid}", json={"text": "tampered"}, headers=admin).status_code == 409
    tok = links()
    assert set(tok) == {"asha@acme-corp.com", "bala@beta-corp.com"}
    # the link email must not contain an OTP, and the stored PDF hash matches what was recorded
    assert not any(re.search(r"\b\d{6}\b", m["body"]) for m in mailer.outbox)
    assert hashlib.sha256(storage.get(db.get_any("signing", sid)["data"]["pdf_key"])).hexdigest() == doc_hash

    page = client.get(f"/public/sign/{tok['asha@acme-corp.com']}").json()
    assert page["signer_name"] == "Asha Rao" and page["sha256"] == doc_hash and "Acme Pvt Ltd" in page["text"]
    assert client.post(f"/public/sign/{tok['asha@acme-corp.com']}/sign", json={"otp": "123456", "typed_name": "Asha Rao", "consent": True}).status_code == 400

    assert sign(client, tok["asha@acme-corp.com"], "asha@acme-corp.com", "Asha Rao").json() == {"signed": True, "all_signed": False}
    assert client.get(f"/contracts/{cid}/signed.pdf", headers=admin).status_code == 409
    assert client.post(f"/public/sign/{tok['asha@acme-corp.com']}/otp").status_code == 409  # already signed
    assert sign(client, tok["bala@beta-corp.com"], "bala@beta-corp.com", "Bala K").json()["all_signed"] is True

    st = client.get(f"/contracts/{cid}/signing", headers=admin).json()
    assert st["status"] == "completed" and [s["status"] for s in st["signers"]] == ["signed", "signed"]
    assert "token_hash" not in str(st) and "otp_hash" not in str(st)
    assert client.get(f"/contracts/{cid}", headers=admin).json()["status"] == "signed"

    pdf = client.get(f"/contracts/{cid}/signed.pdf", headers=admin).content
    assert pdf.startswith(b"%PDF") and client.get(f"/contracts/{cid}/signed.pdf/verify", headers=admin).json()["intact"] is True
    assert len(PdfFileReader(io.BytesIO(pdf)).embedded_signatures) == 1
    tampered = bytearray(pdf); tampered[2000] ^= 0xFF
    assert seal.verify(bytes(tampered))["intact"] is False
    actions = [a["action"] for a in st["audit"]]
    assert actions[0] == "signing.requested" and actions.count("signing.signed") == 2 and actions[-1] == "signing.completed"
    # evidence recorded per signer
    data = db.get_any("signing", sid)["data"]
    assert all(s["ip"] and s["doc_sha256"] == doc_hash and s["typed_name"] for s in data["signers"])


def test_requires_approved_contract_and_unique_signers(client, admin, role_headers):
    cid = client.post("/contracts", json={"template_id": "nda", "answers": NDA}, headers=admin).json()["id"]
    assert client.post(f"/contracts/{cid}/signing", json=SIGNERS, headers=admin).status_code == 409
    cid = approved_contract(client, admin)
    dup = {"signers": [{"name": "A", "email": "x@y-corp.com"}, {"name": "B", "email": "X@y-corp.com"}]}
    assert client.post(f"/contracts/{cid}/signing", json=dup, headers=admin).status_code == 422
    assert client.post(f"/contracts/{cid}/signing", json={"signers": []}, headers=admin).status_code == 422
    assert client.post(f"/contracts/{cid}/signing", json=SIGNERS, headers=role_headers("operator")).status_code == 403


def test_otp_rules(client, admin):
    cid = approved_contract(client, admin)
    client.post(f"/contracts/{cid}/signing", json=SIGNERS, headers=admin)
    t = links()["asha@acme-corp.com"]
    assert client.post(f"/public/sign/{t}/sign", json={"otp": "000000", "typed_name": "Asha", "consent": True}).status_code == 400  # no code yet
    client.post(f"/public/sign/{t}/otp")
    assert client.post(f"/public/sign/{t}/otp").status_code == 429  # resend throttle
    good = otp_for("asha@acme-corp.com")
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(5):
        assert client.post(f"/public/sign/{t}/sign", json={"otp": wrong, "typed_name": "Asha", "consent": True}).status_code == 400
    # attempts exhausted: even the right code is refused until a new one is requested
    assert client.post(f"/public/sign/{t}/sign", json={"otp": good, "typed_name": "Asha", "consent": True}).status_code == 429
    assert client.post(f"/public/sign/{t}/sign", json={"otp": good, "typed_name": "Asha", "consent": False}).status_code == 422


def test_expired_otp_and_expired_link(client, admin):
    cid = approved_contract(client, admin)
    sid = client.post(f"/contracts/{cid}/signing", json=SIGNERS, headers=admin).json()["id"]
    t = links()["asha@acme-corp.com"]
    client.post(f"/public/sign/{t}/otp")
    code = otp_for("asha@acme-corp.com")
    d = db.get_any("signing", sid)

    def age_otp(data):
        data["signers"][0]["otp_expires"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    db.update_locked(d["tenant_id"], "signing", sid, age_otp)
    assert client.post(f"/public/sign/{t}/sign", json={"otp": code, "typed_name": "Asha", "consent": True}).status_code == 400

    def expire_link(data):
        data["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    db.update_locked(d["tenant_id"], "signing", sid, expire_link)
    assert client.get(f"/public/sign/{t}").status_code == 410


def test_forged_tokens(client, admin):
    cid = approved_contract(client, admin)
    sid = client.post(f"/contracts/{cid}/signing", json=SIGNERS, headers=admin).json()["id"]
    t = links()["asha@acme-corp.com"]
    s_id, sg, _ = t.split(".")
    for bad in (f"{s_id}.{sg}.wrongsecret", f"{s_id}.nosigner.x", "nodot", "a.b.c", f"{sid}.{sg}"):
        assert client.get(f"/public/sign/{bad}").status_code == 404
    # asha's secret cannot be used against bala's signer slot
    other = [x for x in db.get_any("signing", sid)["data"]["signers"] if x["email"] == "bala@beta-corp.com"][0]["id"]
    assert client.get(f"/public/sign/{s_id}.{other}.{t.split('.')[2]}").status_code == 404


def test_cancel_and_decline_reopen_contract(client, admin):
    cid = approved_contract(client, admin)
    sid = client.post(f"/contracts/{cid}/signing", json=SIGNERS, headers=admin).json()["id"]
    assert client.post(f"/signing/{sid}/cancel", headers=admin).json()["status"] == "cancelled"
    assert client.get(f"/contracts/{cid}", headers=admin).json()["status"] == "approved"
    assert client.get(f"/public/sign/{links()['asha@acme-corp.com']}").status_code == 410
    mailer.outbox.clear()
    client.post(f"/contracts/{cid}/signing", json=SIGNERS, headers=admin)
    t = links()["bala@beta-corp.com"]
    assert client.post(f"/public/sign/{t}/decline").json() == {"declined": True}
    assert client.get(f"/contracts/{cid}/signing", headers=admin).json()["status"] == "declined"
    assert client.get(f"/contracts/{cid}", headers=admin).json()["status"] == "approved"


def test_isolation_and_quota(client, admin, other_admin, monkeypatch):
    cid = approved_contract(client, admin)
    client.post(f"/contracts/{cid}/signing", json=SIGNERS, headers=admin)
    assert client.get(f"/contracts/{cid}/signing", headers=other_admin).status_code == 404
    monkeypatch.setitem(billing.PLANS, "free", {**billing.PLANS["free"], "signatures": 1})
    cid2 = approved_contract(client, admin)
    assert client.post(f"/contracts/{cid2}/signing", json=SIGNERS, headers=admin).status_code == 402
