"""Database engine, session management and schema bootstrap.

Postgres + pgvector is the production target (Neon). When the deployment has no
Postgres the API transparently falls back to SQLite: everything keeps working,
the vector column becomes JSON, and both the API and the UI report which backend
is live through ``/api/system/capabilities``.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from repolens_shared.errors import DatabaseError

from ..models.tables import Base
from .config import Settings, get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None
_state: dict[str, object] = {"pgvector": False, "dialect": "sqlite", "schema_ready": False}


def _build_engine(settings: Settings) -> Engine:
    url = settings.resolved_database_url()
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
        kwargs["pool_recycle"] = 1800
    try:
        engine = create_engine(url, **kwargs)
    except Exception as exc:  # pragma: no cover - misconfiguration path
        raise DatabaseError(f"Could not create database engine: {exc}",
                            hint="Check DATABASE_URL in your .env file.") from exc

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = _build_engine(settings)
        _state["dialect"] = "postgresql" if settings.is_postgres else "sqlite"
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Rolls back and re-raises as DatabaseError."""
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
        detail = None
        statement = getattr(exc, "statement", None)
        if statement:
            params = getattr(exc, "params", None)
            detail = {"statement": str(statement)[:600], "params": str(params)[:400] if params else None}
        message = f"Database operation failed: {type(exc).__name__}: {exc}"
        raise DatabaseError(message, detail=detail,
                            hint="Check the API logs; the failing statement is included in `detail`.") from exc
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


def has_pgvector(session: Session) -> bool:
    try:
        row = session.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'")).first()
        return row is not None
    except Exception:
        return False


#: Additive column migrations for long-lived databases: new analysis fields are
#: appended here so an existing developer database keeps working after an upgrade.
ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "api_endpoints": {
        "is_example": "BOOLEAN DEFAULT false",
        "is_test": "BOOLEAN DEFAULT false",
        "declarations": "JSON",
    },
    "workflows": {
        "scope": "VARCHAR(20)",
        "scope_note": "TEXT",
    },
}


def _ensure_columns(engine) -> list[str]:
    """Add missing columns in place. Idempotent and safe to run on every boot."""
    settings = get_settings()
    added: list[str] = []
    try:
        with engine.begin() as connection:
            for table, columns in ADDITIVE_COLUMNS.items():
                for name, ddl in columns.items():
                    try:
                        if settings.is_postgres:
                            present = connection.execute(text(
                                "SELECT 1 FROM information_schema.columns "
                                "WHERE table_name = :table AND column_name = :column"
                            ), {"table": table, "column": name}).first()
                        else:
                            present = name in {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
                        if present:
                            continue
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                        added.append(f"{table}.{name}")
                    except Exception as exc:  # pragma: no cover - best effort
                        logger.warning("Could not add column %s.%s: %s", table, name, exc)
    except Exception as exc:  # pragma: no cover - schema is created by create_all
        logger.warning("Column check skipped: %s", exc)
    return added


def init_db() -> dict:
    """Create extensions, tables and, when available, the vector column."""
    settings = get_settings()
    engine = get_engine()
    info = {"dialect": "postgresql" if settings.is_postgres else "sqlite", "pgvector": False, "vector_column": False}

    if settings.is_postgres:
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            info["pgvector"] = True
            info["vector_column"] = True
        except Exception as exc:
            logger.warning("pgvector extension unavailable (%s); falling back to JSON vectors", exc)
            info["pgvector"] = False

    Base.metadata.create_all(engine)
    added_columns = _ensure_columns(engine)
    if added_columns:
        info["added_columns"] = added_columns

    if settings.is_postgres:
        with engine.begin() as connection:
            existing = connection.execute(text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'chunks' AND column_name = 'embedding'"
            )).first()
            dimension = settings.embedding_dim
            if info["pgvector"] and (existing is None or existing[0] != "USER-DEFINED"):
                try:
                    connection.execute(text(f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({dimension}) "
                                            f"USING NULLIF(embedding, '')::vector"))
                    info["vector_column"] = True
                except Exception as exc:
                    logger.warning("Could not convert chunks.embedding to vector: %s", exc)
            elif info["pgvector"]:
                info["vector_column"] = True
            if info["vector_column"]:
                try:
                    connection.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding ON chunks "
                        "USING hnsw (embedding vector_cosine_ops)"
                    ))
                except Exception as exc:
                    logger.info("HNSW index not created (%s) - searching without an index", exc)

    _state.update(info)
    _state["schema_ready"] = True
    return info


def database_state() -> dict:
    return dict(_state)


def reset_state_for_tests() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
