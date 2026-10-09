"""Grounded repository Q&A."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sqlalchemy import select

from ..ai.chat import build_answer
from ..core.config import get_settings
from ..models.tables import ChatMessageRecord
from ..services.store import require_complete
from .deps import ChatRequest, DbSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analyses", tags=["ai"])


@router.post("/{analysis_id}/chat")
def chat(analysis_id: str, payload: ChatRequest, session: DbSession) -> dict:
    analysis = require_complete(session, analysis_id)
    settings = get_settings()
    result = build_answer(session, settings, analysis, payload.question, payload.history, payload.focus_path)
    return result


@router.get("/{analysis_id}/chat/history")
def history(analysis_id: str, session: DbSession, limit: int = 40) -> dict:
    require_complete(session, analysis_id)
    rows = session.execute(
        select(ChatMessageRecord).where(ChatMessageRecord.analysis_id == analysis_id)
        .order_by(ChatMessageRecord.created_at.desc()).limit(min(limit, 200))
    ).scalars().all()
    return {"messages": [
        {"id": row.id, "role": row.role, "content": row.content, "citations": row.citations or [],
         "model": row.model, "created_at": row.created_at.isoformat() if row.created_at else None}
        for row in reversed(rows)
    ]}


@router.get("/{analysis_id}/chat/suggestions")
def suggestions(analysis_id: str, session: DbSession) -> dict:
    """Question ideas derived from what this repository actually contains."""
    require_complete(session, analysis_id)
    from ..services.store import get_database, list_endpoints, list_workflows
    workflows = list_workflows(session, analysis_id, limit=6)["workflows"]
    endpoints = list_endpoints(session, analysis_id)["endpoints"]
    database = get_database(session, analysis_id)

    questions: list[str] = ["Explain this repository."]
    if any("auth" in (endpoint["path"] or "").lower() or "auth" in (endpoint.get("handler") or "").lower()
           for endpoint in endpoints):
        questions.append("How does authentication work?")
    for workflow in workflows[:3]:
        trigger = workflow.get("trigger") or workflow["name"]
        questions.append(f"How does this work: {trigger}?")
    if database.get("models"):
        questions.append("What does the database schema look like?")
    if endpoints:
        questions.append("What could break if I modify the most connected file?")
    if any((endpoint["path"] or "").lower().find("payment") >= 0 for endpoint in endpoints):
        questions.append("Where is payment handled?")
    return {"suggestions": questions[:6]}
