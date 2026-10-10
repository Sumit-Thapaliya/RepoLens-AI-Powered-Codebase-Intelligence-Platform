"""Server-issued, opaque browser sessions used to authorize analysis access.

Only a SHA-256 digest of the bearer cookie is stored in the database. The cookie is
HttpOnly and is never exposed to JavaScript; the client-generated window id is used
only to distinguish tabs after the session has been authenticated.
"""

from __future__ import annotations

import hashlib
import secrets
import time

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..models.tables import BrowserSession

SESSION_COOKIE_NAME = "repolens_session"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _set_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.app_env.lower() == "production",
        samesite="lax",
        path="/",
    )


def establish_session(request: Request, response: Response, session: Session,
                      settings: Settings | None = None) -> dict:
    """Create a session, or refresh the existing valid session cookie."""
    settings = settings or get_settings()
    now = time.time()
    token = request.cookies.get(SESSION_COOKIE_NAME)
    row = session.get(BrowserSession, _digest(token)) if token else None
    reused = bool(row and row.expires_at > now)

    if not reused:
        if row is not None:
            session.delete(row)
            session.flush()
        token = secrets.token_urlsafe(32)
        row = BrowserSession(
            id=_digest(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + settings.session_ttl_seconds,
        )
        session.add(row)
    else:
        row.last_seen_at = now
        row.expires_at = now + settings.session_ttl_seconds

    session.commit()
    _set_cookie(response, token, settings)
    return {"ready": True, "new_session": not reused}


def require_session(request: Request, response: Response, session: Session,
                    settings: Settings | None = None) -> str:
    """Validate and refresh the HttpOnly session cookie; return its database key."""
    settings = settings or get_settings()
    token = request.cookies.get(SESSION_COOKIE_NAME)
    row = session.get(BrowserSession, _digest(token)) if token else None
    now = time.time()
    if row is None or row.expires_at <= now:
        raise HTTPException(
            status_code=401,
            detail="A valid RepoLens session is required.",
            headers={"WWW-Authenticate": "Session"},
        )
    row.last_seen_at = now
    row.expires_at = now + settings.session_ttl_seconds
    session.commit()
    _set_cookie(response, token, settings)
    return row.id
