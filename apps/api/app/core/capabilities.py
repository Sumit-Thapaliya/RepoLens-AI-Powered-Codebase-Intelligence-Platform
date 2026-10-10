"""Runtime capabilities reported to the frontend."""

from __future__ import annotations

from .config import get_settings
from .db import database_state


def describe_capabilities() -> dict:
    settings = get_settings()
    config = settings.public_config()
    database = database_state()
    return {
        "storage": {
            "mode": "memory",
            "dialect": database.get("dialect", "sqlite"),
            "local_files": False,
            "note": "Analysis results are temporary in-memory data and disappear when the API stops.",
        },
        "search": {
            "ranking": "lexical",
            "source_snippets_stored": settings.store_source_snippets,
            "note": (
                "Search uses short source excerpts until expiry."
                if settings.store_source_snippets else
                "Search uses paths, symbols and deduplicated identifier terms; full source excerpts are not stored."
            ),
        },
        "github": {
            "rate_limit": "60 requests/hour (anonymous)",
            "private_repositories_allowed": False,
            "note": "Anonymous access to public GitHub repositories only.",
        },
        "privacy": {
            "source_snippets_stored": settings.store_source_snippets,
            "private_repositories_allowed": False,
            "session_ttl_seconds": settings.session_ttl_seconds,
            "window_ttl_seconds": settings.window_ttl_seconds,
        },
        "limits": config["limits"],
    }
