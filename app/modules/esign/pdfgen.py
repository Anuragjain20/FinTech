"""Deterministic PDF rendering of contract text plus the signature certificate page.

`invariant=1` removes timestamps/random ids from the PDF, so the same text always produces byte-identical
output; the SHA-256 recorded at signing time can therefore be re-derived and checked.
"""
import io
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"]
_BOLD_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"]
_fonts: tuple[str, str] | None = None


def _register() -> tuple[str, str]:
    """DejaVu (covers the rupee sign and accented Latin) when installed, else built-in Helvetica."""
    global _fonts
    if _fonts is None:
        import os
        reg = next((p for p in _FONT_PATHS if os.path.exists(p)), None)
        bold = next((p for p in _BOLD_PATHS if os.path.exists(p)), None)
        if reg and bold:
            pdfmetrics.registerFont(TTFont("DejaVu", reg))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold))
            _fonts = ("DejaVu", "DejaVu-Bold")
        else:
            _fonts = ("Helvetica", "Helvetica-Bold")
    return _fonts


def _styles():
    reg, bold = _register()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName=bold, fontSize=16),
        "h": ParagraphStyle("h", parent=base["Heading3"], fontName=bold, fontSize=11, spaceBefore=8),
        "p": ParagraphStyle("p", parent=base["BodyText"], fontName=reg, fontSize=10, leading=14),
        "small": ParagraphStyle("s", parent=base["BodyText"], fontName=reg, fontSize=8, leading=10),
    }


def _para(text: str, style) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _contract_flow(title: str, text: str, st) -> list:
    flow = [_para(title, st["title"]), Spacer(1, 6)]
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        if len(lines) > 1 and lines[0][:1].isdigit():
            flow += [_para(lines[0], st["h"]), _para("\n".join(lines[1:]), st["p"])]
        else:
            flow.append(_para(block, st["p"]))
    return flow


def _certificate_flow(title: str, sha256: str, signers: list[dict], consent_text: str, st) -> list:
    flow = [_para("Certificate of electronic signature", st["title"]), _para(f"Document: {title}", st["p"]),
            _para(f"SHA-256 of the document exactly as presented to signers:\n{sha256}", st["p"]), Spacer(1, 8)]
    rows = [[_para(h, st["small"]) for h in ("Signer", "Signed (UTC)", "Verification", "IP / device")]]
    for s in signers:
        rows.append([_para(f"{s['typed_name']}\n{s['email']}", st["small"]), _para(s["signed_at"], st["small"]),
                     _para("Link + one-time code sent to email", st["small"]), _para(f"{s['ip']}\n{s['ua'][:80]}", st["small"])])
    t = Table(rows, colWidths=[50 * mm, 32 * mm, 38 * mm, 50 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, (0.6, 0.6, 0.6)), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return flow + [t, Spacer(1, 10), _para("Consent recorded from each signer:", st["h"]), _para(consent_text, st["p"]),
                   Spacer(1, 8), _para("This is an electronic signature with an audit trail (email-link possession, one-time code, "
                                       "typed name, timestamp, IP). It is not an Aadhaar eSign or Class 2/3 Digital Signature "
                                       "Certificate signature. The PDF is sealed with a platform certificate so any later change "
                                       "is detectable.", st["small"])]


def _build(flow: list, title: str) -> bytes:
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, invariant=1, title=title, author="", leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=20 * mm, bottomMargin=20 * mm).build(flow)
    return buf.getvalue()


def contract_pdf(title: str, text: str) -> bytes:
    return _build(_contract_flow(title, text, _styles()), title)


def final_pdf(title: str, text: str, sha256: str, signers: list[dict], consent_text: str) -> bytes:
    """Contract pages followed by the certificate page, in one document (sealed afterwards by seal.py)."""
    st = _styles()
    return _build(_contract_flow(title, text, st) + [PageBreak()] + _certificate_flow(title, sha256, signers, consent_text, st), title)
