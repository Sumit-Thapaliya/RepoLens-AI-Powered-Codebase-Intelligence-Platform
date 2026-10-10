"""Analysis run endpoints: start, poll, cancel, delete."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..core.db import session_scope
from ..models.tables import Analysis, AnalysisWindow, Repo
from ..services.analysis import get_manager
from ..services.store import NotFoundError, analysis_payload, get_analysis, get_overview, repo_payload, require_complete
from ..services.windows import add_owner, release_owner
from .deps import (
    AnalyzeRequest,
    CurrentSession,
    DbSession,
    WindowId,
    WindowRequest,
    enforce_analysis_quota,
    require_window_owner,
)
from ..core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analyses", tags=["analysis"], dependencies=[Depends(require_window_owner)])


@router.post("")
async def create_analysis(
    payload: AnalyzeRequest,
    session: DbSession,
    session_id: CurrentSession,
    window_id: WindowId,
) -> dict:
    """Resolve the URL, authorize its owner, and enqueue one analysis job."""
    if payload.window_id and payload.window_id != window_id:
        raise HTTPException(status_code=400, detail="The body window_id must match the X-Window-Id header.")
    settings = get_settings()
    enforce_analysis_quota(session, session_id, settings)
    session.commit()
    result = await get_manager().create_run(
        payload.url,
        branch=payload.branch,
        force=payload.force,
        owner_session_id=session_id,
    )
    add_owner(session, result["analysis_id"], session_id, window_id)
    session.commit()
    # Refresh the session so the caller immediately sees the queued row.
    session.expire_all()
    analysis = get_analysis(session, result["analysis_id"])
    return {**result, "analysis": analysis_payload(analysis)}


@router.get("")
def list_analyses(
    session: DbSession,
    session_id: CurrentSession,
    window_id: WindowId,
    ids: str = "",
    limit: int = 20,
) -> dict:
    """Return only analyses owned by this authenticated session and browser tab."""
    wanted = [item.strip() for item in ids.split(",") if item.strip()][:50]
    statement = (
        select(Analysis)
        .join(AnalysisWindow, AnalysisWindow.analysis_id == Analysis.id)
        .where(AnalysisWindow.session_id == session_id, AnalysisWindow.window_id == window_id)
        .order_by(Analysis.created_at.desc())
    )
    if wanted:
        statement = statement.where(Analysis.id.in_(wanted))
    rows = session.execute(statement.limit(min(max(limit, 1), 100))).scalars().all()
    own_in_flight = {row.id for row in rows if row.status in {"queued", "running"}}
    repo_ids = {row.repo_id for row in rows}
    repos = {
        repo.id: repo
        for repo in session.execute(select(Repo).where(Repo.id.in_(repo_ids))).scalars().all()
    } if repo_ids else {}
    return {
        "analyses": [
            {**analysis_payload(row),
             "repo": {"id": row.repo_id, "full_name": repos[row.repo_id].full_name if row.repo_id in repos else None,
                      "url": repos[row.repo_id].url if row.repo_id in repos else None}}
            for row in rows
        ],
        "in_flight": [analysis_id for analysis_id in get_manager().in_flight() if analysis_id in own_in_flight],
    }


@router.get("/{analysis_id}")
def get_run(analysis_id: str, session: DbSession, include_overview: bool = False) -> dict:
    analysis = get_analysis(session, analysis_id)
    payload = {"analysis": analysis_payload(analysis)}
    repo = session.get(Repo, analysis.repo_id)
    if repo is not None:
        payload["repo"] = repo_payload(repo)
    if include_overview and analysis.status == "complete":
        payload["overview"] = get_overview(session, analysis_id)
    return payload


@router.post("/{analysis_id}/cancel")
async def cancel_run(analysis_id: str, session: DbSession) -> dict:
    analysis = get_analysis(session, analysis_id)
    if analysis.status in {"complete", "failed", "cancelled"}:
        return {"analysis": analysis_payload(analysis), "cancelled": False,
                "message": f"Run already {analysis.status}."}
    cancelled = get_manager().cancel(analysis_id)
    if not cancelled:
        # The run may belong to a previous API process; mark it cancelled anyway.
        with session_scope() as write_session:
            row = write_session.get(Analysis, analysis_id)
            if row is not None:
                row.status = "cancelled"
                row.message = "Cancelled by user (run was not active in this process)."
    session.expire_all()
    return {"analysis": analysis_payload(get_analysis(session, analysis_id)), "cancelled": True}


@router.post("/{analysis_id}/heartbeat")
def heartbeat(analysis_id: str, payload: WindowRequest, window_id: WindowId) -> dict:
    """Keep this authenticated tab's persistent analysis lease alive."""
    if payload.window_id != window_id:
        raise NotFoundError(f"Analysis `{analysis_id}` is no longer available.")
    return {"alive": True}


@router.post("/{analysis_id}/release")
def release_run(
    analysis_id: str,
    payload: WindowRequest,
    session: DbSession,
    session_id: CurrentSession,
    window_id: WindowId,
) -> dict:
    """Release this tab's lease and delete the results when no live owner remains."""
    if payload.window_id != window_id:
        raise NotFoundError(f"Analysis `{analysis_id}` was not found.")
    no_live_owners = release_owner(
        session, analysis_id, session_id, window_id, get_settings().window_ttl_seconds
    )
    session.commit()
    discarded = get_manager().discard(analysis_id) if no_live_owners else False
    return {"released": analysis_id, "discarded": discarded}


@router.delete("/{analysis_id}")
def delete_run(analysis_id: str) -> dict:
    """Delete a run now. If it is still running it is cancelled and removed as soon as it stops."""
    removed = get_manager().discard(analysis_id)
    return {"deleted": analysis_id, "pending": not removed}


@router.get("/{analysis_id}/bundle")
def export_bundle(analysis_id: str, session: DbSession) -> dict:
    """Full JSON export of a completed analysis (useful for CI or offline review)."""
    analysis = require_complete(session, analysis_id)
    from ..services.store import (
        get_architecture,
        get_database,
        get_dependencies,
        get_quality,
        list_endpoints,
        list_frameworks,
        list_manifests,
        list_workflows,
    )

    return {
        "analysis": analysis_payload(analysis),
        "overview": get_overview(session, analysis_id),
        "architecture": get_architecture(session, analysis_id),
        "endpoints": list_endpoints(session, analysis_id),
        "database": get_database(session, analysis_id),
        "workflows": list_workflows(session, analysis_id, limit=200),
        "dependencies": get_dependencies(session, analysis_id, limit=600),
        "quality": get_quality(session, analysis_id),
        "frameworks": list_frameworks(session, analysis_id),
        "manifests": list_manifests(session, analysis_id),
    }
