"""Plans, quotas, usage metering and the Razorpay subscription webhook.

Quotas are enforced per tenant per calendar month. Payments are handled by
Razorpay (India-native subscriptions/UPI); we only verify its signed webhooks and
map subscription events to a plan. Plan ids are mapped via FINTECH plan notes:
create the Razorpay plan with `notes: {"plan": "starter"}`.
"""
import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update

from . import db
from .auth import Principal, require
from .config import settings

# monthly limits; None = unlimited
PLANS = {
    "free":    {"invoices": 20,   "reconciliations": 2,    "contracts": 5,    "signatures": 3,    "ai_reviews": 5,    "price_inr": 0},
    "starter": {"invoices": 300,  "reconciliations": 10,   "contracts": 30,   "signatures": 30,   "ai_reviews": 50,   "price_inr": 1999},
    "growth":  {"invoices": 2000, "reconciliations": 60,   "contracts": 200,  "signatures": 300,  "ai_reviews": 500,  "price_inr": 4999},
    "scale":   {"invoices": None, "reconciliations": None, "contracts": None, "signatures": None, "ai_reviews": None, "price_inr": 14999},
}

router = APIRouter(tags=["billing"])


def tenant_plan(tenant_id: str) -> str:
    with db.engine().connect() as c:
        r = c.execute(select(db.tenants.c.plan).where(db.tenants.c.id == tenant_id)).first()
    return r[0] if r else "free"


def consume(tenant_id: str, metric: str, n: int = 1) -> None:
    """Raise 402 when the tenant's plan quota for `metric` is exhausted, else count the usage."""
    limit = PLANS[tenant_plan(tenant_id)][metric]
    if limit is not None and db.usage_get(tenant_id, metric) + n > limit:
        raise HTTPException(402, f"Monthly {metric} quota ({limit}) reached for your plan; upgrade to continue")
    db.usage_incr(tenant_id, metric, n)


@router.get("/billing")
def overview(p: Principal = Depends(require("viewer"))):
    plan = tenant_plan(p.tenant_id)
    return {"plan": plan, "limits": PLANS[plan],
            "usage": {m: db.usage_get(p.tenant_id, m) for m in ("invoices", "reconciliations", "contracts", "signatures", "ai_reviews")},
            "plans": PLANS}


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhooks/razorpay", include_in_schema=False)
async def razorpay_webhook(request: Request):
    body = await request.body()
    if not verify_signature(body, request.headers.get("x-razorpay-signature", ""), settings.razorpay_webhook_secret):
        raise HTTPException(400, "Bad signature")
    event = json.loads(body)
    sub = (event.get("payload", {}).get("subscription", {}) or {}).get("entity", {})
    notes = sub.get("notes") or {}
    tenant_id, plan = notes.get("tenant_id"), notes.get("plan")
    if not tenant_id or event.get("event") not in ("subscription.activated", "subscription.charged",
                                                    "subscription.cancelled", "subscription.halted", "subscription.completed"):
        return {"ignored": True}
    new_plan = plan if event["event"] in ("subscription.activated", "subscription.charged") and plan in PLANS else "free"
    with db.engine().begin() as c:
        c.execute(update(db.tenants).where(db.tenants.c.id == tenant_id).values(plan=new_plan, subscription_id=sub.get("id")))
    db.audit(tenant_id, "razorpay", "billing.plan_changed", "tenant", tenant_id, {"event": event["event"], "plan": new_plan})
    return {"ok": True}
