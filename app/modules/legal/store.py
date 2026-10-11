"""Corpus storage and hybrid retrieval (BM25 + dense embeddings, fused with reciprocal-rank fusion).

Scope: tenant_id NULL = shared public-law corpus; otherwise a tenant's private material (playbooks, precedents).
Retrieval for a tenant sees the shared corpus plus its own chunks, never another tenant's.

Embeddings come from the AI gateway. Every vector is stored with the id of the model that produced it, and dense
search only uses vectors from the *currently configured* model - so switching embedding provider never mixes
incompatible vectors. After a switch run `reindex()` (CLI: `ingest --reindex`) to re-embed the corpus; until then
retrieval is lexical-only for the not-yet-reindexed chunks.
"""
import logging
import re
import threading

import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import delete, func, insert, or_, select, update

from app.ai import embeddings
from app.core import db
from app.core.config import settings
from app.modules.legal import chunking

log = logging.getLogger("fintech.legal")
_STOP = set("the a an of and or to in on for by with is are be as at that this it its any all shall may not no from under such "
            "which who whom has have had been was were than then there their his her they them if but so".split())
_lock = threading.Lock()
_cache: dict = {}


def tokenize(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in _STOP or len(w) < 2:
            continue
        for suf in ("ing", "ed", "es", "s"):  # crude stemming: enough to match inflections
            if w.endswith(suf) and len(w) - len(suf) >= 4:
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def _embed(texts: list[str]):
    """(matrix, model_id) or None. A provider outage must not block ingestion: chunks are stored lexical-only
    and picked up by reindex() later."""
    try:
        return embeddings.embed_documents(texts)
    except Exception as e:
        log.warning("embedding_failed_ingest_continues", extra={"error": str(e)[:200]})
        return None


def add_document(tenant_id: str | None, source: str, text: str) -> int:
    chunks = chunking.chunk(text)
    if not chunks:
        return 0
    emb = _embed([c["text"] for c in chunks])
    rows = [{"id": db.new_id(), "tenant_id": tenant_id, "source": source[:300], "section": c["section"], "text": c["text"],
             "embedding": emb[0][i].tobytes() if emb else None, "embedding_model": emb[1] if emb else None,
             "created_at": db.now()} for i, c in enumerate(chunks)]
    with db.engine().begin() as c:
        c.execute(insert(db.rag_chunks), rows)
    return len(rows)


def reindex(batch: int = 128) -> dict:
    """Re-embed every chunk not yet embedded with the currently configured model. Safe to re-run."""
    mid = embeddings.current_model_id()
    if mid is None:
        return {"model": None, "reindexed": 0, "note": "no embedding provider configured"}
    done = 0
    while True:
        with db.engine().connect() as c:
            rows = c.execute(select(db.rag_chunks.c.id, db.rag_chunks.c.text)
                             .where(or_(db.rag_chunks.c.embedding_model.is_(None), db.rag_chunks.c.embedding_model != mid))
                             .limit(batch)).all()
        if not rows:
            break
        vecs, model_id = embeddings.embed_documents([r.text for r in rows])
        with db.engine().begin() as c:
            for r, v in zip(rows, vecs, strict=True):
                c.execute(update(db.rag_chunks).where(db.rag_chunks.c.id == r.id).values(embedding=v.tobytes(), embedding_model=model_id))
        done += len(rows)
    clear_cache()
    return {"model": mid, "reindexed": done}


def delete_source(tenant_id: str | None, source: str) -> int:
    cond = db.rag_chunks.c.tenant_id.is_(None) if tenant_id is None else db.rag_chunks.c.tenant_id == tenant_id
    with db.engine().begin() as c:
        return c.execute(delete(db.rag_chunks).where(cond, db.rag_chunks.c.source == source)).rowcount


def stats(tenant_id: str | None) -> list[dict]:
    cond = db.rag_chunks.c.tenant_id.is_(None) if tenant_id is None else db.rag_chunks.c.tenant_id == tenant_id
    mid = embeddings.current_model_id()
    with db.engine().connect() as c:
        rows = c.execute(select(db.rag_chunks.c.source, func.count()).where(cond).group_by(db.rag_chunks.c.source)).all()
        emb = {}
        if mid:
            emb = dict(c.execute(select(db.rag_chunks.c.source, func.count()).where(cond, db.rag_chunks.c.embedding_model == mid)
                                 .group_by(db.rag_chunks.c.source)).all())
    return [{"source": r[0], "chunks": r[1], "embedded": emb.get(r[0], 0)} for r in rows]


def _index(tenant_id: str):
    """(docs, bm25, dense_positions, matrix) for shared + tenant chunks; rebuilt when the corpus or embedding model changes."""
    where = or_(db.rag_chunks.c.tenant_id.is_(None), db.rag_chunks.c.tenant_id == tenant_id)
    mid = embeddings.current_model_id()
    with db.engine().connect() as c:
        fp = c.execute(select(func.count(), func.max(db.rag_chunks.c.created_at),
                              func.count(db.rag_chunks.c.embedding_model)).where(where)).one()
    key = (str(db.engine().url), tenant_id, mid)
    with _lock:
        hit = _cache.get(key)
        if hit and hit["fp"] == tuple(fp):
            return hit["docs"], hit["bm25"], hit["pos"], hit["matrix"]
    with db.engine().connect() as c:
        rows = c.execute(select(db.rag_chunks).where(where).order_by(db.rag_chunks.c.created_at, db.rag_chunks.c.id)).all()
    docs = [{"id": r.id, "source": r.source, "section": r.section, "text": r.text, "private": r.tenant_id is not None} for r in rows]
    bm25 = BM25Okapi([tokenize(d["text"] + " " + d["source"]) or ["_"] for d in docs]) if docs else None
    pos = [i for i, r in enumerate(rows) if mid and r.embedding and r.embedding_model == mid]
    matrix = np.vstack([np.frombuffer(rows[i].embedding, dtype=np.float32) for i in pos]) if pos else None
    with _lock:
        _cache[key] = {"fp": tuple(fp), "docs": docs, "bm25": bm25, "pos": pos, "matrix": matrix}
    return docs, bm25, pos, matrix


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def search(tenant_id: str, query: str, k: int | None = None, boost_terms: str = "") -> list[dict]:
    k = k or settings.rag_top_k
    docs, bm25, pos, matrix = _index(tenant_id)
    if not docs:
        return []
    q = f"{query} {boost_terms}".strip()
    lex = bm25.get_scores(tokenize(q) or ["_"])
    rankings = [[int(i) for i in np.argsort(-lex)[: k * 4] if lex[i] > 0]]
    if matrix is not None:
        try:
            qv = embeddings.embed_query(q)
        except Exception as e:  # dense is an enhancement: fall back to lexical on provider failure
            log.warning("embedding_failed_search_lexical_only", extra={"error": str(e)[:200]})
            qv = None
        if qv is not None:
            order = np.argsort(-(matrix @ qv[0]))[: k * 4]
            rankings.append([pos[int(j)] for j in order])
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, i in enumerate(ranking):
            fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank)
    top = sorted(fused, key=fused.get, reverse=True)[:k]
    return [{**docs[i], "score": round(fused[i], 4)} for i in top]
