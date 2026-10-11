# FinTech Suite

Multi-tenant SaaS for Indian SMBs / CA firms: **invoice automation**, **bank reconciliation (BRS)** and **contract drafting**, on one platform (API-key auth, per-tenant isolation, RBAC, audit log, plans and quotas).

## Stack (all open source)

| Concern | Component |
|---|---|
| API | FastAPI, Pydantic v2, SlowAPI (rate limits) |
| Database | PostgreSQL (SQLAlchemy 2 + **Alembic** migrations); SQLite for dev/tests |
| Jobs | Celery + Redis (OCR/extraction in the worker, mailbox poller via beat) |
| Files | S3-compatible object storage (MinIO / AWS S3) via boto3, or local disk |
| OCR / extraction | Docling, PaddleOCR (optional install), pdfplumber for bank-statement PDFs |
| Matching | rapidfuzz |
| Documents | python-docx, openpyxl, Jinja2 (sandboxed) |
| Ops | structlog JSON logs, request ids, Prometheus `/metrics`, `/health` + `/ready`, optional Sentry |
| UI | React + TypeScript + Vite, served by the API from the same origin |
| Payments | Razorpay (signed webhook -> plan change); quotas enforced per month |

## Run it

```bash
# development (SQLite, inline jobs, local files)
pip install -e '.[dev]' && pytest
(cd frontend && npm ci && npm run build)
uvicorn app.main:app --reload        # UI + API at :8000, API docs at /docs

# self-hosted production-style stack
cp .env.example .env                  # set real secrets
docker compose up --build             # postgres, redis, minio, migrate, api, worker
```

Bootstrap a tenant: `POST /tenants` with header `X-Admin-Token` returns an admin `api_key`; use it as `X-API-Key` (or sign in through the UI). Admins mint role-scoped keys at `POST /keys` (viewer < operator < approver < admin) and revoke them with `DELETE /keys/{label}`.

In `FINTECH_ENV=production` the app refuses to start with the default admin token, SQLite, or inline (eager) jobs. Settings are `FINTECH_*` env vars (see `app/config.py`, `.env.example`). Put the API behind TLS and **block `/metrics` at the ingress**; it is unauthenticated.

## Features

- **Invoices** - upload (PDF/image/text) -> stored in object storage -> OCR + extraction in a worker (`202`, poll until not `processing`); also by **email** (IMAP mailbox per tenant). Per-field confidence, GSTIN format + checksum, arithmetic, CGST/SGST vs IGST by state, duplicate detection, review queue with human correction, approval (blocking errors need an override reason), approved-only export to CSV and Tally purchase-voucher XML.
- **BRS** - CSV / XLSX / digital-PDF statements; column auto-detection; reference -> amount+date -> fuzzy matching; fuzzy matches stay *suggestions* until confirmed; unmatched items classified (charge, interest, timing, duplicate); statement with unexplained difference; Excel report; finalize requires an approver and no pending suggestions.
- **Contracts** - NDA, service, vendor, employment templates from a clause library; rule-based risk screen (unlimited liability, auto-renew, s.27 non-compete, s.74 penalty, MSME payment terms, missing clauses); versions + diff; draft -> review -> approved; DOCX export.
- **Platform** - plans and monthly quotas (`GET /billing`), 402 when exhausted; audit trail on every state change; CSV/XLSX formula-injection escaping; upload size/type limits; security headers; rate limiting.

## Verification status (be aware before launch)

Verified here: 38 automated tests pass on both SQLite and a real PostgreSQL 16; Alembic upgrade/downgrade/upgrade on PostgreSQL; a live run of API + Redis + Celery worker + PostgreSQL with a headless browser driving login -> invoice upload/approve -> reconciliation -> contract generation; `pip install .` from a clean venv; `ruff` clean; UI typechecks and builds.

**Not verified** (no way to in this environment):
- The Docker image and compose file were not built or run (no Docker daemon); CI is written but has not run.
- Docling / PaddleOCR are optional installs and were not exercised; extraction accuracy on real scans is unmeasured. The regex extractor is a baseline - test on real customer invoices.
- The Razorpay webhook is verified by HMAC in tests, not against live Razorpay; the IMAP poller is tested via message ingestion, not a live mailbox; S3 is tested against moto, not MinIO/AWS.
- Tally XML needs its ledgers to exist; test an import in a Tally company.

## Known limits / not built

- **Contract templates are not lawyer-vetted** (`lawyer_reviewed: false`); outputs are drafts, not legal advice. Have an Indian advocate review templates and the risk rules before selling.
- No e-signature (Aadhaar eSign / DSC integration needs a licensed provider), no legal-RAG review, no SSO/password login (API keys only; the UI keeps the key in `sessionStorage`), no WhatsApp ingestion.
- Duplicate-invoice detection is not atomic under concurrent uploads of the same invoice; add a unique index on (tenant, supplier GSTIN, normalised number) if that matters.
- A reconciliation is stored as one JSON document - fine for typical monthly statements, not for hundreds of thousands of rows.
- Licences: everything above is permissive (MIT/BSD/Apache-2.0) or LGPL/BSD-style; re-check before adding AGPL components (e.g. Documenso) to a proprietary SaaS.
