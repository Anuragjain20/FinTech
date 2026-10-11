"""Structured logging, request ids, security headers, metrics, Sentry."""
import logging
import sys
import time
import uuid

import structlog
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

log = structlog.get_logger("fintech")


def configure_logging() -> None:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[structlog.contextvars.merge_contextvars, structlog.processors.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.JSONRenderer() if settings.env == "production" else structlog.dev.ConsoleRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO), cache_logger_on_first_use=True)


class RequestContext(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        t0 = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        if settings.env == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path not in ("/health", "/ready", "/metrics"):
            log.info("request", method=request.method, path=request.url.path, status=response.status_code,
                     ms=round((time.perf_counter() - t0) * 1000, 1))
        return response


def setup(app: FastAPI) -> None:
    configure_logging()
    app.add_middleware(RequestContext)
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator(excluded_handlers=["/metrics", "/health", "/ready"]).instrument(app).expose(
        app, include_in_schema=False, should_gzip=True)
    if settings.sentry_dsn:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.env, send_default_pii=False)
