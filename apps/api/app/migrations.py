"""Schema bootstrap for RepoLens.

`python -m app.migrations` is the one-shot job used by `docker compose` before the
API starts (and by the `migrate` step in any other deployment). It is idempotent:

1. ``init_db()`` creates/updates every ORM table (SQLite *and* Postgres).
2. On Postgres, the SQL files in ``infrastructure/migrations`` are applied in
   filename order - that is where pgvector lives. Applied files are recorded in
   ``schema_migrations`` so re-running is a no-op.
3. On SQLite the SQL files are skipped (they are Postgres-specific); vector
   ranking falls back to the in-process cosine implementation and the API reports
   that through ``/api/system/capabilities``.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from sqlalchemy import text

from .core.db import get_engine, init_db
from .core.logging import configure_logging

logger = logging.getLogger("repolens.migrations")

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "infrastructure" / "migrations"


def migrations_dir() -> Path:
    configured = os.environ.get("REPOLENS_MIGRATIONS_DIR")
    if configured:
        return Path(configured)
    return DEFAULT_MIGRATIONS_DIR


def _ensure_registry(connection) -> None:
    connection.execute(text(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
        """
    ))


def _applied(connection) -> set[str]:
    rows = connection.execute(text("SELECT filename FROM schema_migrations")).scalars().all()
    return set(rows)


def apply_migrations() -> dict:
    """Apply pending SQL migrations. Returns a small report for logging/tests."""
    engine = get_engine()
    report: dict[str, object] = {"dialect": engine.dialect.name, "applied": [], "skipped": []}

    info = init_db()
    report["tables"] = "created_or_verified"

    if engine.dialect.name != "postgresql":
        report["note"] = (
            "Non-Postgres database: pgvector migrations are not applicable. "
            "Vector search runs in-process (see /api/system/capabilities)."
        )
        logger.info("Skipping SQL migrations on %s (%s)", engine.dialect.name, report["note"])
        return report

    directory = migrations_dir()
    if not directory.exists():
        report["note"] = f"migrations directory {directory} not found"
        logger.warning("Migrations directory %s does not exist; nothing applied", directory)
        return report

    files = sorted(path for path in directory.glob("*.sql"))
    with engine.begin() as connection:
        _ensure_registry(connection)
        already = _applied(connection)
        for path in files:
            if path.name in already:
                report["skipped"].append(path.name)  # type: ignore[union-attr]
                continue
            sql = path.read_text(encoding="utf-8")
            for statement in _split_statements(sql):
                connection.execute(text(statement))
            connection.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:name)"), {"name": path.name}
            )
            report["applied"].append(path.name)  # type: ignore[union-attr]
            logger.info("Applied migration %s", path.name)

    report["pgvector"] = info.get("pgvector")
    report["vector_column"] = info.get("vector_column")
    return report


def _split_statements(sql: str) -> list[str]:
    """Split a .sql file on semicolons, ignoring comments and dollar-quoted blocks."""
    statements: list[str] = []
    buffer: list[str] = []
    dollar_tag: str | None = None
    for raw_line in sql.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not buffer and (not stripped or stripped.startswith("--")):
            continue

        if dollar_tag:
            buffer.append(line)
            if dollar_tag in line:
                dollar_tag = None
            continue

        body = stripped.split("--", 1)[0] if "--" in stripped else stripped
        if "$" in body:
            for token in body.split("$"):
                if token and token.isidentifier():
                    dollar_tag = f"${token}$"
                    break

        buffer.append(line)
        if body.endswith(";") and not dollar_tag:
            statements.append("\n".join(buffer).strip().rstrip(";"))
            buffer = []

    if buffer:
        statements.append("\n".join(buffer).strip().rstrip(";"))
    return [statement for statement in statements if statement]


def main() -> int:
    configure_logging("INFO")
    try:
        report = apply_migrations()
    except Exception as exc:  # pragma: no cover - surfaced to the operator
        logger.error("Migration failed: %s", exc)
        return 1
    logger.info("migrations: %s", report)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
