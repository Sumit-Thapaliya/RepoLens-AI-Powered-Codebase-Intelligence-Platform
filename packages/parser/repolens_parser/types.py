"""Data structures produced by the parsers.

Deliberately plain dataclasses: the analyzers persist them, the API serialises
them and the tests assert on them, so they must stay framework free.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Call:
    """A call site, used to trace workflows across files."""

    name: str                      # `login` for `auth.login(...)`
    line: int
    qualifier: str | None = None   # `auth_service` for `self.auth_service.login(...)`
    full: str = ""                 # best-effort dotted path
    receiver: str | None = None    # `self` / class / variable name

    def to_dict(self) -> dict:
        return {"name": self.name, "line": self.line, "qualifier": self.qualifier, "full": self.full or self.name}


@dataclass(slots=True)
class Symbol:
    name: str
    kind: str
    start_line: int
    end_line: int
    params: list[str] = field(default_factory=list)
    signature: str = ""
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    docstring: str | None = None
    complexity: int = 1
    parent: str | None = None
    exported: bool = False
    is_async: bool = False
    calls: list[Call] = field(default_factory=list)
    shingle: str | None = None
    body_lines: int = 0

    @property
    def loc(self) -> int:
        return max(1, self.end_line - self.start_line + 1)


@dataclass(slots=True)
class Import:
    raw: str
    module: str
    line: int
    names: list[str] = field(default_factory=list)
    is_relative: bool = False
    level: int = 0
    package: str | None = None
    resolved_path: str | None = None
    external: bool = True
    kind: str = "import"


@dataclass(slots=True)
class Route:
    method: str
    path: str
    handler: str | None
    line: int
    framework: str | None = None
    auth_hint: bool = False
    decorators: list[str] = field(default_factory=list)
    notes: str | None = None
    request_model: str | None = None
    response_model: str | None = None
    controller: str | None = None
    #: Name of the router/app object the route is attached to (`router`, `app`, ...).
    #: Used to reconstruct mounted URL prefixes across files.
    router_object: str | None = None


@dataclass(slots=True)
class Model:
    name: str
    line: int
    orm: str | None = None
    table: str | None = None
    fields: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    source: str = "code"


@dataclass(slots=True)
class Query:
    kind: str
    line: int
    table: str | None = None
    orm: str | None = None
    snippet: str = ""


@dataclass(slots=True)
class ParsedFile:
    path: str
    language: str
    loc: int = 0
    size: int = 0
    parse_error: str | None = None
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    models: list[Model] = field(default_factory=list)
    queries: list[Query] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    docstring: str | None = None
    warnings: list[str] = field(default_factory=list)
    #: TS/JS files that Next.js treats as API routes carry their path here.
    framework_hints: list[str] = field(default_factory=list)
    #: router object name -> own URL prefix  (``{"router": "/users"}``)
    router_prefixes: dict[str, str] = field(default_factory=dict)
    #: mounts declared in this file: ``[{"target": "users.router", "prefix": "/v1"}]``
    router_includes: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.parse_error is None
