"""Vector store backends.

* ``PgVectorStore`` - Postgres + pgvector (Neon), cosine distance in SQL.
* ``MemoryVectorStore`` - pure Python fallback for SQLite/offline development.

Both expose the same interface so the search service does not care which one is
active; the active backend is reported by ``/api/system/capabilities`` and shown
in the UI.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from repolens_shared.errors import DatabaseError

from .embedder import cosine_similarity, pack_vector, unpack_vector

logger = logging.getLogger(__name__)


@dataclass
class StoredChunk:
    id: str
    path: str
    symbol: str | None
    kind: str
    start_line: int
    end_line: int
    text: str
    score: float = 0.0


_LEXICAL_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}|\d+")


def lexical_score(query: str, text: str) -> float:
    """Dependency-free BM25-ish overlap score used to blend with vectors."""
    query_tokens = {token.lower() for token in _LEXICAL_TOKEN_RE.findall(query)}
    if not query_tokens:
        return 0.0
    text_lower = text.lower()
    text_tokens = set(_LEXICAL_TOKEN_RE.findall(text_lower))
    overlap = query_tokens & text_tokens
    if not overlap:
        return 0.0
    score = len(overlap) / len(query_tokens)
    # reward exact phrase hits and identifier-shaped matches
    for token in overlap:
        if len(token) > 4:
            occurrences = text_lower.count(token)
            if occurrences:
                score += min(0.25, 0.05 * occurrences)
    return min(1.5, score)


class MemoryVectorStore:
    """In-process hybrid store. Scales to tens of thousands of chunks."""

    backend = "memory"

    def __init__(self) -> None:
        self._rows: list[tuple[str, list[float], StoredChunk]] = []

    def add(self, analysis_id: str, chunks: list[tuple[StoredChunk, list[float]]]) -> None:
        for chunk, vector in chunks:
            self._rows.append((analysis_id, vector, chunk))

    def clear(self, analysis_id: str) -> None:
        self._rows = [row for row in self._rows if row[0] != analysis_id]

    def search(self, analysis_id: str, query: str, query_vector: list[float], limit: int = 12,
               paths: list[str] | None = None, kinds: list[str] | None = None) -> list[StoredChunk]:
        results: list[StoredChunk] = []
        for row_analysis, vector, chunk in self._rows:
            if row_analysis != analysis_id:
                continue
            if paths and chunk.path not in paths:
                continue
            if kinds and chunk.kind not in kinds:
                continue
            semantic = cosine_similarity(query_vector, vector) if query_vector else 0.0
            lexical = lexical_score(query, f"{chunk.path} {chunk.symbol or ''} {chunk.text}")
            score = semantic * 0.65 + lexical * 0.35
            if score <= 0:
                continue
            results.append(StoredChunk(chunk.id, chunk.path, chunk.symbol, chunk.kind, chunk.start_line,
                                       chunk.end_line, chunk.text, round(score, 4)))
        results.sort(key=lambda item: -item.score)
        return results[:limit]

    def count(self, analysis_id: str | None = None) -> int:
        return sum(1 for row in self._rows if analysis_id is None or row[0] == analysis_id)


class PgVectorStore:
    """Postgres + pgvector store, embedded in the main SQLAlchemy session."""

    backend = "pgvector"

    def __init__(self, session, table, chunk_model, dialect: str = "postgresql"):
        self.session = session
        self.table = table
        self.chunk_model = chunk_model

    def _vector_literal(self, vector: list[float]) -> str:
        return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"

    def add(self, analysis_id: str, chunks: list[tuple[StoredChunk, list[float]]]) -> None:
        for chunk, vector in chunks:
            self.session.execute(
                self.table.update().where(self.table.c.id == chunk.id).values(embedding=self._vector_literal(vector))
            )

    def clear(self, analysis_id: str) -> None:
        return None

    def search(self, analysis_id: str, query: str, query_vector: list[float], limit: int = 12,
               paths: list[str] | None = None, kinds: list[str] | None = None) -> list[StoredChunk]:
        if not query_vector:
            return []
        from sqlalchemy import select

        distance = self.table.c.embedding.cosine_distance(self._vector_literal(query_vector)).label("distance")
        statement = select(
            self.table.c.id, self.table.c.path, self.table.c.symbol, self.table.c.kind,
            self.table.c.start_line, self.table.c.end_line, self.table.c.text, distance,
        ).where(self.table.c.analysis_id == analysis_id)
        if paths:
            statement = statement.where(self.table.c.path.in_(paths))
        if kinds:
            statement = statement.where(self.table.c.kind.in_(kinds))
        statement = statement.order_by(distance).limit(max(limit * 3, 24))
        try:
            rows = self.session.execute(statement).all()
        except Exception as exc:  # pragma: no cover - depends on live DB
            raise DatabaseError(f"pgvector search failed: {exc}") from exc
        results: list[StoredChunk] = []
        for row in rows:
            semantic = 1.0 - float(row.distance)
            lexical = lexical_score(query, f"{row.path} {row.symbol or ''} {row.text}")
            score = semantic * 0.65 + lexical * 0.35
            results.append(StoredChunk(row.id, row.path, row.symbol, row.kind, row.start_line, row.end_line,
                                       row.text, round(score, 4)))
        results.sort(key=lambda item: -item.score)
        return results[:limit]

    def count(self, analysis_id: str | None = None) -> int:
        from sqlalchemy import func, select
        statement = select(func.count()).select_from(self.table)
        if analysis_id:
            statement = statement.where(self.table.c.analysis_id == analysis_id)
        return int(self.session.execute(statement).scalar() or 0)


__all__ = ["MemoryVectorStore", "PgVectorStore", "StoredChunk", "lexical_score", "pack_vector", "unpack_vector"]
