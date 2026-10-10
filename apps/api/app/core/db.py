"""Database engine, session management and schema creation.

Persisted analysis records use this policy:

* ``DATABASE_URL`` set to a PostgreSQL URL (for example Neon) - results are stored there.
* ``DATABASE_URL`` empty - results live in an in-memory SQLite database and disappear when
  the process stops. Source checkouts are temporary files, removed after a run or on startup.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from repolens_shared.errors import DatabaseError

from ..models.tables import Base, ChunkRecord, FileRecord
from .config import Settings, get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_anchor = None  # keeps the in-memory database alive, see _build_engine
_SessionLocal: sessionmaker | None = None
_state: dict[str, object] = {"dialect": "sqlite", "storage": "memory", "schema_ready": False}

# In-memory mode shares ONE connection between threads. Writers therefore take this lock for the whole
# transaction, so two analyses (or an analysis and a request) cannot interleave their writes.
# It is reentrant, so a writer may open a nested scope in the same thread.
_WRITE_LOCK = threading.RLock()


def _build_engine(settings: Settings) -> Engine:
    if settings.is_postgres:
        kwargs: dict = {"future": True, "pool_pre_ping": True, "pool_size": 5, "max_overflow": 10,
                        "pool_recycle": 1800}
        url = settings.database_url
        _state.update({"dialect": "postgresql", "storage": "postgres"})
    else:
        # In-memory only. A shared-cache memory database: every session gets its OWN connection to the
        # same database. (One connection shared by threads is not safe in sqlite3 and can crash the process.)
        # Writers are serialised by _WRITE_LOCK; readers do not take table locks (read_uncommitted).
        url = "sqlite:///file:repolens_mem?mode=memory&cache=shared&uri=true"
        kwargs = {"future": True, "poolclass": QueuePool, "pool_size": 10, "max_overflow": 20,
                  "connect_args": {"check_same_thread": False}}
        _state.update({"dialect": "sqlite", "storage": "memory"})
    try:
        engine = create_engine(url, **kwargs)
    except Exception as exc:  # pragma: no cover - misconfiguration path
        raise DatabaseError(f"Could not create database engine: {exc}",
                            hint="Check DATABASE_URL in your environment settings.") from exc

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            if not settings.is_postgres:
                cursor.execute("PRAGMA read_uncommitted=1")
            cursor.close()
        global _anchor
        # Hold one connection open for the life of the process, or the memory database is discarded.
        _anchor = engine.raw_connection()
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings())
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Rolls back and re-raises as DatabaseError."""
    with _WRITE_LOCK:
        factory = get_session_factory()
        session = factory()
        try:
            yield session
            session.commit()
        except Exception as exc:
            session.rollback()
            if isinstance(exc, DatabaseError):
                raise
            logger.exception("Database transaction failed")
            message = f"Database operation failed: {type(exc).__name__}: {exc}"
            raise DatabaseError(message, hint="Check the API logs for the failing statement.") from exc
        finally:
            session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def init_db() -> dict:
    """Create the schema (idempotent), then apply the default source-retention policy."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    _state["schema_ready"] = True
    _scrub_legacy_source_text()
    return dict(_state)


def _scrub_legacy_source_text() -> None:
    """Remove full files and legacy search excerpts when snippets are not explicitly enabled."""
    if get_settings().store_source_snippets:
        return
    try:
        with session_scope() as session:
            session.query(FileRecord).update({FileRecord.content: None}, synchronize_session=False)
            legacy_chunks = session.query(ChunkRecord).filter(
                ~ChunkRecord.text.startswith("__INDEX__ ")
            ).yield_per(500)
            for row in legacy_chunks:
                row.text = "__INDEX__ " + row.path + " " + (row.symbol or "")
    except Exception:
        logger.warning("Could not scrub legacy source excerpts", exc_info=True)


def database_state() -> dict:
    return dict(_state)


def reset_state_for_tests() -> None:  # pragma: no cover - test helper
    global _engine, _SessionLocal, _anchor
    if _anchor is not None:
        _anchor.close()
    _anchor = None
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _state["schema_ready"] = False
