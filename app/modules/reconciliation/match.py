"""Reconciliation matching: bank statement vs books.

Passes (highest trust first), each producing one-to-one pairs:
  1. reference  - normalised reference/UTR/cheque no. equal AND amount equal   (conf 0.99, auto-matched)
  2. exact      - amount equal, dates within `date_tolerance_days`, unique candidate (conf 0.92, auto-matched)
  3. fuzzy      - amount equal, dates within a wider window, ranked by description
                  similarity (conf 0.5-0.85, *suggested* - needs a human to confirm)
A suggestion is never an accounting entry; callers must confirm it.
"""
import re
from datetime import date

from rapidfuzz import fuzz

AUTO_THRESHOLD = 0.9

BANK_ONLY_HINTS = [
    ("bank_charge", r"\b(charges?|fee|gst on|sms|amc|penalty|service chg|min bal)"),
    ("interest", r"\binterest|int\.? ?pd|int cr"),
    ("bounce", r"\b(return|bounce|dishonou?r|chq ret|insufficient)"),
]


def _norm_ref(r: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", r.upper()).lstrip("0")


def _days(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _cents(x: float) -> int:
    return round(x * 100)


def run_matching(bank: list[dict], book: list[dict], date_tolerance_days: int = 3,
                 fuzzy_window_days: int = 10, amount_tolerance: float = 0.0,
                 rejected: set[tuple[str, str]] | None = None) -> list[dict]:
    rejected = rejected or set()
    used_bank: set[str] = set()
    used_book: set[str] = set()
    matches: list[dict] = []
    tol = _cents(amount_tolerance)

    def amt_ok(a, b): return abs(_cents(a["amount"]) - _cents(b["amount"])) <= tol

    def take(bk, bo, rule, conf):
        used_bank.add(bk["id"]); used_book.add(bo["id"])
        matches.append({"bank_id": bk["id"], "book_id": bo["id"], "rule": rule,
                        "confidence": round(conf, 2),
                        "status": "matched" if conf >= AUTO_THRESHOLD else "suggested"})

    def free(bk, bo): return bk["id"] not in used_bank and bo["id"] not in used_book and (bk["id"], bo["id"]) not in rejected

    # Pass 1: reference + amount. Pair in date-proximity order so repeated refs resolve sensibly.
    for bk in bank:
        r = _norm_ref(bk["reference"])
        if len(re.sub(r"[^A-Z0-9]", "", bk["reference"].upper())) < 4 or not r:
            continue  # too short to be a trustworthy reference
        cands = [bo for bo in book if free(bk, bo) and _norm_ref(bo["reference"]) == r and amt_ok(bk, bo)]
        if cands:
            take(bk, min(cands, key=lambda bo: _days(bk["date"], bo["date"])), "reference", 0.99)

    # Pass 2: amount + date window, only when unambiguous in both directions.
    for bk in bank:
        if bk["id"] in used_bank:
            continue
        cands = [bo for bo in book if free(bk, bo) and amt_ok(bk, bo) and _days(bk["date"], bo["date"]) <= date_tolerance_days]
        if len(cands) == 1:
            bo = cands[0]
            reverse = [x for x in bank if x["id"] not in used_bank and amt_ok(x, bo) and _days(x["date"], bo["date"]) <= date_tolerance_days]
            if len(reverse) == 1:
                take(bk, bo, "amount+date", 0.92)

    # Pass 3: fuzzy suggestions, best similarity first, globally ranked.
    pairs = []
    for bk in bank:
        if bk["id"] in used_bank:
            continue
        for bo in book:
            if free(bk, bo) and amt_ok(bk, bo) and _days(bk["date"], bo["date"]) <= fuzzy_window_days:
                sim = fuzz.token_set_ratio(bk["description"], bo["description"]) / 100
                closeness = 1 - _days(bk["date"], bo["date"]) / (fuzzy_window_days + 1)
                pairs.append((0.5 + 0.25 * sim + 0.1 * closeness, bk, bo))
    for conf, bk, bo in sorted(pairs, key=lambda t: -t[0]):
        if free(bk, bo):
            take(bk, bo, "amount+fuzzy", min(conf, 0.85))
    return matches


def classify_unmatched(bank_un: list[dict], book_un: list[dict], all_bank: list[dict], all_book: list[dict]) -> dict:
    """Attach likely explanations to unmatched items (heuristic, for the reviewer)."""
    last_bank = max((t["date"] for t in all_bank), default=None)
    out_bank, out_book = [], []
    for t in bank_un:
        cat, why = "unexplained", "Appears on bank statement but not in books"
        for name, pat in BANK_ONLY_HINTS:
            if t["amount"] < 0 and name != "interest" or t["amount"] > 0 and name == "interest":
                if re.search(pat, t["description"], re.I):
                    cat, why = name, f"Looks like a {name.replace('_', ' ')}; record it in the books"
                    break
        out_bank.append({**t, "category": cat, "explanation": why})
    seen = {}
    for t in book_un:
        cat, why = "unexplained", "Recorded in books but not on bank statement"
        if last_bank and _days(t["date"], last_bank) <= 7:
            cat = "timing_difference"
            why = "Recent entry - likely a cheque/transfer not yet cleared by the bank" if t["amount"] < 0 else "Recent entry - likely a deposit in transit"
        out_book.append({**t, "category": cat, "explanation": why})
    for lst in (out_bank, out_book):
        seen = {}
        for t in lst:
            key = (t["date"], t["amount"], t["description"].lower())
            if key in seen:
                t["category"], t["explanation"] = "possible_duplicate", f"Same date/amount/description as {seen[key]}"
            else:
                seen[key] = t["id"]
    return {"bank": out_bank, "book": out_book}


def summarize(bank, book, matches, bank_closing: float | None, book_closing: float | None) -> dict:
    mb = {m["bank_id"] for m in matches}
    mo = {m["book_id"] for m in matches}
    bank_un = [t for t in bank if t["id"] not in mb]
    book_un = [t for t in book if t["id"] not in mo]
    bank_only = round(sum(t["amount"] for t in bank_un), 2)
    book_only = round(sum(t["amount"] for t in book_un), 2)
    s = {
        "bank_transactions": len(bank), "book_transactions": len(book),
        "matched": sum(1 for m in matches if m["status"] in ("matched", "confirmed")),
        "suggested_pending": sum(1 for m in matches if m["status"] == "suggested"),
        "unmatched_bank": len(bank_un), "unmatched_book": len(book_un),
        "bank_only_net": bank_only, "book_only_net": book_only,
    }
    if bank_closing is not None and book_closing is not None:
        # bank = book + (items only the bank has) - (items only the books have)
        expected_bank = round(book_closing + bank_only - book_only, 2)
        s.update({
            "balance_per_bank": bank_closing, "balance_per_books": book_closing,
            "adjusted_balance_per_books": round(book_closing + bank_only, 2),
            "adjusted_balance_per_bank": round(bank_closing + book_only, 2),
            "unexplained_difference": round(bank_closing - expected_bank, 2),
        })
        s["reconciled"] = s["unexplained_difference"] == 0 and s["suggested_pending"] == 0
    return s
