"""Code search over the indexed chunks of one analysis.

Ranking is lexical: identifier-aware token overlap between the query and each chunk
(path, symbol and code text). It is deterministic, needs no model or API key, and stores no
vectors, which keeps storage small. Every hit reports its score so the UI can show it.
"""

from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from repolens_shared.utils import truncate

from ..core.config import Settings
from ..models.tables import ChunkRecord

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}|\d+")
_SYNTHETIC_PREFIXES = ("file: ", "language: ", "symbol: ", "purpose: ", "code:", "content:")
SCAN_LIMIT = 30_000


def lexical_score(query: str, text: str) -> float:
    """Token-overlap score in [0, 1.5]; rewards identifier-shaped and repeated matches."""
    query_tokens = {token.lower() for token in _TOKEN_RE.findall(query)}
    if not query_tokens:
        return 0.0
    text_lower = text.lower()
    overlap = query_tokens & set(_TOKEN_RE.findall(text_lower))
    if not overlap:
        return 0.0
    score = len(overlap) / len(query_tokens)
    for token in overlap:
        if len(token) > 4:
            occurrences = text_lower.count(token)
            if occurrences:
                score += min(0.25, 0.05 * occurrences)
    return min(1.5, score)


def search(session: Session, settings: Settings, analysis_id: str, query: str, *, limit: int = 12,
           paths: list[str] | None = None, kinds: list[str] | None = None) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    statement = select(ChunkRecord).where(ChunkRecord.analysis_id == analysis_id).limit(SCAN_LIMIT)
    if paths:
        statement = statement.where(ChunkRecord.path.in_(paths))
    if kinds:
        statement = statement.where(ChunkRecord.kind.in_(kinds))
    results: list[dict] = []
    for row in session.execute(statement).scalars().all():
        score = lexical_score(query, f"{row.path} {row.symbol or ''} {row.text}")
        if score <= 0.01:
            continue
        results.append(_hit(row.id, row.path, row.symbol, row.kind, row.start_line, row.end_line, row.text, score))
    results.sort(key=lambda item: -item["score"])
    return results[:limit]


def _hit(chunk_id: str, path: str, symbol: str | None, kind: str, start_line: int, end_line: int,
         body: str, score: float) -> dict:
    return {
        "id": chunk_id, "path": path, "symbol": symbol, "kind": kind, "start_line": start_line,
        "end_line": end_line, "score": round(float(score), 4), "snippet": _snippet(body),
    }


def _snippet(body: str, limit: int = 420) -> str:
    """Return a source excerpt only when explicitly enabled; otherwise explain the privacy-safe index."""
    if (body or "").startswith("__INDEX__ "):
        return "Source text is not retained. Open this result to fetch the file from GitHub."
    lines = [line for line in (body or "").splitlines() if not line.startswith(_SYNTHETIC_PREFIXES)]
    cleaned = "\n".join(lines).strip() or (body or "")
    return truncate(cleaned, limit)


def search_text(session: Session, analysis_id: str, pattern: str, limit: int = 60) -> list[dict]:
    """Search exact stored snippets when enabled, otherwise match all query identifiers."""
    query_terms = {token.casefold() for token in _TOKEN_RE.findall(pattern or "")}
    if not query_terms:
        return []
    rows = session.execute(
        select(ChunkRecord).where(ChunkRecord.analysis_id == analysis_id).limit(SCAN_LIMIT)
    ).scalars().all()
    matches = []
    needle = (pattern or "").casefold()
    for row in rows:
        if row.text.startswith("__INDEX__ "):
            terms = {token.casefold() for token in _TOKEN_RE.findall(row.text)}
            matched = query_terms.issubset(terms)
        else:
            matched = needle in row.text.casefold()
        if matched:
            matches.append({"path": row.path, "symbol": row.symbol, "kind": row.kind,
                            "start_line": row.start_line, "end_line": row.end_line,
                            "snippet": _snippet(row.text, 260)})
            if len(matches) >= min(max(limit, 1), 500):
                break
    return matches


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
