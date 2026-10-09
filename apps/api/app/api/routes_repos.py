"""Repository endpoints: validate/import a GitHub URL and list imported repos."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from repolens_shared.errors import RepoLensError
from repolens_shared.utils import normalize_repo_url

from ..core.config import get_settings
from ..models.tables import Analysis
from ..services.github import GitHubClient
from ..services.store import find_repo_by_full_name, get_repo, latest_analysis, list_repos, repo_payload
from ..services.analysis import get_manager
from .deps import AnalyzeRequest, DbSession, ResolveRequest
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/repos", tags=["repositories"])


@router.post("/resolve")
async def resolve_repository(payload: ResolveRequest) -> dict:
    """Validate a URL and return GitHub metadata + branch list without analysing."""
    settings = get_settings()
    try:
        owner, name, canonical = normalize_repo_url(payload.url)
    except ValueError as exc:
        raise RepoLensError(str(exc), hint="Paste a public repository URL such as https://github.com/owner/repo") from exc
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


@router.get("")
def list_imported(limit: int = 20) -> dict:
    from ..core.db import session_scope
    with session_scope() as session:
        return {"repos": list_repos(session, limit=limit)}


@router.get("/{repo_id}")
def get_repository(repo_id: str, include_analyses: bool = False) -> dict:
    from ..core.db import session_scope
    with session_scope() as session:
        repo = get_repo(session, repo_id)
        payload = {"repo": repo_payload(repo),
                   "last_analysis": (lambda a: None if a is None else _analysis_summary(a))(latest_analysis(session, repo_id))}
        if include_analyses:
            rows = session.execute(select(Analysis).where(Analysis.repo_id == repo_id)
                                   .order_by(Analysis.created_at.desc()).limit(20)).scalars().all()
            payload["analyses"] = [_analysis_summary(row) for row in rows]
        return payload


@router.post("/{repo_id}/analyse")
async def analyse_imported(repo_id: str, payload: AnalyzeRequest | None = None) -> dict:
    from ..core.db import session_scope
    with session_scope() as session:
        repo = get_repo(session, repo_id)
    manager = get_manager()
    result = await manager.reanalyse(repo.id, branch=payload.branch if payload else None,
                                     force=payload.force if payload else True)
    return result


@router.delete("/{repo_id}")
def delete_repository(repo_id: str) -> dict:
    from ..core.db import session_scope
    with session_scope() as session:
        repo = get_repo(session, repo_id)
        session.delete(repo)
    return {"deleted": repo_id}


def _analysis_summary(analysis: Analysis) -> dict:
    from ..services.store import analysis_payload
    return analysis_payload(analysis)


def _imported_repo_id(full_name: str) -> str | None:
    from ..core.db import session_scope
    try:
        with session_scope() as session:
            repo = find_repo_by_full_name(session, full_name)
            return repo.id if repo else None
    except Exception:
        return None
