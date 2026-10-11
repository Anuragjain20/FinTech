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
| SSO | OpenID Connect via Authlib (Keycloak, Authentik, Azure AD, Okta, Google); PKCE; invite-only |
| E-signature | reportlab (PDF), pyHanko (PDF seal), SMTP one-time codes |
| Legal RAG | rank-bm25 + optional sentence-transformers (hybrid, RRF); any OpenAI-compatible LLM (Ollama, vLLM, llama.cpp) |
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

## SSO, e-signature and legal review

**SSO (OIDC).** Set `FINTECH_OIDC_ISSUER/CLIENT_ID/CLIENT_SECRET` and register `<PUBLIC_BASE_URL>/auth/callback` with your IdP. Login is authorization-code + PKCE; the id_token is verified by Authlib and a *verified* email must match a user an admin invited (`POST /users`, or the Admin tab). There is no auto-provisioning, one email belongs to one tenant, deactivating a user ends their sessions. Browser sessions use an HttpOnly cookie; cookie-authenticated writes need an `X-Requested-With` header (CSRF defence). API keys still work for machine clients.

**E-signature.** An approved contract can be sent to up to 10 signers: private link by email, then a separate emailed one-time code, typed name and explicit consent. Evidence per signer: time, IP, user agent, document SHA-256. When everyone has signed, a certificate page is appended and the PDF is sealed with your organisation's certificate (`FINTECH_SIGNING_P12_PATH`; pyHanko); `GET /contracts/{id}/signed.pdf/verify` checks the seal. Without a certificate, dev mode uses an ephemeral self-signed one and production refuses to seal. **This is a simple electronic signature with an audit trail, not Aadhaar eSign or a DSC signature.** Whether it suffices (and stamping/e-stamping) depends on the document; the IT Act excludes some classes entirely. Get legal advice.

**Legal review (RAG).** Contract clauses are matched against a corpus (hybrid BM25 + optional dense embeddings) and, if an LLM is configured, analysed using *only* the retrieved passages. Every reported issue must cite a retrieved passage and shows its quote; findings with missing or unretrieved citations are dropped. Without an LLM it degrades to rule findings + relevant provisions. **No statute text ships with this repo**; load official texts yourself:

```bash
python -m app.rag.ingest ./contract_act.txt --source "Indian Contract Act, 1872"      # shared corpus
# or: POST /legal/corpus (X-Admin-Token); tenants add private playbooks via /legal/documents or the Admin tab
```

Limits of the grounding guard: it proves a citation was *retrieved*, not that the model *applied it correctly or that it is relevant* (a weak model can cite an irrelevant passage). Evaluate the LLM on your own contracts before relying on it, read the quoted passage for every issue, and keep a lawyer in the loop.

## Verification status (be aware before launch)

Verified here: 61 automated tests on SQLite and on real PostgreSQL 16 (stable over repeated runs); Alembic up/down/up and `alembic check` on PostgreSQL; a clean-venv install from `pyproject.toml` running the full suite; `ruff` clean; and a live browser run on PostgreSQL + Redis + a Celery worker with **real SSO login (OIDC code+PKCE) -> contract approval -> AI legal review -> two signers signing through emailed links and OTPs (real SMTP to a local sink) -> signed PDF download -> seal verification**.

**Not verified** (not possible in this environment):
- SSO was tested against a minimal in-repo OIDC provider, not Keycloak/Azure/Okta/Google; SMTP against a local sink, not a real mail server.
- The LLM was a stub, and the corpus a synthetic test fixture: **retrieval quality and legal-analysis quality on real Indian statutes and real LLMs are unmeasured.** Dense embeddings (`sentence-transformers`) were not run (model hosting was unreachable); the code path is tested with a stub embedder.
- The sealed PDF was validated with pyHanko only, not in Adobe Acrobat; a self-signed/dev seal shows as untrusted there.
- The Docker image and CI workflow have never been built/run (no Docker daemon); Docling/PaddleOCR, Razorpay (live) and a real IMAP mailbox are likewise untested. Tally XML needs a test import.

## Known limits / not built

- **Contract templates are not lawyer-vetted** (`lawyer_reviewed: false`); outputs are drafts, not legal advice. Have an Indian advocate review templates and the risk rules before selling.
- No Aadhaar eSign / DSC integration (needs a licensed provider), no password login (SSO or API keys only; the UI keeps a pasted API key in `sessionStorage`), no SAML (OIDC only), no WhatsApp ingestion. Signing PDFs use DejaVu Sans, so Devanagari and other non-Latin names will not render; embed a Noto font for those.
- Duplicate-invoice detection is not atomic under concurrent uploads of the same invoice; add a unique index on (tenant, supplier GSTIN, normalised number) if that matters.
- A reconciliation is stored as one JSON document - fine for typical monthly statements, not for hundreds of thousands of rows.
- Licences: everything above is permissive (MIT/BSD/Apache-2.0) or LGPL/BSD-style; re-check before adding AGPL components (e.g. Documenso) to a proprietary SaaS.
