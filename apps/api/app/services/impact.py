"""Impact analysis over a stored analysis.

Kept out of the route module so the AI layer can reuse exactly the same
computation: the graph, the parsed-file proxy and the result shape are shared.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from repolens_shared.errors import RepoLensError


def build_impact_report(session: Session, analysis_id: str, target_path: str,
                        symbol: str | None = None, depth: int = 3) -> dict[str, Any]:
    """Rehydrate the persisted graph and run the impact analyzer on it."""
    from repolens_graph import FileNode, GraphResult, analyze_impact

    from ..models.tables import FileRecord, GraphEdgeRecord, GraphNodeRecord

    node_rows = session.execute(
        select(GraphNodeRecord).where(GraphNodeRecord.analysis_id == analysis_id)
    ).scalars().all()
    if not node_rows:
        raise RepoLensError("This analysis has no dependency graph.", hint="Re-run the analysis.")

    graph = GraphResult()
    for row in node_rows:
        graph.nodes[row.path] = FileNode(
            path=row.path, language=row.language or "unknown", layer=row.layer, loc=row.loc,
            symbols=row.symbols, is_test=row.is_test, is_entrypoint=row.is_entrypoint,
            fan_in=row.fan_in, fan_out=row.fan_out,
        )
    edge_rows = session.execute(
        select(GraphEdgeRecord).where(GraphEdgeRecord.analysis_id == analysis_id)
    ).scalars().all()
    graph.edges = [
        {"id": row.id, "source": row.source, "target": row.target, "kind": row.kind,
         "weight": row.weight, "symbols": row.symbols or [], "line": row.line}
        for row in edge_rows
    ]
    graph.cycles = _cycles(session, analysis_id)

    file_row = session.execute(
        select(FileRecord).where(FileRecord.analysis_id == analysis_id, FileRecord.path == target_path)
    ).scalars().first()
    if file_row is None:
        raise RepoLensError(f"`{target_path}` is not part of this analysis.",
                            hint="Use a path from GET /analyses/{id}/files.")

    parsed_proxy = ParsedFileProxy(session, analysis_id)
    result = analyze_impact(graph, parsed_proxy.files, target_path, symbol, depth=depth)
    result.setdefault("target", {})
    result["target"]["layer"] = file_row.layer
    result["target"]["loc"] = file_row.loc
    return result


def resolve_target_path(session: Session, analysis_id: str, candidate: str) -> str | None:
    """Map a user supplied string (path or file name) onto a stored file path."""
    from ..models.tables import FileRecord

    needle = (candidate or "").strip().strip("`'\"")
    if not needle:
        return None
    paths = session.execute(
        select(FileRecord.path).where(FileRecord.analysis_id == analysis_id)
    ).scalars().all()
    lowered = needle.lower()
    exact = [path for path in paths if path.lower() == lowered]
    if exact:
        return exact[0]
    suffix = [path for path in paths if path.lower().endswith("/" + lowered)]
    if suffix:
        return suffix[0]
    stem = [path for path in paths if path.rsplit("/", 1)[-1].lower() == lowered]
    if stem:
        return stem[0]
    loose = [path for path in paths if lowered in path.lower()]
    if len(loose) == 1:
        return loose[0]
    return None


def impact_summary_lines(report: dict[str, Any]) -> list[str]:
    """Compact, human readable rendering of an impact report (used by the impact view)."""
    target = report.get("target") or {}
    lines = [f"target: {target.get('path')} (layer {target.get('layer')}, {target.get('loc')} loc)"]
    lines.append(f"direct dependencies: {len(report.get('direct_dependencies') or [])}")
    lines.append(f"files that depend on it: {len(report.get('dependents') or [])}")
    lines.append(f"transitive dependents: {len(report.get('indirect_dependents') or [])}")
    endpoints = report.get("affected_endpoints") or []
    if endpoints:
        lines.append("affected endpoints: " + ", ".join(
            f"{endpoint.get('method')} {endpoint.get('path')}" for endpoint in endpoints[:8]))
    workflows = report.get("affected_workflows") or []
    if workflows:
        lines.append("affected workflows: " + ", ".join(
            f"{workflow.get('name')} ({workflow.get('category')})" for workflow in workflows[:6]))
    tests = report.get("related_tests") or []
    lines.append(f"related tests: {len(tests)}" + (": " + ", ".join(test.get("path", "") for test in tests[:5]) if tests else ""))
    for risk in (report.get("risks") or [])[:4]:
        lines.append(f"risk [{risk.get('level')}]: {risk.get('title')} - {risk.get('detail')}")
    for note in (report.get("notes") or [])[:2]:
        lines.append(f"note: {note}")
    return lines


def _cycles(session, analysis_id: str) -> list[list[str]]:
    from ..models.tables import CycleRecord
    from sqlalchemy import select
    rows = session.execute(select(CycleRecord).where(CycleRecord.analysis_id == analysis_id)).scalars().all()
    return [list(row.paths or []) for row in rows]


class ParsedFileProxy:
    """Minimal stand-in for ParsedFile so the impact analyzer can run from the DB."""

    class _Parsed:
        def __init__(self, path: str, language: str, symbols: list, routes: list, imports: list, models: list,
                     queries: list, loc: int, parse_error: str | None):
            self.path = path
            self.language = language
            self.symbols = symbols
            self.routes = routes
            self.imports = imports
            self.models = models
            self.queries = queries
            self.loc = loc
            self.parse_error = parse_error
            self.warnings = []
            self.docstring = None
            self.framework_hints = []

    class _Symbol:
        def __init__(self, row):
            from repolens_parser import Call, Symbol
            self._symbol = Symbol(
                name=row.name, kind=row.kind, start_line=row.start_line, end_line=row.end_line,
                params=row.params or [], signature=row.signature or "", decorators=row.decorators or [],
                bases=row.bases or [], docstring=row.docstring, complexity=row.complexity or 1,
                parent=row.parent, exported=bool(row.exported), is_async=bool(row.is_async),
                body_lines=max(1, (row.end_line or 0) - (row.start_line or 0) + 1),
                calls=[Call(name=call.get("name", ""), line=call.get("line", 0),
                            qualifier=call.get("qualifier"), full=call.get("full", ""),
                            receiver=call.get("receiver")) for call in (row.calls or [])],
            )

        def __getattr__(self, item):
            return getattr(self._symbol, item)

    def __init__(self, session, analysis_id: str):
        from ..models.tables import (
            ApiEndpointRecord,
            DbModelRecord,
            DbQueryRecord,
            FileRecord,
            GraphEdgeRecord,
            SymbolRecord,
        )
        from sqlalchemy import select
        from repolens_parser import Import, Model, Query, Route

        files = []
        file_rows = session.execute(select(FileRecord).where(FileRecord.analysis_id == analysis_id)).scalars().all()
        symbol_rows = session.execute(select(SymbolRecord).where(SymbolRecord.analysis_id == analysis_id)).scalars().all()
        endpoints = session.execute(select(ApiEndpointRecord).where(ApiEndpointRecord.analysis_id == analysis_id)).scalars().all()
        model_rows = session.execute(select(DbModelRecord).where(DbModelRecord.analysis_id == analysis_id)).scalars().all()
        query_rows = session.execute(select(DbQueryRecord).where(DbQueryRecord.analysis_id == analysis_id)).scalars().all()
        import_edges = session.execute(
            select(GraphEdgeRecord).where(GraphEdgeRecord.analysis_id == analysis_id, GraphEdgeRecord.kind == "import")
        ).scalars().all()

        models_by_path: dict[str, list] = {}
        for row in model_rows:
            models_by_path.setdefault(row.file_path, []).append(Model(
                name=row.name, line=row.line or 1, orm=row.orm, table=row.table_name,
                fields=list(row.fields or []), relationships=list(row.relationships or []),
                source=row.source or "code",
            ))
        queries_by_path: dict[str, list] = {}
        for row in query_rows:
            queries_by_path.setdefault(row.file_path, []).append(Query(
                kind=row.kind, line=row.line or 1, table=row.table_name, orm=row.orm, snippet=row.snippet or "",
            ))
        imports_by_source: dict[str, list] = {}
        for edge in import_edges:
            imports_by_source.setdefault(edge.source, []).append(Import(
                raw=edge.target, module=edge.target, line=edge.line or 1,
                names=list(edge.symbols or []), external=False, resolved_path=edge.target, kind="import",
            ))
        symbols_by_path: dict[str, list] = {}
        for row in symbol_rows:
            symbols_by_path.setdefault(row.path, []).append(self._Symbol(row))
        endpoints_by_path: dict[str, list] = {}
        for row in endpoints:
            endpoints_by_path.setdefault(row.file_path, []).append(Route(
                method=row.method, path=row.path, handler=row.handler, line=row.line or 1,
                framework=row.framework, auth_hint=bool(row.auth_required), controller=row.controller,
                request_model=row.request_model, response_model=row.response_model, notes=row.notes,
            ))
        for row in file_rows:
            files.append(self._Parsed(
                path=row.path, language=row.language, symbols=symbols_by_path.get(row.path, []),
                routes=endpoints_by_path.get(row.path, []), imports=imports_by_source.get(row.path, []),
                models=models_by_path.get(row.path, []), queries=queries_by_path.get(row.path, []),
                loc=row.loc, parse_error=row.parse_error,
            ))
        self.files = files
