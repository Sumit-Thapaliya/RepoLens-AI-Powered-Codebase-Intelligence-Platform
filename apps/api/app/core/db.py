"""In-memory SQLite database and session management.

All analysis records live in RAM and disappear when the API process stops. Source
checkouts are temporary files and are deleted after a run or on startup.
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
from .config import get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_anchor = None  # Keeps the named in-memory database alive for the process lifetime.
_SessionLocal: sessionmaker | None = None
_state: dict[str, object] = {"dialect": "sqlite", "storage": "memory", "schema_ready": False}

# SQLite shared-cache memory databases allow concurrent reads but only one writer.
# Hold this regular (cross-thread releasable) lock from the first DML statement to
# transaction completion, covering both request sessions and background sessions.
_SQLITE_WRITE_LOCK = threading.Lock()
_LOCK_FLAG = "_repolens_sqlite_write_lock"


def _release_record_lock(_dbapi_connection, connection_record) -> None:
    # Pool check-in happens after the DBAPI commit/rollback has completed. The
    # ConnectionEvents commit/rollback hooks fire before that operation, which
    # would release the writer lock too early and allow another UPDATE to race.
    if connection_record.info.pop(_LOCK_FLAG, False):
        _SQLITE_WRITE_LOCK.release()


def _build_engine() -> Engine:
    url = "sqlite:///file:repolens_mem?mode=memory&cache=shared&uri=true"
    try:
        engine = create_engine(
            url,
            future=True,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
    except Exception as exc:  # pragma: no cover - defensive startup error
        raise DatabaseError(f"Could not create the in-memory database: {exc}") from exc

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - exercised on connect
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA read_uncommitted=1")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    @event.listens_for(engine, "before_cursor_execute")
    def _serialize_sqlite_writes(connection, _cursor, statement, _parameters, _context, _executemany):
        first_word = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
        if first_word in {"INSERT", "UPDATE", "DELETE", "REPLACE"} and not connection.info.get(_LOCK_FLAG):
            _SQLITE_WRITE_LOCK.acquire()
            connection.info[_LOCK_FLAG] = True

    event.listen(engine.pool, "checkin", _release_record_lock)

    global _anchor
    _anchor = engine.raw_connection()
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Rolls back and wraps unexpected DB errors consistently."""
    session = get_session_factory()()
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
    """FastAPI request session. SQLite writes are serialized by engine transaction hooks."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_db() -> dict:
    """Create the in-memory schema, then remove any legacy retained source text."""
    Base.metadata.create_all(get_engine())
    _state["schema_ready"] = True
    _scrub_legacy_source_text()
    return dict(_state)


def _scrub_legacy_source_text() -> None:
    """Remove legacy full files and search excerpts if they exist in the current process."""
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
