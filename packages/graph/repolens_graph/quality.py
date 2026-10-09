"""Code-quality heuristics.

Everything produced here is a *signal for review*, computed with explicit
thresholds that are attached to each finding so the UI can show its reasoning.
"""

from __future__ import annotations

import posixpath
import re
from collections import defaultdict

from repolens_shared.constants import GRAPH_LANGUAGES, QUALITY_THRESHOLDS
from repolens_shared.utils import is_example_path, stable_id, truncate
from repolens_parser import ParsedFile
from repolens_parser.python_analyzer import is_test_path, layer_for_path

from .dependency import GraphResult

SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|private[_-]?key|client[_-]?secret|db_password)\b"
    r"\s*[:=]\s*['\"][^'\"]{12,}['\"]"
)
TODO_PATTERN = re.compile(r"(?i)\b(TODO|FIXME|HACK|XXX)\b[:\s](.{0,90})")
#: Files whose whole job is to re-export other modules.
BARREL_FILES = {"__init__.py", "__init__.pyi", "index.ts", "index.js", "index.tsx", "mod.rs"}

PLACEHOLDER_SECRETS = {"changeme", "your-key-here", "xxx", "todo", "placeholder", "example", "test", "secret"}


def analyze_quality(parsed_files: list[ParsedFile], graph: GraphResult, file_contents: dict[str, str] | None = None,
                    max_findings: int = 200, scope: str = "") -> dict:
    issues: list[dict] = []
    files = {parsed.path: parsed for parsed in parsed_files}
    thresholds = QUALITY_THRESHOLDS

    def add(kind: str, severity: str, title: str, detail: str, *, files: list[str] | None = None,
            symbol: str | None = None, metric: dict | None = None, heuristic: bool = True):
        if len(issues) >= max_findings:
            return
        issues.append({
            "id": stable_id(kind, scope, title, ",".join(files or []), symbol or ""),
            "kind": kind, "severity": severity, "title": title, "detail": detail,
            "files": files or [], "symbol": symbol, "metric": metric or {}, "heuristic": heuristic,
        })

    # ---------------------------------------------------------------- cycles
    for cycle in graph.cycles:
        add("circular_dependency", "high" if len(cycle) > 2 else "medium",
            f"Circular dependency between {len(cycle)} files",
            " → ".join(posixpath.basename(path) for path in cycle[:8]) + (" …" if len(cycle) > 8 else ""),
            files=cycle[:12], metric={"cycle_size": len(cycle)})

    # ------------------------------------------------------------- coupling
    for path, node in sorted(graph.nodes.items(), key=lambda item: -item[1].coupling)[:15]:
        # A package __init__ / index barrel that defines no symbols of its own is
        # a deliberate facade, not a coupling problem.
        if node.symbols == 0 and posixpath.basename(path) in BARREL_FILES:
            continue
        if node.coupling >= thresholds["high_coupling_degree"]:
            add("high_coupling", "medium" if node.coupling < 20 else "high",
                f"High coupling in {posixpath.basename(path)} ({node.coupling} connections)",
                f"fan-in {node.fan_in} (dependents) + fan-out {node.fan_out} (dependencies). "
                "Consider splitting responsibilities or introducing an interface.",
                files=[path], metric={"fan_in": node.fan_in, "fan_out": node.fan_out, "coupling": node.coupling})

    # ------------------------------------------------------ large modules
    # Only code modules are measured: a 5,000-line CHANGES.rst is not a large module.
    code_files = [parsed for parsed in parsed_files if parsed.language in GRAPH_LANGUAGES]
    for parsed in sorted(code_files, key=lambda p: -p.loc)[:15]:
        if parsed.loc >= thresholds["large_module_loc"]:
            add("large_module", "medium" if parsed.loc < 1500 else "high",
                f"{posixpath.basename(parsed.path)} is {parsed.loc} lines",
                f"Large files are harder to review and test. This file declares {len(parsed.symbols)} symbols.",
                files=[parsed.path], metric={"loc": parsed.loc, "symbols": len(parsed.symbols)})

    # ------------------------------------------------------- complexity
    complexity_rank: list[tuple[int, str, str, int]] = []
    for parsed in parsed_files:
        for symbol in parsed.symbols:
            if symbol.kind in {"function", "method"}:
                complexity_rank.append((symbol.complexity, parsed.path, symbol.name, symbol.start_line))
    complexity_rank.sort(reverse=True)
    for complexity, path, name, line in complexity_rank[:12]:
        if complexity >= thresholds["high_complexity"]:
            add("high_complexity", "medium" if complexity < 30 else "high",
                f"`{name}` has cyclomatic complexity {complexity}",
                f"Threshold is {thresholds['high_complexity']:.0f}. Consider extracting helpers or guard clauses.",
                files=[path], symbol=name, metric={"complexity": complexity, "line": line})

    # --------------------------------------------------------- god classes
    for parsed in parsed_files:
        for symbol in parsed.symbols:
            if symbol.kind == "class" and len(symbol.params) >= thresholds["god_class_methods"]:
                add("god_class", "medium", f"`{symbol.name}` declares {len(symbol.params)} methods",
                    "Large classes usually mix several responsibilities.",
                    files=[parsed.path], symbol=symbol.name, metric={"methods": len(symbol.params)})

    # ------------------------------------------- duplicate implementations
    shingles: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for parsed in parsed_files:
        for symbol in parsed.symbols:
            if symbol.kind not in {"function", "method"} or symbol.shingle is None:
                continue
            if symbol.loc < thresholds["duplicate_min_lines"]:
                continue
            shingles[symbol.shingle].append((parsed.path, symbol.name, symbol.start_line))
    duplicates = {key: value for key, value in shingles.items() if len(value) > 1}
    for key, group in list(duplicates.items())[:12]:
        paths = sorted({item[0] for item in group})
        add("duplicate_code", "low",
            f"Similar implementations: {', '.join(item[1] for item in group[:3])}",
            "These functions share the same normalised token structure (shingle hash). "
            "Confirm manually - structurally similar code is not always a true duplicate.",
            files=paths, metric={"occurrences": len(group)})

    # ---------------------------------------------------------- missing tests
    test_files = [parsed for parsed in parsed_files if is_test_path(parsed.path)]
    test_count = len(test_files)
    if test_count == 0 and parsed_files:
        add("missing_tests", "high", "No test files detected",
            "No files matched common test conventions (*_test.*, *.test.*, tests/, __tests__/). "
            "Test coverage cannot be measured from static analysis, but the absence of test files is a strong signal.",
            files=[], metric={"test_files": 0})
    else:
        tested_names: set[str] = set()
        for test in test_files:
            for symbol in test.symbols:
                name = re.sub(r"^(test_|it_|should_)", "", symbol.name, flags=re.IGNORECASE)
                tested_names.add(name.lower())
            for imp in test.imports:
                for name in imp.names:
                    tested_names.add(name.lower())
        production = [parsed for parsed in parsed_files
                      if not is_test_path(parsed.path) and not is_example_path(parsed.path)
                      and layer_for_path(parsed.path) not in {"other", "config", "test", "docs"}]
        untested_targets: list[tuple[int, str, str]] = []
        for parsed in production:
            for symbol in parsed.symbols:
                if symbol.kind not in {"function", "method", "class"}:
                    continue
                if not symbol.exported:
                    continue
                candidates = {symbol.name.lower(), symbol.name.lower().replace("_", "")}
                candidates |= {part.lower() for part in re.split(r"(?=[A-Z])|_", symbol.name) if len(part) > 3}
                if not (candidates & tested_names):
                    untested_targets.append((symbol.loc, parsed.path, symbol.name))
        untested_targets.sort(reverse=True)
        for _, path, name in untested_targets[:10]:
            add("missing_tests", "low", f"No test reference found for `{name}`",
                "No test file imports this symbol or mentions its name. This is a heuristic - tests may exercise it "
                "indirectly through an entrypoint.",
                files=[path], symbol=name, metric={"test_files": test_count})

    # ------------------------------------------------------------ dead-ish code
    def _isolatable(path: str) -> bool:
        """Modules that are executed rather than imported are not dead code."""
        if is_test_path(path) or is_example_path(path):
            return False
        if layer_for_path(path) in {"config", "entrypoint"}:
            return False
        if path.endswith((".d.ts", ".pyi")):
            return False
        lowered = "/" + path.lower()
        return not any(segment in lowered for segment in
                       ("/alembic/versions/", "/migrations/", "/scripts/", "/bin/", "/tools/", "/management/commands/"))

    for path in [p for p in graph.orphans if _isolatable(p)][:10]:
        node = graph.nodes[path]
        add("isolated_module", "info", f"{posixpath.basename(path)} has no dependents",
            "Nothing in the analysed set imports this file and it imports nothing. It may be dead code, a script, or "
            "reachable only through dynamic imports.",
            files=[path], metric={"loc": node.loc})

    # --------------------------------------------------------- observability
    contents = file_contents or {}
    todo_count = 0
    todo_samples: list[str] = []
    secret_hits: list[dict] = []
    for path, content in contents.items():
        if not content or len(content) > 400_000:
            continue
        if path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rb", ".java", ".php", ".rs", ".c", ".cpp", ".cs")):
            for match in TODO_PATTERN.finditer(content):
                todo_count += 1
                if len(todo_samples) < 6:
                    line = content[: match.start()].count("\n") + 1
                    todo_samples.append(f"{path}:{line} {truncate(match.group(0), 80)}")
        if re.search(r"(^|/)(\.env|\.env\.local|\.env\.prod|secrets?\.ya?ml|credentials\.json)", path, re.I) and \
                not path.endswith((".example", ".sample", ".template")):
            secret_hits.append({"path": path, "reason": "Environment/secret file committed to the repository"})
        elif path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".yml", ".yaml", ".json", ".env", ".example", ".toml")):
            for match in SECRET_PATTERN.finditer(content[:200_000]):
                literal = match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(0)
                if any(placeholder in str(literal).lower() for placeholder in PLACEHOLDER_SECRETS):
                    continue
                line = content[: match.start()].count("\n") + 1
                secret_hits.append({"path": path, "line": line,
                                    "reason": f"Possible hardcoded credential ({match.group(1)})"})

    if todo_count:
        add("tech_debt", "info", f"{todo_count} TODO/FIXME marker(s)",
            "Technical-debt markers found in source files: " + " | ".join(todo_samples),
            files=[sample.split(":")[0] for sample in todo_samples], metric={"count": todo_count})
    for hit in secret_hits[:12]:
        fixture = is_test_path(hit["path"]) or is_example_path(hit["path"])
        add("possible_secret", "low" if fixture else "high",
            "Possible committed secret" + (" (test/example fixture)" if fixture else ""),
            f"{hit['reason']} in {hit['path']}" + (f":{hit['line']}" if hit.get("line") else "")
            + (". This path is a test or example fixture - verify it holds no real credential."
               if fixture else ""),
            files=[hit["path"]], heuristic=True)

    # --------------------------------------------------------------- summary
    severity_weight = {"high": 1.0, "medium": 0.6, "low": 0.3, "info": 0.1}
    by_kind: dict[str, int] = defaultdict(int)
    by_severity: dict[str, int] = defaultdict(int)
    for issue in issues:
        by_kind[issue["kind"]] += 1
        by_severity[issue["severity"]] += 1

    total_loc = sum(parsed.loc for parsed in parsed_files) or 1
    total_symbols = sum(len(parsed.symbols) for parsed in parsed_files) or 1
    complexity_values = [entry[0] for entry in complexity_rank] or [0]
    production_files = [parsed for parsed in parsed_files if not is_test_path(parsed.path)]
    avg_coupling = round(sum(node.coupling for node in graph.nodes.values()) / max(1, len(graph.nodes)), 2)
    penalty = sum(severity_weight[issue["severity"]] for issue in issues)
    health = max(0, min(100, round(100 - (penalty / max(1, total_symbols / 40)) * 10)))

    summary = {
        "issues": len(issues),
        "by_severity": dict(by_severity),
        "by_kind": dict(by_kind),
        "health_score": health,
        "health_label": ("strong" if health >= 80 else "fair" if health >= 60 else "needs attention"),
    }
    metrics = {
        "files": len(parsed_files),
        "code_files": len(code_files),
        "production_files": len(production_files),
        "test_files": len(test_files),
        "test_file_ratio": round(len(test_files) / max(1, len(parsed_files)), 3),
        "loc": total_loc,
        "symbols": total_symbols,
        "avg_complexity": round(sum(complexity_values) / len(complexity_values), 2),
        "max_complexity": max(complexity_values),
        "avg_coupling": avg_coupling,
        "cycles": len(graph.cycles),
        "orphans": len(graph.orphans),
        "todos": todo_count,
        "duplicate_groups": len(duplicates),
        "thresholds": thresholds,
    }
    issues.sort(key=lambda issue: ({"high": 0, "medium": 1, "low": 2, "info": 3}[issue["severity"]], issue["kind"]))
    return {
        "issues": issues,
        "summary": summary,
        "metrics": metrics,
        "disclaimer": (
            "These findings are static-analysis heuristics computed from parsed source code and import graphs. "
            "They are signals for review, not proof of defects. Thresholds are listed in `metrics.thresholds`."
        ),
    }
