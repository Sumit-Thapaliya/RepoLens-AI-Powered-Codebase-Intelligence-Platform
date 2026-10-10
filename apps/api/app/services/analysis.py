"""Analysis run management: create, schedule, cancel and track runs.

Concurrency is controlled by an ``asyncio.Semaphore`` sized from
``ANALYSIS_WORKERS``; queued runs stay visible with status ``queued`` so the UI
can show an honest position in the queue. Runs execute in background asyncio
tasks, which keeps the deployment to a single container - Redis/Celery are only
worth adding if this ever needs to scale horizontally.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

from sqlalchemy import select

from repolens_shared.errors import RepoLensError
from repolens_shared.utils import stable_id

from ..analyzers.pipeline import AnalysisPipeline
from ..core.config import Settings, get_settings
from ..core.db import session_scope
from ..models.tables import Analysis, AnalysisWindow, Repo
from .github import GitHubClient
from .store import delete_analysis_rows, find_repo_by_full_name, repo_payload
from .windows import expire_windows

logger = logging.getLogger(__name__)


class AnalysisManager:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._semaphore: asyncio.Semaphore | None = None

    # ------------------------------------------------------------- lifecycle
    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(max(1, self.settings.analysis_workers))
        return self._semaphore

    def in_flight(self) -> list[str]:
        return [analysis_id for analysis_id, task in self._tasks.items() if not task.done()]

    # ----------------------------------------------------------------- create
    async def create_run(self, url: str, branch: str | None = None, force: bool = False,
                         owner_session_id: str | None = None) -> dict:
        """Resolve the repository, persist metadata and enqueue an analysis.

        An active run is reusable only by the same authenticated session; two users
        never join the same analysis just because they requested the same repository.
        """
        async with GitHubClient(self.settings) as client:
            ref, metadata = await client.resolve(url)
            branches = await client.get_branches(ref.owner, ref.name)
            selected = branch or metadata.default_branch
            available = {item.name for item in branches}
            if branch and branch not in available and branch != metadata.default_branch:
                raise RepoLensError(
                    f"Branch `{branch}` was not found in {ref.owner}/{ref.name}.",
                    hint=f"Available branches include: {', '.join(sorted(available)[:8]) or 'unknown'}",
                )

        with session_scope() as session:
            repo = find_repo_by_full_name(session, metadata.full_name)
            if repo is None:
                repo = Repo(id=stable_id("repo", metadata.full_name), owner=ref.owner, name=ref.name,
                            full_name=metadata.full_name, url=ref.url)
                session.add(repo)
            _apply_metadata(repo, metadata)
            session.flush()

            if not force and owner_session_id:
                existing = session.execute(
                    select(Analysis)
                    .join(AnalysisWindow, AnalysisWindow.analysis_id == Analysis.id)
                    .where(
                        Analysis.repo_id == repo.id,
                        Analysis.branch == selected,
                        AnalysisWindow.session_id == owner_session_id,
                        Analysis.status.in_(["queued", "running"]),
                    )
                    .order_by(Analysis.created_at.desc())
                ).scalars().first()
                if existing is not None:
                    return {"analysis_id": existing.id, "repo_id": repo.id, "status": existing.status,
                            "reused": True, "repo": repo_payload(repo),
                            "message": "An analysis for this repository is already in progress."}

            analysis_id = stable_id("analysis", repo.id, selected, time.time())
            analysis = Analysis(id=analysis_id, repo_id=repo.id, status="queued", stage="queued", progress=0.0,
                                branch=selected, message="Queued for analysis.")
            session.add(analysis)
            repo_id = repo.id
            repo_snapshot = repo_payload(repo)

        self._schedule(analysis_id)
        return {"analysis_id": analysis_id, "repo_id": repo_id, "status": "queued", "reused": False,
                "repo": repo_snapshot, "branches": [item.model_dump() for item in branches]}

    async def reanalyse(self, repo_id: str, branch: str | None = None, force: bool = True,
                        owner_session_id: str | None = None) -> dict:
        with session_scope() as session:
            repo = session.get(Repo, repo_id)
            if repo is None:
                raise RepoLensError(f"Repository `{repo_id}` is not imported yet.",
                                    hint="Import it first with POST /api/repos/resolve.")
            url = repo.url
        return await self.create_run(url, branch=branch, force=force, owner_session_id=owner_session_id)

    # --------------------------------------------------------------- schedule
    def _schedule(self, analysis_id: str) -> None:
        cancel_event = threading.Event()
        self._cancel_events[analysis_id] = cancel_event
        task = asyncio.create_task(self._run(analysis_id, cancel_event))
        self._tasks[analysis_id] = task
        def _forget_task(_task: asyncio.Task) -> None:
            self._tasks.pop(analysis_id, None)
            self._cancel_events.pop(analysis_id, None)

        task.add_done_callback(_forget_task)

    async def _run(self, analysis_id: str, cancel_event: threading.Event) -> None:
        async with self.semaphore:
            if cancel_event.is_set():
                self._mark_cancelled(analysis_id)
                return
            pipeline = AnalysisPipeline(analysis_id, self.settings, cancel_event)
            await pipeline.run()

    def _mark_cancelled(self, analysis_id: str) -> None:
        with session_scope() as session:
            analysis = session.get(Analysis, analysis_id)
            if analysis:
                analysis.status = "cancelled"
                analysis.message = "Cancelled before it started."

    # ---------------------------------------------------------------- cancel
    def cancel(self, analysis_id: str) -> bool:
        event = self._cancel_events.get(analysis_id)
        if event is None:
            return False
        event.set()
        return True

    # --------------------------------------------------------------- discard
    def discard(self, analysis_id: str) -> bool:
        """Delete a run and all of its data. A run still in progress is cancelled first.

        Returns False when the run was still active; it is discarded by a later sweep once it stops.
        """
        if analysis_id in self.in_flight():
            self.cancel(analysis_id)
            return False
        with session_scope() as session:
            delete_analysis_rows(session, analysis_id)
        return True

    def sweep_windows(self) -> list[str]:
        """Discard runs with no live owner and sessions whose leases expired."""
        with session_scope() as session:
            expired_ids = expire_windows(
                session,
                ttl_seconds=self.settings.window_ttl_seconds,
                session_ttl_seconds=self.settings.session_ttl_seconds,
            )
        removed = []
        for analysis_id in expired_ids:
            try:
                if self.discard(analysis_id):
                    removed.append(analysis_id)
            except Exception:  # keep sweeping even if one run fails
                logger.warning("Could not discard run %s", analysis_id, exc_info=True)
        return removed

    async def shutdown(self) -> None:
        for event in self._cancel_events.values():
            event.set()
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._cancel_events.clear()

def _apply_metadata(repo: Repo, metadata) -> None:
    repo.owner = metadata.owner
    repo.name = metadata.name
    repo.full_name = metadata.full_name
    repo.url = metadata.html_url or repo.url
    repo.description = metadata.description
    repo.default_branch = metadata.default_branch
    repo.stars = metadata.stars
    repo.forks = metadata.forks
    repo.watchers = metadata.watchers
    repo.open_issues = metadata.open_issues
    repo.primary_language = metadata.primary_language
    repo.license = metadata.license
    repo.topics = metadata.topics
    repo.size_kb = metadata.size_kb
    repo.archived = metadata.archived
    repo.is_fork = metadata.is_fork
    repo.homepage = metadata.homepage
    repo.github_created_at = metadata.created_at
    repo.github_pushed_at = metadata.pushed_at
    repo.metadata_json = metadata.model_dump(mode="json")


_manager: AnalysisManager | None = None


def get_manager() -> AnalysisManager:
    global _manager
    if _manager is None:
        _manager = AnalysisManager()
    return _manager


def reset_manager() -> None:
    global _manager
    _manager = None
