"""Split legal source text into citable chunks (one per section where the text looks like a bare Act)."""
import re

# "27. Agreement in restraint of trade void.-" / "Section 27." / "27A. Heading"
_SECTION = re.compile(r"^\s*(?:Section\s+)?(\d{1,3}[A-Z]{0,2})\.\s+(\S.*)$", re.M)
MAX_CHARS = 1800


def _windows(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= MAX_CHARS:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size].strip())
        i += size - overlap
    return [w for w in out if w]


def chunk(text: str) -> list[dict]:
    """Return [{"section": "27" | None, "text": ...}]. Long sections are windowed but keep their section label."""
    matches = list(_SECTION.finditer(text))
    chunks: list[dict] = []
    if len(matches) >= 3:  # looks like a statute with numbered sections
        for i, m in enumerate(matches):
            body = text[m.start(): matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
            chunks += [{"section": m.group(1), "text": w} for w in _windows(body)]
    else:
        for para_group in re.split(r"\n\s*\n", text):
            chunks += [{"section": None, "text": w} for w in _windows(para_group)]
    return chunks
