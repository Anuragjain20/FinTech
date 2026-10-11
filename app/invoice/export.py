"""Export approved invoices: CSV and Tally purchase-voucher XML."""
import functools
from xml.etree import ElementTree as ET

from ..uploads import safe_csv

CSV_COLUMNS = ["id", "invoice_number", "invoice_date", "supplier_name", "supplier_gstin", "buyer_gstin",
               "taxable_value", "cgst", "sgst", "igst", "total"]


def _ledger_entry(voucher, ledger, amount, debit):
    e = ET.SubElement(voucher, "ALLLEDGERENTRIES.LIST")
    ET.SubElement(e, "LEDGERNAME").text = ledger
    ET.SubElement(e, "ISDEEMEDPOSITIVE").text = "Yes" if debit else "No"
    ET.SubElement(e, "AMOUNT").text = f"{-amount if debit else amount:.2f}"


def to_csv(rows: list[dict]) -> str:
    return safe_csv([{"id": r["id"], **r["data"]["invoice"]} for r in rows], CSV_COLUMNS)


def to_tally_xml(rows: list[dict], company: str = "My Company", purchase_ledger: str = "Purchase",
                 cgst_ledger: str = "Input CGST", sgst_ledger: str = "Input SGST", igst_ledger: str = "Input IGST") -> str:
    """Tally Prime import XML. Ledgers named here must already exist in the company."""
    env = ET.Element("ENVELOPE")
    hdr = ET.SubElement(env, "HEADER")
    ET.SubElement(hdr, "TALLYREQUEST").text = "Import Data"
    body = ET.SubElement(env, "BODY")
    imp = ET.SubElement(body, "IMPORTDATA")
    rd = ET.SubElement(imp, "REQUESTDESC")
    ET.SubElement(rd, "REPORTNAME").text = "Vouchers"
    sv = ET.SubElement(rd, "STATICVARIABLES")
    ET.SubElement(sv, "SVCURRENTCOMPANY").text = company
    data = ET.SubElement(imp, "REQUESTDATA")

    for r in rows:
        inv = r["data"]["invoice"]
        tm = ET.SubElement(data, "TALLYMESSAGE", {"xmlns:UDF": "TallyUDF"})
        v = ET.SubElement(tm, "VOUCHER", {"VCHTYPE": "Purchase", "ACTION": "Create"})
        ET.SubElement(v, "DATE").text = (inv.get("invoice_date") or "").replace("-", "")
        ET.SubElement(v, "VOUCHERTYPENAME").text = "Purchase"
        ET.SubElement(v, "VOUCHERNUMBER").text = str(inv.get("invoice_number") or r["id"])
        ET.SubElement(v, "REFERENCE").text = str(inv.get("invoice_number") or "")
        ET.SubElement(v, "PARTYLEDGERNAME").text = inv.get("supplier_name") or ""
        ET.SubElement(v, "NARRATION").text = f"Imported from invoice {r['id']}"

        entry = functools.partial(_ledger_entry, v)
        entry(inv.get("supplier_name") or "", inv["total"], debit=False)
        entry(purchase_ledger, inv["taxable_value"], debit=True)
        for name, led in (("cgst", cgst_ledger), ("sgst", sgst_ledger), ("igst", igst_ledger)):
            if inv.get(name):
                entry(led, inv[name], debit=True)
    return ET.tostring(env, encoding="unicode")
