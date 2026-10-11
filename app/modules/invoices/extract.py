"""Turn invoice text (or files) into structured fields with per-field confidence.

The text-parsing layer is deterministic and dependency-free. Getting text out of
scans/PDFs is delegated to pluggable engines (Docling for digital PDFs, PaddleOCR
for images); both are optional installs (`pip install .[ocr]`).
"""
import re
from datetime import datetime

from app.modules.invoices.gst import validate_gstin

_NUM = r"[\d,]+(?:\.\d+)?"
_GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
_DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d/%m/%y"]
_PARTY_SPLIT = re.compile(r"^\s*(bill(ed)?\s*to|buyer|ship(ped)?\s*to|customer|consignee)\b.*$", re.I | re.M)


def _money(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return round(float(s.replace(",", "")), 2)
    except ValueError:
        return None


def _parse_date(s: str) -> str | None:
    s = s.strip().replace(",", "")
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    return None


def _amount(text: str, labels: list[str]) -> float | None:
    for lab in labels:
        m = re.search(rf"(?im)^[^\n]*?\b(?:{lab})(?![A-Za-z])[^\n\d]*?(?:₹|rs\.?|inr)?\s*({_NUM})\s*$", text)
        if m:
            return _money(m.group(1))
    return None


def parse_invoice_text(text: str) -> dict:
    """Return {"fields": {...}, "confidence": {...}, "line_items": [...]}."""
    f: dict = {}
    conf: dict = {}

    def set_(key, val, c):
        if val not in (None, ""):
            f[key], conf[key] = val, c

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        set_("supplier_name", lines[0][:120], 0.6)

    m = re.search(r"(?i)invoice\s*(?:no|number|#|num)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-_.]{1,29})", text)
    if m:
        set_("invoice_number", m.group(1).strip(".,"), 0.92)

    m = re.search(r"(?i)(?:invoice\s*)?date\s*[:\-]?\s*([0-9]{1,4}[/\-.][0-9]{1,2}[/\-.][0-9]{2,4}|\d{1,2}[ -][A-Za-z]{3,9}[ -,]*\d{4})", text)
    if m:
        d = _parse_date(m.group(1))
        set_("invoice_date", d, 0.9 if d else 0.0)

    # Supplier GSTIN is whatever appears before the buyer block; buyer's after it.
    split = _PARTY_SPLIT.search(text)
    head, tail = (text[: split.start()], text[split.start():]) if split else (text, "")
    sg, bg = _GSTIN_RE.search(head), _GSTIN_RE.search(tail)
    if not sg and not split:
        found = _GSTIN_RE.findall(text)
        sg = None
        if found:
            set_("supplier_gstin", found[0], 0.9)
            if len(found) > 1:
                set_("buyer_gstin", found[1], 0.8)
    if sg:
        set_("supplier_gstin", sg.group(0), 0.92)
    if bg:
        set_("buyer_gstin", bg.group(0), 0.9)
    for k in ("supplier_gstin", "buyer_gstin"):
        if k in f and not validate_gstin(f[k])[0]:
            conf[k] = min(conf[k], 0.4)  # looks like a GSTIN but fails the checksum: likely OCR error

    set_("taxable_value", _amount(text, ["taxable\\s*(?:value|amount)", "sub\\s*-?\\s*total", "net\\s*amount"]), 0.88)
    set_("cgst", _amount(text, ["cgst(?:\\s*@?\\s*[\\d.]+\\s*%)?"]), 0.88)
    set_("sgst", _amount(text, ["sgst(?:\\s*@?\\s*[\\d.]+\\s*%)?", "utgst"]), 0.88)
    set_("igst", _amount(text, ["igst(?:\\s*@?\\s*[\\d.]+\\s*%)?"]), 0.88)
    set_("total", _amount(text, ["grand\\s*total", "invoice\\s*(?:total|value)", "total\\s*amount", "total\\s*payable", "(?<!sub)(?<!sub )(?<!sub-)total"]), 0.9)

    items = []
    row = re.compile(rf"^(.+?)\s+(\d{{4,8}})\s+({_NUM})\s+({_NUM})\s+({_NUM})$")
    for ln in lines:
        r = row.match(ln)
        if r:
            items.append({
                "description": r.group(1), "hsn_sac": r.group(2),
                "quantity": _money(r.group(3)), "rate": _money(r.group(4)), "amount": _money(r.group(5)),
            })
    return {"fields": f, "confidence": conf, "line_items": items}


# ---- text acquisition from files (pluggable OCR) -----------------------------------

class OcrUnavailable(RuntimeError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith((".txt", ".text")):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".pdf") or name.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp")):
        return _ocr(filename, data)
    raise OcrUnavailable(f"Unsupported file type: {filename}")


def _ocr(filename: str, data: bytes) -> str:
    import os
    import tempfile

    suffix = os.path.splitext(filename)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        try:  # Docling: layout-aware parsing for digital PDFs and images
            from docling.document_converter import DocumentConverter
            return DocumentConverter().convert(path).document.export_to_text()
        except ImportError:
            pass
        try:  # PaddleOCR: scanned images
            from paddleocr import PaddleOCR
            res = PaddleOCR(use_angle_cls=True, lang="en").ocr(path)
            return "\n".join(ln[1][0] for page in res or [] for ln in page or [])
        except ImportError:
            raise OcrUnavailable("No OCR engine installed. Install with: pip install '.[ocr]'") from None
    finally:
        os.unlink(path)
