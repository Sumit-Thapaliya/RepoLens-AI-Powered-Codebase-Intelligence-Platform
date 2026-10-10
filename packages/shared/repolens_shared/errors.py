"""Typed error hierarchy.

Every error carries a machine readable ``code`` and an operator/end-user
friendly ``message`` plus an optional ``hint`` describing what the user can do
about it. The API layer renders these directly, so the UI never has to guess.
"""

from __future__ import annotations


class RepoLensError(Exception):
    """Base class for every expected failure in the platform."""

    code = "internal_error"
    http_status = 500

    def __init__(self, message: str, *, hint: str | None = None, detail: object | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.detail = detail

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}


# --------------------------------------------------------------------- GitHub
class GitHostError(RepoLensError):
    code = "github_error"
    http_status = 502


class InvalidRepoUrlError(RepoLensError):
    code = "invalid_repo_url"
    http_status = 400


class RepoNotFoundError(RepoLensError):
    code = "repo_not_found"
    http_status = 404


class GitHubRateLimitError(RepoLensError):
    code = "github_rate_limited"
    http_status = 429

    def __init__(self, message: str, *, reset_at: str | None = None, hint: str | None = None):
        super().__init__(message, hint=hint or (
            "Wait for GitHub's rate-limit reset, then retry. RepoLens uses anonymous public API access."
        ))
        self.reset_at = reset_at

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["reset_at"] = self.reset_at
        return payload


class RepoTooLargeError(RepoLensError):
    code = "repo_too_large"
    http_status = 413


class EmptyRepositoryError(RepoLensError):
    code = "empty_repository"
    http_status = 422


# -------------------------------------------------------------------- Parsing
class ParseError(RepoLensError):
    """Raised only when a whole file cannot be parsed *and* the caller asked
    for strict behaviour. Per-file failures are recorded on the file record and
    never abort an analysis run."""

    code = "parse_error"
    http_status = 422


class UnsupportedLanguageError(RepoLensError):
    code = "unsupported_language"
    http_status = 415


# ----------------------------------------------------------------------- Data
class DatabaseError(RepoLensError):
    code = "database_error"
    http_status = 503



class AnalysisCancelledError(RepoLensError):
    code = "analysis_cancelled"
    http_status = 409


class AnalysisNotReadyError(RepoLensError):
    """The analysis exists but has not finished yet. Not a server fault, so it is 409, not 500."""

    code = "analysis_not_ready"
    http_status = 409
