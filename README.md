# FinTech Suite

Multi-tenant API for Indian SMBs / CA firms: **invoice automation**, **bank reconciliation (BRS)** and **contract drafting**, sharing one platform (API-key auth, per-tenant isolation, RBAC, audit log).

```bash
pip install -e '.[dev]'          # add '.[ocr]' for Docling / PaddleOCR
pytest
FINTECH_ADMIN_TOKEN=change-me uvicorn app.main:app   # docs at /docs
```

Bootstrap: `POST /tenants` (header `X-Admin-Token`) returns a tenant id and an admin `api_key`. Send it as `X-API-Key`. Admins mint more keys via `POST /keys` (roles: viewer < operator < approver < admin).

## Modules

| Module | Endpoints | What it does |
|---|---|---|
| Invoices `app/invoice` | `/invoices/upload`, `/text`, review queue, `PUT` correct, `/approve`, `/export/csv`, `/export/tally` | Text/OCR → fields with per-field confidence; GSTIN format + checksum; total/line arithmetic; CGST/SGST vs IGST by state; duplicate detection; human review queue; approved-only export (CSV, Tally purchase-voucher XML) |
| BRS `app/brs` | `/reconciliations` (CSV/XLSX upload), `confirm`, `reject`, `manual-match`, `finalize`, `report.xlsx` | Auto-detects bank/ledger columns; matches by reference, then amount+date, then fuzzy; fuzzy results are only *suggestions* until a human confirms; classifies unmatched items (charges, interest, timing, duplicates); reconciliation statement with unexplained difference |
| Contracts `app/contracts` | `/contracts/templates`, `POST /contracts`, `PUT`, `compare`, `submit`, `approve`, `docx`, `/contracts/review` | NDA, service, vendor and employment templates built from a clause library; rule-based risk screen (unlimited liability, auto-renew, s.27 non-compete, s.74 penalty, MSME payment terms, missing clauses); version diff; draft → review → approved workflow; DOCX export |

## Honest limitations

- **Contract templates are not lawyer-vetted** (`lawyer_reviewed: false`). Have an Indian advocate review templates and the risk rules before selling; outputs are drafts, never legal advice.
- **OCR is pluggable, not bundled.** `.txt` works out of the box; PDFs/images need `pip install '.[ocr]'`. The regex extractor is a baseline; accuracy on messy real-world scans must be measured on customer samples, and an LLM/layout-model extractor should slot in behind `extract.parse_invoice_text`.
- **Tally export** assumes the named ledgers (`Purchase`, `Input CGST/SGST/IGST`, supplier name) already exist; test import on a Tally company before relying on it.
- Storage is SQLite via `app/db.py` (swap for PostgreSQL), uploads are not persisted to object storage, and there is no billing, UI, e-signature or WhatsApp/email ingestion yet.
- **Licences:** dependencies used or suggested are permissive (FastAPI MIT, PaddleOCR Apache-2.0, Docling MIT, rapidfuzz MIT, python-docx MIT, openpyxl MIT). Re-check before adding AGPL components (e.g. Documenso) to a proprietary SaaS.
