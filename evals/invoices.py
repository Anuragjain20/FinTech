"""Measure invoice-extraction accuracy on a labelled JSONL set.

    python -m evals.invoices                              # synthetic set, whatever LLM is configured in FINTECH_* env
    python -m evals.invoices --data my_labelled.jsonl     # YOUR invoices (same schema as the synthetic file)
    python -m evals.invoices --mode rules                 # force the regex baseline for comparison

Reports per-field exact-match accuracy, the share of invoices with every field right, and - the number that matters for a
ledger - the SILENT ERROR RATE: invoices containing a wrong field that would still pass straight to 'ready' (no validation
issue, all confidences above the review threshold), i.e. errors no human would be asked to look at.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from app.core.config import settings
from app.modules.invoices import graph, validate

FIELDS = ["supplier_gstin", "buyer_gstin", "invoice_number", "invoice_date", "taxable_value", "cgst", "sgst", "igst", "total"]


def same(a, b) -> bool:
    if a in (None, "") and b in (None, "", 0, 0.0):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.01
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def evaluate(rows: list[dict], mode: str = "auto") -> dict:
    per_field = defaultdict(lambda: [0, 0])
    exact = silent = review = 0
    by_layout = defaultdict(lambda: [0, 0])
    llm_used = 0
    for row in rows:
        if mode == "rules":
            from app.ai import chat
            chat_enabled = chat.enabled
            chat.enabled = lambda task="default": False
            try:
                res = graph.extract_invoice(row["text"], "eval")
            finally:
                chat.enabled = chat_enabled
        else:
            res = graph.extract_invoice(row["text"], "eval")
        llm_used += res["extraction"]["method"] == "llm+rules"
        got, conf = res["fields"], res["confidence"]
        wrong = [f for f in FIELDS if not same(got.get(f), row["expected"].get(f))]
        for f in FIELDS:
            per_field[f][1] += 1
            per_field[f][0] += f not in wrong
        inv = {**got, "line_items": res["line_items"]}
        issues = validate.validate(inv, conf, [])
        needs_review = bool(issues)  # same rule the product uses (any issue => review queue)
        review += needs_review
        exact += not wrong
        silent += bool(wrong) and not needs_review
        lay = by_layout[row.get("layout", "-")]
        lay[1] += 1
        lay[0] += not wrong
    n = len(rows)
    return {"n": n, "llm_used": llm_used, "field_accuracy": {f: round(c / t, 3) for f, (c, t) in per_field.items()},
            "invoice_all_fields_correct": round(exact / n, 3), "sent_to_review": round(review / n, 3),
            "silent_error_rate": round(silent / n, 3), "by_layout": {k: round(c / t, 3) for k, (c, t) in sorted(by_layout.items())}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="evals/data/invoices_synthetic.jsonl")
    ap.add_argument("--mode", choices=["auto", "rules"], default="auto")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = [json.loads(line) for line in Path(a.data).read_text().splitlines() if line.strip()]
    rows = rows[: a.limit] if a.limit else rows
    r = evaluate(rows, a.mode)
    if a.json:
        print(json.dumps(r, indent=2))
        return 0
    print(f"{r['n']} invoices | mode={a.mode} | LLM used on {r['llm_used']} | review threshold {settings.review_threshold}")
    for f, acc in r["field_accuracy"].items():
        print(f"  {f:<16}{acc * 100:6.1f}%")
    print(f"  all fields correct   {r['invoice_all_fields_correct'] * 100:5.1f}%")
    print(f"  sent to human review {r['sent_to_review'] * 100:5.1f}%")
    print(f"  SILENT ERROR RATE    {r['silent_error_rate'] * 100:5.1f}%   (wrong but not flagged)")
    print("  by layout:", {k: f"{v * 100:.0f}%" for k, v in r["by_layout"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
