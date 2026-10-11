"""Typed settings from environment (prefix FINTECH_). `config.settings` is the single source."""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_TOKEN = "dev-admin-token"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINTECH_", env_file=".env", extra="ignore")

    env: str = "development"                     # development | test | production
    database_url: str = "sqlite:///fintech.db"   # postgresql+psycopg://user:pw@host/db in production
    admin_token: str = _DEV_TOKEN                # guards POST /tenants
    review_threshold: float = 0.8                # invoice fields below this confidence need human review

    # object storage: "local" (dev) or "s3" (AWS S3 / MinIO / any S3-compatible)
    storage_backend: str = "local"
    storage_local_dir: str = "./uploads"
    s3_bucket: str = "fintech-uploads"
    s3_endpoint_url: str | None = None
    s3_region: str = "ap-south-1"
    s3_sse: bool = False                          # request AES256 server-side encryption (AWS S3)

    # background jobs (Celery + Redis). eager=True runs tasks inline (dev/tests)
    redis_url: str = "redis://localhost:6379/0"
    celery_eager: bool = True

    max_upload_mb: int = 15
    rate_limit: str = "120/minute"
    cors_origins: list[str] = []

    # inbound-invoice mailbox (IMAP). Empty host disables the poller.
    imap_host: str = ""
    imap_user: str = ""
    imap_password: str = ""
    imap_tenant_id: str = ""                     # tenant that owns invoices arriving in this mailbox

    razorpay_webhook_secret: str = ""
    sentry_dsn: str = ""

    @model_validator(mode="after")
    def _production_guards(self):
        if self.env == "production":
            if self.admin_token == _DEV_TOKEN or len(self.admin_token) < 24:
                raise ValueError("FINTECH_ADMIN_TOKEN must be set to a strong secret (>=24 chars) in production")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is not supported in production; set FINTECH_DATABASE_URL to PostgreSQL")
            if self.celery_eager:
                raise ValueError("Set FINTECH_CELERY_EAGER=false in production so work runs in the worker")
        return self


settings = Settings()
