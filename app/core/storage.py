"""Object storage for uploaded originals (invoices, statements). S3-compatible or local disk."""
import os
import re
from functools import lru_cache
from pathlib import Path

from app.core.config import settings


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(name))[:100] or "file"


def key_for(tenant_id: str, doc_id: str, filename: str) -> str:
    return f"{tenant_id}/{doc_id}/{_safe(filename)}"


@lru_cache(maxsize=1)
def _s3():
    import boto3
    return boto3.client("s3", endpoint_url=settings.s3_endpoint_url, region_name=settings.s3_region)


def clear_cache() -> None:
    _s3.cache_clear()


def put(key: str, data: bytes) -> None:
    if settings.storage_backend == "s3":
        _s3().put_object(Bucket=settings.s3_bucket, Key=key, Body=data,
                          **({"ServerSideEncryption": "AES256"} if settings.s3_sse else {}))
        return
    path = Path(settings.storage_local_dir) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def get(key: str) -> bytes:
    if settings.storage_backend == "s3":
        return _s3().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
    return (Path(settings.storage_local_dir) / key).read_bytes()
