"""Split legal source text into citable chunks (one per section where the text looks like a bare Act)."""
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

# "27. Agreement in restraint of trade void.-" / "Section 27." / "27A. Heading"
_SECTION = re.compile(r"^\s*(?:Section\s+)?(\d{1,3}[A-Z]{0,2})\.\s+(\S.*)$", re.M)
MAX_CHARS = 1800


_splitter = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=150, separators=["\n\n", "\n", ". ", " ", ""])


def _windows(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= MAX_CHARS:
        return [text] if text else []
    return [w.strip() for w in _splitter.split_text(text) if w.strip()]


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
