"""Read-side data access: everything the dashboard asks for."""

from __future__ import annotations

from typing import Callable

import posixpath
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from repolens_shared.errors import AnalysisNotReadyError, RepoLensError

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


class NotFoundError(RepoLensError):
    code = "not_found"
    http_status = 404


# --------------------------------------------------------------------------- #
# Repos & runs
# --------------------------------------------------------------------------- #

def get_repo(session: Session, repo_id: str) -> Repo:
    repo = session.get(Repo, repo_id)
    if repo is None:
        raise NotFoundError(f"Repository `{repo_id}` was not found.",
                            hint="Import it again from the dashboard.")
    return repo


def find_repo_by_full_name(session: Session, full_name: str) -> Repo | None:
    return session.execute(select(Repo).where(func.lower(Repo.full_name) == full_name.lower())).scalars().first()


def list_repos(session: Session, limit: int = 20) -> list[dict]:
    repos = session.execute(select(Repo).order_by(Repo.updated_at.desc()).limit(limit)).scalars().all()
    out = []
    for repo in repos:
        analysis = session.execute(
            select(Analysis).where(Analysis.repo_id == repo.id).order_by(Analysis.created_at.desc()).limit(1)
        ).scalars().first()
        out.append(_repo_summary(repo, analysis))
    return out


def get_analysis(session: Session, analysis_id: str) -> Analysis:
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise NotFoundError(f"Analysis `{analysis_id}` was not found.",
                            hint="It may have been deleted - start a new analysis.")
    return analysis


def latest_analysis(session: Session, repo_id: str) -> Analysis | None:
    return session.execute(
        select(Analysis).where(Analysis.repo_id == repo_id).order_by(Analysis.created_at.desc()).limit(1)
    ).scalars().first()


def latest_complete_analysis(session: Session, repo_id: str) -> Analysis | None:
    return session.execute(
        select(Analysis).where(Analysis.repo_id == repo_id, Analysis.status == "complete")
        .order_by(Analysis.created_at.desc()).limit(1)
    ).scalars().first()


def require_complete(session: Session, analysis_id: str) -> Analysis:
    analysis = get_analysis(session, analysis_id)
    if analysis.status not in {"complete"}:
        raise AnalysisNotReadyError(
            f"Analysis is not complete yet (status: {analysis.status}).",
            hint="Wait for the run to finish, or check the progress endpoint.",
        )
    return analysis


def analysis_payload(analysis: Analysis) -> dict:
    return {
        "id": analysis.id, "repo_id": analysis.repo_id, "status": analysis.status, "stage": analysis.stage,
        "progress": round(analysis.progress or 0.0, 4), "message": analysis.message, "error": analysis.error,
        "warnings": analysis.warnings or [], "stages": analysis.stages or [], "branch": analysis.branch,
        "commit_sha": analysis.commit_sha,
        "started_at": analysis.started_at.isoformat() if analysis.started_at else None,
        "finished_at": analysis.finished_at.isoformat() if analysis.finished_at else None,
        "duration_ms": analysis.duration_ms, "file_count": analysis.file_count, "parsed_count": analysis.parsed_count,
        "failed_count": analysis.failed_count, "skipped_count": analysis.skipped_count,
        "provider_info": analysis.provider_info or {},
    }


def repo_payload(repo: Repo) -> dict:
    return {
        "owner": repo.owner, "name": repo.name, "full_name": repo.full_name, "url": repo.url,
        "description": repo.description, "default_branch": repo.default_branch, "html_url": repo.url,
        "stars": repo.stars, "forks": repo.forks, "watchers": repo.watchers, "open_issues": repo.open_issues,
        "primary_language": repo.primary_language, "license": repo.license, "topics": repo.topics or [],
        "size_kb": repo.size_kb, "archived": repo.archived, "is_fork": repo.is_fork, "homepage": repo.homepage,
        "created_at": repo.github_created_at.isoformat() if repo.github_created_at else None,
        "pushed_at": repo.github_pushed_at.isoformat() if repo.github_pushed_at else None,
        "updated_at": (repo.github_pushed_at or repo.updated_at).isoformat() if (repo.github_pushed_at or repo.updated_at) else None,
    }


def _repo_summary(repo: Repo, analysis: Analysis | None) -> dict:
    return {
        "id": repo.id, "full_name": repo.full_name, "url": repo.url, "description": repo.description,
        "default_branch": repo.default_branch, "stars": repo.stars, "primary_language": repo.primary_language,
        "updated_at": (repo.github_pushed_at or repo.updated_at).isoformat() if (repo.github_pushed_at or repo.updated_at) else None,
        "last_analysis": analysis_payload(analysis) if analysis else None,
    }


# --------------------------------------------------------------------------- #
# Artifacts
# --------------------------------------------------------------------------- #

def get_artifact(session: Session, analysis_id: str, kind: str) -> dict | None:
    row = session.execute(
        select(AnalysisArtifact).where(AnalysisArtifact.analysis_id == analysis_id, AnalysisArtifact.kind == kind)
    ).scalars().first()
    return row.payload if row else None


def get_overview(session: Session, analysis_id: str) -> dict:
    analysis = require_complete(session, analysis_id)
    overview = get_artifact(session, analysis_id, "overview")
    if overview is None:
        raise NotFoundError("Overview artefact is missing for this analysis.",
                            hint="Re-run the analysis - the run may have been interrupted.")
    overview = {**overview, "run": analysis_payload(analysis)}
    return overview


def get_architecture(session: Session, analysis_id: str) -> dict:
    require_complete(session, analysis_id)
    payload = get_artifact(session, analysis_id, "architecture")
    if payload is None:
        raise NotFoundError("Architecture artefact is missing.", hint="Re-run the analysis.")
    return payload


def get_dependencies(session: Session, analysis_id: str, view: str = "files", limit: int = 400,
                     layer: str | None = None, kind: str | None = None) -> dict:
    require_complete(session, analysis_id)
    if view == "modules":
        payload = get_artifact(session, analysis_id, "module_graph") or {"nodes": [], "edges": []}
        nodes = payload.get("nodes", [])[: max(limit, 600)]
        node_ids = {node["id"] for node in nodes}
        edges = [edge for edge in payload.get("edges", []) if edge["source"] in node_ids and edge["target"] in node_ids]
        return {"view": "modules", "nodes": nodes, "edges": edges, "cycles": [], "hubs": [],
                "stats": {"nodes": len(nodes), "edges": len(edges)}}

    statement = select(GraphNodeRecord).where(GraphNodeRecord.analysis_id == analysis_id)
    if layer:
        statement = statement.where(GraphNodeRecord.layer == layer)
    nodes = session.execute(statement.order_by(GraphNodeRecord.coupling.desc()).limit(limit)).scalars().all()
    node_ids = {node.path for node in nodes}
    edges = session.execute(
        select(GraphEdgeRecord).where(GraphEdgeRecord.analysis_id == analysis_id).limit(20_000)
    ).scalars().all()
    filtered_edges = [
        {"id": edge.id, "source": edge.source, "target": edge.target, "kind": edge.kind, "weight": edge.weight,
         "symbols": edge.symbols or [], "line": edge.line}
        for edge in edges
        if edge.source in node_ids and edge.target in node_ids and (kind is None or edge.kind == kind)
    ]
    cycles = session.execute(select(CycleRecord).where(CycleRecord.analysis_id == analysis_id)
                             .order_by(CycleRecord.size.desc())).scalars().all()
    payload = get_artifact(session, analysis_id, "dependency_graph") or {}
    file_total = session.execute(
        select(func.count()).select_from(GraphNodeRecord).where(GraphNodeRecord.analysis_id == analysis_id)
    ).scalar() or 0
    return {
        "view": "files",
        "nodes": [{
            "id": node.path, "label": posixpath.basename(node.path), "kind": node.kind, "layer": node.layer,
            "path": node.path, "language": node.language, "loc": node.loc, "symbols": node.symbols,
            "fan_in": node.fan_in, "fan_out": node.fan_out, "coupling": node.coupling,
            "is_cycle_member": node.is_cycle_member, "is_test": node.is_test, "is_entrypoint": node.is_entrypoint,
        } for node in nodes],
        "edges": filtered_edges,
        "cycles": [{"id": cycle.id, "paths": cycle.paths, "size": cycle.size} for cycle in cycles],
        "hubs": (payload.get("hubs") or [])[:20],
        "orphans": (payload.get("orphans") or [])[:60],
        "module_stats": (payload.get("module_stats") or [])[:25],
        "external_dependencies": (payload.get("external_dependencies") or [])[:40],
        "stats": {**(payload.get("stats") or {}), "shown_nodes": len(nodes), "total_nodes": file_total,
                  "truncated": bool(payload.get("truncated")) or len(nodes) < file_total},
        "note": payload.get("note"),
    }


def list_workflows(session: Session, analysis_id: str, category: str | None = None,
                   query: str | None = None, limit: int = 100) -> list[dict]:
    require_complete(session, analysis_id)
    statement = select(WorkflowRecord).where(WorkflowRecord.analysis_id == analysis_id)
    if category:
        statement = statement.where(WorkflowRecord.category == category)
    if query:
        needle = f"%{query.lower()}%"
        statement = statement.where(or_(func.lower(WorkflowRecord.name).like(needle),
                                        func.lower(WorkflowRecord.trigger).like(needle),
                                        func.lower(WorkflowRecord.description).like(needle)))
    rows = session.execute(statement.order_by(WorkflowRecord.confidence.desc()).limit(limit)).scalars().all()
    categories = session.execute(
        select(WorkflowRecord.category, WorkflowRecord.category_label, func.count())
        .where(WorkflowRecord.analysis_id == analysis_id).group_by(WorkflowRecord.category, WorkflowRecord.category_label)
    ).all()
    return {
        "workflows": [_workflow_payload(row) for row in rows],
        "categories": [{"category": row[0], "label": row[1] or row[0], "count": row[2]} for row in categories],
        "total": session.execute(select(func.count()).select_from(WorkflowRecord)
                                 .where(WorkflowRecord.analysis_id == analysis_id)).scalar() or 0,
    }


def get_workflow(session: Session, analysis_id: str, workflow_id: str) -> dict:
    row = session.get(WorkflowRecord, workflow_id)
    if row is None or row.analysis_id != analysis_id:
        raise NotFoundError(f"Workflow `{workflow_id}` was not found in this analysis.")
    return _workflow_payload(row)


def _workflow_payload(row: WorkflowRecord) -> dict:
    return {
        "id": row.id, "name": row.name, "category": row.category, "category_label": row.category_label,
        "description": row.description, "entry_point": row.entry_point, "trigger": row.trigger,
        "framework": row.framework, "steps": row.steps or [], "confidence": row.confidence,
        "evidence": row.evidence or [], "files": row.files or [], "trace_truncated": row.trace_truncated,
        "route": row.route,
        "scope": getattr(row, "scope", None), "scope_note": getattr(row, "scope_note", None),
    }


def list_endpoints(session: Session, analysis_id: str, method: str | None = None, query: str | None = None,
                   framework: str | None = None) -> dict:
    require_complete(session, analysis_id)
    statement = select(ApiEndpointRecord).where(ApiEndpointRecord.analysis_id == analysis_id)
    if method:
        statement = statement.where(ApiEndpointRecord.method.like(f"%{method.upper()}%"))
    if framework:
        statement = statement.where(ApiEndpointRecord.framework == framework)
    if query:
        needle = f"%{query.lower()}%"
        statement = statement.where(or_(
            func.lower(ApiEndpointRecord.path).like(needle),
            func.lower(func.coalesce(ApiEndpointRecord.handler, "")).like(needle),
            func.lower(ApiEndpointRecord.file_path).like(needle),
        ))
    rows = session.execute(statement.order_by(ApiEndpointRecord.path).limit(1000)).scalars().all()
    frameworks = session.execute(
        select(ApiEndpointRecord.framework, func.count()).where(ApiEndpointRecord.analysis_id == analysis_id)
        .group_by(ApiEndpointRecord.framework).order_by(func.count().desc())
    ).all()
    processed_paths: dict[str, list[str]] = {}
    for row in rows:
        processed_paths.setdefault(row.path, [])
        if row.method not in processed_paths[row.path]:
            processed_paths[row.path].append(row.method)
    endpoints = [
        {
            "id": row.id, "method": row.method, "path": row.path, "handler": row.handler,
            "file_path": row.file_path, "line": row.line, "framework": row.framework, "controller": row.controller,
            "service": row.service, "auth_required": row.auth_required, "evidence": row.evidence or [],
            "notes": row.notes, "request_model": row.request_model, "response_model": row.response_model,
            "is_example": bool(getattr(row, "is_example", False)), "is_test": bool(getattr(row, "is_test", False)),
            "declarations": getattr(row, "declarations", None) or [],
        }
        for row in rows
    ]
    return {
        "endpoints": endpoints,
        "frameworks": [{"framework": row[0] or "unknown", "count": row[1]} for row in frameworks],
        "stats": {
            "total": len(endpoints),
            "authenticated": sum(1 for endpoint in endpoints if endpoint["auth_required"]),
            "unique_paths": len(processed_paths),
            "from_examples": sum(1 for endpoint in endpoints if endpoint["is_example"]),
            "from_tests": sum(1 for endpoint in endpoints if endpoint["is_test"]),
            "declared_in_multiple_places": sum(1 for endpoint in endpoints if len(endpoint["declarations"]) > 1),
        },
    }


def get_database(session: Session, analysis_id: str) -> dict:
    require_complete(session, analysis_id)
    payload = get_artifact(session, analysis_id, "database") or {}
    technologies = session.execute(select(DbTechnologyRecord).where(DbTechnologyRecord.analysis_id == analysis_id)
                                   .order_by(DbTechnologyRecord.confidence.desc())).scalars().all()
    models = session.execute(select(DbModelRecord).where(DbModelRecord.analysis_id == analysis_id)
                             .order_by(DbModelRecord.name)).scalars().all()
    queries = session.execute(select(DbQueryRecord).where(DbQueryRecord.analysis_id == analysis_id)
                              .order_by(DbQueryRecord.file_path).limit(600)).scalars().all()
    return {
        "technologies": [{"name": row.name, "kind": row.kind, "confidence": row.confidence,
                          "evidence": row.evidence or []} for row in technologies],
        "models": [{"id": row.id, "name": row.name, "table": row.table_name, "orm": row.orm,
                    "file_path": row.file_path, "line": row.line, "fields": row.fields or [],
                    "relationships": row.relationships or [], "source": row.source,
                    "query_count": (payload.get("stats") or {}).get("queries", 0) and sum(
                        1 for query in queries if query.table_name and query.table_name == row.table_name)} for row in models],
        "queries": [{"id": row.id, "file_path": row.file_path, "line": row.line, "kind": row.kind,
                     "table": row.table_name, "orm": row.orm, "snippet": row.snippet} for row in queries],
        "migrations": payload.get("migrations", []),
        "relations": payload.get("relations", []),
        "orms": payload.get("orms", []),
        "notes": payload.get("notes", []),
        "stats": payload.get("stats", {}),
    }


def get_quality(session: Session, analysis_id: str) -> dict:
    require_complete(session, analysis_id)
    payload = get_artifact(session, analysis_id, "quality") or {}
    issues = session.execute(select(QualityIssueRecord).where(QualityIssueRecord.analysis_id == analysis_id)
                             .order_by(QualityIssueRecord.severity)).scalars().all()
    return {
        "issues": [{"id": row.id, "kind": row.kind, "severity": row.severity, "title": row.title,
                    "detail": row.detail, "files": row.files or [], "symbol": row.symbol,
                    "metric": row.metric or {}, "heuristic": row.heuristic} for row in issues],
        "summary": payload.get("summary", {}),
        "metrics": payload.get("metrics", {}),
        "disclaimer": payload.get("disclaimer", ""),
    }


def list_frameworks(session: Session, analysis_id: str) -> list[dict]:
    rows = session.execute(select(FrameworkRecord).where(FrameworkRecord.analysis_id == analysis_id)
                           .order_by(FrameworkRecord.confidence.desc())).scalars().all()
    return [{"name": row.name, "ecosystem": row.ecosystem, "confidence": row.confidence,
             "evidence": row.evidence or []} for row in rows]


def list_manifests(session: Session, analysis_id: str) -> list[dict]:
    rows = session.execute(select(ManifestRecord).where(ManifestRecord.analysis_id == analysis_id)
                           .order_by(ManifestRecord.path)).scalars().all()
    return [{"id": row.id, "path": row.path, "ecosystem": row.ecosystem, "name": row.name, "version": row.version,
             "dependencies": row.dependencies or [], "scripts": row.scripts or {}, "error": row.error}
            for row in rows]


# --------------------------------------------------------------------------- #
# Files & code
# --------------------------------------------------------------------------- #

def file_tree(session: Session, analysis_id: str, limit: int = 6000) -> dict:
    require_complete(session, analysis_id)
    rows = session.execute(
        select(FileRecord.path, FileRecord.language, FileRecord.loc, FileRecord.layer, FileRecord.is_test,
               FileRecord.symbol_count, FileRecord.parsed, FileRecord.parse_error)
        .where(FileRecord.analysis_id == analysis_id).order_by(FileRecord.path).limit(limit)
    ).all()
    tree: dict = {"name": "", "path": "", "type": "dir", "children": {}}

    def ensure(parts: list[str]) -> dict:
        node = tree
        for index, part in enumerate(parts):
            is_file = index == len(parts) - 1
            children = node["children"]
            child = children.get(part)
            if child is None:
                child = {"name": part, "path": "/".join(parts[: index + 1]),
                         "type": "file" if is_file else "dir", "children": {}}
                children[part] = child
            node = child
        return node

    for row in rows:
        parts = row.path.split("/")
        leaf = ensure(parts)
        leaf.update({
            "type": "file", "language": row.language, "loc": row.loc, "layer": row.layer, "test": row.is_test,
            "symbols": row.symbol_count, "parsed": row.parsed, "parse_error": row.parse_error,
        })

    def finalise(node: dict) -> dict:
        if node["type"] == "file":
            node.pop("children", None)
            return node
        children = [finalise(child) for child in node["children"].values()]
        children.sort(key=lambda item: (item["type"] != "dir", item["name"].lower()))
        node["children"] = children
        node["count"] = sum(1 for _ in walk(node))
        return node

    def walk(node: dict):
        for child in node.get("children", []):
            if child["type"] == "file":
                yield child
            else:
                yield from walk(child)

    finalised = finalise(tree)
    return {"root": finalised, "total": len(rows)}


def get_file(session: Session, analysis_id: str, path: str, source_root: str | None = None,
             max_bytes: int = 400_000, fetch_remote: Callable[[str], str | None] | None = None) -> dict:
    """Return one file for the code explorer.

    Order: content stored with the analysis, then the checkout if it still exists, then an
    on-demand fetch from GitHub (``fetch_remote``). Nothing is kept on disk between requests.
    """
    require_complete(session, analysis_id)
    row = session.execute(select(FileRecord).where(FileRecord.analysis_id == analysis_id,
                                                  FileRecord.path == path)).scalars().first()
    if row is None:
        raise NotFoundError(f"`{path}` is not part of this analysis.",
                            hint="Pick a file from the explorer tree.")
    content = row.content
    source_note: str | None = None
    if content is not None:
        source_note = "Content stored with this analysis."
    truncated = False
    if content is None:
        content = _read_from_disk(source_root, path)
        if content is not None:
            source_note = "Content read from the temporary checkout."
    if content is None and fetch_remote is not None:
        try:
            content = fetch_remote(path)
            if content is not None:
                source_note = "Fetched from GitHub on demand at the analysed commit."
            else:
                source_note = "GitHub has no text content for this file (it may be binary or too large)."
        except RepoLensError as exc:
            content = None
            source_note = f"Could not fetch this file from GitHub: {exc.message}"
    if content is None:
        content = ""
        truncated = True
        source_note = source_note or "Source unavailable for this file."
    elif len(content.encode("utf-8")) > max_bytes:
        truncated = True
        content = content[:max_bytes]

    symbols = session.execute(
        select(SymbolRecord).where(SymbolRecord.analysis_id == analysis_id, SymbolRecord.path == path)
        .order_by(SymbolRecord.start_line)
    ).scalars().all()
    imports = session.execute(
        select(GraphEdgeRecord).where(GraphEdgeRecord.analysis_id == analysis_id, GraphEdgeRecord.source == path)
    ).scalars().all()
    dependents = session.execute(
        select(GraphEdgeRecord).where(GraphEdgeRecord.analysis_id == analysis_id, GraphEdgeRecord.target == path)
    ).scalars().all()
    return {
        "path": row.path, "language": row.language, "content": content, "truncated": truncated,
        "size_bytes": row.size_bytes, "loc": row.loc, "layer": row.layer, "parsed": row.parsed,
        "parse_error": row.parse_error, "warnings": row.warnings or [],
        "symbols": [_symbol_payload(symbol) for symbol in symbols],
        "imports": [{"path": edge.target, "kind": edge.kind, "symbols": edge.symbols or [], "line": edge.line}
                    for edge in imports],
        "dependents": [{"path": edge.source, "kind": edge.kind, "symbols": edge.symbols or [], "line": edge.line}
                       for edge in dependents],
        "artifact_note": source_note,
    }


def _symbol_payload(symbol: SymbolRecord) -> dict:
    return {
        "id": symbol.id, "file_id": symbol.file_id, "path": symbol.path, "name": symbol.name, "kind": symbol.kind,
        "start_line": symbol.start_line, "end_line": symbol.end_line, "signature": symbol.signature,
        "params": symbol.params or [], "decorators": symbol.decorators or [], "bases": symbol.bases or [],
        "docstring": symbol.docstring, "complexity": symbol.complexity, "loc": symbol.loc, "parent": symbol.parent,
        "exported": symbol.exported, "is_async": symbol.is_async, "calls": symbol.calls or [], "called_by": [],
    }


def _read_from_disk(source_root: str | None, path: str) -> str | None:
    if not source_root:
        return None
    root = Path(source_root).resolve()
    candidate = (root / path).resolve()
    if not str(candidate).startswith(str(root)):
        return None
    try:
        if candidate.is_file() and candidate.stat().st_size <= 2_000_000:
            return candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return None


def search_symbols(session: Session, analysis_id: str, query: str, limit: int = 40) -> list[dict]:
    needle = f"%{query.lower()}%"
    rows = session.execute(
        select(SymbolRecord).where(
            SymbolRecord.analysis_id == analysis_id,
            or_(func.lower(SymbolRecord.name).like(needle), func.lower(func.coalesce(SymbolRecord.signature, "")).like(needle),
                func.lower(func.coalesce(SymbolRecord.docstring, "")).like(needle)),
        ).order_by(func.length(SymbolRecord.name)).limit(limit)
    ).scalars().all()
    return [_symbol_payload(row) for row in rows]


def find_symbol(session: Session, analysis_id: str, name: str, path: str | None = None) -> SymbolRecord | None:
    statement = select(SymbolRecord).where(SymbolRecord.analysis_id == analysis_id, SymbolRecord.name == name)
    if path:
        statement = statement.where(SymbolRecord.path == path)
    return session.execute(statement.limit(1)).scalars().first()


def symbol_references(session: Session, analysis_id: str, name: str, limit: int = 60) -> list[dict]:
    """Callers of a symbol, from the persisted call graph."""
    rows = session.execute(select(SymbolRecord).where(SymbolRecord.analysis_id == analysis_id)).scalars().all()
    references: list[dict] = []
    for row in rows:
        for call in row.calls or []:
            if call.get("name") == name:
                references.append({"path": row.path, "symbol": row.name, "kind": row.kind,
                                   "line": call.get("line"), "via": call.get("full") or name,
                                   "caller_signature": row.signature})
                break
        if len(references) >= limit:
            break
    return references


def symbol_count(session: Session, analysis_id: str) -> dict:
    total = session.execute(select(func.count()).select_from(SymbolRecord)
                            .where(SymbolRecord.analysis_id == analysis_id)).scalar() or 0
    by_kind = session.execute(select(SymbolRecord.kind, func.count())
                              .where(SymbolRecord.analysis_id == analysis_id).group_by(SymbolRecord.kind)).all()
    return {"total": total, "by_kind": {row[0]: row[1] for row in by_kind}}


def get_document(session: Session, analysis_id: str, kind: str) -> dict:
    require_complete(session, analysis_id)
    payload = get_artifact(session, analysis_id, f"doc:{kind}")
    if payload is None:
        raise NotFoundError(f"Document `{kind}` was not generated for this analysis.",
                            hint="Supported documents: readme, api, onboarding.")
    return payload


def store_document(session: Session, analysis_id: str, payload: dict) -> None:
    from repolens_shared.utils import stable_id
    row = session.execute(select(AnalysisArtifact).where(
        AnalysisArtifact.analysis_id == analysis_id, AnalysisArtifact.kind == f"doc:{payload['kind']}"
    )).scalars().first()
    if row is None:
        session.add(AnalysisArtifact(id=stable_id("doc", analysis_id, payload["kind"]), analysis_id=analysis_id,
                                     kind=f"doc:{payload['kind']}", payload=payload,
                                     generated_by=payload.get("generated_by")))
    else:
        row.payload = payload
        row.generated_by = payload.get("generated_by")


def chunk_count(session: Session, analysis_id: str) -> int:
    return session.execute(select(func.count()).select_from(ChunkRecord)
                           .where(ChunkRecord.analysis_id == analysis_id)).scalar() or 0


def delete_analysis_rows(session: Session, analysis_id: str) -> None:
    """Remove a run and every row that belongs to it.

    Child tables only hold an ``analysis_id`` column (no foreign key), so each table is cleared
    explicitly. The repository row is removed too once no other run refers to it.
    """
    from sqlalchemy import delete as sa_delete

    from ..models.tables import Base, Repo

    row = session.get(Analysis, analysis_id)
    repo_id = row.repo_id if row is not None else None
    for table in Base.metadata.sorted_tables:
        if table.name == Analysis.__tablename__ or "analysis_id" not in table.c:
            continue
        session.execute(sa_delete(table).where(table.c.analysis_id == analysis_id))
    if row is not None:
        session.delete(row)
        session.flush()
    if repo_id is not None:
        still_used = session.execute(select(Analysis.id).where(Analysis.repo_id == repo_id).limit(1)).first()
        if still_used is None:
            repo = session.get(Repo, repo_id)
            if repo is not None:
                session.delete(repo)
