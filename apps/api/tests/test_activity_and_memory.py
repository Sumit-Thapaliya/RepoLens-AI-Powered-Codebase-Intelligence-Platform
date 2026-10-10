"""Repeatable local checks for lease lifecycle, process-local concurrency and memory use."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
for source_path in (
    ROOT / "apps" / "api",
    ROOT / "packages" / "shared",
    ROOT / "packages" / "parser",
    ROOT / "packages" / "graph",
):
    sys.path.insert(0, str(source_path))

from app.api import deps, routes_analysis
from app.analyzers import pipeline
from app.analyzers.pipeline import PipelineContext, _build_chunks
from app.core import db
from app.models.tables import Analysis, AnalysisWindow, Base, BrowserSession, ChunkRecord, FileRecord, Repo
from app.services import analysis as analysis_service
from app.services.analysis import AnalysisManager
from app.services.windows import expire_windows
from repolens_parser import analyze_source
from repolens_shared.schemas import Branch, RepoMetadata, RepoRef
from repolens_shared.constants import Stage


class ApiWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(db.get_engine())
        Base.metadata.create_all(db.get_engine())
        analysis_service.reset_manager()

    def tearDown(self) -> None:
        analysis_service.reset_manager()

    def test_create_poll_and_idle_expiry_through_http(self) -> None:
        metadata = RepoMetadata(
            owner="owner", name="project", full_name="owner/project",
            html_url="https://github.com/owner/project", default_branch="main",
        )
        ref = RepoRef(owner="owner", name="project", url=metadata.html_url)

        class FakeGitHubClient:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def resolve(self, _url):
                return ref, metadata

            async def get_branches(self, *_args):
                return [Branch(name="main", is_default=True)]

        class FakePipeline:
            def __init__(self, analysis_id, *_args, **_kwargs):
                self.analysis_id = analysis_id

            async def run(self):
                await asyncio.sleep(0.01)
                with db.session_scope() as session:
                    row = session.get(Analysis, self.analysis_id)
                    if row is not None:
                        row.status = "complete"
                        row.stage = "complete"
                        row.progress = 1.0
                        row.file_count = 1

        from app.main import create_app

        window_id = "integration-window"
        headers = {"X-Window-Id": window_id}
        with patch.object(analysis_service, "GitHubClient", FakeGitHubClient), \
                patch.object(analysis_service, "AnalysisPipeline", FakePipeline), \
                TestClient(create_app()) as client:
            self.assertEqual(client.post("/api/session").status_code, 200)
            capabilities = client.get("/api/system/capabilities").json()
            self.assertIn("window_ttl_seconds", capabilities["limits"])
            created = client.post(
                "/api/analyses", headers=headers,
                json={"url": "https://github.com/owner/project", "window_id": window_id},
            )
            self.assertEqual(created.status_code, 200, created.text)
            analysis_id = created.json()["analysis_id"]

            listed = client.get("/api/analyses", headers=headers, params={"ids": analysis_id})
            self.assertEqual(listed.status_code, 200)
            self.assertEqual([run["id"] for run in listed.json()["analyses"]], [analysis_id])

            for _ in range(30):
                detail = client.get(f"/api/analyses/{analysis_id}", headers=headers)
                self.assertEqual(detail.status_code, 200)
                if detail.json()["analysis"]["status"] == "complete":
                    break
                time.sleep(0.01)
            self.assertEqual(detail.json()["analysis"]["status"], "complete")

            with db.session_scope() as session:
                browser = session.query(BrowserSession).one()
                owner_key = (analysis_id, browser.id, window_id)
                owner = session.get(AnalysisWindow, owner_key)
                self.assertIsNotNone(owner)
                original_last_seen = owner.last_seen_at

            for _ in range(10):
                self.assertEqual(client.get(f"/api/analyses/{analysis_id}", headers=headers).status_code, 200)
            with db.session_scope() as session:
                owner = session.get(AnalysisWindow, owner_key)
                self.assertEqual(owner.last_seen_at, original_last_seen)

            with db.session_scope() as session:
                owner = session.get(AnalysisWindow, owner_key)
                owner.last_seen_at = time.time() - analysis_service.get_settings().window_ttl_seconds - 1
            self.assertEqual(client.get("/api/analyses", headers=headers).json()["analyses"], [])
            self.assertEqual(client.get(f"/api/analyses/{analysis_id}", headers=headers).status_code, 404)
            self.assertEqual(
                client.post(
                    f"/api/analyses/{analysis_id}/heartbeat", headers=headers,
                    json={"window_id": window_id},
                ).status_code,
                404,
            )


class LeaseLifecycleTests(unittest.TestCase):
    """Exercise real in-memory SQLite rows and the same route/dependency functions."""

    @classmethod
    def setUpClass(cls) -> None:
        db.init_db()

    @classmethod
    def tearDownClass(cls) -> None:
        if db._anchor is not None:
            db._anchor.close()
            db._anchor = None
        if db._engine is not None:
            db._engine.dispose()
            db._engine = None
            db._SessionLocal = None

    def setUp(self) -> None:
        Base.metadata.drop_all(db.get_engine())
        Base.metadata.create_all(db.get_engine())
        self.session = db.get_session_factory()()
        now = time.time()
        repo = Repo(
            id="repo-test", owner="owner", name="project", full_name="owner/project",
            url="https://github.com/owner/project", default_branch="main",
        )
        analysis = Analysis(id="analysis-test", repo_id=repo.id, status="complete", branch="main")
        browser = BrowserSession(
            id="session-test", created_at=now, last_seen_at=now, expires_at=now + 86_400,
        )
        self.session.add_all([repo, analysis, browser])
        self.session.flush()
        self.owner = AnalysisWindow(
            analysis_id=analysis.id, session_id=browser.id, window_id="window-test",
            created_at=now, last_seen_at=now,
        )
        self.session.add(self.owner)
        self.session.add(FileRecord(
            id="file-test", analysis_id=analysis.id, path="src/app.py", language="python",
            size_bytes=12, loc=1, parsed=True,
        ))
        self.session.commit()
        self.settings = SimpleNamespace(window_ttl_seconds=60, session_ttl_seconds=86_400)

    def tearDown(self) -> None:
        self.session.close()

    def test_ordinary_api_authorization_does_not_touch_lease(self) -> None:
        original = self.owner.last_seen_at
        request = SimpleNamespace(path_params={"analysis_id": "analysis-test"})
        deps.require_window_owner(request, self.session, "session-test", "window-test")
        refreshed = self.session.get(AnalysisWindow, ("analysis-test", "session-test", "window-test"))
        self.assertEqual(refreshed.last_seen_at, original)

    def test_explicit_heartbeat_refreshes_only_a_live_lease(self) -> None:
        self.owner.last_seen_at = time.time() - 20
        self.session.commit()
        with patch.object(routes_analysis, "get_settings", return_value=self.settings):
            result = routes_analysis.heartbeat(
                "analysis-test", routes_analysis.WindowRequest(window_id="window-test"),
                self.session, "session-test", "window-test",
            )
        self.assertTrue(result["alive"])
        refreshed = self.session.get(AnalysisWindow, ("analysis-test", "session-test", "window-test"))
        self.assertGreater(refreshed.last_seen_at, time.time() - 5)

    def test_expired_owner_is_denied_and_hidden_from_run_list(self) -> None:
        self.owner.last_seen_at = time.time() - 61
        self.session.commit()
        request = SimpleNamespace(path_params={"analysis_id": "analysis-test"})
        with patch.object(deps, "get_settings", return_value=self.settings):
            with self.assertRaises(routes_analysis.NotFoundError):
                deps.require_window_owner(request, self.session, "session-test", "window-test")
        with patch.object(routes_analysis, "get_settings", return_value=self.settings):
            result = routes_analysis.list_analyses(
                self.session, "session-test", "window-test", ids="analysis-test",
            )
        self.assertEqual(result["analyses"], [])

    def test_sweeper_removes_expired_artifacts_but_keeps_live_shared_owner(self) -> None:
        now = time.time()
        self.owner.last_seen_at = now - 61
        live_owner = AnalysisWindow(
            analysis_id="analysis-test", session_id="session-test", window_id="other-window",
            created_at=now - 10, last_seen_at=now - 10,
        )
        self.session.add(live_owner)
        self.session.commit()
        self.assertEqual(expire_windows(self.session, 60, 86_400), [])
        self.assertIsNotNone(self.session.get(Analysis, "analysis-test"))

        self.session.delete(live_owner)
        self.session.commit()
        expired = expire_windows(self.session, 60, 86_400)
        self.assertEqual(expired, ["analysis-test"])
        self.session.commit()
        manager = AnalysisManager()
        self.assertTrue(manager.discard("analysis-test"))
        self.session.expire_all()
        self.assertIsNone(self.session.get(Analysis, "analysis-test"))
        self.assertIsNone(self.session.get(FileRecord, "file-test"))

    def test_pipeline_run_releases_intermediates_and_keeps_preclear_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            readme = "# Project guide\n\nA small local fixture for the complete analysis pipeline.\n"
            source = (
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n"
                "@app.get(\"/health\")\n"
                "def health():\n"
                "    return {\"status\": \"private_literal_marker\"}\n"
            )
            (root / "README.md").write_text(readme, encoding="utf-8")
            (root / "src" / "app.py").write_text(source, encoding="utf-8")
            with db.session_scope() as session:
                repo = Repo(
                    id="pipeline-repo", owner="owner", name="pipeline", full_name="owner/pipeline",
                    url="https://github.com/owner/pipeline", default_branch="main",
                )
                session.add(repo)
                session.add(Analysis(
                    id="pipeline-test", repo_id=repo.id, status="queued", branch="main", source_root=str(root),
                ))

            context = PipelineContext(
                analysis_id="pipeline-test", repo_id="pipeline-repo", owner="owner", name="pipeline",
                branch="main", default_branch="main", url="https://github.com/owner/pipeline", root=root,
            )
            settings = db.get_settings().model_copy(update={"store_source_snippets": False})
            runner = pipeline.AnalysisPipeline("pipeline-test", settings)

            async def resolve():
                runner._set_stage(Stage.RESOLVING, detail="local fixture", status="done", fraction=1.0)
                return context

            async def fetch(ctx):
                runner._set_stage(Stage.FETCHING, detail="local fixture", status="done", fraction=1.0)

            runner._stage_resolve = resolve
            runner._stage_fetch = fetch
            result = asyncio.run(runner.run())

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["files"], 2)
        self.assertEqual(context.files, {})
        self.assertEqual(context.parsed_files, [])
        self.assertEqual(context.file_sizes, {})
        self.assertEqual(context.stats, {})
        with db.session_scope() as session:
            analysis = session.get(Analysis, "pipeline-test")
            files = session.query(FileRecord).filter_by(analysis_id="pipeline-test").all()
            chunks = session.query(ChunkRecord).filter_by(analysis_id="pipeline-test").all()
            actual_counts = (analysis.file_count, analysis.parsed_count, analysis.failed_count, analysis.skipped_count)
            chunk_text = " ".join(chunk.text for chunk in chunks)
        self.assertEqual(actual_counts, (2, 2, 0, 0))
        self.assertEqual(len(files), 2)
        self.assertTrue(chunks)
        self.assertTrue(all(file.content is None for file in files))
        self.assertNotIn("private_literal_marker", chunk_text)

    def test_api_restart_clears_ram_database_and_orphaned_checkouts(self) -> None:
        # Closing the sole in-memory anchor models process death: a fresh engine starts empty.
        self.session.close()
        old_engine = db._engine
        if db._anchor is not None:
            db._anchor.close()
        old_engine.dispose()
        db._engine = None
        db._anchor = None
        db._SessionLocal = None
        db.init_db()
        restarted_session = db.get_session_factory()()
        try:
            self.assertIsNone(restarted_session.get(Analysis, "analysis-test"))
        finally:
            restarted_session.close()

        with tempfile.TemporaryDirectory() as temp_dir:
            work_root = Path(temp_dir) / "repolens-work"
            work_root.mkdir()
            (work_root / "orphaned-checkout").mkdir()
            with patch.object(pipeline, "WORK_ROOT", work_root):
                pipeline.cleanup_orphaned_workdirs()
            self.assertEqual(list(work_root.iterdir()), [])


class ProcessLocalConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_workers_bound_concurrent_runs(self) -> None:
        settings = db.get_settings().model_copy(update={"analysis_workers": 2})
        manager = AnalysisManager(settings)
        active = 0
        peak = 0

        class StubPipeline:
            def __init__(self, *_args, **_kwargs):
                pass

            async def run(self):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.03)
                active -= 1

        with patch("app.services.analysis.AnalysisPipeline", StubPipeline):
            for index in range(5):
                manager._schedule(f"run-{index}")
            tasks = list(manager._tasks.values())
            await asyncio.gather(*tasks)
            await asyncio.sleep(0)
        self.assertEqual(peak, 2)
        self.assertEqual(manager.in_flight(), [])
        self.assertEqual(manager._cancel_events, {})


class ChunkMemoryTests(unittest.TestCase):
    def test_chunk_reader_bounds_live_source_memory(self) -> None:
        # The completed analysis phase has already cleared context.files. The search
        # chunker should stream from the temporary checkout, not rebuild a whole-tree cache.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            content = "# Repository guide\n" + "A useful detail about this project.\n" * 7200
            paths: dict[str, int] = {}
            for index in range(96):
                relative = f"docs/guide-{index:03}.md"
                target = root / relative
                target.parent.mkdir(exist_ok=True)
                target.write_text(content, encoding="utf-8")
                paths[relative] = target.stat().st_size
            corpus_size = sum(paths.values())
            context = PipelineContext(
                analysis_id="memory-test", repo_id="repo-test", owner="owner", name="project",
                branch="main", default_branch="main", url="https://github.com/owner/project",
                root=root, files={}, file_sizes=paths,
            )
            del content
            tracemalloc.start()
            chunks = _build_chunks(context, max_chunks=128, scope="memory-test")
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        self.assertEqual(len(chunks), 128)
        self.assertLess(peak, corpus_size // 2)
        self.assertTrue(all(chunk["kind"] == "doc" for chunk in chunks))

    def test_chunk_reader_uses_source_tree_after_in_memory_text_is_released(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = "def hello(name):\n    return f'hello {name}'\n"
            (root / "src").mkdir()
            (root / "src" / "hello.py").write_text(source, encoding="utf-8")
            parsed = analyze_source("src/hello.py", source, "python")
            context = PipelineContext(
                analysis_id="chunks-test", repo_id="repo-test", owner="owner", name="project",
                branch="main", default_branch="main", url="https://github.com/owner/project",
                root=root, files={}, file_sizes={"src/hello.py": len(source)}, parsed_files=[parsed],
            )
            chunks = _build_chunks(context, max_chunks=10, scope="chunks-test")
        symbols = [chunk for chunk in chunks if chunk["kind"] == "symbol"]
        self.assertTrue(symbols)
        self.assertEqual(symbols[0]["symbol"], "hello")
        self.assertIn("return", symbols[0]["text"])


if __name__ == "__main__":
    unittest.main()
