"""Minimal multi-tenant document store on SQLite.

Every row carries a tenant_id and every query filters on it, so one tenant can
never read another's data. Swap for PostgreSQL by re-implementing this module.
"""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from . import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None


def conn() -> sqlite3.Connection:
    global _conn, _conn_path
    if _conn is None or _conn_path != config.DB_PATH:
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn_path = config.DB_PATH
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenants(
              id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS api_keys(
              key_hash TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
              role TEXT NOT NULL, label TEXT);
            CREATE TABLE IF NOT EXISTS docs(
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, kind TEXT NOT NULL,
              status TEXT, data TEXT NOT NULL, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS docs_tk ON docs(tenant_id, kind);
            CREATE TABLE IF NOT EXISTS audit(
              id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL,
              actor TEXT, action TEXT NOT NULL, entity TEXT, entity_id TEXT,
              detail TEXT, at TEXT NOT NULL);
            """
        )
    return _conn


def reset() -> None:
    """Close the connection (used by tests to get a fresh database)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def put(tenant_id: str, kind: str, data: dict, status: str | None = None, doc_id: str | None = None) -> str:
    with _lock:
        c = conn()
        doc_id = doc_id or new_id()
        ts = now()
        c.execute(
            """INSERT INTO docs(id,tenant_id,kind,status,data,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, data=excluded.data,
               updated_at=excluded.updated_at
               WHERE docs.tenant_id=excluded.tenant_id""",
            (doc_id, tenant_id, kind, status, json.dumps(data), ts, ts),
        )
        c.commit()
        return doc_id


def get(tenant_id: str, kind: str, doc_id: str) -> dict | None:
    with _lock:
        r = conn().execute(
            "SELECT * FROM docs WHERE id=? AND tenant_id=? AND kind=?", (doc_id, tenant_id, kind)
        ).fetchone()
    return _row(r) if r else None


def list_(tenant_id: str, kind: str, status: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM docs WHERE tenant_id=? AND kind=?", [tenant_id, kind]
    if status:
        q += " AND status=?"
        args.append(status)
    with _lock:
        rows = conn().execute(q + " ORDER BY created_at, rowid", args).fetchall()
    return [_row(r) for r in rows]


def _row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "status": r["status"], "created_at": r["created_at"],
        "updated_at": r["updated_at"], "data": json.loads(r["data"]),
    }


def audit(tenant_id: str, actor: str, action: str, entity: str = "", entity_id: str = "", detail: dict | None = None) -> None:
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO audit(tenant_id,actor,action,entity,entity_id,detail,at) VALUES(?,?,?,?,?,?,?)",
            (tenant_id, actor, action, entity, entity_id, json.dumps(detail or {}), now()),
        )
        c.commit()


def audit_log(tenant_id: str, entity_id: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM audit WHERE tenant_id=?", [tenant_id]
    if entity_id:
        q += " AND entity_id=?"
        args.append(entity_id)
    with _lock:
        rows = conn().execute(q + " ORDER BY id", args).fetchall()
    return [
        {"actor": r["actor"], "action": r["action"], "entity": r["entity"],
         "entity_id": r["entity_id"], "detail": json.loads(r["detail"]), "at": r["at"]}
        for r in rows
    ]
