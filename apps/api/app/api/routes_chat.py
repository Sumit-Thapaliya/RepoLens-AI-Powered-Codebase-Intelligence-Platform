"""Session-owned repository chat backed by Neon pgvector retrieval."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..models.tables import Analysis, Repo
from ..services.rag import (
    RagIndexMissing,
    RagNotConfigured,
    RagProviderFailure,
    RagService,
    RagServiceError,
    RagStorageFailure,
)
from ..services.store import NotFoundError
from .deps import CurrentSession, DbSession, require_window_owner

router = APIRouter(
    prefix="/analyses",
    tags=["repository chat"],
    dependencies=[Depends(require_window_owner)],
)

_rate_lock = threading.Lock()
_chat_requests: dict[str, deque[float]] = defaultdict(deque)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1_200)

    @field_validator("content")
    @classmethod
    def _trim_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("chat history messages cannot be blank")
        return cleaned


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1_200)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)

    @field_validator("question")
    @classmethod
    def _trim_question(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("question must contain at least two non-whitespace characters")
        return cleaned


def _analysis_and_repo(analysis_id: str, session: Session) -> tuple[Analysis, Repo]:
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise NotFoundError("Analysis was not found.")
    if analysis.status != "complete":
        raise HTTPException(status_code=409, detail="Repository chat is available after analysis completes.")
    repo = session.get(Repo, analysis.repo_id)
    if repo is None:
        raise NotFoundError("Repository was not found.")
    return analysis, repo


def _take_chat_slot(session_id: str, max_per_minute: int) -> None:
    now = time.monotonic()
    cutoff = now - 60
    with _rate_lock:
        bucket = _chat_requests[session_id]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= max_per_minute:
            raise HTTPException(
                status_code=429,
                detail="AI chat is receiving too many requests. Please wait a minute and try again.",
                headers={"Retry-After": "60"},
            )
        bucket.append(now)
        # Bound stale session keys on long-lived API processes.
        if len(_chat_requests) > 5_000:
            for key in list(_chat_requests)[:1_000]:
                stale = _chat_requests[key]
                while stale and stale[0] <= cutoff:
                    stale.popleft()
                if not stale:
                    _chat_requests.pop(key, None)


@router.get("/{analysis_id}/chat/status")
async def get_chat_status(
    analysis_id: str,
    session: DbSession,
    _session_id: CurrentSession,
    settings: Settings = Depends(get_settings),
) -> dict:
    analysis, repo = _analysis_and_repo(analysis_id, session)
    service = RagService(settings)
    status = await service.status(repo.full_name, analysis.commit_sha)
    return {
        **status,
        "repo_full_name": repo.full_name,
        "commit_sha": analysis.commit_sha,
    }


@router.post("/{analysis_id}/chat")
async def chat_with_repository(
    analysis_id: str,
    payload: ChatRequest,
    session: DbSession,
    session_id: CurrentSession,
    settings: Settings = Depends(get_settings),
) -> dict:
    analysis, repo = _analysis_and_repo(analysis_id, session)
    service = RagService(settings)
    if not service.enabled:
        raise HTTPException(
            status_code=503,
            detail=service.configuration_status()["message"] or "AI chat is not configured on this server.",
        )
    if not analysis.commit_sha:
        raise HTTPException(status_code=409, detail="This analysis has no resolved commit SHA for repository chat.")
    _take_chat_slot(session_id, settings.rag_chat_requests_per_minute)
    history = [message.model_dump() for message in payload.history]
    try:
        return await service.chat(repo.full_name, analysis.commit_sha, payload.question.strip(), history)
    except RagNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RagIndexMissing as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RagProviderFailure as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RagStorageFailure as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RagServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
