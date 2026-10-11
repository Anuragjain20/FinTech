"""Multi-tenant document store on SQLAlchemy (PostgreSQL in production, SQLite for dev/tests).

Every query filters on tenant_id, so a tenant can never read another's rows. The
schema is managed by Alembic (see /migrations); `create_all` is used only for
SQLite dev/test databases.
"""
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.core.config import settings

metadata = MetaData()
JSONType = JSON().with_variant(JSONB(), "postgresql")
tenants = Table("tenants", metadata,
                Column("id", String(32), primary_key=True), Column("name", String(200), nullable=False),
                Column("plan", String(32), nullable=False, default="free"),
                Column("subscription_id", String(64)),
                Column("created_at", DateTime(timezone=True), nullable=False))
api_keys = Table("api_keys", metadata,
                 Column("key_hash", String(64), primary_key=True), Column("tenant_id", String(32), nullable=False, index=True),
                 Column("role", String(16), nullable=False), Column("label", String(100)),
                 Column("revoked", Integer, nullable=False, default=0))
docs = Table("docs", metadata,
             Column("id", String(32), primary_key=True), Column("tenant_id", String(32), nullable=False),
             Column("kind", String(32), nullable=False), Column("status", String(32)),
             Column("ref", String(64)),  # secondary lookup key (e.g. supplier GSTIN for invoices)
             Column("data", JSONType, nullable=False),
             Column("created_at", DateTime(timezone=True), nullable=False),
             Column("updated_at", DateTime(timezone=True), nullable=False),
             Index("docs_tenant_kind_status", "tenant_id", "kind", "status", "created_at"),
             Index("docs_tenant_kind_ref", "tenant_id", "kind", "ref"))
audit_t = Table("audit", metadata,
                Column("id", Integer, primary_key=True, autoincrement=True), Column("tenant_id", String(32), nullable=False),
                Column("actor", String(200)), Column("action", String(64), nullable=False),
                Column("entity", String(32)), Column("entity_id", String(32)), Column("detail", JSONType),
                Column("at", DateTime(timezone=True), nullable=False),
                Index("audit_tenant_entity", "tenant_id", "entity_id"))
users = Table("users", metadata,
              Column("id", String(32), primary_key=True), Column("tenant_id", String(32), nullable=False, index=True),
              Column("email", String(254), nullable=False, unique=True),  # one tenant per email address
              Column("name", String(200)), Column("role", String(16), nullable=False),
              Column("active", Integer, nullable=False, default=1),
              Column("created_at", DateTime(timezone=True), nullable=False), Column("last_login", DateTime(timezone=True)))
sessions = Table("sessions", metadata,
                 Column("token_hash", String(64), primary_key=True), Column("user_id", String(32), nullable=False, index=True),
                 Column("created_at", DateTime(timezone=True), nullable=False),
                 Column("expires_at", DateTime(timezone=True), nullable=False))
rag_chunks = Table("rag_chunks", metadata,
                   Column("id", String(32), primary_key=True),
                   Column("tenant_id", String(32), index=True),  # NULL = shared public-law corpus, else tenant-private
                   Column("source", String(300), nullable=False), Column("section", String(100)),
                   Column("text", Text, nullable=False), Column("embedding", LargeBinary),
                   Column("embedding_model", String(160)),  # vectors are only comparable within one model
                   Column("created_at", DateTime(timezone=True), nullable=False))
usage = Table("usage", metadata,
              Column("tenant_id", String(32), primary_key=True), Column("period", String(7), primary_key=True),
              Column("metric", String(32), primary_key=True), Column("count", Integer, nullable=False, default=0))

_engine: Engine | None = None
_url: str | None = None


_engine_lock = threading.Lock()


def engine() -> Engine:
    global _engine, _url
    if _engine is not None and _url == settings.database_url:
        return _engine
    with _engine_lock:  # build fully, then publish: no thread may see a half-initialised engine
        if _engine is not None and _url == settings.database_url:
            return _engine
        url = settings.database_url
        kw: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kw = {"connect_args": {"check_same_thread": False}}
            if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
                from sqlalchemy.pool import StaticPool
                kw["poolclass"] = StaticPool
        eng = create_engine(url, **kw)
        if url.startswith("sqlite"):
            metadata.create_all(eng)
        _engine, _url = eng, url
        return eng


def reset() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=dt.tzinfo or timezone.utc).isoformat(timespec="seconds")


def put(tenant_id: str, kind: str, data: dict, status: str | None = None, doc_id: str | None = None,
        ref: str | None = None) -> str:
    ts = now()
    with engine().begin() as c:
        if doc_id:
            res = c.execute(update(docs).where(docs.c.id == doc_id, docs.c.tenant_id == tenant_id, docs.c.kind == kind)
                            .values(data=data, status=status, updated_at=ts, **({"ref": ref} if ref else {})))
            if res.rowcount:
                return doc_id
        doc_id = doc_id or new_id()
        c.execute(insert(docs).values(id=doc_id, tenant_id=tenant_id, kind=kind, status=status, data=data, ref=ref,
                                      created_at=ts, updated_at=ts))
    return doc_id


def _row(r) -> dict:
    return {"id": r.id, "status": r.status, "created_at": _iso(r.created_at), "updated_at": _iso(r.updated_at), "data": r.data}


def get(tenant_id: str, kind: str, doc_id: str) -> dict | None:
    with engine().connect() as c:
        r = c.execute(select(docs).where(docs.c.id == doc_id, docs.c.tenant_id == tenant_id, docs.c.kind == kind)).first()
    return _row(r) if r else None


def list_(tenant_id: str, kind: str, status: str | None = None, limit: int | None = None, offset: int = 0,
          ref: str | None = None) -> list[dict]:
    q = select(docs).where(docs.c.tenant_id == tenant_id, docs.c.kind == kind)
    if status:
        q = q.where(docs.c.status == status)
    if ref:
        q = q.where(docs.c.ref == ref)
    q = q.order_by(docs.c.created_at, docs.c.id)
    if limit is not None:
        q = q.limit(limit).offset(offset)
    with engine().connect() as c:
        return [_row(r) for r in c.execute(q)]


def get_any(kind: str, doc_id: str) -> dict | None:
    """Tenant-less lookup for unauthenticated, token-guarded flows (e-signature). Caller must prove possession of a secret."""
    with engine().connect() as c:
        r = c.execute(select(docs).where(docs.c.id == doc_id, docs.c.kind == kind)).first()
    return {**_row(r), "tenant_id": r.tenant_id} if r else None


def update_locked(tenant_id: str, kind: str, doc_id: str, fn, status: str | None = None):
    """Atomic read-modify-write of one document (row lock on PostgreSQL). `fn(data)` mutates and may return
    (result, new_status); the result is returned. Prevents lost updates when several people act at once."""
    with engine().begin() as c:
        r = c.execute(select(docs).where(docs.c.id == doc_id, docs.c.tenant_id == tenant_id, docs.c.kind == kind)
                      .with_for_update()).first()
        if r is None:
            raise LookupError(doc_id)
        data = dict(r.data)
        result = fn(data)
        if isinstance(result, tuple):  # fn may return (result, new_status)
            result, status = result
        new_status = status or r.status
        c.execute(update(docs).where(docs.c.id == doc_id).values(data=data, status=new_status, updated_at=now()))
        return result


def count(tenant_id: str, kind: str, status: str | None = None) -> int:
    q = select(func.count()).select_from(docs).where(docs.c.tenant_id == tenant_id, docs.c.kind == kind)
    if status:
        q = q.where(docs.c.status == status)
    with engine().connect() as c:
        return c.execute(q).scalar_one()


def audit(tenant_id: str, actor: str, action: str, entity: str = "", entity_id: str = "", detail: dict | None = None) -> None:
    with engine().begin() as c:
        c.execute(insert(audit_t).values(tenant_id=tenant_id, actor=actor, action=action, entity=entity,
                                         entity_id=entity_id, detail=detail or {}, at=now()))


def audit_log(tenant_id: str, entity_id: str | None = None, limit: int = 1000) -> list[dict]:
    q = select(audit_t).where(audit_t.c.tenant_id == tenant_id)
    if entity_id:
        q = q.where(audit_t.c.entity_id == entity_id)
    with engine().connect() as c:
        rows = c.execute(q.order_by(audit_t.c.id).limit(limit)).all()
    return [{"actor": r.actor, "action": r.action, "entity": r.entity, "entity_id": r.entity_id,
             "detail": r.detail, "at": _iso(r.at)} for r in rows]


# ---- usage metering ---------------------------------------------------------------

def _period() -> str:
    return now().strftime("%Y-%m")


def usage_get(tenant_id: str, metric: str) -> int:
    with engine().connect() as c:
        r = c.execute(select(usage.c.count).where(usage.c.tenant_id == tenant_id, usage.c.period == _period(),
                                                   usage.c.metric == metric)).first()
    return r[0] if r else 0


def usage_incr(tenant_id: str, metric: str, n: int = 1) -> None:
    with engine().begin() as c:
        res = c.execute(update(usage).where(usage.c.tenant_id == tenant_id, usage.c.period == _period(),
                                            usage.c.metric == metric).values(count=usage.c.count + n))
    if res.rowcount:
        return
    try:
        with engine().begin() as c:
            c.execute(insert(usage).values(tenant_id=tenant_id, period=_period(), metric=metric, count=n))
    except IntegrityError:  # lost a first-insert race; the row exists now
        with engine().begin() as c:
            c.execute(update(usage).where(usage.c.tenant_id == tenant_id, usage.c.period == _period(),
                                          usage.c.metric == metric).values(count=usage.c.count + n))
