"""Pydantic contracts shared by the API, the analyzers and the web client.

These mirror the JSON that `apps/api` returns, so the TypeScript types in
`apps/web/lib/types.ts` can be kept in sync field-for-field.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


# --------------------------------------------------------------------- github
class RepoRef(Base):
    owner: str
    name: str
    url: str
    host: Literal["github"] = "github"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class Branch(Base):
    name: str
    sha: str | None = None
    is_default: bool = False
    protected: bool = False


class RepoMetadata(Base):
    owner: str
    name: str
    full_name: str
    description: str | None = None
    default_branch: str = "main"
    html_url: str
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    open_issues: int = 0
    primary_language: str | None = None
    license: str | None = None
    topics: list[str] = Field(default_factory=list)
    size_kb: int = 0
    archived: bool = False
    is_fork: bool = False
    created_at: datetime | None = None
    pushed_at: datetime | None = None
    updated_at: datetime | None = None
    homepage: str | None = None
    has_issues: bool = True


# ------------------------------------------------------------------- analysis
class AnalysisStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageProgress(Base):
    id: str
    label: str
    status: Literal["pending", "running", "done", "skipped", "failed"] = "pending"
    detail: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_ms: int | None = None


class AnalysisRun(Base):
    id: str
    repo_id: str
    status: AnalysisStatus
    stage: str
    progress: float = 0.0
    message: str | None = None
    error: dict | None = None
    warnings: list[dict] = Field(default_factory=list)
    stages: list[StageProgress] = Field(default_factory=list)
    branch: str | None = None
    commit_sha: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    file_count: int = 0
    parsed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    provider_info: dict = Field(default_factory=dict)


# ----------------------------------------------------------------------- code
class SourceFile(Base):
    id: str
    path: str
    language: str
    size_bytes: int = 0
    loc: int = 0
    parsed: bool = False
    parse_error: str | None = None
    symbol_count: int = 0
    complexity: int = 0
    layer: str = "other"
    is_test: bool = False
    is_entrypoint: bool = False
    content_hash: str | None = None
    summary: str | None = None


class SymbolInfo(Base):
    id: str
    file_id: str
    path: str
    name: str
    kind: str  # function | method | class | interface | component | route_handler | variable | schema
    start_line: int
    end_line: int
    signature: str | None = None
    params: list[str] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)
    bases: list[str] = Field(default_factory=list)
    docstring: str | None = None
    complexity: int = 0
    loc: int = 0
    parent: str | None = None
    exported: bool = False
    calls: list[dict] = Field(default_factory=list)
    called_by: list[dict] = Field(default_factory=list)
    is_async: bool = False


class CodeChunk(Base):
    id: str
    path: str
    kind: str  # symbol | file | doc
    symbol: str | None = None
    start_line: int = 1
    end_line: int = 1
    text: str = ""
    tokens: int = 0


class FileContent(Base):
    path: str
    language: str
    content: str
    truncated: bool = False
    size_bytes: int = 0
    loc: int = 0
    symbols: list[SymbolInfo] = Field(default_factory=list)
    imports: list[dict] = Field(default_factory=list)
    dependents: list[dict] = Field(default_factory=list)


# ------------------------------------------------------------------------ api
class ApiEndpoint(Base):
    id: str
    method: str
    path: str
    handler: str | None = None
    file_path: str
    line: int | None = None
    framework: str | None = None
    controller: str | None = None
    service: str | None = None
    auth_required: bool | None = None
    evidence: list[str] = Field(default_factory=list)
    notes: str | None = None
    request_model: str | None = None
    response_model: str | None = None


# ------------------------------------------------------------------- database
class DbField(Base):
    name: str
    type: str | None = None
    primary_key: bool = False
    foreign_key: str | None = None
    nullable: bool = True
    default: str | None = None
    unique: bool = False


class DbModel(Base):
    id: str
    name: str
    table: str | None = None
    orm: str | None = None
    file_path: str
    line: int | None = None
    fields: list[DbField] = Field(default_factory=list)
    relationships: list[dict] = Field(default_factory=list)
    source: str = "code"  # code | migration | prisma | schema


class DbQuery(Base):
    id: str
    file_path: str
    line: int | None = None
    kind: str  # select | insert | update | delete | raw | unknown
    table: str | None = None
    orm: str | None = None
    snippet: str | None = None


class DatabaseTechnology(Base):
    name: str
    kind: str
    confidence: float = 0.5
    evidence: list[str] = Field(default_factory=list)


class DatabaseReport(Base):
    technologies: list[DatabaseTechnology] = Field(default_factory=list)
    models: list[DbModel] = Field(default_factory=list)
    queries: list[DbQuery] = Field(default_factory=list)
    migrations: list[dict] = Field(default_factory=list)
    orms: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ workflows
class WorkflowStep(Base):
    id: str
    label: str
    kind: str  # ui | api | controller | service | repository | database | middleware | external | util
    file_path: str | None = None
    line: int | None = None
    symbol: str | None = None
    detail: str | None = None
    evidence: str | None = None


class Workflow(Base):
    id: str
    name: str
    category: str = "general"
    description: str | None = None
    entry_point: str | None = None
    trigger: str | None = None  # e.g. "POST /api/login"
    steps: list[WorkflowStep] = Field(default_factory=list)
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    trace_truncated: bool = False
    #: Where the entry point lives: application | example | test. Library
    #: repositories only expose example/test apps, and the UI says so instead of
    #: presenting them as shipped routes.
    scope: str | None = None
    scope_note: str | None = None
    route: dict | None = None
    framework: str | None = None


# ---------------------------------------------------------------- dependencies
class DependencyEdge(Base):
    id: str
    source: str
    target: str
    kind: str = "import"  # import | call | inheritance | route | db
    weight: int = 1
    symbols: list[str] = Field(default_factory=list)
    external: bool = False
    line: int | None = None


class GraphNode(Base):
    id: str
    label: str
    kind: str = "file"  # file | module | layer | service | database | external
    layer: str = "other"
    path: str | None = None
    language: str | None = None
    loc: int = 0
    symbols: int = 0
    fan_in: int = 0
    fan_out: int = 0
    coupling: int = 0
    is_cycle_member: bool = False
    summary: str | None = None
    parent: str | None = None
    meta: dict = Field(default_factory=dict)


class GraphEdge(Base):
    id: str
    source: str
    target: str
    kind: str = "import"
    weight: int = 1
    label: str | None = None


class DependencyGraph(Base):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    cycles: list[dict] = Field(default_factory=list)
    hubs: list[dict] = Field(default_factory=list)
    orphans: list[str] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)
    truncated: bool = False


class ArchitectureGraph(Base):
    layers: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    entrypoints: list[dict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# -------------------------------------------------------------------- quality
class QualityIssue(Base):
    id: str
    kind: str
    severity: Literal["info", "low", "medium", "high"] = "info"
    title: str
    detail: str
    files: list[str] = Field(default_factory=list)
    symbol: str | None = None
    metric: dict = Field(default_factory=dict)
    heuristic: bool = True


class QualityReport(Base):
    issues: list[QualityIssue] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    disclaimer: str = (
        "These findings are static-analysis heuristics computed from parsed source code. "
        "They are signals for review, not proof of defects."
    )


# ------------------------------------------------------------------- overview
class LanguageStat(Base):
    language: str
    label: str
    files: int
    loc: int
    percent: float = 0.0


class AnalysisOverview(Base):
    repo: RepoMetadata
    run: AnalysisRun | None = None
    files: int = 0
    parsed_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    loc: int = 0
    languages: list[LanguageStat] = Field(default_factory=list)
    frameworks: list[dict] = Field(default_factory=list)
    databases: list[DatabaseTechnology] = Field(default_factory=list)
    functions: int = 0
    classes: int = 0
    symbols: int = 0
    endpoints: int = 0
    modules: int = 0
    edges: int = 0
    circular_dependencies: int = 0
    high_coupling_modules: int = 0
    workflows: int = 0
    tests_detected: int = 0
    test_files: int = 0
    ci_workflows: list[str] = Field(default_factory=list)
    insights: list[dict] = Field(default_factory=list)
    manifests: list[dict] = Field(default_factory=list)
    dependencies: list[dict] = Field(default_factory=list)


class RepoSummary(Base):
    id: str
    full_name: str
    url: str
    description: str | None = None
    default_branch: str = "main"
    stars: int = 0
    primary_language: str | None = None
    updated_at: datetime | None = None
    last_analysis: AnalysisRun | None = None


class SearchHit(Base):
    id: str
    path: str
    symbol: str | None = None
    kind: str = "symbol"
    start_line: int = 1
    end_line: int = 1
    score: float = 0.0
    snippet: str = ""


class ImpactReport(Base):
    target: dict
    direct_dependencies: list[dict] = Field(default_factory=list)
    indirect_dependencies: list[dict] = Field(default_factory=list)
    dependents: list[dict] = Field(default_factory=list)
    affected_endpoints: list[ApiEndpoint] = Field(default_factory=list)
    affected_workflows: list[dict] = Field(default_factory=list)
    related_tests: list[dict] = Field(default_factory=list)
    risks: list[dict] = Field(default_factory=list)
    graph: DependencyGraph | None = None
    notes: list[str] = Field(default_factory=list)


class GeneratedDoc(Base):
    kind: str
    title: str
    markdown: str
    generated_by: str


class SystemCapabilities(Base):
    storage: dict = Field(default_factory=dict)
    search: dict = Field(default_factory=dict)
    github: dict = Field(default_factory=dict)
    limits: dict = Field(default_factory=dict)


class ErrorEnvelope(Base):
    error: dict
    request_id: str | None = None


class ApiMessage(Base):
    message: str
    detail: Any | None = None
