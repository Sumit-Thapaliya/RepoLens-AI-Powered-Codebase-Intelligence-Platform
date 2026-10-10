"""Analysis run endpoints: start, poll, cancel, delete."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ..core.db import session_scope
from ..models.tables import Analysis, Repo
from ..services.analysis import get_manager
from ..services.store import NotFoundError, analysis_payload, get_analysis, get_overview, repo_payload, require_complete
from ..services.windows import get_windows
from .deps import AnalyzeRequest, DbSession, WindowRequest, require_window_owner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analyses", tags=["analysis"], dependencies=[Depends(require_window_owner)])


@router.post("")
async def create_analysis(payload: AnalyzeRequest, session: DbSession) -> dict:
    """Resolve the URL, import the repository and start analysing it."""
    manager = get_manager()
    result = await manager.create_run(payload.url, branch=payload.branch, force=payload.force)
    get_windows().track(result["analysis_id"], payload.window_id)
    # Refresh the session so the caller immediately sees the queued row.
    session.expire_all()
    analysis = get_analysis(session, result["analysis_id"])
    return {**result, "analysis": analysis_payload(analysis)}


@router.get("")
def list_analyses(session: DbSession, ids: str = "", limit: int = 20) -> dict:
    """Runs for the window that asks: pass its own ids (comma separated). Nothing else is listed."""
    wanted = [item.strip() for item in ids.split(",") if item.strip()][:50]
    if not wanted:
        return {"analyses": [], "in_flight": get_manager().in_flight()}
    statement = (select(Analysis).where(Analysis.id.in_(wanted))
                 .order_by(Analysis.created_at.desc()).limit(min(limit, 100)))
    rows = session.execute(statement).scalars().all()
    repo_ids = {row.repo_id for row in rows}
    repos = {repo.id: repo for repo in session.execute(select(Repo).where(Repo.id.in_(repo_ids))).scalars().all()} if repo_ids else {}
    return {
        "analyses": [
            {**analysis_payload(row),
             "repo": {"id": row.repo_id, "full_name": repos[row.repo_id].full_name if row.repo_id in repos else None,
                      "url": repos[row.repo_id].url if row.repo_id in repos else None}}
            for row in rows
        ],
        "in_flight": get_manager().in_flight(),
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
def heartbeat(analysis_id: str, payload: WindowRequest) -> dict:
    """Sent every few seconds by an open window. Keeps its runs alive."""
    with session_scope() as session:
        exists = session.get(Analysis, analysis_id) is not None
    if not exists:
        get_windows().forget(analysis_id)
    if not exists or not get_windows().heartbeat(analysis_id, payload.window_id):
        raise NotFoundError(f"Analysis `{analysis_id}` is no longer available.",
                            hint="It was discarded when its window closed or a new URL was submitted.")
    return {"alive": True}


@router.post("/{analysis_id}/release")
def release_run(analysis_id: str, payload: WindowRequest) -> dict:
    """A window lets go of a run (it submitted a new URL or removed the run).

    The run is deleted at once when no other open window still owns it.
    """
    if not get_windows().release(analysis_id, payload.window_id):
        return {"released": analysis_id, "discarded": False}
    discarded = get_manager().discard(analysis_id)
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
