"""Persistent per-window ownership and inactivity cleanup for analysis results.

Ownership is scoped to a server-issued browser session and one browser tab. The
records live in the same configured database as the analysis, so expiry continues
to work after an API restart when Postgres is enabled.
"""

from __future__ import annotations

import time

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from ..models.tables import Analysis, AnalysisWindow, BrowserSession


def add_owner(session: Session, analysis_id: str, session_id: str, window_id: str) -> None:
    now = time.time()
    owner = session.get(AnalysisWindow, (analysis_id, session_id, window_id))
    if owner is None:
        session.add(AnalysisWindow(
            analysis_id=analysis_id,
            session_id=session_id,
            window_id=window_id,
            created_at=now,
            last_seen_at=now,
        ))
    else:
        owner.last_seen_at = now


def owns(session: Session, analysis_id: str, session_id: str, window_id: str) -> AnalysisWindow | None:
    return session.get(AnalysisWindow, (analysis_id, session_id, window_id))


def release_owner(session: Session, analysis_id: str, session_id: str, window_id: str,
                  ttl_seconds: int) -> bool:
    """Remove one owner and return True if the analysis has no live owners left."""
    owner = owns(session, analysis_id, session_id, window_id)
    if owner is not None:
        session.delete(owner)
        session.flush()
    cutoff = time.time() - ttl_seconds
    live_owner = session.execute(
        select(AnalysisWindow.analysis_id)
        .where(AnalysisWindow.analysis_id == analysis_id, AnalysisWindow.last_seen_at >= cutoff)
        .limit(1)
    ).first()
    return live_owner is None


def expire_windows(session: Session, ttl_seconds: int, session_ttl_seconds: int) -> list[str]:
    """Prune stale leases and return analyses with no remaining owner."""
    now = time.time()
    cutoff = now - ttl_seconds
    # Rows left by a closed tab or an expired browser session must not keep artifacts alive.
    session.execute(delete(AnalysisWindow).where(AnalysisWindow.last_seen_at < cutoff))
    session_cutoff = now - session_ttl_seconds
    session.execute(delete(BrowserSession).where(
        (BrowserSession.expires_at <= now) | (BrowserSession.last_seen_at < session_cutoff)
    ))
    session.flush()

    has_owner = exists(select(AnalysisWindow.analysis_id).where(AnalysisWindow.analysis_id == Analysis.id))
    stale_ids = session.execute(
        select(Analysis.id)
        .where(~has_owner)
    ).scalars().all()
    return list(stale_ids)
