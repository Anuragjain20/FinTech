from app.modules.contracts import compare, risk, templates

NDA = {"party_a_name": "Acme Pvt Ltd", "party_a_address": "Mumbai", "party_b_name": "Beta LLP", "party_b_address": "Pune",
       "effective_date": "2024-04-01", "seat_city": "Mumbai", "purpose": "evaluating a joint venture"}


def test_templates_render_all():
    base = {**NDA, "services_description": "dev", "fees_amount": "1,00,000", "fees_basis": "per month", "payment_days": 30,
            "liability_cap_text": "the fees paid in the preceding 12 months", "notice_days": 30, "goods_description": "valves",
            "warranty_months": 12, "inspection_days": 7, "job_title": "Engineer", "reporting_to": "CTO", "ctc": "12,00,000",
            "probation_months": 6, "non_solicit_months": 12, "term_months": 24, "survival_years": 3}
    for tid in templates.TEMPLATES:
        doc = templates.render(tid, base)
        text = templates.to_text(doc)
        assert "Acme Pvt Ltd" in text and "{{" not in text and "DRAFT" in text
        assert not templates.TEMPLATES[tid]["lawyer_reviewed"]


def test_employment_has_no_non_compete():
    text = templates.to_text(templates.render("employment", {**NDA, "job_title": "x", "reporting_to": "y", "ctc": "1", "notice_days": 30}))
    assert "non-compete" not in text.lower()
    assert risk.review(text)["high_risk_count"] == 0


def test_missing_answers_rejected():
    try:
        templates.render("nda", {"party_a_name": "x"})
    except templates.TemplateError as e:
        assert "Missing required" in str(e)
    else:
        raise AssertionError


def test_generated_ndas_pass_own_review():
    r = risk.review(templates.to_text(templates.render("nda", NDA)))
    assert r["high_risk_count"] == 0
    assert "governing law" not in {m["clause"] for m in r["missing_clauses"]}


def test_risk_detection():
    bad = ("The Supplier shall have unlimited liability. This Agreement shall automatically renew each year. "
           "The Employee shall be bound by a non-compete after termination. Payment within 90 days. "
           "Governed by the laws of England.")
    r = risk.review(bad)
    codes = {f["code"] for f in r["findings"]}
    assert {"UNLIMITED_LIABILITY", "AUTO_RENEWAL", "POST_EMPLOYMENT_NON_COMPETE", "LONG_PAYMENT_TERM", "FOREIGN_JURISDICTION"} <= codes
    assert r["findings"][0]["severity"] == "high"
    assert {m["clause"] for m in r["missing_clauses"]} >= {"force majeure", "confidentiality"}


def test_compare():
    ch = compare.compare("A\n\nB\n\nC", "A\n\nB2\n\nC\n\nD")
    assert [c["op"] for c in ch] == ["changed", "added"]


def test_workflow_api(client, admin, role_headers):
    op, appr = role_headers("operator"), role_headers("approver")
    assert len(client.get("/contracts/templates", headers=op).json()) == 4
    r = client.post("/contracts", json={"template_id": "nda", "answers": NDA}, headers=op)
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["lawyer_reviewed"] is False
    assert client.post("/contracts", json={"template_id": "nda", "answers": {}}, headers=op).status_code == 422
    # edit introduces a high risk clause
    text = r.json()["text"] + "\n\n99. Liability\nThe Supplier shall have unlimited liability."
    assert client.put(f"/contracts/{cid}", json={"text": text}, headers=op).json()["version"] == 2
    diff = client.get(f"/contracts/{cid}/compare?v1=1&v2=2", headers=op).json()
    assert diff["changes"][0]["op"] == "added"
    assert client.post(f"/contracts/{cid}/approve", json={}, headers=appr).status_code == 409  # not in review yet
    assert client.post(f"/contracts/{cid}/submit", headers=op).json()["status"] == "in_review"
    assert client.put(f"/contracts/{cid}", json={"text": "x"}, headers=op).status_code == 409
    assert client.post(f"/contracts/{cid}/approve", json={}, headers=op).status_code == 403
    assert client.post(f"/contracts/{cid}/approve", json={}, headers=appr).status_code == 409  # high risk
    assert client.post(f"/contracts/{cid}/approve", json={"acknowledge_risks": True}, headers=appr).json()["status"] == "approved"
    d = client.get(f"/contracts/{cid}/docx", headers=op)
    assert d.status_code == 200 and d.content[:2] == b"PK"


def test_review_endpoint_and_isolation(client, admin, other_admin):
    assert client.post("/contracts/review", json={"text": "automatically renew"}, headers=admin).json()["findings"]
    cid = client.post("/contracts", json={"template_id": "nda", "answers": NDA}, headers=admin).json()["id"]
    assert client.get(f"/contracts/{cid}", headers=other_admin).status_code == 404
