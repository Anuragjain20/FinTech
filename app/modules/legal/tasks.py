from app.core import db
from app.core.jobs import celery
from app.modules.legal import review


@celery.task(name="fintech.legal_review", time_limit=900)
def legal_review(tenant_id: str, review_id: str):
    d = db.get(tenant_id, "legal_review", review_id)
    if d is None:
        return None
    try:
        result = review.review(tenant_id, d["data"]["text"])
        db.put(tenant_id, "legal_review", {**d["data"], "result": result}, "completed", review_id)
    except Exception as e:  # keep the request visible to the user instead of failing silently
        db.put(tenant_id, "legal_review", {**d["data"], "error": str(e)}, "failed", review_id)
    return review_id
