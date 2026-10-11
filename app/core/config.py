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

    # --- SSO (OpenID Connect: Keycloak, Authentik, Google, Azure AD, Okta, ...). Empty issuer disables SSO.
    oidc_issuer: str = ""                        # e.g. https://keycloak.example.com/realms/acme
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_provider_name: str = "SSO"
    public_base_url: str = "http://localhost:8000"   # externally visible origin; used for the OIDC redirect URI
    session_secret: str = "dev-session-secret"   # signs the short-lived login-transaction cookie
    session_ttl_hours: int = 12
    cookie_secure: bool | None = None            # default: True in production

    # --- e-signature
    signing_p12_path: str = ""                   # PKCS#12 identity used to seal signed PDFs. Empty: ephemeral self-signed (dev only)
    signing_p12_password: str = ""
    signing_otp_ttl_minutes: int = 10
    signing_link_ttl_days: int = 14
    smtp_host: str = ""                          # empty: emails are captured in memory (dev/tests)
    smtp_port: int = 587
    smtp_starttls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@localhost"

    # --- legal RAG
    llm_base_url: str = ""                       # any OpenAI-compatible server: Ollama (http://ollama:11434/v1), vLLM, llama.cpp
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_s: int = 120
    embedding_model: str = ""                    # sentence-transformers model name; empty = lexical (BM25) retrieval only
    rag_top_k: int = 4

    razorpay_webhook_secret: str = ""
    sentry_dsn: str = ""

    @model_validator(mode="after")
    def _production_guards(self):
        if self.env == "production":
            if self.admin_token == _DEV_TOKEN or len(self.admin_token) < 24:
                raise ValueError("FINTECH_ADMIN_TOKEN must be set to a strong secret (>=24 chars) in production")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is not supported in production; set FINTECH_DATABASE_URL to PostgreSQL")
            if self.session_secret == "dev-session-secret" or len(self.session_secret) < 24:
                raise ValueError("FINTECH_SESSION_SECRET must be set to a strong secret (>=24 chars) in production")
            if self.celery_eager:
                raise ValueError("Set FINTECH_CELERY_EAGER=false in production so work runs in the worker")
        return self

    @property
    def secure_cookies(self) -> bool:
        return self.env == "production" if self.cookie_secure is None else self.cookie_secure


settings = Settings()
