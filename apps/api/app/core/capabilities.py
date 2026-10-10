"""What this deployment can actually do - reported to the UI, never assumed."""

from __future__ import annotations

from .config import get_settings
from .db import database_state


def describe_capabilities() -> dict:
    settings = get_settings()
    config = settings.public_config()
    database = database_state()
    storage = config["storage"]
    return {
        "storage": {
            "mode": storage["mode"],
            "dialect": database.get("dialect"),
            "local_files": False,
            "note": (
                "Completed results are stored in the configured Postgres database (DATABASE_URL) until their owner lease expires; interrupted jobs are marked failed on restart."
                if storage["mode"] == "postgres" else
                "Results are kept in an in-memory SQLite database and cleared when the API restarts."
            ),
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
            "authenticated": bool(settings.github_token),
            "rate_limit": config["github"]["rate_limit"],
            "private_repositories_allowed": settings.allow_private_repos,
            "note": (
                "GitHub token configured - 5000 requests/hour."
                if settings.github_token else
                "Anonymous GitHub access - 60 requests/hour. Set GITHUB_TOKEN for heavier use."
            ),
        },
        "privacy": {
            "source_snippets_stored": settings.store_source_snippets,
            "private_repositories_allowed": settings.allow_private_repos,
            "session_ttl_seconds": settings.session_ttl_seconds,
            "window_ttl_seconds": settings.window_ttl_seconds,
        },
        "limits": config["limits"],
    }
