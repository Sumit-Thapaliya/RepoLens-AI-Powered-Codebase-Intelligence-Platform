"""File-level dependency graph construction.

Edges come from two sources, both evidence backed:

* ``import`` / ``require`` / ``reexport`` - resolved specifiers from the parser
  (only kept when the target file really exists in the repository)
* ``call`` - a symbol in file A calling a symbol that is defined in file B,
  discovered through the file's import table
"""

from __future__ import annotations

import posixpath
from collections import defaultdict
from dataclasses import dataclass, field

from repolens_parser import ParsedFile
from repolens_parser.python_analyzer import is_entrypoint, is_test_path, layer_for_path
from repolens_shared.constants import GRAPH_LANGUAGES
from repolens_shared.utils import is_doc_path


@dataclass
class FileNode:
    path: str
    language: str
    layer: str
    loc: int
    symbols: int
    is_test: bool = False
    is_entrypoint: bool = False
    fan_in: int = 0
    fan_out: int = 0

    @property
    def coupling(self) -> int:
        return self.fan_in + self.fan_out

    def to_dict(self) -> dict:
        return {
            "id": self.path, "label": posixpath.basename(self.path), "kind": "file", "layer": self.layer,
            "path": self.path, "language": self.language, "loc": self.loc, "symbols": self.symbols,
            "fan_in": self.fan_in, "fan_out": self.fan_out, "coupling": self.coupling,
            "is_test": self.is_test, "is_entrypoint": self.is_entrypoint,
        }


@dataclass
class GraphResult:
    nodes: dict[str, FileNode] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    hubs: list[dict] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    module_stats: list[dict] = field(default_factory=list)
    external_dependencies: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Symbol index: (path, symbol name) -> symbol, plus "which file defines name X"
# --------------------------------------------------------------------------- #

def build_symbol_index(parsed_files: list[ParsedFile]) -> dict[str, list[tuple[str, str]]]:
    """name -> [(path, kind)] for cross-file call resolution."""
    index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for parsed in parsed_files:
        for symbol in parsed.symbols:
            if symbol.kind in {"function", "method", "class", "component"} and len(index[symbol.name]) < 40:
                index[symbol.name].append((parsed.path, symbol.kind))
    return index


def imported_symbol_map(parsed: ParsedFile) -> dict[str, str]:
    """local symbol name -> resolved file path for this file's imports."""
    mapping: dict[str, str] = {}
    for imp in parsed.imports:
        if not imp.resolved_path:
            continue
        for name in imp.names:
            if not name or name == "*":
                continue
            mapping[name] = imp.resolved_path
        if not imp.names:
            mapping[imp.module.rsplit("/", 1)[-1].rsplit(".", 1)[-1]] = imp.resolved_path
    return mapping


def build_dependency_graph(parsed_files: list[ParsedFile], external_packages: dict[str, int] | None = None) -> GraphResult:
    result = GraphResult()
    by_path = {parsed.path: parsed for parsed in parsed_files}

    all_nodes: dict[str, FileNode] = {}
    for parsed in parsed_files:
        is_test = is_test_path(parsed.path)
        layer = layer_for_path(parsed.path, is_test)
        all_nodes[parsed.path] = FileNode(
            path=parsed.path, language=parsed.language, layer=layer, loc=parsed.loc,
            symbols=len(parsed.symbols), is_test=is_test, is_entrypoint=is_entrypoint(parsed.path, parsed.language),
        )

    edge_ids: set[tuple[str, str, str]] = set()
    call_edges: dict[tuple[str, str], set[str]] = defaultdict(set)

    for parsed in parsed_files:
        source = parsed.path
        symbol_map = imported_symbol_map(parsed)
        for imp in parsed.imports:
            target = imp.resolved_path
            if not target or target == source or target not in all_nodes:
                continue
            edge_kind = imp.kind if imp.kind in {"import", "require", "reexport"} else "import"
            key = (source, target, edge_kind)
            if key in edge_ids:
                continue
            edge_ids.add(key)
            result.edges.append({"id": f"{edge_kind}:{source}->{target}", "source": source, "target": target,
                                 "kind": edge_kind, "weight": 1, "symbols": [], "external": False, "line": imp.line})
        # cross-file calls
        for symbol in parsed.symbols:
            for call in symbol.calls:
                candidates: list[str] = []
                if call.receiver and call.receiver in symbol_map:
                    candidates.append(symbol_map[call.receiver])
                if call.name in symbol_map:
                    candidates.append(symbol_map[call.name])
                if call.qualifier:
                    head = call.qualifier.split(".")[0]
                    if head in symbol_map:
                        candidates.append(symbol_map[head])
                for candidate in candidates:
                    if candidate == source or candidate not in all_nodes:
                        continue
                    call_edges[(source, candidate)].add(f"{symbol.name} -> {call.full or call.name}")

    for (source, target), symbols in sorted(call_edges.items()):
        key = (source, target, "call")
        if key in edge_ids:
            continue
        edge_ids.add(key)
        result.edges.append({"id": f"call:{source}->{target}", "source": source, "target": target, "kind": "call",
                             "weight": len(symbols), "symbols": sorted(symbols)[:8], "external": False, "line": None})

    # ------------------------------------------------------------- graph scope
    # Only files that can carry dependencies become graph nodes, plus any file a
    # resolved edge points at. Documentation, data and asset files would
    # otherwise dominate the orphan and density statistics with meaningless
    # "no imports" entries.
    kept = {path for path, node in all_nodes.items()
            if node.language in GRAPH_LANGUAGES and not is_doc_path(path, node.language)}
    kept |= {edge["source"] for edge in result.edges}
    kept |= {edge["target"] for edge in result.edges}
    result.nodes = {path: node for path, node in all_nodes.items() if path in kept}
    result.edges = [edge for edge in result.edges
                    if edge["source"] in result.nodes and edge["target"] in result.nodes]
    excluded_files = len(all_nodes) - len(result.nodes)

    # fan-in / fan-out
    for edge in result.edges:
        if edge["source"] in result.nodes:
            result.nodes[edge["source"]].fan_out += 1
        if edge["target"] in result.nodes:
            result.nodes[edge["target"]].fan_in += 1

    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in result.edges:
        adjacency[edge["source"]].append(edge["target"])

    result.cycles = find_cycles(adjacency)
    cycle_members = {path for cycle in result.cycles for path in cycle}
    for path in cycle_members:
        if path in result.nodes:
            result.nodes[path].to_dict()  # ensure node exists (no-op, keeps intent explicit)

    result.hubs = [
        {**node.to_dict(), "is_cycle_member": node.path in cycle_members}
        for node in sorted(result.nodes.values(), key=lambda n: (-n.coupling, n.path))[:20]
        if node.coupling > 0
    ]
    result.orphans = sorted(path for path, node in result.nodes.items() if node.fan_in == 0 and node.fan_out == 0 and not node.is_entrypoint and not node.is_test)
    result.module_stats = _module_stats(result)
    result.external_dependencies = sorted(
        ({"name": name, "imports": count} for name, count in (external_packages or {}).items()),
        key=lambda item: (-item["imports"], item["name"]),
    )[:60]
    languages = defaultdict(int)
    for node in result.nodes.values():
        languages[node.language] += 1
    result.stats = {
        "files": len(result.nodes),
        "edges": len(result.edges),
        "import_edges": sum(1 for e in result.edges if e["kind"] != "call"),
        "call_edges": sum(1 for e in result.edges if e["kind"] == "call"),
        "cycles": len(result.cycles),
        "cycle_members": len(cycle_members),
        "orphans": len(result.orphans),
        "hubs": len(result.hubs),
        "high_coupling": sum(1 for n in result.nodes.values() if n.coupling >= 12),
        "layers": {layer: sum(1 for n in result.nodes.values() if n.layer == layer) for layer in sorted({n.layer for n in result.nodes.values()})},
        "languages": dict(sorted(languages.items(), key=lambda item: -item[1])),
        "parsed_files": sum(1 for p in parsed_files if p.parse_error is None),
        "excluded_files": excluded_files,
        "graph_note": (
            "Graph nodes are code modules: documentation, data and asset files are excluded "
            "unless a resolved import points at them."
        ),
    }
    return result


# --------------------------------------------------------------------------- #
# Cycle detection - Tarjan's strongly connected components (iterative)
# --------------------------------------------------------------------------- #

def find_cycles(adjacency: dict[str, list[str]], max_cycles: int = 25, max_size: int = 12) -> list[list[str]]:
    index_counter = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    components: list[list[str]] = []
    nodes = set(adjacency) | {target for targets in adjacency.values() for target in targets}

    for start in sorted(nodes):
        if start in indices:
            continue
        work: list[tuple[str, int]] = [(start, 0)]
        while work:
            node, child_index = work.pop()
            if child_index == 0:
                indices[node] = index_counter
                lowlink[node] = index_counter
                index_counter += 1
                stack.append(node)
                on_stack.add(node)
            children = adjacency.get(node, [])
            recursed = False
            for position in range(child_index, len(children)):
                child = children[position]
                if child not in indices:
                    work.append((node, position + 1))
                    work.append((child, 0))
                    recursed = True
                    break
                elif child in on_stack:
                    lowlink[node] = min(lowlink[node], indices[child])
            if recursed:
                continue
            if lowlink[node] == indices[node]:
                component: list[str] = []
                while stack:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1 or (len(component) == 1 and component[0] in adjacency.get(component[0], [])):
                    components.append(sorted(component))
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])

    components.sort(key=lambda component: (-len(component), component[0]))
    return components[:max_cycles]


def _module_stats(result: GraphResult) -> list[dict]:
    """Aggregate file metrics per directory (module)."""
    buckets: dict[str, dict] = defaultdict(lambda: {"files": 0, "loc": 0, "fan_in": 0, "fan_out": 0, "symbols": 0})
    for node in result.nodes.values():
        directory = posixpath.dirname(node.path) or "."
        bucket = buckets[directory]
        bucket["files"] += 1
        bucket["loc"] += node.loc
        bucket["fan_in"] += node.fan_in
        bucket["fan_out"] += node.fan_out
        bucket["symbols"] += node.symbols
    return sorted(
        ({"module": name, **values} for name, values in buckets.items()),
        key=lambda item: (-item["files"], item["module"]),
    )[:40]


def subgraph(result: GraphResult, paths: set[str], kinds: set[str] | None = None) -> dict:
    """Induced subgraph for visualisation."""
    edges = [
        edge for edge in result.edges
        if edge["source"] in paths and edge["target"] in paths and (kinds is None or edge["kind"] in kinds)
    ]
    return {
        "nodes": [result.nodes[path].to_dict() for path in sorted(paths) if path in result.nodes],
        "edges": edges,
    }
