"""Database-backed call tracing.

At query time the parsed sources are no longer in memory, so traces are
reconstructed from persisted artefacts: the symbol table (with call sites) and
the call edges of the dependency graph. Every hop carries the evidence that
produced it, and a hop that cannot be resolved simply ends the trace.
"""

from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.tables import GraphEdgeRecord, SymbolRecord

MAX_DEPTH = 6
MAX_STEPS = 12


class DbTracer:
    def __init__(self, session: Session, analysis_id: str):
        self.session = session
        self.analysis_id = analysis_id
        self._symbols_by_path: dict[str, list[SymbolRecord]] = defaultdict(list)
        self._call_edges: dict[str, list[tuple[str, str, str]]] = defaultdict(list)  # path -> [(target, caller, callee)]
        self._layer_cache: dict[str, str] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        rows = self.session.execute(
            select(SymbolRecord).where(SymbolRecord.analysis_id == self.analysis_id)
        ).scalars().all()
        for row in rows:
            self._symbols_by_path[row.path].append(row)
        edges = self.session.execute(
            select(GraphEdgeRecord).where(GraphEdgeRecord.analysis_id == self.analysis_id,
                                          GraphEdgeRecord.kind == "call")
        ).scalars().all()
        for edge in edges:
            for entry in edge.symbols or []:
                if " -> " in entry:
                    caller, callee = entry.split(" -> ", 1)
                    self._call_edges[edge.source].append((edge.target, caller.strip(), callee.strip()))
        self._loaded = True

    # ------------------------------------------------------------------ api
    def symbol(self, path: str, name: str) -> SymbolRecord | None:
        self.load()
        for row in self._symbols_by_path.get(path, []):
            if row.name == name:
                return row
        return None

    def find_symbols(self, name: str, limit: int = 12) -> list[SymbolRecord]:
        self.load()
        out: list[SymbolRecord] = []
        for path, rows in self._symbols_by_path.items():
            for row in rows:
                if row.name == name:
                    out.append(row)
                    if len(out) >= limit:
                        return out
        return out

    def resolve_call(self, path: str, caller: str, call_name: str, qualifier: str | None) -> tuple[str, str] | None:
        self.load()
        # 1. explicit call edge recorded during analysis
        for target, edge_caller, callee in self._call_edges.get(path, []):
            if edge_caller != caller:
                continue
            if callee == call_name or callee.endswith("." + call_name) or callee == f"{qualifier}.{call_name}":
                if self.symbol(target, call_name):
                    return target, call_name
        # 2. imported symbol defined in a single file
        candidates = self.find_symbols(call_name, limit=6)
        if qualifier:
            receiver = qualifier.split(".")[-1]
            for candidate in candidates:
                if receiver and receiver.lower() == candidate.parent and candidate.parent:
                    return candidate.path, candidate.name
        if len(candidates) == 1:
            return candidates[0].path, candidates[0].name
        for candidate in candidates:
            if candidate.kind in {"function", "method"} and candidate.path != path:
                return candidate.path, candidate.name
        return None

    def trace(self, path: str, symbol_name: str) -> dict:
        self.load()
        symbol = self.symbol(path, symbol_name)
        if symbol is None:
            return {"steps": [], "truncated": False, "evidence": [], "files": []}
        steps = [_step(symbol, kind=_kind_for(symbol), detail=symbol.signature or "")]
        visited = {(path, symbol_name)}
        queue: list[tuple[SymbolRecord, int]] = [(symbol, 1)]
        truncated = False
        while queue:
            current, depth = queue.pop(0)
            if depth > MAX_DEPTH or len(steps) >= MAX_STEPS:
                truncated = True
                break
            for call in current.calls or []:
                resolved = self.resolve_call(current.path, current.name, call.get("name") or "",
                                             call.get("qualifier"))
                if not resolved:
                    continue
                target_path, target_name = resolved
                if (target_path, target_name) in visited:
                    continue
                if len(visited) > 30:
                    truncated = True
                    break
                visited.add((target_path, target_name))
                target = self.symbol(target_path, target_name)
                if target is None:
                    continue
                steps.append(_step(target, kind=_kind_for(target),
                                   detail=f"called as `{call.get('full') or target_name}` from "
                                          f"{current.path}:{call.get('line')}"))
                queue.append((target, depth + 1))
        return {
            "steps": steps,
            "truncated": truncated,
            "evidence": [f"{step['label']} at {step['file_path']}:{step.get('line')}" for step in steps],
            "files": sorted({step["file_path"] for step in steps}),
        }


def _kind_for(symbol: SymbolRecord) -> str:
    path = symbol.path.lower()
    layer = "other"
    for marker, value in (("service", "service"), ("repo", "repository"), ("route", "controller"),
                          ("controller", "controller"), ("handler", "controller"), ("model", "repository"),
                          ("middleware", "middleware"), ("component", "ui"), ("page", "ui"), ("hook", "ui")):
        if marker in path:
            layer = value
            break
    if symbol.kind == "class":
        return "repository" if layer in {"repository", "other"} else layer
    return layer if layer != "other" else "service"


def _step(symbol: SymbolRecord, *, kind: str, detail: str) -> dict:
    return {
        "id": symbol.id,
        "label": symbol.name,
        "kind": kind,
        "file_path": symbol.path,
        "line": symbol.start_line,
        "symbol": symbol.name,
        "detail": detail[:200] if detail else None,
        "evidence": f"defined at {symbol.path}:{symbol.start_line}",
        "signature": symbol.signature,
        "docstring": symbol.docstring,
    }


def score_name_match(name: str, tokens: set[str]) -> float:
    """How well a symbol name matches the question tokens."""
    lowered = name.lower()
    if not tokens:
        return 0.0
    if lowered in tokens:
        return 1.0
    best = 0.0
    for token in tokens:
        if len(token) < 3:
            continue
        if token in lowered:
            best = max(best, 0.7)
        else:
            # crude camel/snake similarity
            parts = {part for part in lowered.replace("_", " ").split()}
            if token in parts:
                best = max(best, 0.6)
    if best == 0.0:
        # shared prefix heuristic
        for token in tokens:
            if len(token) >= 4 and lowered.startswith(token[:4]):
                best = max(best, 0.3)
    return best


def word_tokens(text: str) -> set[str]:
    import re
    return {token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text or "")}
