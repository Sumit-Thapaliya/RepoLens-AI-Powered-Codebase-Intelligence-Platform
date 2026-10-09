"""Hybrid code search.

Vector similarity (pgvector when available) blended with lexical overlap over
the same chunks. Both signals are real: the vector part comes from the
configured embedding provider, the lexical part from token overlap, and the
resulting score is reported per hit so the UI can show ranking confidence.
"""

from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from repolens_embeddings import get_embedder, lexical_score, unpack_vector
from repolens_shared.utils import truncate

from ..core.config import Settings
from ..core.db import database_state
from ..models.tables import ChunkRecord

logger = logging.getLogger(__name__)

VECTOR_WEIGHT = 0.65
LEXICAL_WEIGHT = 0.35


def get_query_embedder(settings: Settings):
    return get_embedder(
        settings.embeddings_provider,
        dim=settings.embedding_dim,
        api_key=settings.openai_api_key,
        model=settings.embeddings_model or "text-embedding-3-small",
        base_url=settings.openai_base_url,
    )


def search(session: Session, settings: Settings, analysis_id: str, query: str, *, limit: int = 12,
           paths: list[str] | None = None, kinds: list[str] | None = None) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    vector: list[float] = []
    try:
        embedder = get_query_embedder(settings)
        vector = embedder.embed_one(query)
    except Exception as exc:  # embedding provider outage must not break search
        logger.warning("Query embedding failed (%s); falling back to lexical ranking", exc)

    if database_state().get("pgvector") and vector:
        try:
            return _pgvector_search(session, analysis_id, query, vector, limit, paths, kinds)
        except Exception as exc:
            logger.warning("pgvector search failed (%s); falling back to in-process ranking", exc)
    return _in_process_search(session, analysis_id, query, vector, limit, paths, kinds)


def _pgvector_search(session: Session, analysis_id: str, query: str, vector: list[float], limit: int,
                     paths: list[str] | None, kinds: list[str] | None) -> list[dict]:
    literal = "[" + ",".join(f"{value:.6f}" for value in vector) + "]"
    clauses = ["analysis_id = :analysis_id", "embedding IS NOT NULL"]
    params: dict = {"analysis_id": analysis_id, "limit": max(limit * 3, 30), "vec": literal}
    if paths:
        clauses.append("path = ANY(:paths)")
        params["paths"] = paths
    if kinds:
        clauses.append("kind = ANY(:kinds)")
        params["kinds"] = kinds
    statement = sql_text(
        "SELECT id, path, symbol, kind, start_line, end_line, text, "
        "1 - (embedding <=> CAST(:vec AS vector)) AS similarity "
        f"FROM chunks WHERE {' AND '.join(clauses)} ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :limit"
    )
    rows = session.execute(statement, params).all()
    results = []
    for row in rows:
        semantic = float(row.similarity or 0.0)
        lexical = lexical_score(query, f"{row.path} {row.symbol or ''} {row.text}")
        results.append(_hit(row.id, row.path, row.symbol, row.kind, row.start_line, row.end_line, row.text,
                            semantic * VECTOR_WEIGHT + lexical * LEXICAL_WEIGHT))
    results.sort(key=lambda item: -item["score"])
    return results[:limit]


def _in_process_search(session: Session, analysis_id: str, query: str, vector: list[float], limit: int,
                       paths: list[str] | None, kinds: list[str] | None, scan_limit: int = 30_000) -> list[dict]:
    statement = select(ChunkRecord).where(ChunkRecord.analysis_id == analysis_id).limit(scan_limit)
    if paths:
        statement = statement.where(ChunkRecord.path.in_(paths))
    if kinds:
        statement = statement.where(ChunkRecord.kind.in_(kinds))
    rows = session.execute(statement).scalars().all()
    results: list[dict] = []
    for row in rows:
        semantic = _cosine(vector, unpack_vector(row.embedding)) if vector and row.embedding else 0.0
        lexical = lexical_score(query, f"{row.path} {row.symbol or ''} {row.text}")
        score = semantic * VECTOR_WEIGHT + lexical * LEXICAL_WEIGHT
        if score <= 0.01:
            continue
        results.append(_hit(row.id, row.path, row.symbol, row.kind, row.start_line, row.end_line, row.text, score))
    results.sort(key=lambda item: -item["score"])
    return results[:limit]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    length = min(len(a), len(b))
    dot = sum(a[index] * b[index] for index in range(length))
    norm_a = sum(value * value for value in a[:length]) ** 0.5 or 1.0
    norm_b = sum(value * value for value in b[:length]) ** 0.5 or 1.0
    return dot / (norm_a * norm_b)


def _hit(chunk_id: str, path: str, symbol: str | None, kind: str, start_line: int, end_line: int,
         body: str, score: float) -> dict:
    snippet = _snippet(body)
    return {
        "id": chunk_id, "path": path, "symbol": symbol, "kind": kind, "start_line": start_line,
        "end_line": end_line, "score": round(float(score), 4), "snippet": snippet,
    }


def _snippet(body: str, limit: int = 420) -> str:
    """Strip the synthetic header lines we add when indexing chunks."""
    lines = [line for line in (body or "").splitlines()
             if not line.startswith(("file: ", "language: ", "symbol: ", "purpose: ", "code:", "content:"))]
    cleaned = "\n".join(lines).strip() or (body or "")
    return truncate(cleaned, limit)


def search_text(session: Session, analysis_id: str, pattern: str, limit: int = 60) -> list[dict]:
    """Plain substring search across indexed chunk text (used by the explorer)."""
    needle = f"%{pattern.lower()}%"
    rows = session.execute(
        select(ChunkRecord).where(ChunkRecord.analysis_id == analysis_id,
                                  ChunkRecord.text.ilike(needle)).limit(limit)
    ).scalars().all()
    return [{"path": row.path, "symbol": row.symbol, "kind": row.kind, "start_line": row.start_line,
             "end_line": row.end_line, "snippet": _snippet(row.text, 260)} for row in rows]


def dedupe_by_path(hits: Iterable[dict], max_per_path: int = 2) -> list[dict]:
    counts: dict[str, int] = {}
    out: list[dict] = []
    for hit in hits:
        path = hit["path"]
        if counts.get(path, 0) >= max_per_path:
            continue
        counts[path] = counts.get(path, 0) + 1
        out.append(hit)
    return out
