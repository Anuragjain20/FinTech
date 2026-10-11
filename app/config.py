import os

DB_PATH = os.environ.get("FINTECH_DB", "fintech.db")
# Token required to create tenants (POST /tenants). Must be set in production.
ADMIN_TOKEN = os.environ.get("FINTECH_ADMIN_TOKEN", "dev-admin-token")
# Invoice fields below this confidence are routed to human review.
REVIEW_CONFIDENCE_THRESHOLD = float(os.environ.get("FINTECH_REVIEW_THRESHOLD", "0.8"))
