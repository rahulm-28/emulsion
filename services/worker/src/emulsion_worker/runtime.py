"""Process-wide wiring: settings, blob store, queue.

Lives in the worker rather than the API because it must not depend on anything web —
the worker is the process that has to run without FastAPI present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from emulsion_db import DbQueue, create_all, get_sessionmaker
from emulsion_platform import FilesystemBlobStore


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    adapter: str
    blob_url_prefix: str
    poll_interval_s: float
    lease_seconds: int
    inline_worker: bool
    cors_origins: tuple[str, ...]

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"


@lru_cache(maxsize=1)
def settings() -> Settings:
    data_dir = Path(os.environ.get("EMULSION_DATA_DIR", ".data"))
    origins = os.environ.get("EMULSION_CORS_ORIGINS", "http://localhost:3000")
    return Settings(
        data_dir=data_dir,
        # Defaults to `echo` on purpose: nothing should reach a paid provider because
        # someone forgot to configure something.
        adapter=os.environ.get("EMULSION_ADAPTER", "echo"),
        blob_url_prefix=os.environ.get("EMULSION_BLOB_URL_PREFIX", "/_blobs"),
        poll_interval_s=float(os.environ.get("EMULSION_POLL_INTERVAL_S", "0.5")),
        lease_seconds=int(os.environ.get("EMULSION_LEASE_SECONDS", "900")),
        # One command to run everything locally. Production runs the worker as its own
        # Container Apps Job — see M0 §3.2.
        inline_worker=_flag("EMULSION_INLINE_WORKER", True),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
    )


@lru_cache(maxsize=1)
def blob_store() -> FilesystemBlobStore:
    s = settings()
    return FilesystemBlobStore(s.blob_dir, base_url=s.blob_url_prefix)


@lru_cache(maxsize=1)
def queue() -> DbQueue:
    return DbQueue(get_sessionmaker())


def bootstrap() -> None:
    """Create tables and the blob directory. Safe to call repeatedly."""
    create_all()
    blob_store()
