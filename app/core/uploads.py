import csv
import io

from fastapi import HTTPException, UploadFile

from app.core.config import settings


async def read_limited(f: UploadFile, allowed: tuple[str, ...]) -> tuple[str, bytes]:
    name = f.filename or ""
    if not name.lower().endswith(allowed):
        raise HTTPException(415, f"Unsupported file type; allowed: {', '.join(allowed)}")
    limit = settings.max_upload_mb * 1024 * 1024
    data = await f.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")
    if not data:
        raise HTTPException(422, "Empty file")
    return name, data


def safe_cell(v):
    """Neutralise spreadsheet formula injection (=, +, -, @, tab, CR) in exported text cells."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def safe_csv(rows: list[dict], columns: list[str]) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: safe_cell(r.get(k)) for k in columns})
    return out.getvalue()
