"""Business validation for extracted invoices. Pure functions; no I/O."""
from decimal import Decimal

from ..config import settings
from .gst import state_code, validate_gstin

ROUNDING = Decimal("1.00")  # invoices often carry round-off up to a rupee
CRITICAL = ["supplier_gstin", "invoice_number", "invoice_date", "taxable_value", "total"]


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def validate(inv: dict, confidence: dict, existing: list[dict]) -> list[dict]:
    """Return a list of issues: {code, severity('error'|'warning'), field, message}."""
    issues: list[dict] = []

    def add(code, sev, field, msg):
        issues.append({"code": code, "severity": sev, "field": field, "message": msg})

    for k in CRITICAL:
        if inv.get(k) in (None, ""):
            add("MISSING_FIELD", "error", k, f"{k} is missing")

    for k in ("supplier_gstin", "buyer_gstin"):
        if inv.get(k):
            ok, why = validate_gstin(inv[k])
            if not ok:
                add("INVALID_GSTIN", "error" if k == "supplier_gstin" else "warning", k, f"{k} invalid: {why}")

    taxable, total = _d(inv.get("taxable_value")), _d(inv.get("total"))
    cgst, sgst, igst = _d(inv.get("cgst")), _d(inv.get("sgst")), _d(inv.get("igst"))
    tax = cgst + sgst + igst

    if inv.get("total") is not None and inv.get("taxable_value") is not None:
        if abs(taxable + tax - total) > ROUNDING:
            add("TOTAL_MISMATCH", "error", "total",
                f"taxable {taxable} + tax {tax} = {taxable + tax}, but total is {total}")

    s, b = state_code(inv.get("supplier_gstin")), state_code(inv.get("buyer_gstin"))
    if s and b:
        if s == b and igst > 0:
            add("WRONG_TAX_TYPE", "error", "igst", "Intra-state supply should charge CGST+SGST, not IGST")
        if s != b and (cgst > 0 or sgst > 0):
            add("WRONG_TAX_TYPE", "error", "cgst", "Inter-state supply should charge IGST, not CGST/SGST")
    if abs(cgst - sgst) > Decimal("0.02"):
        add("CGST_SGST_UNEQUAL", "warning", "sgst", "CGST and SGST should be equal")

    items = inv.get("line_items") or []
    if items:
        s_amt = sum((_d(i.get("amount")) for i in items), Decimal(0))
        if inv.get("taxable_value") is not None and abs(s_amt - taxable) > ROUNDING:
            add("LINE_SUM_MISMATCH", "warning", "line_items", f"Line amounts sum to {s_amt}, taxable value is {taxable}")
        for n, i in enumerate(items, 1):
            if i.get("quantity") is not None and i.get("rate") is not None and i.get("amount") is not None:
                if abs(_d(i["quantity"]) * _d(i["rate"]) - _d(i["amount"])) > Decimal("0.05"):
                    add("LINE_ARITHMETIC", "warning", f"line_items[{n}]", "quantity x rate does not equal amount")

    # Duplicate detection: same supplier + normalised invoice number, or same supplier+date+total.
    def norm(x): return "".join(ch for ch in str(x or "").upper() if ch.isalnum())
    for other in existing:
        o = other["data"]["invoice"]
        if o.get("supplier_gstin") and o.get("supplier_gstin") == inv.get("supplier_gstin"):
            if norm(o.get("invoice_number")) and norm(o.get("invoice_number")) == norm(inv.get("invoice_number")):
                add("DUPLICATE", "error", "invoice_number", f"Duplicate of invoice {other['id']}")
                break
            if o.get("invoice_date") == inv.get("invoice_date") and o.get("total") == inv.get("total"):
                add("POSSIBLE_DUPLICATE", "warning", "total", f"Same supplier, date and total as {other['id']}")
                break

    for k in CRITICAL:
        if k in inv and confidence.get(k, 1.0) < settings.review_threshold:
            add("LOW_CONFIDENCE", "warning", k, f"{k} extracted with confidence {confidence.get(k):.2f}")
    return issues


def status_for(issues: list[dict]) -> str:
    return "needs_review" if issues else "ready"
