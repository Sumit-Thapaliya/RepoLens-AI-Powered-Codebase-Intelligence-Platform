"""Shared FastAPI dependencies, session authorization and request models."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.db import get_db
from ..models.tables import Analysis, AnalysisWindow
from ..services.sessions import require_session as validate_browser_session
from ..services.store import NotFoundError
from ..services.windows import owns

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
WindowId = Annotated[str, Header(alias="X-Window-Id", min_length=1, max_length=64)]
OptionalWindowId = Annotated[str | None, Header(alias="X-Window-Id", max_length=64)]


def require_session(request: Request, response: Response, session: DbSession) -> str:
    """Require the server-issued HttpOnly cookie and refresh its idle expiry."""
    return validate_browser_session(request, response, session, get_settings())


CurrentSession = Annotated[str, Depends(require_session)]


def require_window_owner(
    request: Request,
    session: DbSession,
    session_id: CurrentSession,
    x_window_id: OptionalWindowId = None,
) -> None:
    """Authorize analysis requests against the cookie-backed session and tab lease."""
    if not x_window_id:
        raise NotFoundError("Analysis was not found.",
                            hint="A valid X-Window-Id header is required for analysis requests.")
    analysis_id = request.path_params.get("analysis_id")
    if analysis_id is None:
        return
    owner = owns(session, analysis_id, session_id, x_window_id)
    if owner is None:
        raise NotFoundError(f"Analysis `{analysis_id}` was not found.",
                            hint="Analyses belong to the browser session and tab that started them.")
    owner.last_seen_at = time.time()
    session.commit()


def enforce_analysis_quota(session: Session, session_id: str, settings: Settings) -> None:
    """Bound concurrent and hourly analysis submissions for one authenticated session."""
    active = session.execute(
        select(func.count(distinct(Analysis.id)))
        .join(AnalysisWindow, AnalysisWindow.analysis_id == Analysis.id)
        .where(
            AnalysisWindow.session_id == session_id,
            Analysis.status.in_(["queued", "running"]),
        )
    ).scalar_one()
    if active >= settings.max_active_analyses_per_session:
        raise HTTPException(
            status_code=429,
            detail=f"This session already has {active} active analysis job(s).",
            headers={"Retry-After": "30"},
        )

    cutoff = datetime.fromtimestamp(time.time() - 3600, timezone.utc)
    recent = session.execute(
        select(func.count(distinct(Analysis.id)))
        .join(AnalysisWindow, AnalysisWindow.analysis_id == Analysis.id)
        .where(AnalysisWindow.session_id == session_id, Analysis.created_at >= cutoff)
    ).scalar_one()
    if recent >= settings.max_analyses_per_hour:
        raise HTTPException(
            status_code=429,
            detail=f"This session has reached the limit of {settings.max_analyses_per_hour} analyses per hour.",
            headers={"Retry-After": "3600"},
        )


class AnalyzeRequest(BaseModel):
    url: str = Field(..., description="GitHub repository URL", examples=["https://github.com/tiangolo/fastapi"])
    branch: str | None = Field(default=None, description="Branch to analyse (defaults to the default branch)")
    force: bool = Field(default=True, description="Start a fresh analysis instead of reusing this session's active run")
    window_id: str | None = Field(default=None, max_length=64, description="Browser tab that owns the run")


class ReanalyseRequest(BaseModel):
    branch: str | None = Field(default=None, description="Branch to analyse (defaults to the default branch)")
    force: bool = Field(default=True, description="Start a fresh analysis instead of reusing this session's active run")


class WindowRequest(BaseModel):
    window_id: str = Field(..., min_length=1, max_length=64, description="Browser tab that owns the run")


class ResolveRequest(BaseModel):
    url: str = Field(..., description="GitHub repository URL")


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=400)
    limit: int = Field(default=12, ge=1, le=50)
    paths: list[str] | None = Field(default=None, description="Restrict the search to these files")
    kinds: list[str] | None = Field(default=None, description="Restrict to symbol/file/doc chunks")


class ImpactRequest(BaseModel):
    path: str = Field(..., description="File path inside the analysed repository")
    symbol: str | None = Field(default=None, description="Optional symbol name to narrow the analysis")
    depth: int = Field(default=3, ge=1, le=5)


class GenerateDocRequest(BaseModel):
    kind: str = Field(default="readme", description="readme | api | onboarding")


def pagination(limit: int = Query(default=100, ge=1, le=2000), offset: int = Query(default=0, ge=0)) -> tuple[int, int]:
    return limit, offset
