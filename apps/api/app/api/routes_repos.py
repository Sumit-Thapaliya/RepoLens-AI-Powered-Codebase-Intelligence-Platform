"""GitHub repository resolution and session-scoped repository management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from repolens_shared.errors import InvalidRepoUrlError
from repolens_shared.utils import normalize_repo_url

from ..core.config import get_settings
from ..core.db import session_scope
from ..models.tables import Analysis, AnalysisWindow
from ..services.analysis import get_manager
from ..services.github import GitHubClient
from ..services.store import find_repo_by_full_name, get_repo, repo_payload
from ..services.windows import add_owner
from .deps import (
    CurrentSession,
    DbSession,
    ReanalyseRequest,
    ResolveRequest,
    WindowId,
    enforce_analysis_quota,
    require_session,
)

router = APIRouter(
    prefix="/repos",
    tags=["repositories"],
    dependencies=[Depends(require_session)],
)


@router.post("/resolve")
async def resolve_repository(payload: ResolveRequest) -> dict:
    """Validate a GitHub URL and check the caller can read repository metadata."""
    settings = get_settings()
    try:
        owner, name, canonical = normalize_repo_url(payload.url)
    except ValueError as exc:
        raise InvalidRepoUrlError(
            str(exc),
            hint="Paste a GitHub repository URL such as https://github.com/owner/repo",
        ) from exc
    async with GitHubClient(settings) as client:
        metadata = await client.get_repo(owner, name)
        branches = await client.get_branches(owner, name)
        rate = await client.rate_limit()
    return {
        "repo": metadata.model_dump(mode="json"),
        "branches": [branch.model_dump() for branch in branches],
        "canonical_url": canonical,
        "github_rate_limit": rate,
        "already_imported": _imported_repo_id(metadata.full_name),
    }


@router.get("/{repo_id}")
def get_repository(repo_id: str, session: DbSession) -> dict:
    """Return repository metadata to an authenticated browser session."""
    return {"repo": repo_payload(get_repo(session, repo_id))}


@router.post("/{repo_id}/analyse")
async def analyse_imported(
    repo_id: str,
    session: DbSession,
    session_id: CurrentSession,
    window_id: WindowId,
    payload: ReanalyseRequest | None = None,
) -> dict:
    """Reanalyse a repository and attach the run to the caller's authenticated tab."""
    enforce_analysis_quota(session, session_id, get_settings())
    repo = get_repo(session, repo_id)
    session.commit()
    result = await get_manager().reanalyse(
        repo.id,
        branch=payload.branch if payload else None,
        force=payload.force if payload else True,
        owner_session_id=session_id,
    )
    add_owner(session, result["analysis_id"], session_id, window_id)
    session.commit()
    return result


@router.delete("/{repo_id}")
def delete_repository(repo_id: str, session: DbSession, session_id: CurrentSession) -> dict:
    """Delete a repository only when every analysis belongs to this session.

    Repository metadata is shared, so one session is never allowed to cascade-delete
    another session's analysis artifacts.
    """
    repo = get_repo(session, repo_id)
    all_ids = set(session.execute(
        select(Analysis.id).where(Analysis.repo_id == repo_id)
    ).scalars().all())
    owned_ids = set(session.execute(
        select(AnalysisWindow.analysis_id)
        .join(Analysis, AnalysisWindow.analysis_id == Analysis.id)
        .where(Analysis.repo_id == repo_id, AnalysisWindow.session_id == session_id)
    ).scalars().all())
    shared_ids = set(session.execute(
        select(AnalysisWindow.analysis_id)
        .where(AnalysisWindow.analysis_id.in_(all_ids or {""}), AnalysisWindow.session_id != session_id)
    ).scalars().all())
    if (all_ids - owned_ids) or shared_ids:
        raise HTTPException(
            status_code=409,
            detail="This repository has analysis data owned by another session; it was not deleted.",
        )
    if all_ids:
        pending = [analysis_id for analysis_id in all_ids if not get_manager().discard(analysis_id)]
        if pending:
            raise HTTPException(
                status_code=409,
                detail="Active analyses are being cancelled. Retry deletion after they stop.",
            )
    else:
        session.delete(repo)
        session.commit()
    return {"deleted": repo_id}


def _imported_repo_id(full_name: str) -> str | None:
    try:
        with session_scope() as session:
            repo = find_repo_by_full_name(session, full_name)
            return repo.id if repo else None
    except Exception:
        return None
