import re

from pydantic import BaseModel, Field, field_validator

from app.modules.invoices.extract import _parse_date


def _num(v):
    """Accept 1,18,000.50 / ₹ 1000 / '12.5%'-less strings; reject anything else as null."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = re.sub(r"[₹,\s]|rs\.?|inr", "", str(v), flags=re.I)
    try:
        return round(float(s), 2)
    except ValueError:
        return None


class LineItem(BaseModel):
    description: str | None = None
    hsn_sac: str | None = None
    quantity: float | None = None
    rate: float | None = None
    amount: float | None = None

    _n = field_validator("quantity", "rate", "amount", mode="before")(lambda cls, v: _num(v))


class InvoiceExtraction(BaseModel):
    """What the LLM must return. Every field is optional: null means 'not present on the invoice'."""
    supplier_name: str | None = None
    supplier_gstin: str | None = None
    buyer_gstin: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = Field(default=None, description="YYYY-MM-DD")
    taxable_value: float | None = None
    cgst: float | None = None
    sgst: float | None = None
    igst: float | None = None
    total: float | None = None
    line_items: list[LineItem] = Field(default_factory=list, max_length=200)

    _n = field_validator("taxable_value", "cgst", "sgst", "igst", "total", mode="before")(lambda cls, v: _num(v))

    @field_validator("supplier_gstin", "buyer_gstin", mode="before")
    @classmethod
    def _gstin(cls, v):
        v = re.sub(r"\s+", "", str(v)).upper() if v else None
        return v or None

    @field_validator("invoice_date", mode="before")
    @classmethod
    def _date(cls, v):
        if not v:
            return None
        s = str(v).strip()
        return _parse_date(s) or (s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None)

    @field_validator("supplier_name", "invoice_number", mode="before")
    @classmethod
    def _text(cls, v):
        v = str(v).strip() if v not in (None, "") else None
        return v or None
