"""Corpus storage and hybrid retrieval (BM25 + optional dense, fused with reciprocal-rank fusion).

Scope: tenant_id NULL = shared public-law corpus; otherwise a tenant's private material (playbooks, precedents).
Retrieval for a tenant sees the shared corpus plus its own chunks, never another tenant's.
"""
import re
import threading

import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import delete, func, insert, or_, select

from .. import db
from ..config import settings
from . import chunking, embed

_STOP = set("the a an of and or to in on for by with is are be as at that this it its any all shall may not no from under such "
            "which who whom has have had been was were than then there their his her they them if but so".split())
_lock = threading.Lock()
_cache: dict = {}


def tokenize(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in _STOP or len(w) < 2:
            continue
        for suf in ("ing", "ed", "es", "s"):  # crude stemming: enough to match "restrains"/"restraint"-style inflections
            if w.endswith(suf) and len(w) - len(suf) >= 4:
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def add_document(tenant_id: str | None, source: str, text: str) -> int:
    chunks = chunking.chunk(text)
    if not chunks:
        return 0
    vecs = embed.embed([c["text"] for c in chunks])
    rows = [{"id": db.new_id(), "tenant_id": tenant_id, "source": source[:300], "section": c["section"], "text": c["text"],
             "embedding": vecs[i].tobytes() if vecs is not None else None, "created_at": db.now()} for i, c in enumerate(chunks)]
    with db.engine().begin() as c:
        c.execute(insert(db.rag_chunks), rows)
    return len(rows)


def delete_source(tenant_id: str | None, source: str) -> int:
    cond = db.rag_chunks.c.tenant_id.is_(None) if tenant_id is None else db.rag_chunks.c.tenant_id == tenant_id
    with db.engine().begin() as c:
        return c.execute(delete(db.rag_chunks).where(cond, db.rag_chunks.c.source == source)).rowcount


def stats(tenant_id: str | None) -> list[dict]:
    cond = db.rag_chunks.c.tenant_id.is_(None) if tenant_id is None else db.rag_chunks.c.tenant_id == tenant_id
    with db.engine().connect() as c:
        rows = c.execute(select(db.rag_chunks.c.source, func.count()).where(cond).group_by(db.rag_chunks.c.source)).all()
    return [{"source": r[0], "chunks": r[1]} for r in rows]


def _index(tenant_id: str):
    """(rows, bm25, matrix) for shared + tenant chunks; rebuilt when the corpus changes."""
    where = or_(db.rag_chunks.c.tenant_id.is_(None), db.rag_chunks.c.tenant_id == tenant_id)
    with db.engine().connect() as c:
        fp = c.execute(select(func.count(), func.max(db.rag_chunks.c.created_at)).where(where)).one()
    key = (str(db.engine().url), tenant_id)
    with _lock:
        hit = _cache.get(key)
        if hit and hit["fp"] == tuple(fp):
            return hit["rows"], hit["bm25"], hit["matrix"]
    with db.engine().connect() as c:
        rows = c.execute(select(db.rag_chunks).where(where).order_by(db.rag_chunks.c.created_at, db.rag_chunks.c.id)).all()
    docs = [{"id": r.id, "source": r.source, "section": r.section, "text": r.text, "private": r.tenant_id is not None} for r in rows]
    bm25 = BM25Okapi([tokenize(d["text"] + " " + d["source"]) or ["_"] for d in docs]) if docs else None
    vecs = [np.frombuffer(r.embedding, dtype=np.float32) for r in rows if r.embedding]
    matrix = np.vstack(vecs) if vecs and len(vecs) == len(rows) else None
    with _lock:
        _cache[key] = {"fp": tuple(fp), "rows": docs, "bm25": bm25, "matrix": matrix}
    return docs, bm25, matrix


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def search(tenant_id: str, query: str, k: int | None = None, boost_terms: str = "") -> list[dict]:
    k = k or settings.rag_top_k
    docs, bm25, matrix = _index(tenant_id)
    if not docs:
        return []
    q = f"{query} {boost_terms}"
    lex = bm25.get_scores(tokenize(q) or ["_"])
    rankings = [np.argsort(-lex)[: k * 4]]
    rankings[0] = np.array([i for i in rankings[0] if lex[i] > 0])
    if matrix is not None:
        qv = embed.embed([q])
        if qv is not None:
            rankings.append(np.argsort(-(matrix @ qv[0]))[: k * 4])
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, i in enumerate(ranking):
            fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (60 + rank)
    top = sorted(fused, key=fused.get, reverse=True)[:k]
    return [{**docs[i], "score": round(fused[i], 4)} for i in top]
