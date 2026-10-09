"""Workflow detection: trace real execution paths across files.

Every workflow is built from evidence found in the repository - an HTTP route
declaration, a symbol that calls another symbol, an ORM query in the callee.
When a link cannot be established the trace stops and the step list says so
instead of fabricating a hop.
"""

from __future__ import annotations

import posixpath
import re
from collections import defaultdict

from repolens_shared.constants import WORKFLOW_SIGNALS
from repolens_shared.utils import is_doc_path, is_example_path, stable_id, truncate
from repolens_parser import ParsedFile
from repolens_parser.python_analyzer import is_test_path, layer_for_path

from .dependency import GraphResult, build_symbol_index, imported_symbol_map

MAX_DEPTH = 7
MAX_STEPS = 14

STEP_KIND_BY_LAYER = {
    "ui": "ui",
    "route": "controller",
    "middleware": "middleware",
    "service": "service",
    "repository": "repository",
    "util": "util",
    "config": "external",
    "entrypoint": "controller",
    "other": "service",
    "test": "util",
}


class WorkflowTracer:
    def __init__(self, parsed_files: list[ParsedFile], graph: GraphResult):
        self.files = {parsed.path: parsed for parsed in parsed_files}
        self.graph = graph
        self.symbol_index = build_symbol_index(parsed_files)
        self.layer_of: dict[str, str] = {node.path: node.layer for node in graph.nodes.values()}
        self.import_maps = {parsed.path: imported_symbol_map(parsed) for parsed in parsed_files}
        self.source_cache = {parsed.path: None for parsed in parsed_files}

    # ------------------------------------------------------------------ tools
    def symbol_in_file(self, path: str, name: str):
        parsed = self.files.get(path)
        if not parsed:
            return None
        for symbol in parsed.symbols:
            if symbol.name == name:
                return symbol
        return None

    def resolve_callee(self, from_path: str, call) -> tuple[str, str] | None:
        """Return (path, symbol name) for a call made from ``from_path``."""
        mapping = self.import_maps.get(from_path, {})
        candidates: list[str] = []
        receiver = call.receiver or ""
        if receiver and receiver in mapping:
            candidates.append(f"{mapping[receiver]}:{call.name}")
        if call.qualifier:
            head = call.qualifier.split(".")[0]
            if head in mapping:
                candidates.append(f"{mapping[head]}:{call.name}")
        if call.name in mapping:
            candidates.append(f"{mapping[call.name]}:{call.name}")
        # same-file definition
        if self.symbol_in_file(from_path, call.name):
            candidates.append(f"{from_path}:{call.name}")
        for candidate in candidates:
            path, _, name = candidate.partition(":")
            if path in self.files and self.symbol_in_file(path, name):
                return path, name
        # last resort: unique definition of the symbol name anywhere
        definitions = self.symbol_index.get(call.name, [])
        if len(definitions) == 1 and definitions[0][0] != from_path:
            path, _ = definitions[0]
            if self.symbol_in_file(path, call.name):
                return path, call.name
        return None

    def find_callers(self, callee_name: str, callee_path: str, limit: int = 40) -> list[tuple[str, str, int]]:
        """(path, symbol, line) of callers - used to walk *up* a workflow."""
        out: list[tuple[str, str, int]] = []
        for path, parsed in self.files.items():
            if path == callee_path:
                continue
            mapping = self.import_maps.get(path, {})
            imports_target = callee_path in set(mapping.values()) or any(
                imp.resolved_path == callee_path for imp in parsed.imports
            )
            for symbol in parsed.symbols:
                for call in symbol.calls:
                    if call.name != callee_name:
                        continue
                    same_file = path == callee_path
                    if imports_target or same_file:
                        out.append((path, symbol.name, call.line))
                        if len(out) >= limit:
                            return out
        return out


# --------------------------------------------------------------------------- #
# Flow construction
# --------------------------------------------------------------------------- #

def _category_for(text: str) -> str:
    lowered = text.lower()
    best, best_score = "general", 0
    for category, signals in WORKFLOW_SIGNALS.items():
        score = sum(1 for signal in signals if signal in lowered)
        if score > best_score:
            best, best_score = category, score
    return best


def _humanize(value: str) -> str:
    text = re.sub(r"[_\-/]+", " ", value)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"\b(id|api|http|db|url)\b", lambda m: m.group(1).upper(), text, flags=re.IGNORECASE)
    return " ".join(word.capitalize() if word.islower() else word for word in text.split())[:70]


CATEGORY_LABELS = {
    "auth": "Authentication & Sessions",
    "signup": "Registration & Onboarding",
    "payment": "Payments & Orders",
    "upload": "File Handling",
    "search": "Search & Filtering",
    "notification": "Notifications",
    "crud": "CRUD",
    "realtime": "Realtime / Events",
    "general": "General Request",
}


#: Languages that can genuinely call an HTTP endpoint from the client. Docs and
#: data files are excluded: a URL inside a `.rst` tutorial is documentation, not
#: a call site.
UI_CALL_LANGUAGES = {"tsx", "jsx", "typescript", "javascript", "vue", "svelte", "html"}


def _ui_step_for(tracer: WorkflowTracer, path: str) -> dict | None:
    """Find a UI code file that references this endpoint path (fetch('/api/...'))."""
    if len(path) < 4:
        return None
    needle = path.strip("/")
    pattern = re.compile(re.escape(path) + r"|" + re.escape(needle))
    for candidate_path, parsed in tracer.files.items():
        if tracer.layer_of.get(candidate_path) != "ui":
            continue
        if parsed.language not in UI_CALL_LANGUAGES:
            continue
        if is_test_path(candidate_path) or is_example_path(candidate_path) or is_doc_path(candidate_path):
            continue
        content = tracer.source_cache.get(candidate_path)
        if content is None:
            try:
                content = _read(candidate_path)
            except Exception:
                content = ""
            tracer.source_cache[candidate_path] = content
        if not content:
            continue
        match = pattern.search(content)
        if match:
            line = content[: match.start()].count("\n") + 1
            return {
                "id": stable_id("ui", candidate_path, line),
                "label": _humanize(posixpath.basename(candidate_path).rsplit(".", 1)[0]),
                "kind": "ui", "file_path": candidate_path, "line": line,
                "detail": "Client code calls this endpoint",
                "evidence": truncate(content.splitlines()[line - 1] if line - 1 < len(content.splitlines()) else "", 120),
            }
    return None


_SOURCE_ROOTS: dict[str, str] = {}


def _read(path: str) -> str:
    root = _SOURCE_ROOTS.get("root")
    if not root:
        return ""
    full = posixpath.join(root, path)
    with open(full, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read(400_000)


def set_source_root(root: str) -> None:
    _SOURCE_ROOTS["root"] = root


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def detect_workflows(parsed_files: list[ParsedFile], graph: GraphResult, source_root: str | None = None,
                     endpoints: list[dict] | None = None, max_workflows: int = 24,
                     scope: str = "") -> list[dict]:
    if source_root:
        set_source_root(source_root)
    tracer = WorkflowTracer(parsed_files, graph)
    workflows: list[dict] = []
    seen_keys: set[str] = set()

    endpoint_records: list[dict] = []
    if endpoints:
        endpoint_records = endpoints
    else:
        for parsed in parsed_files:
            for route in parsed.routes:
                endpoint_records.append({
                    "method": route.method, "path": route.path, "handler": route.handler,
                    "file_path": parsed.path, "line": route.line, "framework": route.framework,
                    "auth_required": route.auth_hint, "controller": route.controller,
                })

    # Order by "interestingness": auth/payment/order-related endpoints first.
    def interest(record: dict) -> tuple:
        text = f"{record.get('path', '')} {record.get('handler', '')}"
        category = _category_for(text)
        return (0 if category in {"auth", "payment", "signup"} else 1, record.get("path", ""))

    for record in sorted(endpoint_records, key=interest)[:60]:
        workflow = _trace_endpoint(tracer, record, scope=scope)
        if workflow is None:
            continue
        key = f"{workflow['trigger']}::{workflow.get('entry_point')}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        workflows.append(workflow)
        if len(workflows) >= max_workflows:
            break

    workflows.extend(_detect_background_workflows(tracer, parsed_files, seen_keys, scope=scope))

    workflows.sort(key=lambda wf: (-wf["confidence"], -len(wf["steps"]), wf["name"]))
    return workflows


def _trace_endpoint(tracer: WorkflowTracer, record: dict, scope: str = "") -> dict | None:
    file_path = record.get("file_path")
    if not file_path or file_path not in tracer.files:
        return None
    handler_name = record.get("handler") or ""
    handler_symbol = tracer.symbol_in_file(file_path, handler_name) if handler_name else None

    steps: list[dict] = []
    evidence: list[str] = []
    files: list[str] = []
    trigger = f"{record.get('method', 'ANY')} {record.get('path', '')}"

    ui_step = _ui_step_for(tracer, record.get("path", ""))
    if ui_step:
        steps.append(ui_step)
        files.append(ui_step["file_path"])

    # 1. transport / API step
    api_step = {
        "id": stable_id("api", scope, file_path, trigger, record.get("line")),
        "label": f"{record.get('method', 'ANY')} {record.get('path', '')}",
        "kind": "api", "file_path": file_path, "line": record.get("line"),
        "symbol": handler_name or None,
        "detail": (record.get("framework") or "HTTP endpoint") + (f" · controller {record['controller']}" if record.get("controller") else ""),
        "evidence": f"route declared at {file_path}:{record.get('line')}",
    }
    steps.append(api_step)
    files.append(file_path)
    evidence.append(api_step["evidence"])

    if record.get("auth_required"):
        steps.append({
            "id": stable_id("mw", scope, file_path, trigger),
            "label": "Authentication / authorisation check",
            "kind": "middleware", "file_path": file_path, "line": record.get("line"),
            "detail": "Route declares an auth dependency or guard",
            "evidence": "auth marker found on the route declaration",
        })

    if handler_symbol is None:
        # Still useful: we know the endpoint and the file, but not the body.
        return _finalize(trigger, record, steps, evidence, files, confidence=0.35, truncated=True,
                         note="handler symbol could not be located (generated or dynamic routing)", scope=scope)

    handler_layer = tracer.layer_of.get(file_path, "route")
    steps.append({
        "id": stable_id("handler", scope, file_path, handler_symbol.name, handler_symbol.start_line),
        "label": handler_symbol.name,
        "kind": "controller" if handler_layer != "service" else "service",
        "file_path": file_path, "line": handler_symbol.start_line, "symbol": handler_symbol.name,
        "detail": truncate(handler_symbol.signature or "", 120),
        "evidence": handler_symbol.docstring and truncate(handler_symbol.docstring, 110) or f"defined in {file_path}",
    })
    evidence.append(f"handler `{handler_symbol.name}` at {file_path}:{handler_symbol.start_line}")

    visited: set[tuple[str, str]] = {(file_path, handler_symbol.name)}
    queue: list[tuple[str, str, int]] = [(file_path, handler_symbol.name, 1)]
    truncated = False
    db_steps: list[dict] = []

    while queue:
        current_path, current_symbol_name, depth = queue.pop(0)
        if depth > MAX_DEPTH or len(steps) >= MAX_STEPS:
            truncated = True
            break
        symbol = tracer.symbol_in_file(current_path, current_symbol_name)
        if symbol is None:
            continue

        # ORM / SQL activity attached to this symbol's file
        parsed = tracer.files.get(current_path)
        if parsed and parsed.queries:
            in_symbol = [query for query in parsed.queries
                         if query.line and symbol.start_line <= query.line <= symbol.end_line]
            contextual = in_symbol if in_symbol else (parsed.queries if depth <= 2 else [])
            for query in contextual[:3]:
                label = f"{query.orm or 'SQL'} · {query.table}" if query.table else (query.orm or "SQL query")
                if any(existing["detail"] == label for existing in db_steps):
                    continue
                db_steps.append({
                    "id": stable_id("db", scope, current_path, query.line, query.table),
                    "label": label,
                    "kind": "database", "file_path": current_path, "line": query.line,
                    "detail": label,
                    "evidence": truncate(query.snippet or "", 120),
                })

        for call in symbol.calls:
            resolved = tracer.resolve_callee(current_path, call)
            if not resolved:
                continue
            target_path, target_name = resolved
            if (target_path, target_name) in visited:
                continue
            if len(visited) > 40:
                truncated = True
                break
            visited.add((target_path, target_name))
            target_symbol = tracer.symbol_in_file(target_path, target_name)
            if target_symbol is None:
                continue
            layer = tracer.layer_of.get(target_path, "other")
            if layer == "test":
                continue
            steps.append({
                "id": stable_id("step", scope, target_path, target_name, target_symbol.start_line),
                "label": target_name,
                "kind": STEP_KIND_BY_LAYER.get(layer, "service"),
                "file_path": target_path, "line": target_symbol.start_line, "symbol": target_name,
                "detail": f"{layer} layer · {truncate(target_symbol.signature or '', 90)}",
                "evidence": f"called as `{call.full or call.name}` from {current_path}:{call.line}",
            })
            files.append(target_path)
            evidence.append(f"`{current_symbol_name}` calls `{target_name}` ({target_path})")
            queue.append((target_path, target_name, depth + 1))

    if db_steps:
        # keep the deepest/most specific three database hops
        steps.extend(db_steps[-3:])
        files.extend(step["file_path"] for step in db_steps[-3:])

    confidence = 0.4 + min(0.5, 0.08 * len(steps)) + (0.05 if record.get("framework") else 0)
    if truncated:
        confidence -= 0.08
    return _finalize(trigger, record, steps, evidence, files, confidence=round(min(0.95, confidence), 2),
                     truncated=truncated, scope=scope)


def _finalize(trigger: str, record: dict, steps: list[dict], evidence: list[str], files: list[str],
              confidence: float, truncated: bool = False, note: str | None = None, scope: str = "") -> dict:
    text = f"{trigger} {record.get('handler', '')}"
    category = _category_for(text)
    entry_path = record.get("file_path") or ""
    scope_kind = "test" if is_test_path(entry_path) else ("example" if is_example_path(entry_path) else "application")
    scope_note = None
    if scope_kind == "example":
        scope_note = "Entry point lives in an example application bundled with this repository"
    elif scope_kind == "test":
        scope_note = "Entry point lives in a test application - useful for reference, not a shipped route"

    human = _humanize(record.get("handler") or record.get("path", "").strip("/").replace("/", " "))
    name = f"{human} ({trigger})" if human else trigger
    description = f"{trigger} → " + " → ".join(step["label"] for step in steps[2:6]) if len(steps) > 2 else f"{trigger} handled in {record.get('file_path')}"
    return {
        "id": stable_id("workflow", scope, trigger, record.get("file_path"), record.get("handler")),
        "name": name[:110],
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, "General Request"),
        "description": (note + " · " if note else "") + description[:220],
        "entry_point": record.get("handler") or record.get("file_path"),
        "trigger": trigger,
        "steps": steps,
        "confidence": confidence,
        "evidence": evidence[:14],
        "files": sorted(set(files))[:20],
        "trace_truncated": truncated,
        "framework": record.get("framework"),
        "route": {"method": record.get("method"), "path": record.get("path"), "auth_required": record.get("auth_required")},
        # A library repository (Flask, requests, an SDK) has no application of
        # its own, so its traceable routes live in examples or test apps. Say so
        # rather than presenting them as production endpoints.
        "scope": scope_kind,
        "scope_note": scope_note,
    }


def _detect_background_workflows(tracer: WorkflowTracer, parsed_files: list[ParsedFile],
                                 seen_keys: set[str], scope: str = "") -> list[dict]:
    """Celery tasks, cron jobs, websocket consumers and CLI entrypoints."""
    workflows: list[dict] = []
    task_pattern = re.compile(r"@(app|celery|shared_task|task)[\w.]*\.?(task|periodic_task)?\s*[\(\n]", re.IGNORECASE)
    for parsed in parsed_files:
        if parsed.parse_error:
            continue
        content = _read(parsed.path) if _SOURCE_ROOTS.get("root") else None
        is_task_module = "task" in parsed.path.lower() or "worker" in parsed.path.lower() or "jobs" in parsed.path.lower()
        if not is_task_module:
            continue
        steps = []
        for symbol in parsed.symbols[:6]:
            if symbol.kind in {"function", "method"} and (symbol.decorators or symbol.name.startswith("task")):
                steps.append({
                    "id": stable_id("task", scope, parsed.path, symbol.name, symbol.start_line),
                    "label": symbol.name, "kind": "service", "file_path": parsed.path,
                    "line": symbol.start_line, "symbol": symbol.name,
                    "detail": f"background task · {truncate(symbol.signature or '', 80)}",
                    "evidence": f"defined in {parsed.path}",
                })
        if not steps:
            continue
        trigger = f"background:{parsed.path.rsplit('/', 1)[-1]}"
        key = f"{trigger}::background"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        workflows.append({
            "id": stable_id("workflow-bg", scope, parsed.path),
            "name": f"Background jobs in {parsed.path.rsplit('/', 1)[-1]}",
            "category": "general", "category_label": "Background Processing",
            "description": f"Task definitions found in {parsed.path}",
            "entry_point": steps[0]["label"], "trigger": trigger, "steps": steps,
            "confidence": 0.45, "evidence": [f"task module detected: {parsed.path}"],
            "files": [parsed.path], "trace_truncated": True,
            "route": None,
            "framework": "Celery" if content and "celery" in content.lower() else None,
            "scope": "test" if is_test_path(parsed.path) else ("example" if is_example_path(parsed.path) else "application"),
            "scope_note": ("Background module lives in an example application bundled with this repository"
                           if is_example_path(parsed.path) else None),
        })
    return workflows[:6]


def trace_symbol(tracer: WorkflowTracer, path: str, symbol_name: str) -> dict | None:
    """Trace a single symbol outward - used by the AI chat for 'how does X work'."""
    symbol = tracer.symbol_in_file(path, symbol_name)
    if symbol is None:
        return None
    record = {"method": "CALL", "path": f"{symbol_name}", "handler": symbol_name, "file_path": path,
              "line": symbol.start_line, "framework": None, "auth_required": False}
    return _trace_endpoint(tracer, record)


def find_entrypoints_for(tracer: WorkflowTracer, path: str, symbol_name: str, limit: int = 6) -> list[dict]:
    """Endpoints whose traced cone contains (path, symbol_name)."""
    endpoints: list[dict] = []
    for parsed in tracer.files.values():
        for route in parsed.routes:
            endpoints.append({"method": route.method, "path": route.path, "handler": route.handler,
                              "file_path": parsed.path, "line": route.line, "framework": route.framework,
                              "auth_required": route.auth_hint})
    hits = []
    for record in endpoints[:80]:
        workflow = _trace_endpoint(tracer, record, scope=scope)
        if not workflow:
            continue
        for step in workflow["steps"]:
            if step.get("file_path") == path and (step.get("symbol") == symbol_name or not symbol_name):
                hits.append({"trigger": workflow["trigger"], "name": workflow["name"],
                             "file_path": record["file_path"], "confidence": workflow["confidence"]})
                break
        if len(hits) >= limit:
            break
    return hits
