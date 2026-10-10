"""Shared FastAPI dependencies and request models."""

from __future__ import annotations

from typing import Annotated, Iterator

from fastapi import Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.db import get_db
from ..services.store import NotFoundError
from ..services.windows import get_windows


def require_window_owner(
    request: Request,
    x_window_id: Annotated[str | None, Header()] = None,
) -> None:
    """Only the window that started an analysis may read it.

    The browser sends its window id in the X-Window-Id header. Any other caller gets "not found",
    so the response does not reveal whether the analysis exists.
    """
    analysis_id = request.path_params.get("analysis_id")
    if analysis_id is None:
        return
    if not x_window_id or not get_windows().is_owner(analysis_id, x_window_id):
        raise NotFoundError(f"Analysis `{analysis_id}` was not found.",
                            hint="Analyses belong to the browser window that started them.")


class AnalyzeRequest(BaseModel):
    url: str = Field(..., description="Public GitHub repository URL", examples=["https://github.com/tiangolo/fastapi"])
    branch: str | None = Field(default=None, description="Branch to analyse (defaults to the default branch)")
    force: bool = Field(default=True, description="Start a new run even if one is already running")
    window_id: str | None = Field(default=None, max_length=64, description="Browser window that owns the run")


class WindowRequest(BaseModel):
    window_id: str = Field(..., min_length=1, max_length=64, description="Browser window that owns the run")


class ResolveRequest(BaseModel):
    url: str = Field(..., description="Public GitHub repository URL")


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


DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def pagination(limit: int = Query(default=100, ge=1, le=2000), offset: int = Query(default=0, ge=0)) -> tuple[int, int]:
    return limit, offset


def _unused(_value: Iterator) -> None:  # pragma: no cover - keeps typing imports honest
    return None
