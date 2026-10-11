import difflib
import re


def _paras(t: str) -> list[str]:
    return [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", t) if p.strip()]


def compare(old: str, new: str) -> list[dict]:
    """Paragraph-level diff: [{op: added|removed|changed, old, new}]."""
    a, b = _paras(old), _paras(new)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                o = a[i1 + k] if i1 + k < i2 else None
                n = b[j1 + k] if j1 + k < j2 else None
                out.append({"op": "changed" if o and n else ("removed" if o else "added"), "old": o, "new": n})
        elif tag == "delete":
            out += [{"op": "removed", "old": p, "new": None} for p in a[i1:i2]]
        else:
            out += [{"op": "added", "old": None, "new": p} for p in b[j1:j2]]
    return out
