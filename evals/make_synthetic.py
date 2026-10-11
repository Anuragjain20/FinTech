"""Generate a labelled synthetic invoice set in several layouts (incl. OCR-style stacked tables and GSTIN OCR errors).

    python -m evals.make_synthetic --n 60 --out evals/data/invoices_synthetic.jsonl

Synthetic data is only a smoke test / regression guard. Measure real accuracy on YOUR labelled invoices, using the same
JSONL schema:  {"id", "text", "expected": {supplier_gstin, buyer_gstin, invoice_number, invoice_date, taxable_value, cgst, sgst, igst, total, ...}}
"""
import argparse
import json
import random
from datetime import date, timedelta

from app.modules.invoices.gst import checksum_char

SUPPLIERS = ["Sharma Traders Pvt Ltd", "Kaveri Industrial Supplies", "Om Sai Packaging LLP", "Bright Logistics India Pvt Ltd", "Patel & Sons Hardware"]
BUYERS = ["Acme Industries Ltd", "Zenith Components Pvt Ltd", "Lotus Retail Pvt Ltd"]
STATES = ["27", "29", "07", "33", "24", "19"]
PANS = ["AAPFU0939F", "AABCT1332L", "AAACS8577K", "BBJPK4521M", "AAHCP2188Q", "CCDPS7712R"]


def gstin(state: str, pan: str) -> str:
    base = f"{state}{pan}1Z"
    return base + checksum_char(base)


def inr(x: float, indian: bool) -> str:
    s = f"{x:.2f}"
    whole, frac = s.split(".")
    if indian and len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head: parts.insert(0, head)
        whole = ",".join(parts + [tail])
    else:
        whole = f"{int(whole):,}"
    return f"{whole}.{frac}"


def make(i: int, rng: random.Random) -> dict:
    layout = rng.choice("ABCDE")
    s_state, b_state = rng.choice(STATES), rng.choice(STATES)
    if layout == "E":
        b_state = s_state if s_state != "27" else "29"
    inter = s_state != b_state
    sg, bg = gstin(s_state, rng.choice(PANS)), gstin(b_state, rng.choice(PANS))
    taxable = round(rng.uniform(2000, 900000), 2)
    rate = rng.choice([5, 12, 18, 28])
    tax = round(taxable * rate / 100, 2)
    cgst = sgst = None if inter else round(tax / 2, 2)
    igst = tax if inter else None
    total = round(taxable + (igst if inter else cgst * 2), 2)
    d = date(2024, 4, 1) + timedelta(days=rng.randint(0, 330))
    no = rng.choice([f"INV/24-25/{i:04d}", f"{rng.randint(100,999)}/{i}", f"TI-{i:05d}", f"A{rng.randint(1000,9999)}"])
    name, buyer = rng.choice(SUPPLIERS), rng.choice(BUYERS)
    indian = rng.random() < 0.6
    f = lambda x: inr(x, indian)
    shown_sg = sg.replace("0", "O", 1) if (rng.random() < 0.15 and "0" in sg) else sg  # OCR confusion in the *printed* text
    qty = rng.randint(1, 500)
    hsn = rng.choice(["8481", "7318", "39239", "4819"])

    if layout in "AE":
        lines = [name, f"GSTIN: {shown_sg}", "Tax Invoice", f"Invoice No: {no}", f"Invoice Date: {d.strftime('%d/%m/%Y')}", "",
                 f"Bill To: {buyer}", f"GSTIN: {bg}", "", f"Goods {hsn} {qty} {f(taxable / qty)} {f(taxable)}", f"Taxable Value: {f(taxable)}"]
        lines += [f"IGST @{rate}%: {f(igst)}"] if inter else [f"CGST @{rate/2:g}%: {f(cgst)}", f"SGST @{rate/2:g}%: {f(sgst)}"]
        lines += [f"Grand Total: {f(total)}"]
    elif layout == "B":
        lines = [name.upper(), f"GSTIN/UIN : {shown_sg}", "TAX INVOICE", f"Inv. No. : {no}", f"Dated : {d.strftime('%d-%b-%Y')}", "",
                 f"Buyer (Bill to): {buyer}", f"GSTIN/UIN : {bg}", "", f"Taxable Value ₹ {f(taxable)}"]
        lines += [f"IGST {rate}% ₹ {f(igst)}"] if inter else [f"CGST {rate/2:g}% ₹ {f(cgst)}", f"SGST {rate/2:g}% ₹ {f(sgst)}"]
        lines += [f"Total Invoice Value ₹ {f(total)}"]
    elif layout == "C":  # stacked label/value lines, typical of table OCR
        lines = [name, "GSTIN", shown_sg, "Invoice Number", no, "Invoice Date", d.strftime("%d %b %Y"), "Bill To", buyer, "GSTIN", bg,
                 "Taxable Amount", f(taxable)]
        lines += ["IGST", f(igst)] if inter else ["CGST", f(cgst), "SGST", f(sgst)]
        lines += ["Grand Total", f(total)]
    else:  # D: compact one-line summary
        lines = [name, f"GSTIN: {shown_sg}", f"Invoice: {no} | Date {d.strftime('%d/%m/%Y')}", "Bill To: " + buyer, f"GSTIN: {bg}",
                 f"Taxable {f(taxable)} | " + (f"IGST {f(igst)}" if inter else f"CGST {f(cgst)} | SGST {f(sgst)}") + f" | Total {f(total)}"]
    return {"id": f"syn-{i:03d}-{layout}", "layout": layout, "text": "\n".join(lines),
            "expected": {"supplier_gstin": sg, "buyer_gstin": bg, "invoice_number": no, "invoice_date": d.isoformat(), "taxable_value": taxable,
                         "cgst": cgst, "sgst": sgst, "igst": igst, "total": total, "supplier_name": name}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="evals/data/invoices_synthetic.jsonl")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    with open(a.out, "w") as fh:
        for i in range(a.n):
            fh.write(json.dumps(make(i, rng), ensure_ascii=False) + "\n")
    print(f"wrote {a.n} invoices to {a.out}")
