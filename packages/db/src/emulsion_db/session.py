"""Engine and session factory.

Defaults to SQLite so the product runs with nothing installed. Point DATABASE_URL at
Postgres (M0's production choice) and nothing else changes.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_SQLITE_PATH = Path(os.environ.get("EMULSION_DATA_DIR", ".data")) / "emulsion.db"


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    connect_args = {}
    if url.startswith("sqlite"):
        # The API and the worker are separate processes hitting the same file.
        connect_args = {"check_same_thread": False, "timeout": 30}
    try:
        engine = create_engine(url, future=True, connect_args=connect_args)
    except ModuleNotFoundError as exc:
        # The Postgres driver is an optional extra: the default is SQLite and psycopg
        # needs libpq. Without this, copying .env.example — which documents a Postgres
        # DATABASE_URL — buries the cause under a SQLAlchemy import traceback.
        raise RuntimeError(
            f"DATABASE_URL={url.split('://')[0]}:// needs a driver that is not installed "
            f"({exc.name}). Either install it with `uv sync --extra postgres`, or unset "
            "DATABASE_URL to use the default SQLite file."
        ) from exc

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            # WAL lets the worker write while the API reads — without it the two
            # processes lock each other out constantly.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


def create_all(engine: Engine | None = None) -> None:
    """Create tables if absent.

    ponytail: `create_all`, not Alembic. M0 picked Alembic and it is the right answer the
    moment a column changes under real data. Until the schema settles, a migration per
    edit is pure friction — generate the first migration from these models when M3 lands.
    """
    Base.metadata.create_all(engine or get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
