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
                "Results are stored in the configured Postgres database (DATABASE_URL)."
                if storage["mode"] == "postgres" else
                "Results are kept in memory only and cleared when the server restarts. "
                "Nothing is written to your disk. Set DATABASE_URL to keep results across restarts."
            ),
        },
        "search": {"ranking": "lexical", "note": "Ranked by identifier and text overlap. No embeddings or AI."},
        "github": {
            "authenticated": bool(settings.github_token),
            "rate_limit": config["github"]["rate_limit"],
            "note": (
                "GitHub token configured - 5000 requests/hour."
                if settings.github_token else
                "Anonymous GitHub access - 60 requests/hour. Set GITHUB_TOKEN for heavier use."
            ),
        },
        "limits": config["limits"],
    }
