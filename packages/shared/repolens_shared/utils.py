"""Small, dependency-free helpers used across packages."""

from __future__ import annotations

import contextvars
import hashlib
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath

from .constants import (
    BINARY_EXTENSIONS,
    DOC_LANGUAGES,
    EXAMPLE_PATH_PATTERNS,
    LANGUAGE_BY_EXTENSION,
    LANGUAGE_LABELS,
    LANGUAGE_BY_NAME,
)

_GITHUB_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com[/:](?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?(?:/.*)?$",
    re.IGNORECASE,
)
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.\- ]+$")


def sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", "replace")).hexdigest()


# Set by the analysis pipeline to its analysis id. Every id made during that run includes it, so two
# runs of the same repository never produce the same primary key (the tables are shared).
RUN_SCOPE: contextvars.ContextVar[str] = contextvars.ContextVar("repolens_run_scope", default="")


def stable_id(*parts: object) -> str:
    """Deterministic id for records whose identity is (type, path, name, line), scoped to the current run."""
    scope = RUN_SCOPE.get()
    items = (scope, *parts) if scope else parts
    return sha1("::".join(str(p) for p in items))[:20]


def truncate(text: str, limit: int = 400, suffix: str = "…") -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - len(suffix)].rstrip() + suffix


def normalize_repo_url(url: str) -> tuple[str, str, str]:
    """Return ``(owner, repo, canonical_url)`` or raise ``ValueError``.

    Accepts the shapes users actually paste:
    ``https://github.com/owner/repo``, ``github.com/owner/repo/tree/branch``,
    ``git@github.com:owner/repo.git``, ``owner/repo``.
    """
    candidate = (url or "").strip()
    if not candidate:
        raise ValueError("Repository URL is empty.")

    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", candidate):
        candidate = f"https://github.com/{candidate}"

    match = _GITHUB_URL_RE.match(candidate)
    if not match:
        raise ValueError("Only public GitHub repositories (https://github.com/owner/repo) are supported.")

    owner = match.group("owner")
    repo = match.group("repo")
    if not _SAFE_SEGMENT_RE.match(owner) or not _SAFE_SEGMENT_RE.match(repo):
        raise ValueError("Repository owner/name contains unsupported characters.")
    if repo.lower() in {"owner", "repo"} and owner.lower() == "owner":
        raise ValueError("That looks like a placeholder URL - paste a real repository address.")
    return owner, repo, f"https://github.com/{owner}/{repo}"


def language_for_path(path: str) -> str:
    name = PurePosixPath(path).name.lower()
    # Extensionless and dot files are matched by name first: a Dockerfile, a
    # Makefile and a dotfile such as `.editorconfig` have no extension at all.
    if name in LANGUAGE_BY_NAME:
        return LANGUAGE_BY_NAME[name]
    if name.startswith("dockerfile.") or name.startswith("docker-compose."):
        return "docker" if name.startswith("dockerfile") else "yaml"
    if name.startswith("license") or name.startswith("notice") or name.startswith("copying"):
        return "text"
    if name.startswith("requirements") and name.endswith(".txt"):
        return "text"
    suffix = PurePosixPath(name).suffix
    if not suffix:
        # Extensionless files and dotfiles (LICENSE, Procfile, .python-version,
        # .fastapicloudignore) are text, not "unrecognised".
        return "text"
    return LANGUAGE_BY_EXTENSION.get(suffix, "unknown")


DOC_DIR_NAMES = {"docs", "doc", "documentation", "website", "book"}


def is_doc_path(path: str, language: str | None = None) -> bool:
    """True for documentation: prose files, or files inside a docs directory.

    Used to keep documentation out of code heuristics - an ``.rst`` tutorial that
    mentions ``/api/login`` is not a client call site, and ``docs/conf.py`` is
    documentation tooling rather than an application module.
    """
    if language is not None and language in DOC_LANGUAGES:
        return True
    lowered = path.lower()
    parts = [part for part in re.split(r"[/\\]", lowered) if part]
    if any(part in DOC_DIR_NAMES for part in parts[:-1]):
        return True
    return language_for_path(path) in DOC_LANGUAGES


def is_example_path(path: str) -> bool:
    """True when a path lives in an examples/demos/samples folder."""
    lowered = "/" + path.lower().lstrip("/")
    return any(pattern in lowered for pattern in EXAMPLE_PATH_PATTERNS)


def language_label(language: str) -> str:
    return LANGUAGE_LABELS.get(language, language.replace("_", " ").title())


def is_probably_binary(path: str, sample: bytes | None = None) -> bool:
    suffix = PurePosixPath(path.lower()).suffix
    if suffix in BINARY_EXTENSIONS:
        return True
    if sample:
        if b"\x00" in sample[:1024]:
            return True
        # Heuristic: > 30% non-text bytes in the sample window.
        window = sample[:4096]
        if window:
            printable = sum(1 for b in window if 32 <= b < 127 or b in (9, 10, 13))
            if printable / len(window) < 0.7:
                return True
    return False


def relative_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - value
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3600}h ago"
    if seconds < 2_592_000:
        return f"{seconds // 86_400}d ago"
    if seconds < 31_536_000:
        return f"{seconds // 2_592_000}mo ago"
    return f"{seconds // 31_536_000}y ago"


def shingle_hash(text: str, size: int = 6) -> str:
    """Normalised token-shingle hash used by the duplicate-code heuristic."""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+|[^\sA-Za-z0-9_]", text or "")
    tokens = [t for t in tokens if t not in {"self", "this", "def", "function", "const", "let", "var"}]
    if len(tokens) < size:
        return sha1(" ".join(tokens))
    window = " ".join(tokens[: min(len(tokens), 240)])
    return sha1(window)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "item"


def sql_kind(statement: str) -> str:
    statement = (statement or "").strip().lower()
    for kind, pattern in (
        ("select", r"^select\b"),
        ("insert", r"^insert\b"),
        ("update", r"^update\b"),
        ("delete", r"^delete\b"),
        ("create", r"^create\b"),
        ("alter", r"^alter\b"),
        ("drop", r"^drop\b"),
    ):
        if re.search(pattern, statement):
            return kind
    return "unknown"


def sql_tables(statement: str) -> list[str]:
    text = (statement or "").strip()
    tables: list[str] = []
    patterns = (
        r"\bfrom\s+[\"`\[]?([A-Za-z_][A-Za-z0-9_]*)",
        r"\bjoin\s+[\"`\[]?([A-Za-z_][A-Za-z0-9_]*)",
        r"\binto\s+[\"`\[]?([A-Za-z_][A-Za-z0-9_]*)",
        r"\bupdate\s+[\"`\[]?([A-Za-z_][A-Za-z0-9_]*)",
        r"\bdelete\s+from\s+[\"`\[]?([A-Za-z_][A-Za-z0-9_]*)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            table = match.group(1)
            if table.upper() not in {"SELECT", "WHERE", "SET", "VALUES", "AS", "ON"} and table not in tables:
                tables.append(table)
    return tables
