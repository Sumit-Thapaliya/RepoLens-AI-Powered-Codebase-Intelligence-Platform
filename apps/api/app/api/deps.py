"""Shared FastAPI dependencies and request models."""

from __future__ import annotations

from typing import Annotated, Iterator

from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.db import get_db


class AnalyzeRequest(BaseModel):
    url: str = Field(..., description="Public GitHub repository URL", examples=["https://github.com/tiangolo/fastapi"])
    branch: str | None = Field(default=None, description="Branch to analyse (defaults to the default branch)")
    force: bool = Field(default=True, description="Start a new run even if one is already running")


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


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=2000)
    history: list[dict] = Field(default_factory=list, description="Previous turns: [{role, content}]")
    focus_path: str | None = None


class GenerateDocRequest(BaseModel):
    kind: str = Field(default="readme", description="readme | api | onboarding")
    use_llm: bool = Field(default=True, description="Use the configured LLM to polish the deterministic draft")


DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def pagination(limit: int = Query(default=100, ge=1, le=2000), offset: int = Query(default=0, ge=0)) -> tuple[int, int]:
    return limit, offset


def _unused(_value: Iterator) -> None:  # pragma: no cover - keeps typing imports honest
    return None
