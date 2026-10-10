"""Impact analysis: what is affected when a file or symbol changes."""

from __future__ import annotations

from collections import defaultdict, deque

from repolens_shared.utils import truncate
from repolens_parser import ParsedFile
from repolens_parser.python_analyzer import is_test_path

from .dependency import GraphResult
from .workflows import WorkflowTracer, _trace_endpoint


def _file_summary(graph: GraphResult, path: str) -> dict:
    node = graph.nodes.get(path)
    if node is None:
        return {"path": path}
    return {"path": path, "layer": node.layer, "loc": node.loc, "symbols": node.symbols,
            "fan_in": node.fan_in, "fan_out": node.fan_out, "coupling": node.coupling,
            "is_test": node.is_test}


def analyze_impact(graph: GraphResult, parsed_files: list[ParsedFile], target_path: str,
                   target_symbol: str | None = None, depth: int = 3) -> dict:
    files = {parsed.path: parsed for parsed in parsed_files}
    if target_path not in graph.nodes:
        return {"error": f"`{target_path}` is not part of the analysed file set.",
                "notes": ["Pick a file from the code explorer or dependency graph."]}

    parsed = files.get(target_path)
    target_symbol_obj = None
    if parsed and target_symbol:
        target_symbol_obj = next((s for s in parsed.symbols if s.name == target_symbol), None)

    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge["source"]].append(edge)
        incoming[edge["target"]].append(edge)

    direct_deps = [
        {**_file_summary(graph, edge["target"]), "kind": edge["kind"], "symbols": edge.get("symbols", [])[:6], "line": edge.get("line")}
        for edge in outgoing.get(target_path, [])
    ]
    direct_dependents = [
        {**_file_summary(graph, edge["source"]), "kind": edge["kind"], "symbols": edge.get("symbols", [])[:6]}
        for edge in incoming.get(target_path, [])
    ]

    # transitive dependents (BFS) and transitive dependencies
    def bfs(reverse: bool, max_depth: int) -> list[dict]:
        seen = {target_path}
        queue = deque([(target_path, 0)])
        results: list[dict] = []
        while queue:
            node, level = queue.popleft()
            if level >= max_depth:
                continue
            edges = incoming.get(node, []) if reverse else outgoing.get(node, [])
            for edge in edges:
                neighbour = edge["source"] if reverse else edge["target"]
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                results.append({**_file_summary(graph, neighbour), "distance": level + 1, "via": node,
                                "kind": edge["kind"]})
                queue.append((neighbour, level + 1))
        return results

    indirect_dependents = bfs(reverse=True, max_depth=depth)
    indirect_deps = bfs(reverse=False, max_depth=depth)

    # Affected endpoints: declared in the target file, or in files that depend on it.
    affected_paths = {target_path} | {item["path"] for item in direct_dependents}
    shallow_affected = affected_paths | {item["path"] for item in indirect_dependents if item["distance"] <= 2}
    endpoints: list[dict] = []
    for path in sorted(shallow_affected):
        file = files.get(path)
        if not file:
            continue
        for route in file.routes:
            endpoints.append({
                "id": f"{path}:{route.method}:{route.path}:{route.line}", "method": route.method, "path": route.path,
                "handler": route.handler, "file_path": path, "line": route.line, "framework": route.framework,
                "controller": route.controller, "auth_required": route.auth_hint,
                "notes": "declared in the changed file" if path == target_path else f"declared in dependent file ({path})",
            })

    # Affected workflows: re-trace endpoints and look for the target in the cone.
    tracer = WorkflowTracer(parsed_files, graph)
    endpoint_records: list[dict] = []
    for path, file in files.items():
        for route in file.routes:
            endpoint_records.append({"method": route.method, "path": route.path, "handler": route.handler,
                                     "file_path": path, "line": route.line, "framework": route.framework,
                                     "auth_required": route.auth_hint})
    affected_workflows: list[dict] = []
    for record in endpoint_records[:40]:
        workflow = _trace_endpoint(tracer, record)
        if not workflow:
            continue
        hit_steps = [step for step in workflow["steps"] if step.get("file_path") in shallow_affected]
        if not hit_steps:
            continue
        affected_workflows.append({
            "id": workflow["id"], "name": workflow["name"], "trigger": workflow["trigger"],
            "category": workflow["category"], "confidence": workflow["confidence"],
            "impacted_steps": [{"label": step["label"], "file_path": step.get("file_path"),
                                "kind": step["kind"], "symbol": step.get("symbol")} for step in hit_steps[:6]],
            "distance": 0 if any(step.get("file_path") == target_path for step in hit_steps) else 1,
        })
        if len(affected_workflows) >= 12:
            break

    # Related tests: tests that depend on the target, import it, or reference its symbols.
    target_names = {symbol.name for symbol in (parsed.symbols if parsed else []) if symbol.kind in {"function", "class", "component"}}
    related_tests: list[dict] = []
    test_dependents = {item["path"] for item in direct_dependents + indirect_dependents if is_test_path(item["path"])}
    for path, file in files.items():
        if not is_test_path(path):
            continue
        reason = None
        if path in test_dependents:
            reason = "imports the target file"
        else:
            for imp in file.imports:
                if imp.resolved_path == target_path:
                    reason = "imports the target file"
                    break
        if reason is None and target_names:
            referenced = sorted(name for name in target_names if any(name in imp.names for imp in file.imports))
            if referenced:
                reason = f"references {', '.join(referenced[:3])}"
        if reason is None:
            continue
        related_tests.append({**_file_summary(graph, path), "reason": reason})
        if len(related_tests) >= 20:
            break

    # Risk heuristics - explicitly labelled as heuristics.
    node = graph.nodes[target_path]
    risks: list[dict] = []
    if node.coupling >= 12:
        risks.append({"level": "high", "title": f"Highly coupled module ({node.coupling} connections)",
                      "detail": f"{node.fan_in} files depend on it and it depends on {node.fan_out}. Changes here have a wide blast radius.",
                      "heuristic": True})
    elif node.fan_in >= 5:
        risks.append({"level": "medium", "title": f"{node.fan_in} direct dependents",
                      "detail": "Several modules import this file; update them together.", "heuristic": True})
    if any(len(cycle) and target_path in cycle for cycle in graph.cycles):
        cycle = next(cycle for cycle in graph.cycles if target_path in cycle)
        risks.append({"level": "high", "title": "Part of a circular dependency",
                      "detail": " → ".join(cycle[:6]) + (" …" if len(cycle) > 6 else ""), "heuristic": True})
    if endpoints:
        risks.append({"level": "high" if any(e["file_path"] == target_path for e in endpoints) else "medium",
                      "title": f"{len(endpoints)} API endpoint(s) in the impact cone",
                      "detail": "Contract changes here are visible to API consumers.", "heuristic": True})
    if parsed and parsed.models:
        risks.append({"level": "high", "title": f"Defines {len(parsed.models)} database model(s)",
                      "detail": "Schema changes require migrations and may break existing data.",
                      "heuristic": True})
    if target_symbol_obj and target_symbol_obj.complexity >= 15:
        risks.append({"level": "medium", "title": f"`{target_symbol_obj.name}` has high complexity ({target_symbol_obj.complexity})",
                      "detail": "High-complexity code is harder to change safely.", "heuristic": True})
    if not related_tests:
        risks.append({"level": "medium", "title": "No related tests detected",
                      "detail": "No test file in the repository imports this file or references its symbols.",
                      "heuristic": True})
    if parsed and parsed.parse_error:
        risks.append({"level": "low", "title": "File did not parse cleanly",
                      "detail": f"Analysis is partial: {parsed.parse_error}", "heuristic": False})

    subgraph_paths = {target_path} | {item["path"] for item in direct_dependents} | {item["path"] for item in direct_deps} \
        | {item["path"] for item in indirect_dependents if item["distance"] == 2}
    subgraph_edges = [edge for edge in graph.edges if edge["source"] in subgraph_paths and edge["target"] in subgraph_paths]

    notes = [
        "Impact is computed from static imports/calls plus workflow traces - dynamic dispatch (reflection, DI containers, string-based routing) can create links this analysis cannot see.",
    ]
    if target_symbol:
        notes.append(f"Targeted symbol: `{target_symbol}`" + ("" if target_symbol_obj else " (not found in this file - file level analysis only)"))

    return {
        "target": {
            "path": target_path, "symbol": target_symbol,
            "symbol_info": {
                "name": target_symbol_obj.name, "kind": target_symbol_obj.kind,
                "signature": truncate(target_symbol_obj.signature or "", 200),
                "start_line": target_symbol_obj.start_line, "end_line": target_symbol_obj.end_line,
                "complexity": target_symbol_obj.complexity, "calls": [c.to_dict() for c in target_symbol_obj.calls[:25]],
            } if target_symbol_obj else None,
            "layer": node.layer, "loc": node.loc,
        },
        "direct_dependencies": direct_deps,
        "indirect_dependencies": indirect_deps[:40],
        "dependents": direct_dependents,
        "indirect_dependents": indirect_dependents[:40],
        "affected_endpoints": endpoints[:30],
        "affected_workflows": affected_workflows,
        "related_tests": related_tests,
        "risks": risks,
        "graph": {
            "nodes": [graph.nodes[path].to_dict() for path in sorted(subgraph_paths) if path in graph.nodes],
            "edges": subgraph_edges,
        },
        "notes": notes,
    }
