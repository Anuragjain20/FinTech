# FinTech Suite

Multi-tenant SaaS for Indian SMBs / CA firms: **invoice automation**, **bank reconciliation (BRS)** and **contract drafting**, on one platform (API-key auth, per-tenant isolation, RBAC, audit log, plans and quotas).

## Stack (all open source)

| Concern | Component |
|---|---|
| API | FastAPI, Pydantic v2, SlowAPI (rate limits) |
| Database | PostgreSQL (SQLAlchemy 2 + **Alembic** migrations); SQLite for dev/tests |
| Jobs | Celery + Redis (OCR/extraction in the worker, mailbox poller via beat) |
| Files | S3-compatible object storage (MinIO / AWS S3) via boto3, or local disk |
| OCR | Docling, PaddleOCR (optional install), pdfplumber for bank-statement PDFs |
| LLM orchestration | **LangChain** (chat models, embeddings, splitters) + **LangGraph** (invoice extraction loop, legal-review pipeline) |
| Default models | **DeepSeek** (`deepseek-chat`) for chat; **Jina** free-tier hosted embeddings (`jina-embeddings-v3`) - both swappable by config |
| Matching | rapidfuzz |
| Documents | python-docx, openpyxl, Jinja2 (sandboxed) |
| Ops | structlog JSON logs, request ids, Prometheus `/metrics`, `/health` + `/ready`, optional Sentry |
| UI | React + TypeScript + Vite, served by the API from the same origin |
| SSO | OpenID Connect via Authlib (Keycloak, Authentik, Azure AD, Okta, Google); PKCE; invite-only |
| E-signature | reportlab (PDF), pyHanko (PDF seal), SMTP one-time codes |
| Retrieval | rank-bm25 + dense embeddings through the gateway (hybrid, reciprocal-rank fusion), tenant-scoped |
| Payments | Razorpay (signed webhook -> plan change); quotas enforced per month |

## Architecture

A modular monolith with enforced boundaries (`lint-imports`, run in CI):

```
app/
  main.py  worker.py        composition roots: wire modules together, nothing else
  modules/                  feature modules - independent of each other
    identity/   SSO (OIDC) + invited users
    invoices/   OCR text -> LangGraph extraction -> validation -> approval -> CSV/Tally
    reconciliation/   statement parsing + matching + BRS report
    contracts/  templates, rule screening, versions, workflow;   public.py = the ONLY API others may call
    esign/      signing requests, OTP, sealed PDF            (uses contracts.public)
    legal/      corpus + hybrid retrieval + LangGraph review (uses contracts.public)
  ai/                       the AI gateway: providers, chat, structured output, embeddings (LangChain)
  core/                     platform: config, db, auth/RBAC, billing/quotas, storage, jobs, observability
evals/                      accuracy harnesses (invoices, retrieval) - run these on YOUR data
```

Rules enforced by import-linter: `main/worker > modules > ai > core`; feature modules may not import each other, except
`esign` and `legal` calling `contracts.public`. Each module owns its API router, tasks and domain logic; shared tables live
in `core/db.py` (one Alembic history). To split a module into its own service later, its seams are already the public APIs.

## AI: how it works and how to switch

Feature modules never import a provider SDK. They ask the gateway (`app/ai`) for a model **by task** (`extract`, `review`,
`verify`). Defaults: DeepSeek chat + Jina embeddings. Switching is configuration only:

```bash
# DeepSeek (default)                 FINTECH_LLM_PROVIDER=deepseek  FINTECH_LLM_API_KEY=sk-...
# stronger model just for checks     FINTECH_LLM_TASK_MODELS='{"verify":"deepseek-reasoner"}'
# OpenAI                             FINTECH_LLM_PROVIDER=openai    FINTECH_LLM_API_KEY=...  FINTECH_LLM_MODEL=gpt-4o-mini
# Anthropic (pip install '.[anthropic]')  FINTECH_LLM_PROVIDER=anthropic  FINTECH_LLM_API_KEY=...
# local Ollama / vLLM / OpenRouter   FINTECH_LLM_PROVIDER=openai_compat FINTECH_LLM_BASE_URL=http://ollama:11434/v1 FINTECH_LLM_MODEL=qwen2.5:14b
# embeddings (free hosted)           FINTECH_EMBEDDING_PROVIDER=jina FINTECH_EMBEDDING_API_KEY=jina_...
# embeddings (local, pip '.[hf]')    FINTECH_EMBEDDING_PROVIDER=local  FINTECH_EMBEDDING_MODEL=BAAI/bge-m3
```

`GET /ai/status?probe=true` (admin) shows the active models and does a live round-trip. Every vector is stored with the id of
the model that made it; dense search only uses vectors from the *current* model, so a switch never mixes incompatible vectors.
After switching embeddings run `python -m app.modules.legal.ingest --reindex` (until then those chunks are lexical-only).
No key = LLM features off and everything falls back to the deterministic path. Token usage is metered per tenant.

**Workflows (LangGraph)**
- *Invoice extraction*: regex baseline -> LLM structured extraction -> deterministic OCR-confusion GSTIN fixer -> validators
  (arithmetic, GSTIN checksum, CGST/SGST-vs-IGST) -> on failure, feed the exact errors back for up to 2 repairs -> merge with
  evidence-based confidence (two extractors agree = high; disagree = flagged for review). Models cannot talk their way past
  the validators, so prompt-injected totals still land in the review queue.
- *Legal review*: clauses fan out in parallel; each runs retrieve -> analyse (cites passages only) -> ground-check ->
  **independent verification** (a separate call judges whether the cited quote actually supports the issue) -> finish.

## Measuring accuracy (do this before you sell)

```bash
python -m evals.make_synthetic --n 60                      # smoke-test set (synthetic; NOT a substitute for real data)
python -m evals.invoices --mode rules                       # regex baseline
python -m evals.invoices                                    # with the configured LLM
python -m evals.invoices --data my_labelled.jsonl           # YOUR invoices: same JSONL schema
python -m evals.retrieval --data my_queries.jsonl --k 4     # legal retrieval recall@k on the live corpus
```

Headline metric is the **silent error rate**: invoices with a wrong field that would reach the ledger without human review.
Baseline measured on the synthetic set, regex only: 53% of invoices fully correct, 77% sent to review, silent error rate 0.0%
(safe but would overwhelm reviewers; layouts with labels like "Inv. No." or one-line summaries fail entirely). **The LLM path
has not been measured on real models or real invoices** (the DeepSeek/Jina hosts are not reachable from the build sandbox);
`tests/test_evals.py` only proves the repair/validation machinery with a scripted noisy fake model.

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
python -m app.modules.legal.ingest ./contract_act.txt --source "Indian Contract Act, 1872"      # shared corpus
# or: POST /legal/corpus (X-Admin-Token); tenants add private playbooks via /legal/documents or the Admin tab
```

Limits of the grounding guard: it proves a citation was *retrieved*, not that the model *applied it correctly or that it is relevant* (a weak model can cite an irrelevant passage). Evaluate the LLM on your own contracts before relying on it, read the quoted passage for every issue, and keep a lawyer in the loop.

## Verification status (be aware before launch)

Verified here: 88 automated tests on SQLite and on real PostgreSQL 16; Alembic up/down/up and `alembic check`; clean-venv
install running the full suite; `ruff` and `lint-imports` (3 contracts, including a check that a forbidden import is caught);
a browser run on PostgreSQL + Redis + Celery of SSO login -> approval -> legal review -> signing -> sealed PDF (previous
round; re-run the e2e after upgrading the LLM path).

**Not verified** (not possible in this environment):
- **Real DeepSeek / Jina / Hugging Face calls.** All LLM and embedding paths were tested against fake OpenAI-compatible
  servers (request shape, JSON mode, retry, switching, metering). Jina's OpenAI-compatible embeddings route and
  DeepSeek's JSON mode are used per their docs but unconfirmed here. Run `GET /ai/status?probe=true` with real keys first.
- **Accuracy of any real model** on invoices or legal text, and retrieval quality on real statutes. No statute text ships
  with the repo. Use `evals/` on your own labelled data and set your own go/no-go thresholds.
- SSO against real IdPs, SMTP against a real server, the sealed PDF in Adobe Acrobat, the Docker image and CI workflow,
  Docling/PaddleOCR, Razorpay (live), a real IMAP mailbox, and Tally import.

## Known limits / not built

- **Contract templates are not lawyer-vetted** (`lawyer_reviewed: false`); outputs are drafts, not legal advice. Have an Indian advocate review templates and the risk rules before selling.
- No Aadhaar eSign / DSC integration (needs a licensed provider), no password login (SSO or API keys only; the UI keeps a pasted API key in `sessionStorage`), no SAML (OIDC only), no WhatsApp ingestion. Signing PDFs use DejaVu Sans, so Devanagari and other non-Latin names will not render; embed a Noto font for those.
- Duplicate-invoice detection is not atomic under concurrent uploads of the same invoice; add a unique index on (tenant, supplier GSTIN, normalised number) if that matters.
- A reconciliation is stored as one JSON document - fine for typical monthly statements, not for hundreds of thousands of rows.
- Licences: everything above is permissive (MIT/BSD/Apache-2.0) or LGPL/BSD-style; re-check before adding AGPL components (e.g. Documenso) to a proprietary SaaS.
