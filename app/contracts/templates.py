"""Clause library and contract templates (Indian-law starting points).

IMPORTANT: these are drafting aids. `lawyer_reviewed` is False until a qualified
Indian advocate has vetted a template; the API surfaces that flag to users, and
every generated document is labelled a DRAFT for legal review.
"""
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

_env = SandboxedEnvironment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)

PARTY_Q = [
    {"key": "party_a_name", "label": "First party legal name", "type": "text", "required": True},
    {"key": "party_a_address", "label": "First party registered address", "type": "text", "required": True},
    {"key": "party_b_name", "label": "Second party legal name", "type": "text", "required": True},
    {"key": "party_b_address", "label": "Second party address", "type": "text", "required": True},
    {"key": "effective_date", "label": "Effective date (YYYY-MM-DD)", "type": "date", "required": True},
    {"key": "seat_city", "label": "Arbitration seat / courts city", "type": "text", "required": True},
]

CLAUSES = {
    "parties": {"title": "Parties", "text":
        "This Agreement is entered into on {{ effective_date }} (the \"Effective Date\") between {{ party_a_name }}, having its registered office at {{ party_a_address }} (\"{{ a_label | default('First Party') }}\"), and {{ party_b_name }}, having its address at {{ party_b_address }} (\"{{ b_label | default('Second Party') }}\")."},
    "confidentiality_def": {"title": "Confidential Information", "text":
        "\"Confidential Information\" means all non-public information, in any form, disclosed {% if mutual %}by either party{% else %}by the Disclosing Party{% endif %} in connection with {{ purpose }}, excluding information that is or becomes public without breach, was already lawfully known to the recipient, is independently developed, or is lawfully received from a third party."},
    "confidentiality_obl": {"title": "Obligations of Confidentiality", "text":
        "The recipient shall hold Confidential Information in strict confidence, use it solely for {{ purpose }}, not disclose it except to personnel who need to know and are bound by equivalent obligations, and protect it with at least reasonable care. Compelled disclosure under law is permitted after prompt written notice to the discloser where legally allowed."},
    "term_fixed": {"title": "Term", "text":
        "This Agreement commences on the Effective Date and continues for {{ term_months }} months unless terminated earlier in accordance with this Agreement. It does not renew automatically; any renewal must be agreed in writing."},
    "survival_conf": {"title": "Survival", "text":
        "The confidentiality obligations survive for {{ survival_years }} years after termination or expiry of this Agreement; obligations relating to trade secrets survive for as long as the information remains a trade secret."},
    "return_info": {"title": "Return of Information", "text":
        "On written request or termination, the recipient shall promptly return or destroy all Confidential Information and confirm in writing that it has done so, save for copies required to be retained by law."},
    "services": {"title": "Services", "text":
        "{{ party_b_name }} (the \"Service Provider\") shall provide the following services to {{ party_a_name }} (the \"Client\"): {{ services_description }}, in accordance with the specifications and timelines agreed in writing."},
    "fees_gst": {"title": "Fees, Taxes and Payment", "text":
        "The Client shall pay the Service Provider INR {{ fees_amount }} {{ fees_basis }}, exclusive of GST. The Service Provider shall issue a valid GST tax invoice, and GST shall be payable in addition at the applicable rate. Undisputed invoices shall be paid within {{ payment_days }} days of receipt. The Client may deduct tax at source (TDS) as required by the Income-tax Act, 1961 and shall provide the corresponding TDS certificate."},
    "ip_work_product": {"title": "Intellectual Property", "text":
        "Upon receipt of full payment, all rights in the deliverables created specifically for the Client under this Agreement shall vest in the Client. The Service Provider retains rights in its pre-existing materials and tools, and grants the Client a non-exclusive, perpetual licence to use them as embedded in the deliverables."},
    "liability_cap": {"title": "Limitation of Liability", "text":
        "Neither party's aggregate liability under this Agreement shall exceed {{ liability_cap_text }}, except for liability arising from breach of confidentiality, fraud, wilful misconduct, or any liability that cannot be limited by law. Neither party is liable for indirect or consequential loss."},
    "termination_notice": {"title": "Termination", "text":
        "Either party may terminate this Agreement by giving {{ notice_days }} days' written notice. Either party may terminate immediately by written notice if the other commits a material breach that remains uncured {{ cure_days | default(30) }} days after written notice. Accrued rights and payment obligations survive termination."},
    "indemnity_mutual": {"title": "Indemnity", "text":
        "Each party shall indemnify the other against third-party claims, and resulting losses and reasonable costs, arising from its breach of this Agreement, its negligence or wilful misconduct, or its infringement of third-party intellectual property rights, subject to the limitation of liability above."},
    "force_majeure": {"title": "Force Majeure", "text":
        "Neither party is liable for delay or failure caused by events beyond its reasonable control, including natural disaster, epidemic, war, or government action, provided it notifies the other promptly and uses reasonable efforts to resume performance. Payment obligations for work already performed are not excused."},
    "governing_law": {"title": "Governing Law and Dispute Resolution", "text":
        "This Agreement is governed by the laws of India. Disputes shall first be referred to good-faith negotiation between senior representatives for {{ negotiation_days | default(30) }} days, failing which they shall be finally resolved by arbitration under the Arbitration and Conciliation Act, 1996 before a sole arbitrator appointed by mutual consent. The seat and venue of arbitration shall be {{ seat_city }}, the language shall be English, and the courts at {{ seat_city }} shall have exclusive jurisdiction over matters not subject to arbitration and for interim relief."},
    "stamp_duty": {"title": "Stamp Duty", "text":
        "This Agreement shall be duly stamped as required under the stamp law applicable in the State where it is executed. Stamp duty shall be borne by {{ stamp_duty_borne_by | default(party_a_name) }}."},
    "entire_agreement": {"title": "Entire Agreement; Amendment; Notices", "text":
        "This Agreement is the entire agreement between the parties on its subject matter and supersedes prior understandings. Amendments must be in writing and signed by both parties. Notices must be in writing and delivered to the addresses above (or as updated by notice)."},
    "supply_terms": {"title": "Supply of Goods", "text":
        "{{ party_b_name }} (the \"Supplier\") shall supply {{ goods_description }} to {{ party_a_name }} (the \"Buyer\") per purchase orders issued under this Agreement. Goods shall conform to agreed specifications, be free from defects, and be delivered to the location specified in each purchase order. Title and risk pass on delivery and acceptance."},
    "warranty_goods": {"title": "Warranty and Rejection", "text":
        "The Supplier warrants the goods for {{ warranty_months }} months from delivery. The Buyer may reject non-conforming goods within {{ inspection_days }} days of delivery, and the Supplier shall replace or refund them at its cost."},
    "msme": {"title": "MSME Payment Timelines", "text":
        "If the Supplier is a micro or small enterprise registered under the MSMED Act, 2006, payment shall be made within the period required by Section 15 of that Act (not exceeding 45 days from the day of acceptance), and the Supplier shall provide its Udyam registration details."},
    "employment_role": {"title": "Position and Duties", "text":
        "{{ party_b_name }} (the \"Employee\") is appointed as {{ job_title }} with {{ party_a_name }} (the \"Employer\") from the Effective Date, reporting to {{ reporting_to }}, and shall perform the duties assigned in good faith and in line with Employer policies."},
    "employment_comp": {"title": "Compensation", "text":
        "The Employee shall receive an annual cost-to-company of INR {{ ctc }}, paid monthly, subject to deduction of tax at source and statutory contributions (including provident fund and ESI where applicable). Salary is reviewed periodically at the Employer's discretion."},
    "probation_notice": {"title": "Probation and Notice Period", "text":
        "The Employee is on probation for {{ probation_months }} months. After confirmation, either party may terminate employment by giving {{ notice_days }} days' written notice or pay in lieu thereof. The Employer may terminate without notice for serious misconduct after following a fair process."},
    "emp_confidentiality_ip": {"title": "Confidentiality and Work Product", "text":
        "The Employee shall keep the Employer's confidential information secret during and after employment and shall not use it except for the Employer's business. All work product created in the course of employment belongs to the Employer, and the Employee shall execute any documents needed to confirm this."},
    "non_solicit": {"title": "Non-Solicitation", "text":
        "For {{ non_solicit_months }} months after employment ends, the Employee shall not solicit the Employer's employees or customers by using the Employer's confidential information. Nothing in this Agreement restrains the Employee from engaging in any lawful profession, trade or business after employment ends."},
    "posh": {"title": "Workplace Policies", "text":
        "The Employee shall comply with the Employer's policies, including the policy on prevention of sexual harassment at the workplace under the Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, 2013, and the code of conduct."},
}

_PURPOSE = {"key": "purpose", "label": "Purpose of disclosure", "type": "text", "required": True}

TEMPLATES = {
    "nda": {
        "name": "Non-Disclosure Agreement", "description": "One-way or mutual NDA under Indian law.",
        "lawyer_reviewed": False,
        "questions": PARTY_Q + [_PURPOSE,
            {"key": "mutual", "label": "Mutual NDA?", "type": "bool", "required": False, "default": True},
            {"key": "term_months", "label": "Term (months)", "type": "int", "required": True, "default": 24},
            {"key": "survival_years", "label": "Confidentiality survival (years)", "type": "int", "required": True, "default": 3}],
        "clauses": ["parties", "confidentiality_def", "confidentiality_obl", "return_info", "term_fixed", "survival_conf", "governing_law", "stamp_duty", "entire_agreement"],
        "labels": {"a_label": "First Party", "b_label": "Second Party"},
    },
    "service_agreement": {
        "name": "Service Agreement", "description": "Consulting / professional services with GST and TDS terms.",
        "lawyer_reviewed": False,
        "questions": PARTY_Q + [
            {"key": "services_description", "label": "Description of services", "type": "text", "required": True},
            {"key": "fees_amount", "label": "Fees (INR)", "type": "text", "required": True},
            {"key": "fees_basis", "label": "Fee basis (e.g. per month, fixed)", "type": "text", "required": True},
            {"key": "payment_days", "label": "Payment days", "type": "int", "required": True, "default": 30},
            {"key": "liability_cap_text", "label": "Liability cap (e.g. the fees paid in the 12 months preceding the claim)", "type": "text", "required": True},
            {"key": "notice_days", "label": "Termination notice (days)", "type": "int", "required": True, "default": 30}],
        "clauses": ["parties", "services", "fees_gst", "ip_work_product", "liability_cap", "indemnity_mutual", "force_majeure", "termination_notice", "governing_law", "stamp_duty", "entire_agreement"],
        "labels": {"a_label": "Client", "b_label": "Service Provider"},
    },
    "vendor_agreement": {
        "name": "Vendor / Supply Agreement", "description": "Goods supply with warranty, rejection and MSME payment terms.",
        "lawyer_reviewed": False,
        "questions": PARTY_Q + [
            {"key": "goods_description", "label": "Goods supplied", "type": "text", "required": True},
            {"key": "fees_amount", "label": "Price (INR)", "type": "text", "required": True},
            {"key": "fees_basis", "label": "Price basis (e.g. per unit)", "type": "text", "required": True},
            {"key": "payment_days", "label": "Payment days", "type": "int", "required": True, "default": 30},
            {"key": "warranty_months", "label": "Warranty (months)", "type": "int", "required": True, "default": 12},
            {"key": "inspection_days", "label": "Inspection days", "type": "int", "required": True, "default": 7},
            {"key": "liability_cap_text", "label": "Liability cap", "type": "text", "required": True},
            {"key": "notice_days", "label": "Termination notice (days)", "type": "int", "required": True, "default": 30}],
        "clauses": ["parties", "supply_terms", "fees_gst", "warranty_goods", "msme", "liability_cap", "indemnity_mutual", "force_majeure", "termination_notice", "governing_law", "stamp_duty", "entire_agreement"],
        "labels": {"a_label": "Buyer", "b_label": "Supplier"},
    },
    "employment": {
        "name": "Employment Agreement", "description": "Employment letter terms. Post-employment non-compete is intentionally omitted (see Section 27, Indian Contract Act, 1872).",
        "lawyer_reviewed": False,
        "questions": PARTY_Q + [
            {"key": "job_title", "label": "Job title", "type": "text", "required": True},
            {"key": "reporting_to", "label": "Reports to", "type": "text", "required": True},
            {"key": "ctc", "label": "Annual CTC (INR)", "type": "text", "required": True},
            {"key": "probation_months", "label": "Probation (months)", "type": "int", "required": True, "default": 6},
            {"key": "notice_days", "label": "Notice period (days)", "type": "int", "required": True, "default": 60},
            {"key": "non_solicit_months", "label": "Non-solicit (months)", "type": "int", "required": True, "default": 12}],
        "clauses": ["parties", "employment_role", "employment_comp", "probation_notice", "emp_confidentiality_ip", "non_solicit", "posh", "governing_law", "stamp_duty", "entire_agreement"],
        "labels": {"a_label": "Employer", "b_label": "Employee"},
    },
}


class TemplateError(ValueError):
    pass


def _coerce(q: dict, v):
    if q["type"] == "int":
        return int(v)
    if q["type"] == "bool":
        return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")
    return str(v)


def render(template_id: str, answers: dict) -> dict:
    t = TEMPLATES.get(template_id)
    if not t:
        raise TemplateError(f"Unknown template '{template_id}'")
    ctx, missing = dict(t["labels"]), []
    for q in t["questions"]:
        v = answers.get(q["key"], q.get("default"))
        if v in (None, "") and q.get("required"):
            missing.append(q["key"])
        elif v is not None:
            try:
                ctx[q["key"]] = _coerce(q, v)
            except (TypeError, ValueError):
                raise TemplateError(f"Invalid value for {q['key']}")
    if missing:
        raise TemplateError(f"Missing required answers: {', '.join(missing)}")
    ctx.setdefault("mutual", False)
    clauses = []
    for n, cid in enumerate(t["clauses"], 1):
        c = CLAUSES[cid]
        clauses.append({"id": cid, "number": n, "title": c["title"], "text": _env.from_string(c["text"]).render(**ctx)})
    return {"title": t["name"], "clauses": clauses, "lawyer_reviewed": t["lawyer_reviewed"]}


def to_text(doc: dict) -> str:
    body = "\n\n".join(f"{c['number']}. {c['title']}\n{c['text']}" for c in doc["clauses"])
    return f"{doc['title'].upper()}\n(DRAFT - for review by a qualified legal professional)\n\n{body}\n"
