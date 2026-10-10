"""System endpoints: health, capabilities, and supported languages."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from repolens_parser import available_languages
from repolens_shared.constants import LANGUAGE_LABELS, TEXT_INDEXED_LANGUAGES, TREE_SITTER_LANGUAGES

from ..core.capabilities import describe_capabilities
from ..core.config import get_settings
from ..core.db import database_state
from ..services.sessions import establish_session
from .deps import DbSession
from sqlalchemy import text

router = APIRouter(tags=["system"])


@router.post("/session")
def create_or_refresh_session(request: Request, response: Response, session: DbSession) -> dict:
    """Issue or refresh the HttpOnly browser session cookie used by protected routes."""
    return establish_session(request, response, session, get_settings())


@router.get("/health")
def health(session: DbSession) -> dict:
    database = {"status": "unknown", "dialect": database_state().get("dialect")}
    try:
        session.execute(text("SELECT 1"))
        database["status"] = "ok"
    except Exception as exc:  # pragma: no cover
        database = {"status": "error", "error": str(exc), "dialect": database_state().get("dialect")}
    return {"status": "ok" if database["status"] == "ok" else "degraded", "version": "0.1.0", "database": database}


@router.get("/system/capabilities")
def capabilities() -> dict:
    return describe_capabilities()


@router.get("/system/languages")
def languages() -> dict:
    loaded = set(available_languages())
    deep = [
        {"language": language, "label": LANGUAGE_LABELS.get(language, language), "parser": "tree-sitter/python-ast",
         "available": language in loaded or language == "python"}
        for language in sorted(TREE_SITTER_LANGUAGES)
    ]
    indexed = [
        {"language": language, "label": LANGUAGE_LABELS.get(language, language), "parser": "text/indexed",
         "available": True}
        for language in sorted(TEXT_INDEXED_LANGUAGES)
    ]
    return {
        "deep_analysis": deep,
        "indexed_only": indexed,
        "note": "Deep analysis parses symbols, imports, routes and models. Indexed-only languages are searchable but "
                "do not contribute symbols, routes or dependency edges.",
        "limits": get_settings().public_config()["limits"],
    }
