"""Graph configuration; commercial and account policy stay with the host."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from atlas_graph.runtime import host


def _signing_secret(directory: Path) -> str:
    configured = os.environ.get("ATLAS_SIGNING_SECRET", "").strip()
    if configured:
        return configured
    if os.environ.get("ATLAS_MODE", "local") != "local":
        raise RuntimeError("ATLAS_SIGNING_SECRET is required for hosted Atlas")
    directory.mkdir(parents=True, exist_ok=True)
    filename = directory / ".signing-secret"
    if filename.exists():
        return filename.read_text().strip()
    value = secrets.token_urlsafe(48)
    try:
        descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return filename.read_text().strip()
    with os.fdopen(descriptor, "w") as stream:
        stream.write(value)
    return value


def __getattr__(name: str):
    upstream = host().config
    if upstream is not None and hasattr(upstream, name):
        return getattr(upstream, name)
    database = os.environ.get("ATLAS_DATABASE_URL", "").strip()
    directory = Path(os.environ.get("ATLAS_DATA_DIR", "./data")).resolve()
    values = {
        "MODE": os.environ.get("ATLAS_MODE", "local"),
        "DATA_DIR": directory,
        "BLOBS_DIR": directory / "blobs",
        "DB_PATH": directory / "atlas.db",
        "DATABASE_URL": database,
        "DATABASE_SCHEMA": os.environ.get("ATLAS_DATABASE_SCHEMA", "public"),
        "USE_POSTGRES": bool(database),
        "INDEXING_ENABLED": os.environ.get("ATLAS_INDEXING_ENABLED", "false").lower() == "true",
        "PUBLIC_GRAPHS_ENABLED": os.environ.get(
            "ATLAS_PUBLIC_GRAPHS_ENABLED", "false"
        ).lower()
        == "true",
        "SERVER_URL": os.environ.get("ATLAS_SERVER_URL", "http://127.0.0.1:8002"),
        "SIGNED_URL_TTL_SECONDS": 3600,
        "BATCH_TOKEN_TTL_SECONDS": 900,
        "MAX_UPLOAD_BYTES": 10_485_760,
        "SUPABASE_URL": os.environ.get("ATLAS_SUPABASE_URL", ""),
        "SUPABASE_SERVICE_ROLE_KEY": os.environ.get(
            "ATLAS_SUPABASE_SERVICE_ROLE_KEY", ""
        ),
        "SUPABASE_JWT_SECRET": None,
        "SUPABASE_STORAGE_BUCKET": os.environ.get("ATLAS_STORAGE_BUCKET", "blobs"),
        "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
        "IDEMPOTENCY_TTL_DAYS": 7,
        "IDEMPOTENCY_MAX_BODY_BYTES": 1_048_576,
        "IDEMPOTENCY_MAX_RESPONSE_BYTES": 1_048_576,
    }
    if name not in values:
        raise AttributeError(name)
    if name == "SUPABASE_JWT_SECRET":
        return _signing_secret(directory)
    return values[name]
