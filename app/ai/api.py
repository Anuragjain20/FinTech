"""Operator diagnostics for the AI configuration (which provider/model is active, and does it respond)."""
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ai import chat, embeddings
from app.ai.providers import chat_config, embed_config
from app.core.auth import Principal, require

router = APIRouter(prefix="/ai", tags=["ai"])


class _Pong(BaseModel):
    ok: bool


@router.get("/status")
def status(probe: bool = False, p: Principal = Depends(require("admin"))):
    c, e = chat_config(), embed_config()
    out = {"chat": {"enabled": c is not None, "provider": c.provider if c else None, "model": c.model if c else None},
           "embeddings": {"enabled": e is not None, "model_id": e.model_id if e else None}}
    if probe:  # live round-trip so a bad key/URL is found before users hit it
        if c:
            t0 = time.perf_counter()
            r = chat.structured("default", _Pong, "Reply with {\"ok\": true}.", "ping", max_attempts=1)
            out["chat"]["probe"] = {"ok": r is not None, "ms": round((time.perf_counter() - t0) * 1000)}
        if e:
            try:
                r = embeddings.embed_query("ping")
                out["embeddings"]["probe"] = {"ok": r is not None, "dims": int(len(r[0]))}
            except Exception as ex:
                out["embeddings"]["probe"] = {"ok": False, "error": str(ex)[:200]}
    return out
