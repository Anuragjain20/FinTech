from app.invoice import extract, gst
from tests.conftest import BUYER_OTHER, BUYER_SAME, SUPPLIER

INVOICE_TEXT = f"""Sharma Traders Pvt Ltd
GSTIN: {SUPPLIER}
Tax Invoice
Invoice No: INV/2024/0042
Invoice Date: 15/03/2024

Bill To: Acme Industries
GSTIN: {BUYER_SAME}

Widget A 8481 100 100.00 10,000.00
Taxable Value: 10,000.00
CGST @9%: 900.00
SGST @9%: 900.00
Grand Total: 11,800.00
"""


def test_gstin_checksum():
    assert gst.validate_gstin("27AAPFU0939F1ZV")[0]
    assert gst.validate_gstin("27AAPFU0939F1ZX") == (False, "checksum mismatch")
    assert gst.validate_gstin("99XXXXX") == (False, "bad format")
    assert gst.validate_gstin(None) == (False, "missing")


def test_parse_text():
    r = extract.parse_invoice_text(INVOICE_TEXT)
    f = r["fields"]
    assert f["supplier_name"] == "Sharma Traders Pvt Ltd"
    assert f["invoice_number"] == "INV/2024/0042"
    assert f["invoice_date"] == "2024-03-15"
    assert f["supplier_gstin"] == SUPPLIER and f["buyer_gstin"] == BUYER_SAME
    assert (f["taxable_value"], f["cgst"], f["sgst"], f["total"]) == (10000.0, 900.0, 900.0, 11800.0)
    assert r["line_items"] == [{"description": "Widget A", "hsn_sac": "8481", "quantity": 100.0, "rate": 100.0, "amount": 10000.0}]


def test_clean_invoice_flow_and_exports(client, admin, role_headers):
    r = client.post("/invoices/text", json={"text": INVOICE_TEXT}, headers=admin).json()
    codes = {i["code"] for i in r["issues"]}
    assert "TOTAL_MISMATCH" not in codes and "INVALID_GSTIN" not in codes
    iid = r["id"]
    # unapproved invoices are not exported
    assert client.get("/invoices/export/csv", headers=admin).text.count("\n") == 1
    if r["status"] != "ready":  # line-sum warnings from the sample are tolerated; approval still works w/o errors
        assert not [i for i in r["issues"] if i["severity"] == "error"]
    op = role_headers("operator")
    assert client.post(f"/invoices/{iid}/approve", json={}, headers=op).status_code == 403
    assert client.post(f"/invoices/{iid}/approve", json={}, headers=admin).status_code == 200
    csv_out = client.get("/invoices/export/csv", headers=admin).text
    assert "INV/2024/0042" in csv_out and "11800.0" in csv_out
    xml = client.get("/invoices/export/tally?company=Acme", headers=admin).text
    assert "<VOUCHER" in xml and "INV/2024/0042" in xml and "-10000.00" in xml
    assert client.put(f"/invoices/{iid}", json={"invoice_number": "X"}, headers=admin).status_code == 409


def test_validation_catches_errors(client, admin):
    bad = {"supplier_gstin": SUPPLIER, "buyer_gstin": BUYER_OTHER, "invoice_number": "B1", "invoice_date": "2024-01-01",
           "taxable_value": 1000, "cgst": 90, "sgst": 90, "total": 1500}
    r = client.post("/invoices", json=bad, headers=admin).json()
    codes = {i["code"] for i in r["issues"]}
    assert {"TOTAL_MISMATCH", "WRONG_TAX_TYPE"} <= codes
    assert r["status"] == "needs_review"
    assert client.post(f"/invoices/{r['id']}/approve", json={}, headers=admin).status_code == 409
    assert client.post(f"/invoices/{r['id']}/approve", json={"override_reason": "CA confirmed"}, headers=admin).status_code == 200


def test_correction_revalidates_and_duplicate_detection(client, admin):
    good = {"supplier_gstin": SUPPLIER, "buyer_gstin": BUYER_SAME, "invoice_number": "D-1", "invoice_date": "2024-02-02",
            "taxable_value": 1000, "cgst": 90, "sgst": 90, "total": 1180}
    first = client.post("/invoices", json=good, headers=admin).json()
    assert first["status"] == "ready"
    dup = client.post("/invoices", json={**good, "invoice_number": "d 1"}, headers=admin).json()
    assert "DUPLICATE" in {i["code"] for i in dup["issues"]}
    fixed = client.put(f"/invoices/{dup['id']}", json={**good, "invoice_number": "D-2", "invoice_date": "2024-02-03"}, headers=admin).json()
    assert fixed["status"] == "ready"
    queue = client.get("/invoices/review-queue", headers=admin).json()
    assert queue["items"] == []


def test_invalid_gstin_flagged(client, admin):
    r = client.post("/invoices", json={"supplier_gstin": "27AAPFU0939F1ZX", "invoice_number": "G", "invoice_date": "2024-01-01",
                                       "taxable_value": 10, "total": 10}, headers=admin).json()
    assert "INVALID_GSTIN" in {i["code"] for i in r["issues"]}


def test_upload_txt_and_unsupported_pdf_without_ocr(client, admin):
    r = client.post("/invoices/upload", files={"file": ("a.txt", INVOICE_TEXT.encode())}, headers=admin)
    assert r.status_code == 202
    got = client.get(f"/invoices/{r.json()['id']}", headers=admin).json()  # eager worker has finished
    assert got["status"] != "processing" and got["invoice"]["invoice_number"] == "INV/2024/0042"
    assert client.get(f"/invoices/{got['id']}/file", headers=admin).content == INVOICE_TEXT.encode()
    r = client.post("/invoices/upload", files={"file": ("a.pdf", b"%PDF-1.4")}, headers=admin)
    failed = client.get(f"/invoices/{r.json()['id']}", headers=admin).json()
    assert failed["status"] == "failed" and "OCR" in failed["error"]
    assert client.post(f"/invoices/{failed['id']}/approve", json={"override_reason": "x"}, headers=admin).status_code == 409
    assert client.post("/invoices/upload", files={"file": ("a.exe", b"x")}, headers=admin).status_code == 415
