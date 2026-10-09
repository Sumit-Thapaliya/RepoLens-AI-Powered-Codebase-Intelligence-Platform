"""Architecture view: collapse the file graph into architectural layers."""

from __future__ import annotations

import posixpath
from collections import defaultdict

from repolens_parser import ParsedFile

from .dependency import GraphResult

#: Canonical layer order for the architecture diagram (left to right).
LAYER_ORDER = ["ui", "route", "middleware", "service", "repository", "util", "config", "test", "entrypoint", "other"]

LAYER_LABELS = {
    "ui": "Frontend / UI",
    "route": "API Layer",
    "middleware": "Middleware & Security",
    "service": "Services",
    "repository": "Data Access",
    "util": "Shared Utilities",
    "config": "Configuration & Infra",
    "test": "Tests",
    "entrypoint": "Entrypoints",
    "other": "Other Modules",
}

LAYER_DESCRIPTIONS = {
    "ui": "Components, pages and client-side state",
    "route": "HTTP handlers, routers and controllers",
    "middleware": "Auth, guards, interceptors and filters",
    "service": "Business logic and use cases",
    "repository": "Repositories, models and persistence",
    "util": "Cross-cutting helpers",
    "config": "Settings, CI/CD and infrastructure",
    "test": "Test suites",
    "entrypoint": "Process entrypoints (main, server, CLI)",
    "other": "Files that do not match a known convention",
}


def build_architecture(graph: GraphResult, parsed_files: list[ParsedFile]) -> dict:
    layer_files: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes.values():
        layer_files[node.layer].append(node.path)

    file_layer = {node.path: node.layer for node in graph.nodes.values()}
    layer_edges: dict[tuple[str, str], dict] = defaultdict(lambda: {"weight": 0, "samples": [], "kinds": set()})
    same_layer: set[str] = set()
    for edge in graph.edges:
        source_layer = file_layer.get(edge["source"])
        target_layer = file_layer.get(edge["target"])
        if not source_layer or not target_layer:
            continue
        if source_layer == target_layer:
            same_layer.add(source_layer)
            continue
        bucket = layer_edges[(source_layer, target_layer)]
        bucket["weight"] += edge["weight"]
        bucket["kinds"].add(edge["kind"])
        if len(bucket["samples"]) < 12:
            bucket["samples"].append({"source": edge["source"], "target": edge["target"], "kind": edge["kind"], "line": edge.get("line")})

    layers = []
    for layer in LAYER_ORDER:
        paths = sorted(layer_files.get(layer, []))
        if not paths:
            continue
        nodes = [graph.nodes[path] for path in paths]
        layers.append({
            "id": layer,
            "label": LAYER_LABELS[layer],
            "description": LAYER_DESCRIPTIONS[layer],
            "files": len(paths),
            "loc": sum(node.loc for node in nodes),
            "symbols": sum(node.symbols for node in nodes),
            "fan_in": sum(node.fan_in for node in nodes),
            "fan_out": sum(node.fan_out for node in nodes),
            "sample_files": [
                {"path": node.path, "loc": node.loc, "symbols": node.symbols, "fan_in": node.fan_in, "fan_out": node.fan_out}
                for node in sorted(nodes, key=lambda n: (-n.coupling, n.path))[:8]
            ],
            "internal_edges": same_layer_count(graph, layer),
        })

    edges = [
        {"source": source, "target": target, "weight": bucket["weight"], "kinds": sorted(bucket["kinds"]),
         "samples": bucket["samples"]}
        for (source, target), bucket in sorted(layer_edges.items(), key=lambda item: -item[1]["weight"])
    ]

    entrypoints = []
    for node in graph.nodes.values():
        if node.is_entrypoint:
            entrypoints.append({"path": node.path, "layer": node.layer, "kind": "process entrypoint",
                                "detail": f"{node.loc} LOC, {node.symbols} symbols"})
    seen = {entrypoint["path"] for entrypoint in entrypoints}
    # Files with a route but not named like an entrypoint are still entrypoints for users.
    for parsed in parsed_files:
        if parsed.routes and parsed.path not in seen:
            entrypoints.append({
                "path": parsed.path, "layer": file_layer.get(parsed.path, "route"), "kind": "http router",
                "detail": f"{len(parsed.routes)} endpoint(s) declared",
            })
            seen.add(parsed.path)

    notes = []
    names = {layer["id"] for layer in layers}
    if "ui" in names and "route" in names:
        notes.append("Frontend and API layers are both present in this repository.")
    if "service" in names:
        notes.append("A dedicated service layer was detected (business logic separated from transport).")
    if "repository" in names:
        notes.append("A data-access/repository layer was detected.")
    if not names & {"service", "repository"}:
        notes.append("No conventional service/repository directories were found - layering is inferred from naming only.")
    if "test" in names:
        notes.append("Tests are colocated with the source tree or in a dedicated test directory.")
    notes.append("Layers are heuristic: they are derived from directory and file naming conventions, not from runtime behaviour.")

    return {"layers": layers, "edges": edges, "entrypoints": entrypoints[:40], "notes": notes}


def same_layer_count(graph: GraphResult, layer: str) -> int:
    return sum(1 for edge in graph.edges
               if graph.nodes.get(edge["source"]) and graph.nodes[edge["source"]].layer == layer
               and graph.nodes.get(edge["target"]) and graph.nodes[edge["target"]].layer == layer)


def layer_of(path: str, graph: GraphResult) -> str:
    node = graph.nodes.get(path)
    return node.layer if node else "other"


def module_graph(graph: GraphResult, depth: int = 2) -> dict:
    """Directory level roll-up of the file graph (useful for large repos)."""
    def module_of(path: str) -> str:
        parts = path.split("/")
        return "/".join(parts[:depth]) if len(parts) > depth else (posixpath.dirname(path) or path)

    buckets: dict[str, dict] = defaultdict(lambda: {"files": 0, "loc": 0, "fan_in": 0, "fan_out": 0, "layers": defaultdict(int)})
    file_module: dict[str, str] = {}
    for path, node in graph.nodes.items():
        module = module_of(path)
        file_module[path] = module
        bucket = buckets[module]
        bucket["files"] += 1
        bucket["loc"] += node.loc
        bucket["fan_in"] += node.fan_in
        bucket["fan_out"] += node.fan_out
        bucket["layers"][node.layer] += 1

    edges: dict[tuple[str, str], int] = defaultdict(int)
    for edge in graph.edges:
        source, target = file_module.get(edge["source"]), file_module.get(edge["target"])
        if not source or not target or source == target:
            continue
        edges[(source, target)] += edge["weight"]

    return {
        "nodes": [
            {"id": module, "label": module, "kind": "module", "files": bucket["files"], "loc": bucket["loc"],
             "fan_in": bucket["fan_in"], "fan_out": bucket["fan_out"],
             "layer": max(bucket["layers"].items(), key=lambda item: item[1])[0]}
            for module, bucket in sorted(buckets.items())
        ],
        "edges": [{"id": f"module:{s}->{t}", "source": s, "target": t, "kind": "import", "weight": w}
                  for (s, t), w in sorted(edges.items(), key=lambda item: -item[1])],
    }
