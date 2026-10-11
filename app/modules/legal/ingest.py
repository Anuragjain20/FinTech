"""CLI: load legal source documents into the shared corpus (or a tenant's private corpus).

    python -m app.modules.legal.ingest ./acts/contract_act.txt --source "Indian Contract Act, 1872"
    python -m app.modules.legal.ingest ./playbook.pdf --source "Acme playbook" --tenant <tenant_id>

Use official texts (e.g. India Code, indiacode.nic.in). This repo ships no statute text: verify what you load.
"""
import argparse
import sys
from pathlib import Path

from app.modules.legal import store


def read_text(name: str, data: bytes) -> str:
    if name.lower().endswith(".pdf"):
        import io

        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    return data.decode("utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path)
    ap.add_argument("--source", required=True, help="Citation label, e.g. 'Indian Contract Act, 1872'")
    ap.add_argument("--tenant", default=None, help="Tenant id for a private corpus (default: shared)")
    ap.add_argument("--replace", action="store_true", help="Delete existing chunks with this source first")
    a = ap.parse_args(argv)
    if a.replace:
        store.delete_source(a.tenant, a.source)
    n = store.add_document(a.tenant, a.source, read_text(a.path.name, a.path.read_bytes()))
    print(f"ingested {n} chunks from {a.path} as '{a.source}'")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
