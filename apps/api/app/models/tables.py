"""SQLAlchemy models - the single schema for RepoLens.

The design keeps a hard boundary around ``analysis_id``: every artefact of a run
belongs to exactly one analysis row, which makes re-analysis, diffing and
cleanup trivial.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(200), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    full_name: Mapped[str] = mapped_column(String(400), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    stars: Mapped[int] = mapped_column(Integer, default=0)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    watchers: Mapped[int] = mapped_column(Integer, default=0)
    open_issues: Mapped[int] = mapped_column(Integer, default=0)
    primary_language: Mapped[str | None] = mapped_column(String(80), nullable=True)
    license: Mapped[str | None] = mapped_column(String(120), nullable=True)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    size_kb: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fork: Mapped[bool] = mapped_column(Boolean, default=False)
    homepage: Mapped[str | None] = mapped_column(String(400), nullable=True)
    github_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    github_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    analyses: Mapped[list["Analysis"]] = relationship(back_populates="repo", cascade="all, delete-orphan")


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    repo_id: Mapped[str] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    stages: Mapped[list] = mapped_column(JSON, default=list)
    branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_root: Mapped[str | None] = mapped_column(String(600), nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    parsed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    provider_info: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    repo: Mapped[Repo] = relationship(back_populates="analyses")


class FileRecord(Base):
    __tablename__ = "files"
    __table_args__ = (UniqueConstraint("analysis_id", "path", name="uq_file_path"), Index("ix_files_analysis", "analysis_id"))

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(String(700), index=True)
    language: Mapped[str] = mapped_column(String(40), default="unknown")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    loc: Mapped[int] = mapped_column(Integer, default=0)
    parsed: Mapped[bool] = mapped_column(Boolean, default=False)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    complexity: Mapped[int] = mapped_column(Integer, default=0)
    layer: Mapped[str] = mapped_column(String(20), default="other")
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    is_entrypoint: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)


class SymbolRecord(Base):
    __tablename__ = "symbols"
    __table_args__ = (Index("ix_symbols_analysis_path", "analysis_id", "path"), Index("ix_symbols_name", "analysis_id", "name"))

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    file_id: Mapped[str] = mapped_column(String(40), index=True)
    path: Mapped[str] = mapped_column(String(700))
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(40), default="function")
    start_line: Mapped[int] = mapped_column(Integer, default=1)
    end_line: Mapped[int] = mapped_column(Integer, default=1)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[list] = mapped_column(JSON, default=list)
    decorators: Mapped[list] = mapped_column(JSON, default=list)
    bases: Mapped[list] = mapped_column(JSON, default=list)
    docstring: Mapped[str | None] = mapped_column(Text, nullable=True)
    complexity: Mapped[int] = mapped_column(Integer, default=1)
    loc: Mapped[int] = mapped_column(Integer, default=1)
    parent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    exported: Mapped[bool] = mapped_column(Boolean, default=False)
    is_async: Mapped[bool] = mapped_column(Boolean, default=False)
    calls: Mapped[list] = mapped_column(JSON, default=list)
    shingle: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ChunkRecord(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(String(700), index=True)
    symbol: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="symbol")
    start_line: Mapped[int] = mapped_column(Integer, default=1)
    end_line: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer, default=0)


class ApiEndpointRecord(Base):
    __tablename__ = "api_endpoints"
    __table_args__ = (Index("ix_endpoints_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    method: Mapped[str] = mapped_column(String(20), default="GET")
    path: Mapped[str] = mapped_column(String(500))
    handler: Mapped[str | None] = mapped_column(String(300), nullable=True)
    file_path: Mapped[str] = mapped_column(String(700))
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    framework: Mapped[str | None] = mapped_column(String(120), nullable=True)
    controller: Mapped[str | None] = mapped_column(String(300), nullable=True)
    service: Mapped[str | None] = mapped_column(String(300), nullable=True)
    auth_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_model: Mapped[str | None] = mapped_column(String(300), nullable=True)
    response_model: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: True when the *primary* declaration lives in an examples/ or tests/ folder.
    is_example: Mapped[bool] = mapped_column(Boolean, default=False)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Every declaration of this (method, path) pair, primary first. Kept so
    #: deduplication is visible instead of silently dropping evidence.
    declarations: Mapped[list] = mapped_column(JSON, default=list)


class DbModelRecord(Base):
    __tablename__ = "db_models"
    __table_args__ = (Index("ix_db_models_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(300))
    table_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    orm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_path: Mapped[str] = mapped_column(String(700))
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fields: Mapped[list] = mapped_column(JSON, default=list)
    relationships: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(40), default="code")


class DbQueryRecord(Base):
    __tablename__ = "db_queries"
    __table_args__ = (Index("ix_db_queries_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    file_path: Mapped[str] = mapped_column(String(700))
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(40), default="unknown")
    table_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    orm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)


class DbTechnologyRecord(Base):
    __tablename__ = "db_technologies"
    __table_args__ = (Index("ix_db_tech_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(80), default="relational")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence: Mapped[list] = mapped_column(JSON, default=list)


class WorkflowRecord(Base):
    __tablename__ = "workflows"
    __table_args__ = (Index("ix_workflows_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(40), default="general")
    category_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_point: Mapped[str | None] = mapped_column(String(300), nullable=True)
    trigger: Mapped[str | None] = mapped_column(String(300), nullable=True)
    framework: Mapped[str | None] = mapped_column(String(120), nullable=True)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    files: Mapped[list] = mapped_column(JSON, default=list)
    trace_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    route: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: application | example | test - library repos only expose example/test apps.
    scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    scope_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class GraphNodeRecord(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (Index("ix_graph_nodes_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(String(700), index=True)
    label: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20), default="file")
    layer: Mapped[str] = mapped_column(String(20), default="other")
    language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    loc: Mapped[int] = mapped_column(Integer, default=0)
    symbols: Mapped[int] = mapped_column(Integer, default=0)
    fan_in: Mapped[int] = mapped_column(Integer, default=0)
    fan_out: Mapped[int] = mapped_column(Integer, default=0)
    coupling: Mapped[int] = mapped_column(Integer, default=0)
    is_cycle_member: Mapped[bool] = mapped_column(Boolean, default=False)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    is_entrypoint: Mapped[bool] = mapped_column(Boolean, default=False)


class GraphEdgeRecord(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (Index("ix_graph_edges_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(700), index=True)
    target: Mapped[str] = mapped_column(String(700), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="import")
    weight: Mapped[int] = mapped_column(Integer, default=1)
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CycleRecord(Base):
    __tablename__ = "cycles"
    __table_args__ = (Index("ix_cycles_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    paths: Mapped[list] = mapped_column(JSON, default=list)
    size: Mapped[int] = mapped_column(Integer, default=2)


class FrameworkRecord(Base):
    __tablename__ = "frameworks"
    __table_args__ = (Index("ix_frameworks_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(160))
    ecosystem: Mapped[str | None] = mapped_column(String(60), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence: Mapped[list] = mapped_column(JSON, default=list)


class ManifestRecord(Base):
    __tablename__ = "manifests"
    __table_args__ = (Index("ix_manifests_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(String(700))
    ecosystem: Mapped[str | None] = mapped_column(String(60), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    scripts: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class QualityIssueRecord(Base):
    __tablename__ = "quality_issues"
    __table_args__ = (Index("ix_quality_analysis", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20), default="info")
    title: Mapped[str] = mapped_column(String(400))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    files: Mapped[list] = mapped_column(JSON, default=list)
    symbol: Mapped[str | None] = mapped_column(String(300), nullable=True)
    metric: Mapped[dict] = mapped_column(JSON, default=dict)
    heuristic: Mapped[bool] = mapped_column(Boolean, default=True)


class AnalysisArtifact(Base):
    """Opaque JSON payloads (overview, architecture, quality summary, docs)."""

    __tablename__ = "analysis_artifacts"
    __table_args__ = (UniqueConstraint("analysis_id", "kind", name="uq_artifact_kind"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    generated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
