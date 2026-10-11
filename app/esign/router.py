"""E-signature workflow for approved contracts.

Lifecycle: approved contract -> signing request (PDF rendered, SHA-256 recorded, links emailed) -> each signer
opens their private link, requests a one-time code (emailed separately), then signs with code + typed name +
explicit consent -> when everyone has signed, a certificate page is appended and the PDF is sealed.

Evidence kept per signer: email-link possession, OTP, typed name, UTC time, IP, user agent, document hash.
This is a *simple* electronic signature with an audit trail; it is not Aadhaar eSign or a DSC signature.
Check with counsel which documents need those (and stamping) - the IT Act's First Schedule excludes some
document classes entirely.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from .. import billing, db, storage
from ..auth import Principal, require
from ..config import settings
from . import mailer, pdfgen, seal

router = APIRouter(tags=["e-signature"])
SIGNING, CONTRACT = "signing", "contract"
CONSENT_VERSION = "v1"
CONSENT_TEXT = ("I have read this document. I agree to sign it electronically, and I intend my electronic signature "
                "to have the same effect as a handwritten signature.")
MAX_OTP_ATTEMPTS, MAX_OTP_SENDS, OTP_RESEND_SECONDS = 5, 5, 30


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class SignerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr


class RequestIn(BaseModel):
    signers: list[SignerIn] = Field(min_length=1, max_length=10)


def _public_view(data: dict) -> dict:
    """Signer list without secrets (token/OTP hashes)."""
    return [{"name": s["name"], "email": s["email"], "status": s["status"], "signed_at": s.get("signed_at")} for s in data["signers"]]


# ---------------- authenticated side ----------------

@router.post("/contracts/{cid}/signing", status_code=201)
def request_signatures(cid: str, body: RequestIn, p: Principal = Depends(require("approver"))):
    c = db.get(p.tenant_id, CONTRACT, cid)
    if not c:
        raise HTTPException(404, "Contract not found")
    if c["status"] != "approved":
        raise HTTPException(409, f"Only approved contracts can be sent for signature (status: {c['status']})")
    emails = [s.email.lower() for s in body.signers]
    if len(set(emails)) != len(emails):
        raise HTTPException(422, "Signer emails must be unique")
    billing.consume(p.tenant_id, "signatures")
    versions = c["data"]["versions"]
    text = versions[-1]["text"]
    pdf = pdfgen.contract_pdf(c["data"]["title"], text)
    sid = db.new_id()
    key = storage.key_for(p.tenant_id, sid, "contract.pdf")
    storage.put(key, pdf)
    tokens, signers = {}, []
    for s in body.signers:
        sg_id, secret = db.new_id()[:12], secrets.token_urlsafe(24)
        tokens[s.email.lower()] = f"{sid}.{sg_id}.{secret}"
        signers.append({"id": sg_id, "name": s.name.strip(), "email": s.email.lower(), "token_hash": _h(secret), "status": "pending",
                        "otp_hash": None, "otp_expires": None, "otp_attempts": 0, "otp_sends": 0, "otp_last_sent": None})
    data = {"contract_id": cid, "title": c["data"]["title"], "version": len(versions), "text": text, "pdf_key": key,
            "sha256": hashlib.sha256(pdf).hexdigest(), "signers": signers, "final_key": None,
            "expires_at": _iso(_now() + timedelta(days=settings.signing_link_ttl_days))}
    db.put(p.tenant_id, SIGNING, data, "pending", sid, ref=cid)
    db.put(p.tenant_id, CONTRACT, c["data"], "out_for_signature", cid)
    for sg in signers:
        link = f"{settings.public_base_url.rstrip('/')}/s/{tokens[sg['email']]}"
        mailer.send(sg["email"], f"Please sign: {data['title']}",
                    f"Hello {sg['name']},\n\n{p.label} has asked you to review and sign \"{data['title']}\".\n\nOpen this private link:\n"
                    f"{link}\n\nYou will be sent a one-time code before you can sign. The link expires on {data['expires_at'][:10]}. "
                    f"If you were not expecting this, ignore this email.\n")
    db.audit(p.tenant_id, p.actor, "signing.requested", SIGNING, sid, {"contract": cid, "signers": emails, "sha256": data["sha256"]})
    return {"id": sid, "status": "pending", "sha256": data["sha256"], "signers": _public_view(data), "expires_at": data["expires_at"]}


def _latest(p: Principal, cid: str) -> dict:
    rows = db.list_(p.tenant_id, SIGNING, ref=cid)
    if not rows:
        raise HTTPException(404, "No signing request for this contract")
    return rows[-1]


@router.get("/contracts/{cid}/signing")
def signing_status(cid: str, p: Principal = Depends(require("viewer"))):
    d = _latest(p, cid)
    return {"id": d["id"], "status": d["status"], "sha256": d["data"]["sha256"], "signers": _public_view(d["data"]),
            "expires_at": d["data"]["expires_at"], "audit": db.audit_log(p.tenant_id, d["id"])}


@router.get("/contracts/{cid}/signed.pdf")
def signed_pdf(cid: str, p: Principal = Depends(require("viewer"))):
    from fastapi.responses import Response
    d = _latest(p, cid)
    if not d["data"].get("final_key"):
        raise HTTPException(409, "Not fully signed yet")
    return Response(storage.get(d["data"]["final_key"]), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{cid}-signed.pdf"'})


@router.get("/contracts/{cid}/signed.pdf/verify")
def verify_signed(cid: str, p: Principal = Depends(require("viewer"))):
    d = _latest(p, cid)
    if not d["data"].get("final_key"):
        raise HTTPException(409, "Not fully signed yet")
    return seal.verify(storage.get(d["data"]["final_key"]))


@router.post("/signing/{sid}/cancel")
def cancel(sid: str, p: Principal = Depends(require("approver"))):
    d = db.get(p.tenant_id, SIGNING, sid)
    if not d:
        raise HTTPException(404, "Signing request not found")
    if d["status"] != "pending":
        raise HTTPException(409, f"Cannot cancel a {d['status']} request")
    _reopen_contract(p.tenant_id, d["data"]["contract_id"])
    db.put(p.tenant_id, SIGNING, d["data"], "cancelled", sid)
    db.audit(p.tenant_id, p.actor, "signing.cancelled", SIGNING, sid)
    return {"id": sid, "status": "cancelled"}


def _reopen_contract(tenant_id: str, cid: str) -> None:
    c = db.get(tenant_id, CONTRACT, cid)
    if c and c["status"] == "out_for_signature":
        db.put(tenant_id, CONTRACT, c["data"], "approved", cid)


# ---------------- public (token-guarded) side ----------------

def _resolve(token: str) -> tuple[dict, dict]:
    """Return (signing doc incl. tenant_id, signer) for a valid, unexpired link or raise 404/410."""
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(404, "Invalid link")
    sid, sg_id, secret = parts
    d = db.get_any(SIGNING, sid)
    signer = next((s for s in (d["data"]["signers"] if d else []) if s["id"] == sg_id), None)
    if not d or not signer or not hmac.compare_digest(signer["token_hash"], _h(secret)):
        raise HTTPException(404, "Invalid link")
    if d["status"] in ("cancelled", "declined"):
        raise HTTPException(410, f"This signing request was {d['status']}")
    if datetime.fromisoformat(d["data"]["expires_at"]) < _now() and d["status"] == "pending":
        raise HTTPException(410, "This link has expired")
    return d, signer


@router.get("/public/sign/{token}")
def view(token: str):
    d, s = _resolve(token)
    return {"title": d["data"]["title"], "text": d["data"]["text"], "sha256": d["data"]["sha256"], "signer_name": s["name"],
            "status": s["status"], "signing_status": d["status"], "consent_text": CONSENT_TEXT,
            "signers": [{"name": x["name"], "status": x["status"]} for x in d["data"]["signers"]]}


@router.post("/public/sign/{token}/otp")
def send_otp(token: str):
    d, s = _resolve(token)
    if s["status"] == "signed":
        raise HTTPException(409, "You have already signed")

    def mutate(data):
        sg = next(x for x in data["signers"] if x["id"] == s["id"])
        last = datetime.fromisoformat(sg["otp_last_sent"]) if sg["otp_last_sent"] else None
        if sg["otp_sends"] >= MAX_OTP_SENDS:
            raise HTTPException(429, "Too many codes requested; contact the sender")
        if last and (_now() - last).total_seconds() < OTP_RESEND_SECONDS:
            raise HTTPException(429, f"Please wait {OTP_RESEND_SECONDS} seconds before requesting another code")
        code = f"{secrets.randbelow(10**6):06d}"
        sg.update(otp_hash=_h(f"{sg['id']}:{code}"), otp_expires=_iso(_now() + timedelta(minutes=settings.signing_otp_ttl_minutes)),
                  otp_attempts=0, otp_sends=sg["otp_sends"] + 1, otp_last_sent=_iso(_now()))
        return code

    code = db.update_locked(d["tenant_id"], SIGNING, d["id"], mutate)
    mailer.send(s["email"], "Your signing code", f"Your one-time code to sign \"{d['data']['title']}\" is {code}.\n"
                f"It expires in {settings.signing_otp_ttl_minutes} minutes. Never share it.\n")
    db.audit(d["tenant_id"], f"signer:{s['email']}", "signing.otp_sent", SIGNING, d["id"])
    return {"sent": True}


class SignIn(BaseModel):
    otp: str = Field(min_length=6, max_length=6)
    typed_name: str = Field(min_length=2, max_length=120)
    consent: bool


@router.post("/public/sign/{token}/sign")
def sign(token: str, body: SignIn, request: Request):
    d, s = _resolve(token)
    if not body.consent:
        raise HTTPException(422, "Consent is required")
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")[:200]

    def mutate(data):
        sg = next(x for x in data["signers"] if x["id"] == s["id"])
        if sg["status"] == "signed":
            raise HTTPException(409, "You have already signed")
        if not sg["otp_hash"] or not sg["otp_expires"] or datetime.fromisoformat(sg["otp_expires"]) < _now():
            raise HTTPException(400, "Request a new code")
        if sg["otp_attempts"] >= MAX_OTP_ATTEMPTS:
            raise HTTPException(429, "Too many attempts; request a new code")
        sg["otp_attempts"] += 1
        if not hmac.compare_digest(sg["otp_hash"], _h(f"{sg['id']}:{body.otp}")):
            return "bad_otp"  # commit the attempt counter, report below
        sg.update(status="signed", signed_at=_iso(_now()), typed_name=body.typed_name.strip(), ip=ip, ua=ua,
                  consent=CONSENT_VERSION, consent_sha256=_h(CONSENT_TEXT), doc_sha256=data["sha256"], otp_hash=None)
        return "all_signed" if all(x["status"] == "signed" for x in data["signers"]) else "signed"

    result = db.update_locked(d["tenant_id"], SIGNING, d["id"], mutate)
    if result == "bad_otp":
        raise HTTPException(400, "Incorrect code")
    db.audit(d["tenant_id"], f"signer:{s['email']}", "signing.signed", SIGNING, d["id"], {"ip": ip, "sha256": d["data"]["sha256"]})
    if result == "all_signed":
        _finalize(d["tenant_id"], d["id"])
    return {"signed": True, "all_signed": result == "all_signed"}


@router.post("/public/sign/{token}/decline")
def decline(token: str):
    d, s = _resolve(token)
    if s["status"] == "signed":
        raise HTTPException(409, "You have already signed")
    if d["status"] != "pending":
        raise HTTPException(409, f"Request is {d['status']}")
    db.update_locked(d["tenant_id"], SIGNING, d["id"], lambda data: None, status="declined")
    _reopen_contract(d["tenant_id"], d["data"]["contract_id"])
    db.audit(d["tenant_id"], f"signer:{s['email']}", "signing.declined", SIGNING, d["id"])
    return {"declined": True}


def _finalize(tenant_id: str, sid: str) -> None:
    def mutate(data):
        if data.get("final_key"):  # idempotent: a concurrent finaliser already did it
            return None
        signed = [s for s in data["signers"] if s["status"] == "signed"]
        pdf = pdfgen.final_pdf(data["title"], data["text"], data["sha256"], signed, CONSENT_TEXT)
        sealed = seal.seal(pdf)
        key = storage.key_for(tenant_id, sid, "signed.pdf")
        storage.put(key, sealed)
        data["final_key"], data["final_sha256"] = key, hashlib.sha256(sealed).hexdigest()
        data["completed_at"] = _iso(_now())
        return "completed", "completed"

    if db.update_locked(tenant_id, SIGNING, sid, mutate) == "completed":
        d = db.get(tenant_id, SIGNING, sid)
        c = db.get(tenant_id, CONTRACT, d["data"]["contract_id"])
        if c:
            db.put(tenant_id, CONTRACT, c["data"], "signed", c["id"])
        db.audit(tenant_id, "system", "signing.completed", SIGNING, sid, {"final_sha256": d["data"]["final_sha256"]})
