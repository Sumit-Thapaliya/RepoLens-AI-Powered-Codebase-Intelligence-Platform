"""The analysis pipeline.

Stage order mirrors `repolens_shared.constants.ANALYSIS_STAGES`. Every stage is
isolated: a failure in one file, one parser or one heuristic records a warning
and the run continues. Only the two stages that produce the source tree itself
(resolve/fetch) can fail the run.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import posixpath
import re
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from repolens_graph import (
    analyze_quality,
    build_architecture,
    build_dependency_graph,
    detect_workflows,
    module_graph as build_module_graph,
    set_source_root,
)
from repolens_parser import (
    ProjectIndex,
    analyze_source,
    detect_databases,
    detect_frameworks,
    detect_manifests,
    is_test_path,
    language_stats,
    layer_for_path,
    package_name,
    resolve_imports,
)
from repolens_parser.python_analyzer import is_entrypoint
from repolens_shared.constants import (
    ANALYSIS_STAGES,
    DEFAULT_IGNORED_DIRS,
    DEFAULT_IGNORED_FILE_SUFFIXES,
    Stage,
)
from repolens_shared.errors import EmptyRepositoryError, RepoLensError
from repolens_shared.utils import RUN_SCOPE, language_for_path, sha1, stable_id, truncate

from ..core.config import Settings
from ..core.db import session_scope
from ..models.tables import (
    Analysis,
    AnalysisArtifact,
    ApiEndpointRecord,
    ChunkRecord,
    CycleRecord,
    DbModelRecord,
    DbQueryRecord,
    DbTechnologyRecord,
    FileRecord,
    FrameworkRecord,
    GraphEdgeRecord,
    GraphNodeRecord,
    ManifestRecord,
    QualityIssueRecord,
    Repo,
    SymbolRecord,
    WorkflowRecord,
)
from ..services.github import GitHubClient, read_source_files
from .database import build_database_report
from .docs import generate_docs
from .endpoints import build_endpoints, endpoint_stats
from .insights import build_insights

logger = logging.getLogger(__name__)

STAGE_WEIGHTS = {str(stage["id"].value if hasattr(stage["id"], "value") else stage["id"]): stage["weight"]
                 for stage in ANALYSIS_STAGES}
STAGE_LABELS = {str(stage["id"].value if hasattr(stage["id"], "value") else stage["id"]): stage["label"]
                for stage in ANALYSIS_STAGES}
STAGE_ORDER = [str(stage["id"].value if hasattr(stage["id"], "value") else stage["id"]) for stage in ANALYSIS_STAGES]

MAX_SYMBOLS = 40_000
MAX_CHUNKS = 12_000
# Temporary checkouts live under the OS temp dir and are deleted when a run ends.
WORK_ROOT = Path(tempfile.gettempdir()) / "repolens-work"
GRAPH_NODE_BUDGET = 1_600


def cleanup_orphaned_workdirs() -> None:
    """Remove checkouts left behind by an ungraceful process/container restart."""
    shutil.rmtree(WORK_ROOT, ignore_errors=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)


class AnalysisCancelled(Exception):
    """Raised internally when a user cancels a run."""


@dataclass
class PipelineContext:
    analysis_id: str
    repo_id: str
    owner: str
    name: str
    branch: str
    default_branch: str
    url: str
    root: Path | None = None
    files: dict[str, str] = field(default_factory=dict)
    file_sizes: dict[str, int] = field(default_factory=dict)
    parsed_files: list = field(default_factory=list)
    skipped_files: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


class AnalysisPipeline:
    def __init__(self, analysis_id: str, settings: Settings, cancel_event: threading.Event | None = None):
        self.analysis_id = analysis_id
        self.settings = settings
        self.cancel_event = cancel_event or threading.Event()
        self.started = time.perf_counter()
        self._stage_started: dict[str, float] = {}
        self._completed_weight = 0.0

    # ------------------------------------------------------------- utilities
    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise AnalysisCancelled()
        limit = self.settings.max_analysis_seconds
        if limit and time.perf_counter() - self.started > limit:
            raise RepoLensError(
                f"Analysis stopped after the {limit}-second time limit.",
                hint="Raise MAX_ANALYSIS_SECONDS in your .env file for very large repositories.",
            )

    def _set_stage(self, stage: str, *, detail: str | None = None, fraction: float = 0.0,
                   status: str = "running", warnings: list[dict] | None = None) -> None:
        """Persist progress for one stage."""
        stage = str(stage.value) if isinstance(stage, Stage) else str(stage)
        weight = STAGE_WEIGHTS.get(stage, 0.0)
        progress = min(1.0, self._completed_weight + weight * max(0.0, min(1.0, fraction)))
        with session_scope() as session:
            analysis = session.get(Analysis, self.analysis_id)
            if analysis is None:
                raise AnalysisCancelled()
            stages = list(analysis.stages or [])
            entry = next((item for item in stages if item.get("id") == stage), None)
            now_iso = _iso()
            if entry is None:
                entry = {"id": stage, "label": STAGE_LABELS.get(stage, stage), "status": "pending",
                         "detail": None, "started_at": None, "finished_at": None, "elapsed_ms": None}
                stages.append(entry)
            if status == "running" and entry["status"] != "running":
                entry["started_at"] = now_iso
                self._stage_started[stage] = time.perf_counter()
            entry["status"] = status
            if detail is not None:
                entry["detail"] = detail
            if status in {"done", "failed", "skipped"}:
                entry["finished_at"] = now_iso
                started = self._stage_started.get(stage)
                if started is not None:
                    entry["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            analysis.stages = stages
            analysis.stage = stage
            analysis.progress = progress
            analysis.message = detail or analysis.message
            if warnings:
                analysis.warnings = list(analysis.warnings or []) + warnings
        if status in {"done", "failed", "skipped"}:
            self._completed_weight = min(1.0, self._completed_weight + weight)

    def _warn(self, code: str, message: str, **detail) -> None:
        payload = {"code": code, "message": message, "detail": detail or None, "stage": None}
        with session_scope() as session:
            analysis = session.get(Analysis, self.analysis_id)
            if analysis is not None:
                analysis.warnings = list(analysis.warnings or []) + [payload]

    def _finish(self, *, status: str, error: dict | None = None, message: str | None = None,
                counts: dict | None = None) -> None:
        with session_scope() as session:
            analysis = session.get(Analysis, self.analysis_id)
            if analysis is None:
                return
            analysis.status = status
            analysis.message = message or analysis.message
            analysis.error = error
            if counts:
                for key, value in counts.items():
                    if hasattr(analysis, key):
                        setattr(analysis, key, value)
            if status in {"complete", "failed", "cancelled"}:
                analysis.finished_at = _now()
                analysis.duration_ms = int((time.perf_counter() - self.started) * 1000)
                analysis.progress = 1.0 if status == "complete" else analysis.progress

    # ------------------------------------------------------------------- run
    async def run(self) -> dict:
        RUN_SCOPE.set(self.analysis_id)  # ids made in this run are scoped to it
        try:
            context = await self._stage_resolve()
            await self._stage_fetch(context)
            await self._stage_detect(context)
            await self._stage_parse(context)
            artifacts = await self._stage_analyse(context)
            await self._stage_embed(context, artifacts)
            self._finalise_progress()
            self._finish(
                status="complete",
                message=f"Analysis complete - {len(context.parsed_files)} files parsed, "
                        f"{artifacts['endpoints_count']} endpoints, {len(artifacts['workflows'])} workflows.",
                counts={
                    "file_count": len(context.files) + len(context.skipped_files),
                    "parsed_count": sum(1 for parsed in context.parsed_files if parsed.parse_error is None),
                    "failed_count": sum(1 for parsed in context.parsed_files if parsed.parse_error),
                    "skipped_count": len(context.skipped_files),
                },
            )
            return {"status": "complete", "analysis_id": self.analysis_id, **artifacts.get("summary", {})}
        except AnalysisCancelled:
            self._finish(status="cancelled", message="Analysis cancelled by user.")
            return {"status": "cancelled", "analysis_id": self.analysis_id}
        except RepoLensError as exc:
            logger.warning("Analysis %s failed: %s", self.analysis_id, exc.message)
            self._finish(status="failed", error=exc.to_dict(), message=exc.message)
            return {"status": "failed", "analysis_id": self.analysis_id, "error": exc.to_dict()}
        except Exception as exc:  # pragma: no cover - safety net
            logger.exception("Analysis %s crashed", self.analysis_id)
            payload = {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}",
                       "hint": "This looks like a RepoLens bug - the API logs contain the traceback."}
            self._finish(status="failed", error=payload, message=payload["message"])
            return {"status": "failed", "analysis_id": self.analysis_id, "error": payload}
        finally:
            self._cleanup_sources()

    def _cleanup_sources(self) -> None:
        """Always delete the temporary checkout once a run ends. Nothing is kept on disk.

        The code explorer falls back to fetching files from GitHub on demand, so the checkout
        is never needed after the run.
        """
        shutil.rmtree(WORK_ROOT / self.analysis_id, ignore_errors=True)
        try:
            with session_scope() as session:
                analysis = session.get(Analysis, self.analysis_id)
                if analysis is not None and analysis.source_root:
                    analysis.source_root = None
        except Exception:
            logger.debug("Could not clear source path for %s", self.analysis_id, exc_info=True)

    def _finalise_progress(self) -> None:
        with session_scope() as session:
            analysis = session.get(Analysis, self.analysis_id)
            if analysis is None:
                return
            stages = list(analysis.stages or [])
            for stage in STAGE_ORDER:
                entry = next((item for item in stages if item.get("id") == stage), None)
                if entry is None:
                    stages.append({"id": stage, "label": STAGE_LABELS.get(stage, stage), "status": "skipped",
                                   "detail": "not required for this repository", "started_at": None,
                                   "finished_at": _iso(), "elapsed_ms": 0})
                elif entry["status"] == "running":
                    entry["status"] = "done"
            analysis.stages = stages
            analysis.progress = 1.0

    # --------------------------------------------------------------- stages
    async def _stage_resolve(self) -> PipelineContext:
        self._set_stage(Stage.RESOLVING, detail="Reading repository metadata from GitHub", status="running")
        self._check_cancel()
        with session_scope() as session:
            analysis = session.get(Analysis, self.analysis_id)
            if analysis is None:
                raise AnalysisCancelled()
            repo = session.get(Repo, analysis.repo_id)
            if repo is None:
                raise RepoLensError("Repository record disappeared.", hint="Re-import the repository.")
            branch = analysis.branch or repo.default_branch
            context = PipelineContext(
                analysis_id=self.analysis_id, repo_id=repo.id, owner=repo.owner, name=repo.name,
                branch=branch, default_branch=repo.default_branch, url=repo.url,
            )
        async with GitHubClient(self.settings) as client:
            try:
                sha = await client.get_commit_sha(context.owner, context.name, context.branch)
            except RepoLensError:
                sha = None
            context.stats["commit_sha"] = sha
        with session_scope() as session:
            analysis = session.get(Analysis, self.analysis_id)
            if analysis:
                analysis.commit_sha = context.stats.get("commit_sha")
                analysis.branch = context.branch
        self._set_stage(Stage.RESOLVING, detail=f"Resolved {context.owner}/{context.name}@{context.branch}", status="done",
                        fraction=1.0)
        return context

    async def _stage_fetch(self, context: PipelineContext) -> None:
        self._set_stage(Stage.FETCHING, detail="Downloading sources from GitHub", status="running")
        self._check_cancel()
        workdir = WORK_ROOT / self.analysis_id
        if workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True, exist_ok=True)
        download_task = None
        try:
            async with GitHubClient(self.settings) as client:
                download_task = asyncio.create_task(client.download_sources(
                    context.owner,
                    context.name,
                    context.branch,
                    workdir,
                    self.settings.max_repo_bytes,
                    self.settings.max_files,
                ))
                while not download_task.done():
                    self._check_cancel()
                    limit = self.settings.max_analysis_seconds
                    remaining = limit - (time.perf_counter() - self.started) if limit else 1.0
                    if limit and remaining <= 0:
                        raise RepoLensError(
                            f"Analysis stopped after the {limit}-second time limit.",
                            hint="Raise MAX_ANALYSIS_SECONDS only if this repository is trusted and expected to take longer.",
                        )
                    await asyncio.wait({download_task}, timeout=min(0.25, remaining) if limit else 0.25)
                root, method = download_task.result()
                self._check_cancel()
        finally:
            if download_task is not None and not download_task.done():
                download_task.cancel()
                await asyncio.gather(download_task, return_exceptions=True)
        context.root = root
        set_source_root(str(root))
        with session_scope() as session:
            analysis = session.get(Analysis, self.analysis_id)
            if analysis:
                analysis.source_root = str(root)
                analysis.provider_info = {**(analysis.provider_info or {}), "fetch_method": method}
        self._set_stage(Stage.FETCHING, detail=f"Sources downloaded via {method}", status="done", fraction=1.0)

    async def _stage_detect(self, context: PipelineContext) -> None:
        self._set_stage(Stage.DETECTING, detail="Detecting languages, manifests and frameworks", status="running")
        self._check_cancel()
        assert context.root is not None

        def _read() -> tuple[dict[str, str], dict[str, int], list[dict]]:
            files: dict[str, str] = {}
            sizes: dict[str, int] = {}
            skipped: list[dict] = []
            for path, text, size in read_source_files(
                context.root, self.settings.max_file_bytes, self.settings.max_files,
                DEFAULT_IGNORED_DIRS, DEFAULT_IGNORED_FILE_SUFFIXES,
            ):
                files[path] = text
                sizes[path] = size
            if not files:
                for path in sorted(context.root.rglob("*"))[:200]:
                    if path.is_file() and path.stat().st_size > self.settings.max_file_bytes:
                        skipped.append({"path": path.relative_to(context.root).as_posix(),
                                        "reason": f"file exceeds MAX_FILE_BYTES ({self.settings.max_file_bytes} bytes)"})
            return files, sizes, skipped

        context.files, context.file_sizes, context.skipped_files = await asyncio.to_thread(_read)
        if not context.files:
            raise EmptyRepositoryError(
                "No analysable text files were found in this repository.",
                hint="The repository may be empty, binary-only, or entirely above the file-size limit.",
            )
        context.stats["manifests"] = detect_manifests(context.files)
        context.stats["frameworks"] = detect_frameworks(context.stats["manifests"], [], context.files)
        self._set_stage(Stage.DETECTING,
                        detail=f"{len(context.files)} text files, {len(context.stats['manifests'])} manifest(s)",
                        status="done", fraction=1.0)

    async def _stage_parse(self, context: PipelineContext) -> None:
        paths = list(context.files.items())
        total = len(paths)
        self._set_stage(Stage.PARSING, detail=f"Parsing {total} files with tree-sitter", status="running")
        parsed_files: list = []
        parse_failures: list[dict] = []
        workers = max(1, min(8, (self.settings.analysis_workers or 2) * 2))
        loop = asyncio.get_running_loop()

        def _parse_batch(batch: list[tuple[str, str]]) -> list:
            return [analyze_source(path, text, language_for_path(path)) for path, text in batch]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            chunk_size = 64
            for start in range(0, total, chunk_size):
                self._check_cancel()
                batch = paths[start: start + chunk_size]
                ctx = contextvars.copy_context()  # the worker thread must see the run scope too
                results = await loop.run_in_executor(pool, ctx.run, _parse_batch, batch)
                parsed_files.extend(results)
                for parsed in results:
                    if parsed.parse_error:
                        parse_failures.append({"path": parsed.path, "error": parsed.parse_error})
                fraction = min(1.0, (start + len(batch)) / max(1, total))
                self._set_stage(Stage.PARSING, detail=f"Parsed {start + len(batch)}/{total} files",
                                fraction=fraction)
        context.parsed_files = parsed_files
        context.stats["parse_failures"] = parse_failures[:40]
        context.stats["language_stats"] = language_stats(parsed_files)
        context.stats["frameworks"] = detect_frameworks(context.stats["manifests"], parsed_files, context.files)
        detail = f"{sum(1 for p in parsed_files if p.parse_error is None)}/{total} parsed"
        if parse_failures:
            detail += f", {len(parse_failures)} failed"
            self._warn("parse_failures", f"{len(parse_failures)} file(s) could not be parsed",
                       files=[failure["path"] for failure in parse_failures[:20]])
        self._set_stage(Stage.PARSING, detail=detail, status="done", fraction=1.0)

    async def _stage_analyse(self, context: PipelineContext) -> dict:
        parsed_files = context.parsed_files

        # ------------------------------------------------------- dependencies
        # (built before the API surface so endpoint records can reference the
        #  service each handler actually calls)
        self._set_stage(Stage.GRAPHING, detail="Resolving imports and building the dependency graph", status="running")
        self._check_cancel()
        files = context.files
        index = ProjectIndex.build(list(files)).with_configs(files)
        resolve_stats = resolve_imports(parsed_files, index)
        external_counter: dict[str, int] = {}
        for parsed in parsed_files:
            for imp in parsed.imports:
                if imp.resolved_path:
                    continue
                name = package_name(imp.module, parsed.language)
                if name:
                    external_counter[name] = external_counter.get(name, 0) + 1
        graph = build_dependency_graph(parsed_files, external_counter)
        context.stats["resolve"] = resolve_stats
        architecture = build_architecture(graph, parsed_files)
        modules = build_module_graph(graph)
        self._set_stage(Stage.GRAPHING,
                        detail=f"{graph.stats['files']} nodes, {graph.stats['edges']} edges, "
                               f"{graph.stats['cycles']} cycle(s)",
                        status="done", fraction=1.0)

        # ------------------------------------------------------------- APIs
        self._set_stage(Stage.EXTRACTING_APIS, detail="Extracting API surface", status="running")
        endpoints = build_endpoints(parsed_files, graph, scope=self.analysis_id)
        self._set_stage(Stage.EXTRACTING_APIS, detail=f"{len(endpoints)} endpoint(s)", status="done", fraction=1.0)

        # ---------------------------------------------------------- database
        self._set_stage(Stage.EXTRACTING_DATABASE, detail="Extracting database layer", status="running")
        self._check_cancel()
        technologies = detect_databases(context.stats.get("manifests", []), parsed_files, files)
        database = build_database_report(parsed_files, technologies, files, scope=self.analysis_id)
        self._set_stage(Stage.EXTRACTING_DATABASE,
                        detail=f"{database['stats']['models']} model(s), {database['stats']['queries']} query site(s)",
                        status="done", fraction=1.0)

        # --------------------------------------------------------- workflows
        self._set_stage(Stage.WORKFLOWS, detail="Tracing application workflows", status="running")
        self._check_cancel()
        workflows = detect_workflows(parsed_files, graph, str(context.root), endpoints,
                                     scope=self.analysis_id)
        self._set_stage(Stage.WORKFLOWS, detail=f"{len(workflows)} workflow(s) traced", status="done", fraction=1.0)

        # ----------------------------------------------------------- quality
        self._set_stage(Stage.QUALITY, detail="Running code-quality heuristics", status="running")
        self._check_cancel()
        quality = analyze_quality(parsed_files, graph, files, scope=self.analysis_id)
        self._set_stage(Stage.QUALITY,
                        detail=f"{quality['summary']['issues']} finding(s), health {quality['summary']['health_score']}/100",
                        status="done", fraction=1.0)

        # ------------------------------------------------------------ persist
        overview = self._build_overview(context, graph, endpoints, database, workflows, quality, architecture)
        self._persist(context, graph, endpoints, database, workflows, quality, architecture, modules, overview)
        return {"endpoints_count": len(endpoints), "workflows": workflows,
                "summary": {"files": len(context.files), "endpoints": len(endpoints),
                            "workflows": len(workflows), "issues": quality["summary"]["issues"]}}

    async def _stage_embed(self, context: PipelineContext, artifacts: dict) -> None:
        """Build the search index: text chunks only. No vectors are computed or stored."""
        self._set_stage(Stage.INDEXING, detail="Building the code search index", status="running")
        self._check_cancel()
        chunks = _build_chunks(context, max_chunks=MAX_CHUNKS, scope=self.analysis_id)
        _store_chunks(
            self.analysis_id,
            chunks,
            store_source_snippets=self.settings.store_source_snippets,
        )
        with session_scope() as session:
            analysis = session.get(Analysis, self.analysis_id)
            if analysis:
                analysis.provider_info = {**(analysis.provider_info or {}),
                                          "search": {"ranking": "lexical", "chunks": len(chunks)}}
        self._set_stage(Stage.INDEXING, detail=f"{len(chunks)} chunks indexed for search", status="done",
                        fraction=1.0)

    # ----------------------------------------------------------- artefacts
    def _build_overview(self, context: PipelineContext, graph, endpoints, database, workflows, quality,
                        architecture) -> dict:
        parsed_files = context.parsed_files
        languages = context.stats.get("language_stats", [])
        functions = sum(1 for parsed in parsed_files for symbol in parsed.symbols if symbol.kind in {"function", "method"})
        classes = sum(1 for parsed in parsed_files for symbol in parsed.symbols if symbol.kind == "class")
        symbols = sum(len(parsed.symbols) for parsed in parsed_files)
        test_files = [parsed for parsed in parsed_files if is_test_path(parsed.path)]
        modules = {posixpath.dirname(path) or "." for path in context.files}
        with session_scope() as session:
            analysis = session.get(Analysis, self.analysis_id)
            repo = session.get(Repo, context.repo_id)
            run_payload = _analysis_payload(analysis) if analysis else None
            repo_payload = _repo_payload(repo) if repo else {}
            commit_sha = analysis.commit_sha if analysis else None

        ci_workflows = sorted({
            path for path in context.files
            if path.startswith(".github/workflows/") or path in {"Jenkinsfile", ".gitlab-ci.yml"}
        })
        overview = {
            "repo": repo_payload,
            "run": run_payload,
            "files": len(context.files),
            "parsed_files": sum(1 for parsed in parsed_files if parsed.parse_error is None),
            "failed_files": sum(1 for parsed in parsed_files if parsed.parse_error),
            "skipped_files": len(context.skipped_files),
            "loc": sum(parsed.loc for parsed in parsed_files),
            "languages": languages,
            "frameworks": context.stats.get("frameworks", []),
            "databases": database.get("technologies", []),
            "functions": functions,
            "classes": classes,
            "symbols": symbols,
            "endpoints": len(endpoints),
            "modules": len(modules),
            "edges": graph.stats.get("edges", 0),
            "circular_dependencies": graph.stats.get("cycles", 0),
            "high_coupling_modules": graph.stats.get("high_coupling", 0),
            "workflows": len(workflows),
            "test_files": len(test_files),
            "ci_workflows": ci_workflows[:20],
            "commit_sha": commit_sha,
            "hubs": graph.hubs[:8],
            "layers": architecture.get("layers", []),
            "endpoint_stats": endpoint_stats(endpoints),
            "database_stats": database.get("stats", {}),
            "quality": quality.get("summary", {}),
            "graph_stats": graph.stats,
            "manifests": [
                {"path": manifest["path"], "ecosystem": manifest.get("ecosystem"),
                 "name": manifest.get("name"), "version": manifest.get("version"),
                 "dependencies": len(manifest.get("dependencies", [])),
                 "scripts": list((manifest.get("scripts") or {}).keys())[:12],
                 "error": manifest.get("error")}
                for manifest in context.stats.get("manifests", [])
            ],
            "top_dependencies": graph.external_dependencies[:24],
            "parse_failures": context.stats.get("parse_failures", [])[:20],
            "resolve_stats": context.stats.get("resolve", {}),
            "warnings": (run_payload or {}).get("warnings", []),
            "limits": {"max_files": self.settings.max_files, "max_file_bytes": self.settings.max_file_bytes},
        }
        overview["insights"] = build_insights(
            parsed_files=parsed_files, graph=graph, endpoints=endpoints, database=database, workflows=workflows,
            frameworks=context.stats.get("frameworks", []), quality=quality,
            manifests=context.stats.get("manifests", []),
        )
        context.stats["overview"] = overview
        context.stats["architecture"] = architecture
        context.stats["graph"] = graph
        context.stats["database"] = database
        context.stats["quality"] = quality
        context.stats["endpoints"] = endpoints
        context.stats["workflows"] = workflows
        return overview

    def _persist(self, context, graph, endpoints, database, workflows, quality, architecture, modules, overview) -> None:
        """Write every artefact of the run. Rows are de-duplicated by primary key
        so a repeated detector result can never fail the transaction."""
        parsed_files = context.parsed_files
        graph_nodes = sorted(graph.nodes.values(), key=lambda node: -node.coupling)
        truncated = len(graph_nodes) > GRAPH_NODE_BUDGET
        kept = {node.path for node in graph_nodes[:GRAPH_NODE_BUDGET]}
        graph_payload = {
            "nodes": [node.to_dict() for node in graph_nodes[:GRAPH_NODE_BUDGET]],
            "edges": [edge for edge in graph.edges if edge["source"] in kept and edge["target"] in kept][:12_000],
            "cycles": graph.cycles[:25],
            "hubs": graph.hubs[:20],
            "orphans": graph.orphans[:60],
            "stats": graph.stats,
            "module_stats": graph.module_stats,
            "external_dependencies": graph.external_dependencies,
            "truncated": truncated,
            "note": (f"Showing the {GRAPH_NODE_BUDGET} most connected files of {len(graph.nodes)} "
                     "to keep the graph responsive." if truncated else None),
        }

        with session_scope() as session:
            for model in (FileRecord, SymbolRecord, ChunkRecord, ApiEndpointRecord, DbModelRecord, DbQueryRecord,
                          DbTechnologyRecord, WorkflowRecord, GraphNodeRecord, GraphEdgeRecord, CycleRecord,
                          FrameworkRecord, ManifestRecord, QualityIssueRecord):
                session.query(model).filter(model.analysis_id == self.analysis_id).delete(synchronize_session=False)
            session.query(AnalysisArtifact).filter(AnalysisArtifact.analysis_id == self.analysis_id).delete(
                synchronize_session=False)

            file_rows: list[FileRecord] = []
            symbol_rows: list[SymbolRecord] = []
            symbol_budget = MAX_SYMBOLS
            for parsed in parsed_files:
                file_id = stable_id("file", self.analysis_id, parsed.path)
                is_test = is_test_path(parsed.path)
                content = context.files.get(parsed.path) or ""
                # Full source files are never persisted with analysis artifacts. The code
                # explorer fetches them from GitHub on demand after the temporary checkout is removed.
                file_rows.append(FileRecord(
                    id=file_id, analysis_id=self.analysis_id, path=parsed.path, language=parsed.language,
                    size_bytes=parsed.size, loc=parsed.loc, parsed=parsed.parse_error is None,
                    parse_error=parsed.parse_error, warnings=parsed.warnings[:6], symbol_count=len(parsed.symbols),
                    complexity=max([symbol.complexity for symbol in parsed.symbols] or [1]),
                    layer=layer_for_path(parsed.path, is_test), is_test=is_test,
                    is_entrypoint=is_entrypoint(parsed.path, parsed.language),
                    content_hash=sha1(content[:200_000]), summary=_file_summary(parsed),
                    content=None,
                ))
                for symbol in parsed.symbols:
                    if symbol_budget <= 0:
                        break
                    symbol_budget -= 1
                    symbol_rows.append(SymbolRecord(
                        id=stable_id("symbol", self.analysis_id, parsed.path, symbol.name, symbol.start_line),
                        analysis_id=self.analysis_id, file_id=file_id, path=parsed.path, name=symbol.name,
                        kind=symbol.kind, start_line=symbol.start_line, end_line=symbol.end_line,
                        signature=symbol.signature, params=symbol.params[:20], decorators=symbol.decorators[:10],
                        bases=symbol.bases[:10], docstring=truncate(symbol.docstring, 1200) if symbol.docstring else None,
                        complexity=symbol.complexity, loc=symbol.loc, parent=symbol.parent, exported=symbol.exported,
                        is_async=symbol.is_async, calls=[call.to_dict() for call in symbol.calls[:120]],
                        shingle=symbol.shingle,
                    ))

            endpoint_rows = [ApiEndpointRecord(
                id=endpoint["id"], analysis_id=self.analysis_id, method=endpoint["method"], path=endpoint["path"],
                handler=endpoint["handler"], file_path=endpoint["file_path"], line=endpoint["line"],
                framework=endpoint["framework"], controller=endpoint["controller"], service=endpoint["service"],
                auth_required=endpoint["auth_required"], evidence=endpoint["evidence"], notes=endpoint["notes"],
                request_model=endpoint["request_model"], response_model=endpoint["response_model"],
                is_example=endpoint.get("is_example", False), is_test=endpoint.get("is_test", False),
                declarations=endpoint.get("declarations", []),
            ) for endpoint in endpoints]  # `local_path` is intentionally not persisted


            model_rows = [DbModelRecord(
                id=model["id"], analysis_id=self.analysis_id, name=model["name"],
                table_name=model.get("table"), orm=model.get("orm"), file_path=model["file_path"],
                line=model.get("line"), fields=model.get("fields", []),
                relationships=model.get("relationships", []), source=model.get("source", "code"),
            ) for model in database.get("models", [])]

            query_rows = [DbQueryRecord(
                id=query["id"], analysis_id=self.analysis_id, file_path=query["file_path"],
                line=query.get("line"), kind=query["kind"], table_name=query.get("table"),
                orm=query.get("orm"), snippet=query.get("snippet"),
            ) for query in database.get("queries", [])]

            tech_rows = [DbTechnologyRecord(
                id=stable_id("dbtech", self.analysis_id, tech["name"]), analysis_id=self.analysis_id,
                name=tech["name"], kind=tech.get("kind", "unknown"),
                confidence=float(tech.get("confidence", 0.5)), evidence=tech.get("evidence", []),
            ) for tech in database.get("technologies", [])]

            workflow_rows = [WorkflowRecord(
                id=workflow["id"], analysis_id=self.analysis_id, name=workflow["name"],
                category=workflow["category"], category_label=workflow.get("category_label"),
                description=workflow.get("description"), entry_point=workflow.get("entry_point"),
                trigger=workflow.get("trigger"), framework=workflow.get("framework"),
                steps=workflow.get("steps", []), confidence=float(workflow.get("confidence", 0.0)),
                evidence=workflow.get("evidence", []), files=workflow.get("files", []),
                trace_truncated=bool(workflow.get("trace_truncated")), route=workflow.get("route"),
                scope=workflow.get("scope"), scope_note=workflow.get("scope_note"),
            ) for workflow in workflows]

            cycle_members = {path for cycle in graph.cycles for path in cycle}
            node_rows = [GraphNodeRecord(
                id=stable_id("gnode", self.analysis_id, node.path), analysis_id=self.analysis_id,
                path=node.path, label=posixpath.basename(node.path), kind="file", layer=node.layer,
                language=node.language, loc=node.loc, symbols=node.symbols, fan_in=node.fan_in,
                fan_out=node.fan_out, coupling=node.coupling, is_cycle_member=node.path in cycle_members,
                is_test=node.is_test, is_entrypoint=node.is_entrypoint,
            ) for node in graph.nodes.values()]

            edge_rows = [GraphEdgeRecord(
                id=stable_id("gedge", self.analysis_id, edge["source"], edge["target"], edge["kind"]),
                analysis_id=self.analysis_id, source=edge["source"], target=edge["target"],
                kind=edge["kind"], weight=edge["weight"], symbols=edge.get("symbols", []),
                line=edge.get("line"),
            ) for edge in graph.edges]

            cycle_rows = [CycleRecord(
                id=stable_id("cycle", self.analysis_id, ",".join(cycle)), analysis_id=self.analysis_id,
                paths=cycle, size=len(cycle),
            ) for cycle in graph.cycles]

            framework_rows = [FrameworkRecord(
                id=stable_id("framework", self.analysis_id, framework["name"]), analysis_id=self.analysis_id,
                name=framework["name"], ecosystem=framework.get("ecosystem"),
                confidence=float(framework.get("confidence", 0.5)), evidence=framework.get("evidence", []),
            ) for framework in context.stats.get("frameworks", [])]

            manifest_rows = [ManifestRecord(
                id=stable_id("manifest", self.analysis_id, manifest["path"]), analysis_id=self.analysis_id,
                path=manifest["path"], ecosystem=manifest.get("ecosystem"), name=manifest.get("name"),
                version=manifest.get("version"), dependencies=manifest.get("dependencies", [])[:300],
                scripts=manifest.get("scripts", {}), error=manifest.get("error"),
            ) for manifest in context.stats.get("manifests", [])]

            issue_rows = [QualityIssueRecord(
                id=issue["id"], analysis_id=self.analysis_id, kind=issue["kind"], severity=issue["severity"],
                title=issue["title"][:380], detail=issue["detail"], files=issue["files"], symbol=issue["symbol"],
                metric=issue["metric"], heuristic=bool(issue.get("heuristic", True)),
            ) for issue in quality.get("issues", [])]

            for batch in (file_rows, symbol_rows, endpoint_rows, model_rows, query_rows, tech_rows, workflow_rows,
                          node_rows, edge_rows, cycle_rows, framework_rows, manifest_rows, issue_rows):
                for start in range(0, len(batch), 1500):
                    session.bulk_save_objects(_dedupe(batch[start:start + 1500]))
                    session.flush()

            artifacts = {
                "overview": overview,
                "architecture": architecture,
                "dependency_graph": graph_payload,
                "module_graph": modules,
                "database": database,
                "quality": quality,
                "insights": {"insights": overview["insights"]},
            }
            for kind, payload in artifacts.items():
                session.add(AnalysisArtifact(id=stable_id("artifact", self.analysis_id, kind),
                                             analysis_id=self.analysis_id, kind=kind, payload=payload,
                                             generated_by="analysis-pipeline"))
            docs = {}
            for doc_kind in ("readme", "api", "onboarding"):
                document = generate_docs(
                    doc_kind, overview=overview, architecture=architecture, endpoints=endpoints, database=database,
                    workflows=workflows, frameworks=context.stats.get("frameworks", []), graph_stats=graph.stats,
                    quality=quality,
                )
                docs[doc_kind] = document
                session.add(AnalysisArtifact(id=stable_id("doc", self.analysis_id, doc_kind),
                                             analysis_id=self.analysis_id, kind=f"doc:{doc_kind}",
                                             payload=document, generated_by=document["generated_by"]))
            context.stats["docs"] = docs


def _dedupe(rows: list) -> list:
    """Guarantee primary-key uniqueness before a bulk insert.

    Detectors run in several passes (framework patterns, generic symbol scan,
    migration parsing) so the same logical entity can be produced twice; the
    first occurrence wins and the duplicate is dropped instead of failing the run.
    """
    seen: set = set()
    out: list = []
    for row in rows:
        key = getattr(row, "id", None)
        if key is None:
            out.append(row)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _parsed_identifier_terms(parsed) -> list[str]:
    """Extract structured code identifiers without retaining comments or literals."""
    terms: list[str] = []
    for symbol in parsed.symbols:
        terms.extend([symbol.name, symbol.kind, symbol.parent or "", *symbol.params])
        for call in symbol.calls:
            terms.extend([call.name, call.qualifier or "", call.full or ""])
    for item in parsed.imports:
        terms.extend([item.module, *item.names])
    terms.extend(parsed.exports)
    for route in parsed.routes:
        terms.extend([route.handler or "", route.request_model or "", route.response_model or ""])
    for model in parsed.models:
        terms.append(model.name)
        terms.extend(field.get("name", "") for field in model.fields if isinstance(field, dict))
    for query in parsed.queries:
        terms.extend([query.orm or "", query.kind])
    return list(dict.fromkeys(term.strip() for term in terms if isinstance(term, str) and term.strip()))


def _build_chunks(context: PipelineContext, max_chunks: int, scope: str = "") -> list[dict]:
    """Symbol-level, file-level and doc-level chunks with real line ranges."""
    chunks: list[dict] = []
    lines_cache: dict[str, list[str]] = {}

    def lines_for(path: str) -> list[str]:
        if path not in lines_cache:
            lines_cache[path] = (context.files.get(path) or "").splitlines()
        return lines_cache[path]

    # Documentation first: README and docs/ are the highest-signal context.
    for path, content in context.files.items():
        lowered = path.lower()
        is_doc = lowered.endswith((".md", ".mdx", ".rst", ".adoc")) or lowered in {"readme", "docs/index.md"}
        if not is_doc or not content.strip():
            continue
        for index in range(0, len(content), 4000):
            text = content[index: index + 4000]
            if len(text.strip()) < 40:
                continue
            line_start = content[:index].count("\n") + 1
            chunks.append({"id": stable_id("chunk-doc", scope, path, index), "path": path, "symbol": None, "kind": "doc",
                           "start_line": line_start, "end_line": line_start + text.count("\n"),
                           "text": f"{path}\n{text}"[:6000], "identifiers": [],
                           "tokens": max(1, len(text) // 4), "priority": 0})
            if len(chunks) >= max_chunks:
                return chunks[:max_chunks]

    for parsed in context.parsed_files:
        if parsed.parse_error:
            continue
        file_lines = lines_for(parsed.path)
        identifiers = _parsed_identifier_terms(parsed)
        for symbol in parsed.symbols:
            if symbol.kind not in {"function", "method", "class", "component"}:
                continue
            body = "\n".join(file_lines[symbol.start_line - 1: min(len(file_lines), symbol.end_line)])
            if len(body) > 4000:
                body = body[:4000] + "\n… (truncated)"
            text = (
                f"file: {parsed.path}\n"
                f"language: {parsed.language}\n"
                f"symbol: {symbol.kind} {symbol.name}"
                + (f" in class {symbol.parent}" if symbol.parent else "") + "\n"
                + (f"purpose: {symbol.docstring}\n" if symbol.docstring else "")
                + f"code:\n{body}"
            )
            chunks.append({"id": stable_id("chunk-symbol", scope, parsed.path, symbol.name, symbol.start_line),
                           "path": parsed.path, "symbol": symbol.name, "kind": "symbol", "identifiers": identifiers,
                           "start_line": symbol.start_line, "end_line": symbol.end_line,
                           "text": text[:6000], "tokens": max(1, len(text) // 4), "priority": 1})
            if len(chunks) >= max_chunks:
                return chunks[:max_chunks]
        # File-level summary chunk keeps context for files with no parseable symbols.
        if len(parsed.symbols) <= 2:
            content = context.files.get(parsed.path) or ""
            header = content[:2500]
            if len(header.strip()) > 60:
                chunks.append({
                    "id": stable_id("chunk-file", scope, parsed.path), "path": parsed.path, "symbol": None, "kind": "file",
                    "start_line": 1, "end_line": max(1, header.count("\n")), "identifiers": identifiers,
                    "text": f"file: {parsed.path}\nlanguage: {parsed.language}\ncontent:\n{header}"[:6000],
                    "tokens": max(1, len(header) // 4), "priority": 2,
                })
            if len(chunks) >= max_chunks:
                return chunks[:max_chunks]
    return chunks[:max_chunks]


def _store_chunks(analysis_id: str, chunks: list[dict], *, store_source_snippets: bool = False) -> None:
    """Persist a bounded search index, not full source excerpts by default."""
    token_re = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}|\d+")
    rows = []
    for chunk in chunks:
        if store_source_snippets:
            indexed_text = chunk["text"]
        else:
            # Retain structured code identifiers and paths only. The index deliberately
            # excludes comments, docstrings, string literals, syntax and line text.
            terms = []
            seen = set()
            source_terms = [chunk["path"], chunk.get("symbol") or "", *chunk.get("identifiers", [])]
            for source_term in source_terms:
                spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", source_term)
                candidates = [source_term, *token_re.findall(spaced.replace("_", " ").replace(".", " "))]
                for term in candidates:
                    if not term:
                        continue
                    folded = term.casefold()
                    if folded not in seen:
                        seen.add(folded)
                        terms.append(term)
                    if len(terms) >= 800:
                        break
                if len(terms) >= 800:
                    break
            indexed_text = "__INDEX__ " + " ".join(terms)
        rows.append(ChunkRecord(
            id=chunk["id"], analysis_id=analysis_id, path=chunk["path"], symbol=chunk.get("symbol"),
            kind=chunk["kind"], start_line=chunk["start_line"], end_line=chunk["end_line"],
            text=indexed_text, tokens=chunk["tokens"],
        ))

    with session_scope() as session:
        session.query(ChunkRecord).filter(ChunkRecord.analysis_id == analysis_id).delete(synchronize_session=False)
        for start_index in range(0, len(rows), 1000):
            session.bulk_save_objects(rows[start_index: start_index + 1000])
            session.flush()


def _file_summary(parsed) -> str:
    kinds: dict[str, int] = {}
    for symbol in parsed.symbols:
        kinds[symbol.kind] = kinds.get(symbol.kind, 0) + 1
    parts = [f"{parsed.language}", f"{parsed.loc} LOC"]
    if kinds:
        parts.append(", ".join(f"{count} {kind}{'s' if count > 1 else ''}" for kind, count in sorted(kinds.items())))
    if parsed.routes:
        parts.append(f"{len(parsed.routes)} route(s)")
    if parsed.models:
        parts.append(f"{len(parsed.models)} model(s)")
    if parsed.parse_error:
        parts.append("unparsed")
    if parsed.docstring:
        parts.append(truncate(parsed.docstring, 160))
    return " · ".join(parts)


def _analysis_payload(analysis: Analysis | None) -> dict | None:
    if analysis is None:
        return None
    return {
        "id": analysis.id, "repo_id": analysis.repo_id, "status": analysis.status, "stage": analysis.stage,
        "progress": analysis.progress, "message": analysis.message, "error": analysis.error,
        "warnings": analysis.warnings or [], "stages": analysis.stages or [], "branch": analysis.branch,
        "commit_sha": analysis.commit_sha, "started_at": _iso_value(analysis.started_at),
        "finished_at": _iso_value(analysis.finished_at), "duration_ms": analysis.duration_ms,
        "file_count": analysis.file_count, "parsed_count": analysis.parsed_count,
        "failed_count": analysis.failed_count, "skipped_count": analysis.skipped_count,
        "provider_info": analysis.provider_info or {},
    }


def _repo_payload(repo: Repo | None) -> dict:
    if repo is None:
        return {}
    return {
        "owner": repo.owner, "name": repo.name, "full_name": repo.full_name, "url": repo.url,
        "description": repo.description, "default_branch": repo.default_branch, "html_url": repo.url,
        "stars": repo.stars, "forks": repo.forks, "watchers": repo.watchers, "open_issues": repo.open_issues,
        "primary_language": repo.primary_language, "license": repo.license, "topics": repo.topics or [],
        "size_kb": repo.size_kb, "archived": repo.archived, "is_fork": repo.is_fork, "homepage": repo.homepage,
        "created_at": _iso_value(repo.github_created_at), "pushed_at": _iso_value(repo.github_pushed_at),
        "updated_at": _iso_value(repo.github_pushed_at),
    }


def _iso_value(value) -> str | None:
    return value.isoformat() if value is not None else None


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now().isoformat()
