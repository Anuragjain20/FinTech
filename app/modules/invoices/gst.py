"""GSTIN validation (format + state code + mod-36 checksum)."""
import re

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_FORMAT = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
VALID_STATE_CODES = {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}


def checksum_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        v = _CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return _CHARS[(36 - total % 36) % 36]


def validate_gstin(gstin: str | None) -> tuple[bool, str]:
    """Return (ok, reason). reason is '' when valid."""
    if not gstin:
        return False, "missing"
    g = gstin.strip().upper()
    if not _FORMAT.match(g):
        return False, "bad format"
    if g[:2] not in VALID_STATE_CODES:
        return False, "unknown state code"
    if checksum_char(g[:14]) != g[14]:
        return False, "checksum mismatch"
    return True, ""


def state_code(gstin: str | None) -> str | None:
    return gstin[:2] if gstin and len(gstin) >= 2 and gstin[:2].isdigit() else None
