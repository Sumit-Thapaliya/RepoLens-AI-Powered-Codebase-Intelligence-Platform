"""Turn parsed routes into API endpoint records.

Two things happen here that make the endpoint list faithful to the running app:

1. **URL reconstruction** - routers declare a local prefix (``APIRouter(prefix=...)``)
   and are mounted elsewhere (``app.include_router(users.router, prefix="/users")``,
   ``app.use('/api/users', usersRouter)``). Those fragments are composed across
   files so the endpoint shows the URL a client would actually call.
2. **Service attribution** - the first call from the handler into a
   service/repository/util module is recorded as the service, with the call site
   as evidence.
"""

from __future__ import annotations

import posixpath
from collections import defaultdict

from repolens_parser import ParsedFile
from repolens_parser.python_analyzer import is_test_path
from repolens_shared.utils import is_example_path, stable_id

from repolens_graph import GraphResult, WorkflowTracer

MAX_MOUNT_DEPTH = 6


def _join_prefix(*parts: str) -> str:
    segments: list[str] = []
    for part in parts:
        if not part:
            continue
        segments.extend(segment for segment in part.split("/") if segment)
    if not segments:
        return ""
    return "/" + "/".join(segments)


def resolve_router_prefixes(parsed_files: list[ParsedFile]) -> dict[tuple[str, str], str]:
    """Compose full URL prefixes for every (file, router object) pair."""
    files = {parsed.path: parsed for parsed in parsed_files}
    own: dict[tuple[str, str], str] = {}
    mounts: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)

    for parsed in parsed_files:
        for name, prefix in (parsed.router_prefixes or {}).items():
            own[(parsed.path, name)] = prefix
        for include in parsed.router_includes or []:
            target = include.get("target") or ""
            if not target or target == "(middleware)":
                continue
            prefix = include.get("prefix") or ""
            parent_object = include.get("parent") or ""
            base, _, attr = target.rpartition(".")
            target_key: tuple[str, str] | None = None

            if not base and (parsed.path, attr) in own:
                target_key = (parsed.path, attr)
            elif base and (parsed.path, base) in own and (parsed.path, attr) not in own:
                # ``app.include_router(api_router, ...)`` inside the same module
                target_key = (parsed.path, base) if attr != base else None
            if target_key is None:
                for candidate in [c for c in (base, attr or target) if c]:
                    import_entry = next((imp for imp in parsed.imports if candidate in imp.names and imp.resolved_path), None)
                    if import_entry is None or import_entry.resolved_path not in files:
                        continue
                    child = files[import_entry.resolved_path]
                    child_routers = child.router_prefixes or {}
                    if attr and attr in child_routers:
                        target_key = (child.path, attr)
                    elif len(child_routers) == 1:
                        target_key = (child.path, next(iter(child_routers)))
                    elif child.routes:
                        target_key = (child.path, attr or "router")
                    if target_key:
                        break
            if target_key:
                mounts[target_key].append((parsed.path, parent_object, prefix))

    memo: dict[tuple[str, str], str] = {}

    def total(key: tuple[str, str], depth: int = 0) -> str:
        if key in memo:
            return memo[key]
        if depth > MAX_MOUNT_DEPTH:
            return own.get(key, "")
        memo[key] = own.get(key, "")  # cycle guard: value replaced below if a longer chain exists
        best_parent = ""
        for parent_file, parent_object, prefix in mounts.get(key, []):
            parent_key = (parent_file, parent_object) if parent_object and (parent_file, parent_object) in own else None
            parent_prefix = total(parent_key, depth + 1) if parent_key and parent_key != key else ""
            candidate = _join_prefix(parent_prefix, prefix)
            if len(candidate) > len(best_parent):
                best_parent = candidate
        result = _join_prefix(best_parent, own.get(key, ""))
        memo[key] = result
        return result

    return {key: total(key) for key in own}


def build_endpoints(parsed_files: list[ParsedFile], graph: GraphResult, scope: str = "") -> list[dict]:
    """``scope`` is the analysis id: record ids are unique per analysis so the
    same repository can be analysed repeatedly without key collisions."""
    files = {parsed.path: parsed for parsed in parsed_files}
    records: list[dict] = []
    handler_index: dict[str, list[str]] = defaultdict(list)
    for parsed in parsed_files:
        for symbol in parsed.symbols:
            handler_index[symbol.name].append(parsed.path)

    tracer = WorkflowTracer(parsed_files, graph)
    prefixes = resolve_router_prefixes(parsed_files)

    for parsed in parsed_files:
        for route in parsed.routes:
            prefix = ""
            if route.router_object:
                prefix = prefixes.get((parsed.path, route.router_object), "")
            full_path = _join_prefix(prefix, route.path) or "/"
            if route.framework in {"Next.js App Router", "Next.js Pages Router"}:
                full_path = route.path
            service = _find_service(tracer, parsed.path, route.handler)

            evidence = [f"declared in {parsed.path}:{route.line}"]
            if prefix:
                evidence.append(f"mounted under `{prefix}` (router `{route.router_object}`)")
            if route.decorators:
                evidence.append("decorators: " + ", ".join(route.decorators[:4]))
            if route.framework:
                evidence.append(f"framework: {route.framework}")
            if route.handler and handler_index.get(route.handler) and parsed.path not in handler_index[route.handler]:
                evidence.append(f"handler `{route.handler}` is defined in {handler_index[route.handler][0]}")
            if service:
                evidence.append(f"handler calls into {service}")

            records.append({
                "id": stable_id("endpoint", scope, parsed.path, route.method, full_path, route.line),
                "method": route.method or "ANY",
                "path": full_path,
                "handler": route.handler,
                "file_path": parsed.path,
                "line": route.line,
                "framework": route.framework,
                "controller": route.controller or (posixpath.basename(parsed.path).rsplit(".", 1)[0]),
                "service": service,
                "auth_required": bool(route.auth_hint) or None,
                "evidence": evidence,
                "notes": route.notes,
                "request_model": route.request_model,
                "response_model": route.response_model,
                "local_path": route.path,
            })

    for record in records:
        record["is_test"] = is_test_path(record["file_path"])
        record["is_example"] = is_example_path(record["file_path"])

    # One row per (method, path). When the same URL is declared in several files
    # (an example app, a test app, a doc snippet) the application's own
    # declaration wins, and the others are kept in `declarations` so the UI can
    # show them instead of pretending they do not exist.
    def declaration_rank(item: dict) -> tuple:
        return (
            1 if item["is_test"] else 0,
            1 if item["is_example"] else 0,
            0 if item["framework"] else 1,
            len(item["file_path"]),
            item["file_path"],
            item["line"] or 0,
        )

    unique: dict[tuple[str, str], dict] = {}
    for record in sorted(records, key=declaration_rank):
        key = (record["method"], record["path"])
        primary = unique.get(key)
        if primary is None:
            record["declarations"] = [{
                "path": record["file_path"], "line": record["line"], "framework": record["framework"],
                "handler": record["handler"], "is_example": record["is_example"], "is_test": record["is_test"],
            }]
            unique[key] = record
            continue
        if any(d["path"] == record["file_path"] and d["line"] == record["line"] for d in primary["declarations"]):
            continue
        kind = "test" if record["is_test"] else ("example" if record["is_example"] else "source")
        primary["declarations"].append({
            "path": record["file_path"], "line": record["line"], "framework": record["framework"],
            "handler": record["handler"], "is_example": record["is_example"], "is_test": record["is_test"],
        })
        primary["evidence"].append(f"also declared in {record['file_path']}:{record['line']} ({kind})")
    return sorted(unique.values(), key=lambda item: (item["path"], item["method"]))


LAYER_PRIORITY = ["service", "repository", "middleware", "util"]


def _find_service(tracer: WorkflowTracer, path: str, handler: str | None) -> str | None:
    """The module the handler delegates to, with the call site as evidence.

    Pydantic/SQLModel classes and other data containers are skipped - they are
    values passed around, not the service doing the work.
    """
    if not handler:
        return None
    symbol = tracer.symbol_in_file(path, handler)
    if symbol is None:
        return None
    best: tuple[int, str] | None = None
    for call in symbol.calls[:40]:
        resolved = tracer.resolve_callee(path, call)
        if not resolved:
            continue
        target_path, target_name = resolved
        if target_path == path:
            continue
        target_symbol = tracer.symbol_in_file(target_path, target_name)
        if target_symbol is not None and target_symbol.kind in {"class", "interface", "type", "enum"}:
            continue
        layer = tracer.layer_of.get(target_path, "other")
        if layer not in LAYER_PRIORITY:
            continue
        rank = LAYER_PRIORITY.index(layer)
        if best is None or rank < best[0]:
            best = (rank, f"{target_name} ({target_path})")
        if rank == 0:
            break
    return best[1] if best else None


def endpoint_stats(endpoints: list[dict]) -> dict:
    methods: dict[str, int] = defaultdict(int)
    frameworks: dict[str, int] = defaultdict(int)
    for endpoint in endpoints:
        for method in str(endpoint["method"]).split("/"):
            methods[method] += 1
        frameworks[endpoint["framework"] or "unknown"] += 1
    return {
        "total": len(endpoints),
        "methods": dict(sorted(methods.items(), key=lambda item: -item[1])),
        "frameworks": dict(sorted(frameworks.items(), key=lambda item: -item[1])),
        "authenticated": sum(1 for endpoint in endpoints if endpoint.get("auth_required")),
        "from_examples": sum(1 for endpoint in endpoints if endpoint.get("is_example")),
        "from_tests": sum(1 for endpoint in endpoints if endpoint.get("is_test")),
        "declared_in_multiple_places": sum(1 for endpoint in endpoints if len(endpoint.get("declarations") or []) > 1),
    }
