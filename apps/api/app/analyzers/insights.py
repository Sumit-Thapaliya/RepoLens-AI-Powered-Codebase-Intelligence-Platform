"""Deterministic insights for the Overview page.

Nothing here is invented: each insight is derived from counts and evidence that
the analysis actually produced, and each carries the artefacts it came from.
"""

from __future__ import annotations

from collections import Counter

from repolens_parser import is_test_path


def build_insights(*, parsed_files, graph, endpoints: list[dict], database: dict, workflows: list[dict],
                   frameworks: list[dict], quality: dict, manifests: list[dict]) -> list[dict]:
    insights: list[dict] = []

    def add(kind: str, severity: str, title: str, detail: str, evidence: list[dict] | None = None,
            actions: list[dict] | None = None):
        insights.append({
            "id": f"insight:{kind}:{len(insights)}",
            "kind": kind,
            "severity": severity,          # info | positive | warning | critical
            "title": title,
            "detail": detail,
            "evidence": evidence or [],
            "actions": actions or [],
        })

    if endpoints:
        auth_endpoints = [endpoint for endpoint in endpoints if endpoint.get("auth_required")]
        add("api", "info", f"{len(endpoints)} API endpoint(s) detected",
            f"Across {len({endpoint['file_path'] for endpoint in endpoints})} file(s). "
            f"{len(auth_endpoints)} are marked as authenticated based on decorators, guards or middleware.",
            evidence=[{"path": endpoint["file_path"], "line": endpoint.get("line"),
                       "label": f"{endpoint['method']} {endpoint['path']}"} for endpoint in endpoints[:5]],
            actions=[{"label": "Open APIs", "target": "apis"}])

    auth_related = [
        endpoint for endpoint in endpoints
        if any(token in f"{endpoint['path']} {endpoint['handler']} {endpoint.get('controller') or ''}".lower()
               for token in ("auth", "login", "session", "token", "signin", "oauth"))
    ]
    if auth_related or any("auth" in parsed.path.lower() or any("auth" in (s.name or "").lower() for s in parsed.symbols)
                           for parsed in parsed_files):
        add("security", "info", "Authentication module detected",
            f"{len(auth_related)} endpoint(s) and {sum(1 for parsed in parsed_files if 'auth' in parsed.path.lower())} "
            "file(s) reference authentication concepts.",
            evidence=[{"path": endpoint["file_path"], "line": endpoint.get("line"),
                       "label": f"{endpoint['method']} {endpoint['path']}"} for endpoint in auth_related[:4]],
            actions=[{"label": "Trace auth workflows", "target": "workflows"}])

    database_tech = database.get("technologies") or []
    relational = [tech for tech in database_tech if tech.get("kind") in {"relational", "orm", "vector", "baas"}]
    if relational:
        primary = relational[0]
        add("database", "info", f"{primary['name']} usage detected",
            f"{len(database.get('models', []))} model(s)/table(s) and {len(database.get('queries', []))} query site(s) "
            f"were extracted. ORMs: {', '.join(database.get('orms') or ['(none detected)'])}.",
            evidence=[{"path": model["file_path"], "line": model.get("line"), "label": f"model {model['name']}"}
                      for model in database.get("models", [])[:4]],
            actions=[{"label": "Open Database", "target": "database"}])

    cycles = graph.cycles
    if cycles:
        add("quality", "warning", f"{len(cycles)} circular dependency group(s) found",
            "Circular imports make refactoring and testing harder. The largest group contains "
            f"{max(len(cycle) for cycle in cycles)} files.",
            evidence=[{"path": cycle[0], "label": " → ".join(cycle[:4]) + ("…" if len(cycle) > 4 else "")}
                      for cycle in cycles[:4]],
            actions=[{"label": "Inspect dependencies", "target": "dependencies"}])

    high_coupling = [node for node in graph.nodes.values() if node.coupling >= 12]
    if high_coupling:
        top = sorted(high_coupling, key=lambda node: -node.coupling)[:3]
        add("architecture", "warning", f"{len(high_coupling)} high-coupling module(s) detected",
            "Modules with a high fan-in + fan-out are change hotspots: "
            + ", ".join(f"{node.path} ({node.coupling})" for node in top),
            evidence=[{"path": node.path, "label": f"fan-in {node.fan_in}, fan-out {node.fan_out}"} for node in top],
            actions=[{"label": "Open dependencies", "target": "dependencies"}])

    test_files = [parsed for parsed in parsed_files if is_test_path(parsed.path)]
    if test_files:
        add("quality", "positive", f"{len(test_files)} test file(s) detected",
            f"Tests cover roughly {round(len(test_files) / max(1, len(parsed_files)) * 100)}% of the file count.",
            evidence=[{"path": parsed.path, "label": "test file"} for parsed in test_files[:4]])
    else:
        add("quality", "warning", "No test files detected",
            "No file matched common test conventions. This is a strong signal that the repository has no automated tests "
            "RepoLens could find.",
            actions=[{"label": "Open quality", "target": "quality"}])

    if workflows:
        categories = Counter(workflow["category_label"] for workflow in workflows)
        add("workflow", "positive", f"{len(workflows)} application workflow(s) traced",
            "Most common: " + ", ".join(f"{label} ({count})" for label, count in categories.most_common(3)),
            evidence=[{"path": (workflow["steps"][1].get("file_path") if len(workflow["steps"]) > 1 else workflow.get("files", [None])[0]),
                       "label": workflow["name"]} for workflow in workflows[:4]],
            actions=[{"label": "Open workflows", "target": "workflows"}])

    parse_failures = [parsed for parsed in parsed_files if parsed.parse_error]
    if parse_failures:
        add("analysis", "warning", f"{len(parse_failures)} file(s) could not be parsed",
            "These files are indexed for search but excluded from symbol, graph and workflow analysis.",
            evidence=[{"path": parsed.path, "label": (parsed.parse_error or "")[:90]} for parsed in parse_failures[:5]])

    unsupported = {parsed.language for parsed in parsed_files
                   if any("Unsupported language" in warning or "does not have a deep symbol parser" in warning
                          for warning in parsed.warnings)}
    if unsupported:
        add("analysis", "info", "Some languages are indexed but not deeply analysed",
            "Deep parsing is available for Python, JS/TS, Go, Java, Ruby, PHP, Rust and C/C#. "
            f"Indexed only: {', '.join(sorted(unsupported))}.")

    if quality.get("summary", {}).get("by_severity", {}).get("high"):
        add("quality", "critical", f"{quality['summary']['by_severity']['high']} high-severity quality finding(s)",
            "Review them in the Quality page - they are heuristics, not confirmed defects.",
            actions=[{"label": "Open quality report", "target": "quality"}])

    if frameworks:
        top = [framework for framework in frameworks if framework.get("confidence", 0) >= 0.6][:5]
        if top:
            add("stack", "info", "Detected stack: " + ", ".join(framework["name"] for framework in top),
                "Detected from dependency manifests and code usage.",
                evidence=[{"label": f"{framework['name']}: {', '.join(framework.get('evidence', [])[:2])}",
                           "path": (framework.get("evidence") or [""])[0]} for framework in top])

    monorepo = [manifest for manifest in manifests if "/" in manifest.get("path", "")]
    if len(monorepo) >= 2:
        add("structure", "info", f"Multi-package repository ({len(manifests)} manifests)",
            "Several manifests were found, which usually means a monorepo or multiple deployables.",
            evidence=[{"path": manifest["path"], "label": manifest.get("name") or manifest.get("ecosystem")}
                      for manifest in manifests[:6]])

    return insights
