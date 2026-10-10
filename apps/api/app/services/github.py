"""GitHub access: metadata, branches, source download and file content.

Sources are fetched from the REST tarball endpoint by default. A shallow ``git clone``
fallback is available only when ``MAX_REPO_BYTES=0``; with a hard size cap enabled,
the API fails closed rather than risk an unbounded clone.
"""

from __future__ import annotations

from urllib.parse import quote

import asyncio
import logging
import os
import shutil
import tarfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import httpx

from repolens_shared.errors import (
    GitHostError,
    GitHubRateLimitError,
    RepoNotFoundError,
    RepoTooLargeError,
)
from repolens_shared.schemas import Branch, RepoMetadata, RepoRef
from repolens_shared.utils import normalize_repo_url

from ..core.config import Settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
USER_AGENT = "RepoLens/0.1 (+https://github.com/repolens)"


class GitHubClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._owns_client = client is None
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ------------------------------------------------------------- lifecycle
    async def __aenter__(self) -> "GitHubClient":
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=GITHUB_API_BASE, headers=self._headers,
                                             timeout=httpx.Timeout(30.0, read=180.0), follow_redirects=True)
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise GitHostError("GitHub client is not initialised.",
                               hint="This is a bug - the client must be used inside `async with GitHubClient(...)`.")
        return self._client

    # ---------------------------------------------------------------- errors
    def _raise_for_status(self, response: httpx.Response, context: str) -> None:
        status = response.status_code
        if status < 400:
            return
        remaining = response.headers.get("x-ratelimit-remaining")
        if status in {403, 429} and remaining == "0":
            reset = response.headers.get("x-ratelimit-reset")
            reset_at = None
            if reset and reset.isdigit():
                reset_at = datetime.utcfromtimestamp(int(reset)).isoformat() + "Z"
            raise GitHubRateLimitError("GitHub API rate limit reached.", reset_at=reset_at)
        if status == 401:
            raise GitHostError(
                "GitHub rejected an anonymous API request.",
                hint="Retry later. RepoLens uses public GitHub access and does not accept private-repository credentials.",
            )
        if status == 404:
            raise RepoNotFoundError(
                f"GitHub returned 404 for {context}.",
                hint="Check the URL. RepoLens supports public GitHub repositories only.",
            )
        if status == 451:
            raise GitHostError("GitHub refused to serve this repository (DMCA/unavailable).")
        raise GitHostError(f"GitHub API error {status} for {context}: {response.text[:200]}")

    # -------------------------------------------------------------- metadata
    async def get_repo(self, owner: str, name: str) -> RepoMetadata:
        response = await self.client.get(f"/repos/{owner}/{name}")
        self._raise_for_status(response, f"{owner}/{name}")
        data = response.json()
        if data.get("private"):
            raise GitHostError(
                "Private repositories are not supported.",
                hint="Use a public GitHub repository URL.",
            )
        return _to_metadata(data)

    async def resolve(self, url: str) -> tuple[RepoRef, RepoMetadata]:
        try:
            owner, name, canonical = normalize_repo_url(url)
        except ValueError as exc:
            from repolens_shared.errors import InvalidRepoUrlError
            raise InvalidRepoUrlError(str(exc),
                                      hint="Paste a URL like https://github.com/owner/repository") from exc
        metadata = await self.get_repo(owner, name)
        return RepoRef(owner=owner, name=name, url=canonical), metadata

    async def get_branches(self, owner: str, name: str, limit: int = 100) -> list[Branch]:
        response = await self.client.get(f"/repos/{owner}/{name}/branches", params={"per_page": min(limit, 100)})
        self._raise_for_status(response, f"{owner}/{name}/branches")
        branches = [
            Branch(name=item["name"], sha=(item.get("commit") or {}).get("sha"),
                   protected=bool(item.get("protected")))
            for item in response.json()
        ]
        default = next((branch for branch in branches if branch.name in {"main", "master"}), branches[0] if branches else None)
        if default:
            default.is_default = True
        return branches

    async def get_commit_sha(self, owner: str, name: str, ref: str) -> str | None:
        response = await self.client.get(f"/repos/{owner}/{name}/commits/{ref}")
        if response.status_code >= 400:
            return None
        return (response.json() or {}).get("sha")

    async def get_file(self, owner: str, name: str, path: str, ref: str) -> str | None:
        response = await self.client.get(f"/repos/{owner}/{name}/contents/{quote(path, safe='/')}", params={"ref": ref})
        if response.status_code == 404:
            return None
        self._raise_for_status(response, f"{owner}/{name}/contents/{path}")
        data = response.json()
        import base64
        if isinstance(data, dict) and data.get("encoding") == "base64":
            try:
                return base64.b64decode(data.get("content", "")).decode("utf-8", "replace")
            except Exception:
                return None
        return None

    async def rate_limit(self) -> dict:
        try:
            response = await self.client.get("/rate_limit")
            if response.status_code >= 400:
                return {"available": False}
            core = (response.json() or {}).get("resources", {}).get("core", {})
            return {"available": True, "limit": core.get("limit"), "remaining": core.get("remaining"),
                    "reset": core.get("reset")}
        except httpx.HTTPError:
            return {"available": False}

    # -------------------------------------------------------------- downloads
    async def download_sources(self, owner: str, name: str, ref: str, destination: Path,
                               max_bytes: int, max_files: int = 4000) -> tuple[Path, str]:
        """Fetch the repository tree. Returns (root_dir, method)."""
        destination.mkdir(parents=True, exist_ok=True)
        try:
            return await self._download_tarball(owner, name, ref, destination, max_bytes, max_files), "tarball"
        except (GitHostError, httpx.HTTPError) as exc:
            if max_bytes:
                raise GitHostError(
                    "The GitHub tarball could not be downloaded within the configured safety limits.",
                    hint="Retry later or raise MAX_REPO_BYTES. The git-clone fallback is disabled when a hard size cap is active.",
                ) from exc
            logger.warning("Tarball download failed for %s/%s@%s (%s); falling back to git clone", owner, name, ref, exc)
        return await self._git_clone(owner, name, ref, destination), "git-clone"

    async def _download_tarball(self, owner: str, name: str, ref: str, destination: Path,
                                max_bytes: int, max_files: int) -> Path:
        archive = destination / "source.tar.gz"
        size = 0
        url = f"{GITHUB_API_BASE}/repos/{owner}/{name}/tarball/{ref}"
        async with self.client.stream("GET", url, headers=self._headers, follow_redirects=True) as response:
            self._raise_for_status(response, f"{owner}/{name}/tarball/{ref}")
            with open(archive, "wb") as handle:
                async for chunk in response.aiter_bytes(1 << 16):
                    size += len(chunk)
                    if max_bytes and size > max_bytes:
                        handle.close()
                        archive.unlink(missing_ok=True)
                        raise RepoTooLargeError(
                            f"Repository archive exceeds the configured limit of {max_bytes // (1024 * 1024)} MiB.",
                            hint="Choose a smaller repository or increase MAX_REPO_BYTES if the larger download is expected."
                        )
                    handle.write(chunk)
        root = await asyncio.to_thread(_extract_tarball, archive, destination, max_bytes, max_files)
        archive.unlink(missing_ok=True)
        return root

    async def _git_clone(self, owner: str, name: str, ref: str, destination: Path) -> Path:
        target = destination / "clone"
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)

        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
        clone_url = f"https://github.com/{owner}/{name}.git"
        command = ["git", "clone", "--depth", "1", "--single-branch", "--branch", ref, clone_url, str(target)]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=900)
        except asyncio.TimeoutError as exc:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise GitHostError("Cloning the repository timed out after 15 minutes.") from exc
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode != 0:
            message = (stderr or b"").decode("utf-8", "replace")
            if "not found" in message.lower() or "could not read" in message.lower():
                raise RepoNotFoundError(f"git clone failed for {owner}/{name}: repository or branch not found.",
                                        detail=message[:300])
            raise GitHostError(
                "Could not download the repository sources.",
                hint="Install `git` in the API container or retry - the tarball endpoint was unavailable.",
                detail=message[:300],
            )
        return target


def _extract_tarball(archive: Path, destination: Path, max_bytes: int = 0,
                     max_files: int = 4000) -> Path:
    """Safely extract a GitHub tarball, bounding expanded bytes and member count."""
    extract_dir = destination / "extracted"
    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        safe_members = []
        expanded_bytes = 0
        file_count = 0
        entry_count = 0
        for member in tar:
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                continue
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                continue
            entry_count += 1
            if entry_count > max(1000, max_files * 10):
                raise RepoTooLargeError(
                    "The archive contains too many filesystem entries.",
                    hint="Raise MAX_FILES if the repository legitimately contains more paths.",
                )
            if member.isfile():
                file_count += 1
                expanded_bytes += max(0, member.size)
                if max_bytes and expanded_bytes > max_bytes:
                    raise RepoTooLargeError(
                        "The expanded repository exceeds MAX_REPO_BYTES.",
                        hint="Raise MAX_REPO_BYTES only if this repository is trusted and expected to be larger.",
                    )
                if file_count > max(100, max_files * 5):
                    raise RepoTooLargeError(
                        f"The archive contains more than {max_files * 5} file entries.",
                        hint="Raise MAX_FILES if the repository legitimately contains more source files.",
                    )
            safe_members.append(member)
        tar.extractall(extract_dir, members=safe_members, filter="data")
    roots = [entry for entry in extract_dir.iterdir() if entry.is_dir()]
    if len(roots) == 1:
        return roots[0]
    return extract_dir


def _to_metadata(data: dict[str, Any]) -> RepoMetadata:
    license_info = data.get("license") or {}
    return RepoMetadata(
        owner=(data.get("owner") or {}).get("login") or data["full_name"].split("/")[0],
        name=data.get("name") or data["full_name"].split("/")[-1],
        full_name=data.get("full_name") or "",
        description=data.get("description"),
        default_branch=data.get("default_branch") or "main",
        html_url=data.get("html_url") or "",
        stars=data.get("stargazers_count") or 0,
        forks=data.get("forks_count") or 0,
        watchers=data.get("subscribers_count") or data.get("watchers_count") or 0,
        open_issues=data.get("open_issues_count") or 0,
        primary_language=data.get("language"),
        license=(license_info.get("spdx_id") if isinstance(license_info, dict) else None),
        topics=data.get("topics") or [],
        size_kb=data.get("size") or 0,
        archived=bool(data.get("archived")),
        is_fork=bool(data.get("fork")),
        created_at=_parse_date(data.get("created_at")),
        pushed_at=_parse_date(data.get("pushed_at")),
        updated_at=_parse_date(data.get("updated_at")),
        homepage=data.get("homepage"),
        has_issues=bool(data.get("has_issues", True)),
    )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_source_files(root: Path, max_file_bytes: int, max_files: int,
                      ignored_dirs: set[str], ignored_suffixes: tuple[str, ...]) -> Iterator[tuple[str, str, int]]:
    """Yield (relative_path, text, size) for text files under ``root``.

    Binary and oversized files are skipped here; the caller records them as
    "skipped" so the UI can explain what was excluded.
    """
    from repolens_shared.utils import is_probably_binary

    count = 0
    for path in sorted(root.rglob("*")):
        if count >= max_files:
            return
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part in ignored_dirs for part in parts[:-1]):
            continue
        if any(part.startswith(".git") for part in parts[:-1]):
            continue
        name = path.name
        if name.lower().endswith(ignored_suffixes):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size == 0 or size > max_file_bytes:
            continue
        try:
            with open(path, "rb") as handle:
                sample = handle.read(4096)
                if is_probably_binary(str(path), sample):
                    continue
                handle.seek(0)
                text = handle.read().decode("utf-8", "replace")
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(root).as_posix()
        count += 1
        yield relative, text, size


def clone_dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def fetch_file_on_demand(settings: Settings, owner: str, name: str, path: str, ref: str) -> str | None:
    """Fetch one file from GitHub for the code explorer (no checkout kept on disk).

    Returns None when GitHub has no text content for the path. Raises RepoLensError on API errors.
    """
    async def _fetch() -> str | None:
        async with GitHubClient(settings) as client:
            return await client.get_file(owner, name, path, ref)

    return asyncio.run(_fetch())
