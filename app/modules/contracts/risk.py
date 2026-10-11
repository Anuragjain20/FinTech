"""Rule-based contract review: missing clauses and risky language.

Deterministic first line of defence. Findings cite the matched text so a human can
verify them. An LLM/RAG layer (grounded in statute text) can be added on top, but
must never replace these checks or present output as legal advice.
"""
import re

REQUIRED = {
    "governing law": r"governed by the laws? of",
    "dispute resolution": r"arbitrat|jurisdiction of the courts|courts at",
    "termination": r"terminat",
    "confidentiality": r"confidential",
    "limitation of liability": r"(limit(ation)? of liability|liability .{0,60}shall not exceed|aggregate liability)",
    "force majeure": r"force majeure|beyond (its|their) reasonable control",
    "stamp duty": r"stamp",
}

RISKS = [
    ("UNLIMITED_LIABILITY", "high", r"unlimited liability|liability .{0,40}(shall )?not be limited|no limit(ation)? (on|of) liability",
     "Unlimited liability exposes you to uncapped claims.", "Add a liability cap (commonly fees paid in the prior 12 months) with carve-outs for fraud/confidentiality."),
    ("AUTO_RENEWAL", "medium", r"(automatically|auto)[- ]renew|shall be deemed (to be )?renewed",
     "Auto-renewal can lock you in unnoticed.", "Require written renewal, or a notice window before renewal."),
    ("UNILATERAL_TERMINATION", "medium", r"(sole|absolute) discretion[^.]{0,80}terminat|terminat[^.]{0,80}(sole|absolute) discretion|terminate (this agreement )?at any time without (cause|notice)",
     "Termination right appears one-sided.", "Make termination rights mutual with reasonable notice."),
    ("POST_EMPLOYMENT_NON_COMPETE", "high", r"(non[- ]?compete|shall not (engage|work|be employed)[^.]{0,80}(after|following) (termination|cessation|the end))",
     "Post-termination non-competes are generally void under Section 27 of the Indian Contract Act, 1872.", "Replace with confidentiality and non-solicitation obligations; take legal advice."),
    ("PERPETUAL_TERM", "medium", r"in perpetuity|perpetual(ly)? (term|obligation)|irrevocabl[ey]",
     "Perpetual/irrevocable obligations are hard to exit.", "Limit duration, or tie to a defined event."),
    ("BROAD_INDEMNITY", "high", r"indemnif[^.]{0,120}(any and all|all) (claims|losses|damages)",
     "Broad 'any and all losses' indemnity is open-ended.", "Limit to third-party claims from a defined breach, subject to the liability cap."),
    ("PENALTY_CLAUSE", "medium", r"\bpenalt(y|ies)\b",
     "Under Section 74 of the Indian Contract Act, courts award only reasonable compensation, not a penalty.", "Frame as genuine pre-estimate of loss (liquidated damages)."),
    ("FOREIGN_JURISDICTION", "medium", r"(courts?|laws?) of (england|singapore|new york|delaware|california|united states|usa|uk)\b",
     "Foreign law/forum raises enforcement cost for an Indian SMB.", "Prefer Indian law and a domestic arbitration seat unless a counterparty requires otherwise."),
    ("IP_ASSIGNMENT_NO_PAYMENT", "low", r"all (intellectual property|rights)[^.]{0,80}(vest|belong)[^.]{0,60}(immediately|from creation)",
     "IP vests before payment is secured.", "Tie IP transfer to full payment."),
]


def _excerpt(text: str, m: re.Match, width: int = 80) -> str:
    s, e = max(0, m.start() - width), min(len(text), m.end() + width)
    return re.sub(r"\s+", " ", text[s:e]).strip()


def review(text: str) -> dict:
    findings = []
    for code, sev, pat, msg, fix in RISKS:
        m = re.search(pat, text, re.I)
        if m:
            findings.append({"code": code, "severity": sev, "message": msg, "suggestion": fix, "excerpt": _excerpt(text, m)})

    pay = re.search(r"within\s+(\d{2,3})\s+days", text, re.I)
    if pay and int(pay.group(1)) > 60:
        findings.append({"code": "LONG_PAYMENT_TERM", "severity": "medium",
                         "message": f"Payment term of {pay.group(1)} days. Micro/small suppliers must be paid within 45 days (MSMED Act, s.15).",
                         "suggestion": "Shorten payment terms or confirm supplier is not MSME.", "excerpt": _excerpt(text, pay)})
    missing = [{"clause": name, "message": f"No '{name}' clause detected"} for name, pat in REQUIRED.items() if not re.search(pat, text, re.I)]
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: order[f["severity"]])
    return {"findings": findings, "missing_clauses": missing,
            "high_risk_count": sum(1 for f in findings if f["severity"] == "high"),
            "disclaimer": "Automated screening only; not legal advice. Have a qualified lawyer review before signing."}
