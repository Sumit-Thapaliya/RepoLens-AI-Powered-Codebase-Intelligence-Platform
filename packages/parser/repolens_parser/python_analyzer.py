"""Python analysis built on the standard library ``ast`` module.

The stdlib parser gives us exact symbols, docstrings, decorators and call sites
without shipping a grammar, so Python gets the deepest analysis of any language
RepoLens supports.
"""

from __future__ import annotations

import ast
import re
from typing import Iterable

from repolens_shared.constants import DOC_LANGUAGES
from repolens_shared.utils import language_for_path, shingle_hash, truncate

from .types import Call, Import, Model, ParsedFile, Query, Route, Symbol

# --------------------------------------------------------------------------- #
# Framework vocabulary
# --------------------------------------------------------------------------- #

HTTP_DECORATORS: set[str] = {
    "get", "post", "put", "patch", "delete", "head", "options", "trace",
    "route", "api_route", "websocket", "websocket_route",
}
FASTAPI_ROUTER_OBJECTS = {"app", "router", "api", "api_router", "fastapi", "application"}

AUTH_HINTS = (
    "login_required", "requires_auth", "jwt_required", "auth_required", "permission_classes",
    "is_authenticated", "current_user", "get_current_user", "requires_permissions", "authenticated",
)

ORM_BASES = {
    "Base", "Model", "DeclarativeBase", "db.Model", "BaseModel", "models.Model", "SQLModel",
    "Document", "EmbeddedDocument", "AsyncAttrs", "Table",
}

DJANGO_FIELD_PREFIX = "models."
SQLALCHEMY_FIELD_FUNCS = {
    "Column", "mapped_column", "relationship", "ForeignKey", "Integer", "String", "Text",
    "Boolean", "DateTime", "Float", "Numeric", "Date", "Time", "JSON", "JSONB", "UUID",
    "LargeBinary", "Enum", "ARRAY", "BigInteger", "SmallInteger", "Unicode", "UnicodeText",
    "Index", "UniqueConstraint", "PrimaryKeyConstraint", "CheckConstraint", "ForeignKeyConstraint",
    "Field", "relationship", "ColumnProperty", "deferred",
}
DJANGO_MANAGER_METHODS = {
    "filter": "select", "get": "select", "all": "select", "first": "select", "last": "select",
    "values": "select", "values_list": "select", "count": "select", "exists": "select",
    "select_related": "select", "prefetch_related": "select", "annotate": "select",
    "create": "insert", "bulk_create": "insert", "get_or_create": "insert", "update_or_create": "upsert",
    "update": "update", "bulk_update": "update",
    "delete": "delete",
}
SQLALCHEMY_SESSION_METHODS = {
    "query": "select", "execute": "raw", "scalars": "select", "get": "select", "scalar": "select",
    "add": "insert", "add_all": "insert", "merge": "upsert", "delete": "delete",
    "commit": "unknown", "refresh": "select", "exec": "raw", "get_one": "select",
}

_COMPLEXITY_NODES = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.ExceptHandler, ast.With, ast.AsyncWith,
    ast.BoolOp, ast.IfExp, ast.comprehension, ast.Match,
)

_SECRET_RE = re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|private[_-]?key|access[_-]?key)\b\s*[:=]\s*['\"][^'\"]{6,}['\"]")
_SQL_RE = re.compile(r"\b(select|insert\s+into|update|delete\s+from)\b", re.IGNORECASE)
_SQL_STRING_RE = re.compile(r"(?is)^\s*(select|insert|update|delete|create\s+table|alter\s+table|drop\s+table)\b")

#: Directory segment -> architectural layer. Shared with the JS analyzer.
#: Strong entrypoint file stems (checked before directory names).
ENTRYPOINT_STEMS: set[str] = {
    "main", "manage", "wsgi", "asgi", "server", "cli", "__main__", "run", "start", "worker",
    "celery_app", "bootstrap",
}
#: Generic stems that only become entrypoints when no directory matched a layer.
WEAK_ENTRYPOINT_STEMS: set[str] = {"app", "index"}

LAYER_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("route", ("routes", "route", "routers", "router", "urls", "api", "endpoints", "controllers", "controller", "handlers", "handler", "views", "view", "pages", "app")),
    ("service", ("services", "service", "usecases", "use_cases", "domain", "business", "managers", "manager")),
    ("repository", ("repositories", "repository", "repos", "repo", "dao", "crud", "store", "stores", "models", "model", "entities", "entity", "schema", "schemas", "db", "database", "persistence", "migrations")),
    ("middleware", ("middleware", "middlewares", "guards", "interceptors", "filters", "security", "auth", "permissions")),
    ("ui", ("components", "component", "ui", "widgets", "screens", "layouts", "hooks", "styles", "templates", "static", "assets")),
    ("config", ("config", "configs", "settings", "env", "constants", "infra", "infrastructure", "deploy", "deployment", ".github", "docker", "scripts", "ci")),
    ("test", ("test", "tests", "__tests__", "spec", "specs", "e2e", "fixtures", "testing")),
    ("util", ("utils", "util", "helpers", "helper", "lib", "libs", "common", "shared", "core", "tools", "support")),
]


def layer_for_path(path: str, is_test: bool = False) -> str:
    """Classify a file into an architectural layer.

    Priority order (most specific first):

    1. the file name - ``crud.py`` is data access, ``main.py`` is an entrypoint
    2. the directories, from the deepest one outwards - ``.../routes/users.py``
       is a route even though the file is called ``users``

    Everything is heuristic; the UI labels layers as "inferred from naming".
    """
    lowered = path.lower()
    parts = [part for part in re.split(r"[/\\]", lowered) if part]
    if not parts:
        return "other"
    name = parts[-1]
    stem = re.sub(r"[^a-z0-9_]", "", name.split(".")[0])

    if is_test or re.match(r"^(test_|conftest)", name) or re.search(r"(_test|\.test|\.spec|\.test_)\.", name):
        return "test"
    if language_for_path(path) in DOC_LANGUAGES:
        # Prose is not an architectural layer: docs must never be mistaken for
        # UI ("static", "assets") or a service module.
        return "docs"
    if stem in ENTRYPOINT_STEMS:
        return "entrypoint"
    for layer, keywords in LAYER_RULES:
        if layer == "test":
            continue
        if stem in keywords:
            return layer
    for segment in reversed([re.sub(r"[^a-z0-9_]", "", part.split(".")[0]) for part in parts[:-1]]):
        if not segment:
            continue
        for layer, keywords in LAYER_RULES:
            if layer == "test":
                continue
            if segment in keywords:
                return layer
    if stem in WEAK_ENTRYPOINT_STEMS:
        return "entrypoint"
    return "other"


def is_test_path(path: str) -> bool:
    lowered = "/" + path.lower().lstrip("/")
    if re.search(r"(^|/)(tests?|__tests__|specs?|e2e)/", lowered):
        return True
    name = lowered.rsplit("/", 1)[-1]
    return bool(re.match(r"(test_|conftest)", name) or re.search(r"(_test|\.test|\.spec)\.", name))


def is_entrypoint(path: str, language: str) -> bool:
    name = path.lower().rsplit("/", 1)[-1]
    if language == "python":
        return name in {"main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "server.py", "__main__.py", "cli.py", "run.py"}
    if language in {"javascript", "typescript", "tsx", "jsx"}:
        return name in {"index.ts", "index.js", "server.ts", "server.js", "main.ts", "main.js", "app.ts", "app.js"}
    if language == "go":
        return name == "main.go"
    if language == "java":
        return bool(re.search(r"(application|main)\.java$", name))
    return False


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _normalize_prefix(prefix: str) -> str:
    prefix = (prefix or "").strip()
    if not prefix:
        return ""
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    return prefix.rstrip("/")


def dotted_name(node: ast.AST | None) -> str:
    """Best-effort dotted path for an attribute/name expression."""
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    if isinstance(node, ast.Subscript):
        return dotted_name(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def call_targets(node: ast.AST) -> list[str]:
    """Flatten decorator arguments, e.g. ``Depends(get_current_user)``."""
    targets: list[str] = []
    if isinstance(node, ast.Call):
        targets.append(dotted_name(node.func))
        for arg in node.args:
            targets.extend(call_targets(arg))
        for kw in node.keywords:
            targets.extend(call_targets(kw.value))
    elif isinstance(node, ast.Attribute):
        targets.append(dotted_name(node))
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for element in node.elts:
            targets.extend(call_targets(element))
    return [t for t in targets if t]


def decorator_names(decorator_list: Iterable[ast.expr]) -> list[str]:
    names: list[str] = []
    for decorator in decorator_list:
        if isinstance(decorator, ast.Call):
            names.append(dotted_name(decorator.func))
        else:
            names.append(dotted_name(decorator))
    return [n for n in names if n]


def decorator_has_auth(decorator_list: Iterable[ast.expr]) -> bool:
    for decorator in decorator_list:
        for target in call_targets(decorator) + decorator_names([decorator]):
            lowered = target.lower()
            if any(hint in lowered for hint in AUTH_HINTS):
                return True
    return False


def first_string_arg(node: ast.Call) -> str | None:
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def compute_complexity(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _COMPLEXITY_NODES):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += max(0, len(child.values) - 1)
    return score


def collect_calls(node: ast.AST, limit: int = 400) -> list[Call]:
    calls: list[Call] = []
    seen: set[tuple[str, int]] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        full = dotted_name(child.func)
        if not full:
            continue
        parts = full.split(".")
        name = parts[-1]
        qualifier = ".".join(parts[:-1]) or None
        key = (full, child.lineno)
        if key in seen:
            continue
        seen.add(key)
        receiver = parts[0] if len(parts) > 1 else None
        calls.append(Call(name=name, line=child.lineno, qualifier=qualifier, full=full, receiver=receiver))
        if len(calls) >= limit:
            break
    return calls


def is_sql_literal(value: str) -> bool:
    return bool(_SQL_STRING_RE.match(value or ""))


# --------------------------------------------------------------------------- #
# Analyzer
# --------------------------------------------------------------------------- #

class PythonAnalyzer:
    language = "python"

    def __init__(self, source: str, path: str):
        self.source = source
        self.path = path
        self.lines = source.splitlines()
        self.file_name = path.rsplit("/", 1)[-1]
        self.framework_hints: set[str] = set()
        self.auth_aliases: set[str] = set()

    # -- public -------------------------------------------------------------
    def analyze(self) -> ParsedFile:
        loc = len(self.lines)
        parsed = ParsedFile(path=self.path, language=self.language, loc=loc, size=len(self.source.encode("utf-8")))
        try:
            tree = ast.parse(self.source, filename=self.path)
        except SyntaxError as exc:
            parsed.parse_error = f"SyntaxError: {exc.msg} (line {exc.lineno})"
            return parsed
        except (ValueError, RecursionError, MemoryError) as exc:
            parsed.parse_error = f"{type(exc).__name__}: {exc}"
            return parsed

        parsed.docstring = ast.get_docstring(tree)
        self._collect_auth_aliases(tree)
        self._walk_module(tree, parsed)
        self._detect_django_urls(tree, parsed)
        self._detect_sqlalchemy_models(tree, parsed)
        parsed.framework_hints = sorted(self.framework_hints)
        parsed.exports = sorted({s.name for s in parsed.symbols if not s.name.startswith("_")})
        return parsed

    # -- module level -------------------------------------------------------
    def _walk_module(self, tree: ast.Module, parsed: ParsedFile) -> None:
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parsed.imports.append(
                        Import(raw=f"import {alias.name}", module=alias.name, line=node.lineno,
                               names=[alias.asname or alias.name.split(".")[0]])
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [alias.name for alias in node.names]
                parsed.imports.append(
                    Import(
                        raw=f"from {'.' * (node.level or 0)}{module} import {', '.join(names)}",
                        module=module, line=node.lineno, names=names,
                        is_relative=bool(node.level), level=node.level or 0,
                        package=self._package_of_file(),
                    )
                )
                self._note_framework_from_module(module)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parsed.symbols.append(self._function_symbol(node, parent=None))
                self._detect_route(node, parsed, controller=None)
            elif isinstance(node, ast.ClassDef):
                parsed.symbols.append(self._class_symbol(node))
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        parsed.symbols.append(self._function_symbol(item, parent=node.name))
                        self._detect_route(item, parsed, controller=node.name)
            elif isinstance(node, ast.Assign):
                self._maybe_module_constant(node, parsed)
                self._maybe_route_assignment(node, parsed)
            elif isinstance(node, ast.Expr):
                self._maybe_include_router(node, parsed)

    def _package_of_file(self) -> str:
        parts = self.path.split("/")
        return "/".join(parts[:-1])

    def _note_framework_from_module(self, module: str) -> None:
        lowered = (module or "").lower()
        for marker, hint in (
            ("fastapi", "FastAPI"), ("flask", "Flask"), ("django", "Django"), ("rest_framework", "Django REST Framework"),
            ("sqlalchemy", "SQLAlchemy"), ("pydantic", "Pydantic"), ("celery", "Celery"), ("starlette", "Starlette"),
            ("tortoise", "Tortoise ORM"), ("peewee", "Peewee"), ("mongoengine", "MongoEngine"), ("boto3", "AWS SDK"),
        ):
            if lowered.startswith(marker) or marker in lowered:
                self.framework_hints.add(hint)

    def _maybe_module_constant(self, node: ast.Assign, parsed: ParsedFile) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                value = node.value
                if isinstance(value, (ast.Constant, ast.List, ast.Tuple, ast.Dict)):
                    parsed.symbols.append(
                        Symbol(
                            name=target.id, kind="constant", start_line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
                            signature=f"{target.id} = {truncate(repr(getattr(value, 'value', '...')), 60)}",
                            docstring=None, complexity=1,
                        )
                    )

    def _maybe_route_assignment(self, node: ast.Assign, parsed: ParsedFile) -> None:
        """Captures ``router = APIRouter(prefix="/users")``, Blueprints and FastAPI apps,
        including the URL prefix each router declares."""
        value = node.value
        if not isinstance(value, ast.Call):
            return
        func_name = dotted_name(value.func)
        short = func_name.split(".")[-1]
        if short not in {"APIRouter", "Blueprint", "FastAPI", "Flask", "Router"}:
            return
        self.framework_hints.add("FastAPI" if short in {"APIRouter", "FastAPI"} else "Flask")
        prefix = ""
        for kw in value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                prefix = kw.value.value
        if not prefix and short == "Blueprint":
            prefix = first_string_arg(value) or ""
        for target in node.targets:
            if isinstance(target, ast.Name):
                parsed.router_prefixes[target.id] = _normalize_prefix(prefix)

    def _maybe_include_router(self, node: ast.Expr, parsed: ParsedFile) -> None:
        """``app.include_router(users.router, prefix="/users")`` - the mount table
        that turns route-local paths into real URLs."""
        if not isinstance(node.value, ast.Call):
            return
        call = node.value
        func = dotted_name(call.func)
        if not func.endswith("include_router") and not func.endswith("register_blueprint"):
            return
        prefix = ""
        for kw in call.keywords:
            if kw.arg in {"prefix", "url_prefix"} and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                prefix = str(kw.value.value)
        if func.endswith("register_blueprint") and not prefix:
            prefix = first_string_arg(call) or ""
            parsed.router_includes.append({"target": None, "prefix": _normalize_prefix(prefix),
                                           "source": "blueprint"})
            return
        if not call.args:
            return
        target = dotted_name(call.args[0])
        if not target:
            return
        parsed.router_includes.append({"target": target, "prefix": _normalize_prefix(prefix),
                                       "parent": func.rsplit(".", 1)[0] if "." in func else None})

    # -- symbols ------------------------------------------------------------
    def _class_symbol(self, node: ast.ClassDef) -> Symbol:
        doc = ast.get_docstring(node)
        bases = [dotted_name(base) for base in node.bases if dotted_name(base)]
        decorators = decorator_names(node.decorator_list)
        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        fields = self._class_fields(node)
        signature = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
        if fields:
            signature += f"  # fields: {', '.join(f['name'] for f in fields[:8])}"
        return Symbol(
            name=node.name, kind="class", start_line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
            params=[m.name for m in methods], signature=signature, decorators=decorators, bases=bases,
            docstring=truncate(doc, 600) if doc else None, complexity=sum(compute_complexity(m) for m in methods) or 1,
            calls=[], is_async=False, shingle=shingle_hash(self._slice(node)),
        )

    def _class_fields(self, node: ast.ClassDef) -> list[dict]:
        fields: list[dict] = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                annotation = dotted_name(item.annotation)
                fields.append({"name": item.target.id, "type": annotation, "line": item.lineno})
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        fields.append({"name": target.id, "type": type(item.value).__name__, "line": item.lineno})
        return fields[:60]

    def _function_symbol(self, node: ast.AST, parent: str | None) -> Symbol:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        is_async = isinstance(node, ast.AsyncFunctionDef)
        params = [a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
        if node.args.vararg:
            params.append("*" + node.args.vararg.arg)
        if node.args.kwarg:
            params.append("**" + node.args.kwarg.arg)
        returns = f" -> {dotted_name(node.returns)}" if node.returns is not None else ""
        signature = f"{'async ' if is_async else ''}def {node.name}({', '.join(params)}){returns}"
        doc = ast.get_docstring(node)
        return Symbol(
            name=node.name, kind="method" if parent else "function",
            start_line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
            params=params, signature=truncate(signature, 300), decorators=decorator_names(node.decorator_list),
            docstring=truncate(doc, 900) if doc else None, complexity=compute_complexity(node),
            parent=parent, is_async=is_async, exported=not node.name.startswith("_"),
            calls=collect_calls(node), shingle=shingle_hash(self._slice(node)),
        )

    def _slice(self, node: ast.AST) -> str:
        start = getattr(node, "lineno", 1) - 1
        end = getattr(node, "end_lineno", start + 1)
        return "\n".join(self.lines[start:end])

    # -- routes -------------------------------------------------------------
    def _detect_route(self, node: ast.AST, parsed: ParsedFile, controller: str | None) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list:
            target = dotted_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
            if not target:
                continue
            parts = target.split(".")
            method = parts[-1].lower()
            obj = parts[0].lower() if len(parts) > 1 else ""
            if method not in HTTP_DECORATORS:
                continue
            if method in {"route", "api_route", "websocket", "websocket_route"} and obj not in FASTAPI_ROUTER_OBJECTS:
                # Flask Blueprint route / Django-ish helper still counts if it takes a path.
                if not isinstance(decorator, ast.Call):
                    continue
            if not isinstance(decorator, ast.Call):
                continue
            route_path = first_string_arg(decorator)
            if not route_path:
                continue
            methods: list[str] = []
            if method in {"route", "api_route"}:
                methods = ["GET"]
                for kw in decorator.keywords:
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
                        methods = [dotted_name(elt).upper() for elt in kw.value.elts if dotted_name(elt)]
            elif method == "websocket":
                methods = ["WS"]
            else:
                methods = [method.upper()]

            request_model = None
            response_model = None
            for kw in decorator.keywords:
                if kw.arg == "response_model":
                    response_model = dotted_name(kw.value)
                if kw.arg in {"request_model", "body", "model"}:
                    request_model = dotted_name(kw.value)
            # Pydantic body parameter (FastAPI: `payload: LoginRequest`).
            for arg in node.args.args:
                annotation = dotted_name(arg.annotation)
                if annotation and annotation[0].isupper() and annotation not in {"Request", "Response"}:
                    request_model = request_model or annotation
                    break

            framework = None
            if obj in {"app", "router", "api_router"}:
                framework = "FastAPI" if "FastAPI" in self.framework_hints else ("Flask" if "Flask" in self.framework_hints else None)
            if method in {"route"} and "Flask" in self.framework_hints:
                framework = "Flask"
            if method == "websocket":
                framework = "FastAPI WebSocket"
            self.framework_hints.add(framework or "Python HTTP framework")

            parsed.routes.append(
                Route(
                    method="/".join(methods), path=route_path, handler=node.name, line=node.lineno,
                    framework=framework, auth_hint=decorator_has_auth(node.decorator_list) or self._param_auth(node, parsed),
                    decorators=decorator_names(node.decorator_list)[:8], controller=controller,
                    request_model=request_model, response_model=response_model,
                    router_object=(parts[0] if len(parts) > 1 else None),
                )
            )

    def _param_auth(self, node: ast.AST, parsed: ParsedFile) -> bool:
        """Detect authentication supplied through parameters rather than decorators.

        Covers ``def read(current_user: CurrentUser)`` where ``CurrentUser`` is an
        ``Annotated[User, Depends(get_current_user)]`` alias, ``Depends(get_current_user)``
        defaults, and ``Security(...)`` markers.
        """
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        arguments = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
        for argument in arguments:
            annotation = dotted_name(argument.annotation)
            if annotation:
                leaf = annotation.split(".")[-1]
                if leaf in self.auth_aliases:
                    return True
                if re.search(r"(?i)(current[_]?user|authenticated[_]?user|current[_]?account|auth[_]?user|logged[_]?in[_]?user)", leaf):
                    return True
            if argument.annotation is not None:
                for target in call_targets(argument.annotation):
                    if any(hint in target.lower() for hint in AUTH_HINTS):
                        return True
        defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
        for default in defaults:
            for target in call_targets(default):
                if any(hint in target.lower() for hint in AUTH_HINTS):
                    return True
        return False

    def _collect_auth_aliases(self, tree: ast.Module) -> None:
        """Module level ``X = Annotated[User, Depends(get_current_user)]`` aliases."""
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                value = node.value
                names = [dotted_name(value)]
                if isinstance(value, ast.Subscript):
                    names.extend(call_targets(value))
                text = " ".join(names).lower()
                if "depends(" in text or "security(" in text:
                    targets = call_targets(value) if isinstance(value, ast.Subscript) else []
                    if any(any(hint in item.lower() for hint in AUTH_HINTS) for item in targets) or \
                            re.search(r"(?i)(current|auth|user|active)", target.id):
                        self.auth_aliases.add(target.id)

    def _detect_django_urls(self, tree: ast.Module, parsed: ParsedFile) -> None:
        """``urls.py`` style routers and DRF ``DefaultRouter().register(...)``."""
        if self.file_name != "urls.py" and "urlpatterns" not in self.source:
            return
        self.framework_hints.add("Django")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = dotted_name(node.func)
                short = func.split(".")[-1]
                if short in {"path", "re_path", "url"} and len(node.args) >= 2:
                    route_path = first_string_arg(node)
                    view = dotted_name(node.args[1]) if len(node.args) > 1 else ""
                    name = None
                    for kw in node.keywords:
                        if kw.arg == "name":
                            name = dotted_name(kw.value)
                    if route_path is not None:
                        handler = view.split(".")[-1] if view else None
                        if handler == "as_view":
                            handler = view.split(".")[-2] if len(view.split(".")) > 1 else handler
                        parsed.routes.append(
                            Route(
                                method="ANY", path=route_path.replace("^", "").replace("$", ""), handler=handler,
                                line=node.lineno, framework="Django URLs", controller=(name or None),
                                notes=f"view: {view}" if view else None,
                            )
                        )
                if short == "register" and len(node.args) >= 2:
                    prefix = first_string_arg(node)
                    viewset = dotted_name(node.args[1])
                    if prefix is not None:
                        self.framework_hints.add("Django REST Framework")
                        parsed.routes.append(
                            Route(
                                method="ANY", path=f"/{prefix.strip('/')}", handler=viewset.split(".")[-1],
                                line=node.lineno, framework="DRF Router",
                                notes="RESTful ViewSet - method set derived from the viewset class",
                            )
                        )

    # -- ORM ----------------------------------------------------------------
    def _detect_sqlalchemy_models(self, tree: ast.Module, parsed: ParsedFile) -> None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [dotted_name(base) for base in node.bases]
            base_names = {b.split(".")[-1] for b in bases}
            is_model = bool(base_names & ORM_BASES) or any(
                b.endswith(("Base", "Model")) and b not in {"BaseModel"} for b in bases
            )
            table_name = None
            fields: list[dict] = []
            relationships: list[dict] = []
            orm = None

            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "__tablename__" and isinstance(item.value, ast.Constant):
                            table_name = str(item.value.value)
                field = self._orm_field(item)
                if field:
                    fields.append(field)
                    if field.get("foreign_key"):
                        target_table, _, target_col = field["foreign_key"].partition(".")
                        relationships.append({
                            "kind": "foreign_key", "name": field["name"], "field": field["name"],
                            "target": target_table, "target_field": target_col or "id",
                        })
                    if field.get("relation_target"):
                        relationships.append({
                            "kind": field.get("relation_kind", "relationship"), "name": field["name"],
                            "field": field["name"], "target": field["relation_target"],
                        })

            if base_names & {"Model"} and any(f.get("orm") == "Django ORM" for f in fields):
                orm = "Django ORM"
            elif fields and any(f.get("orm") == "SQLAlchemy" for f in fields):
                orm = "SQLAlchemy"
            elif base_names & {"Document", "EmbeddedDocument"}:
                orm = "MongoEngine"
            elif any(b.split(".")[-1] == "SQLModel" for b in bases):
                orm = "SQLModel"

            if orm is None and is_model:
                orm = "ORM model"
            if orm is None:
                continue
            parsed.models.append(
                Model(name=node.name, line=node.lineno, orm=orm,
                      table=table_name or self._default_table(node.name, orm),
                      fields=fields[:80], relationships=relationships, bases=bases)
            )
            self.framework_hints.add(orm)

    @staticmethod
    def _default_table(class_name: str, orm: str) -> str | None:
        if orm not in {"Django ORM", "SQLAlchemy", "SQLModel", "ORM model"}:
            return None
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
        if orm == "Django ORM":
            return snake if class_name != class_name.lower() else snake
        return f"{snake}s" if not snake.endswith("s") else snake

    def _orm_field(self, item: ast.stmt) -> dict | None:
        name = None
        annotation = None
        value = None
        line = getattr(item, "lineno", 0)
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            name, annotation, value = item.target.id, dotted_name(item.annotation), item.value
        elif isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
            name, value = item.targets[0].id, item.value
        if not name or value is None:
            return None

        func = dotted_name(value.func) if isinstance(value, ast.Call) else ""
        short = func.split(".")[-1]
        is_django = func.startswith(DJANGO_FIELD_PREFIX)
        if not is_django and short not in SQLALCHEMY_FIELD_FUNCS and annotation in {None, ""}:
            return None
        if short in {"Index", "UniqueConstraint", "CheckConstraint", "declared_attr"}:
            return None

        field: dict = {"name": name, "line": line, "type": self._annotation_label(annotation) or short or "unknown"}
        field["nullable"] = True
        args = [a for a in getattr(value, "args", [])]
        for arg in args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if short == "ForeignKey":
                    field["foreign_key"] = arg.value
                elif short in {"Column", "mapped_column"} and field.get("type") in {"unknown", None}:
                    field["type"] = arg.value
                elif short == "relationship":
                    field["relation_target"] = arg.value.split(".")[-1]
                    field["relation_kind"] = "relationship"
        for kw in getattr(value, "keywords", []):
            if kw.arg == "primary_key" and self._is_true(kw.value):
                field["primary_key"] = True
                field["nullable"] = False
            if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
                field["nullable"] = bool(kw.value.value)
            if kw.arg == "unique" and self._is_true(kw.value):
                field["unique"] = True
            if kw.arg == "default" and isinstance(kw.value, (ast.Constant, ast.Name)):
                field["default"] = dotted_name(kw.value) or repr(getattr(kw.value, "value", None))
            if kw.arg in {"foreign_key", "target"} and short == "mapped_column":
                for target in call_targets(kw.value):
                    if "." in target:
                        field["foreign_key"] = target
            if kw.arg == "ondelete":
                field["on_delete"] = dotted_name(kw.value)
        if is_django:
            field["orm"] = "Django ORM"
            field["type"] = short
        elif short == "relationship":
            field["orm"] = "SQLAlchemy" if "SQLAlchemy" in self.framework_hints or True else "SQLAlchemy"
        elif short in {"mapped_column", "Column"}:
            field["orm"] = "SQLAlchemy"
        elif annotation:
            field["orm"] = "SQLAlchemy"
        if isinstance(item, ast.AnnAssign) and item.value is not None and short not in SQLALCHEMY_FIELD_FUNCS:
            field["orm"] = field.get("orm") or "SQLAlchemy"
        return field

    @staticmethod
    def _is_true(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and bool(node.value) is True

    @staticmethod
    def _annotation_label(annotation: str | None) -> str | None:
        if not annotation:
            return None
        cleaned = annotation
        for prefix in ("Mapped[", "Optional[", "Column["):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].rstrip("]")
        if cleaned.startswith("str"):
            return "string"
        if cleaned.startswith("int"):
            return "integer"
        if cleaned.startswith("float") or cleaned.startswith("Decimal"):
            return "numeric"
        if cleaned.startswith("bool"):
            return "boolean"
        if cleaned.startswith("datetime") or cleaned.startswith("date"):
            return "datetime"
        if cleaned.startswith("UUID"):
            return "uuid"
        if cleaned.startswith("dict") or cleaned.startswith("JSON"):
            return "json"
        if cleaned:
            return cleaned
        return None

    # -- queries ------------------------------------------------------------
    def detect_queries(self, tree: ast.Module) -> list[Query]:
        queries: list[Query] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                queries.extend(self._query_from_call(node))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and is_sql_literal(node.value):
                kind = re.match(r"(?is)\s*(\w+)", node.value)
                queries.append(Query(kind=(kind.group(1).lower() if kind else "unknown"), line=getattr(node, "lineno", 0),
                                     snippet=truncate(node.value.strip(), 200), orm="raw SQL"))
        return queries

    def _query_from_call(self, node: ast.Call) -> list[Query]:
        results: list[Query] = []
        full = dotted_name(node.func)
        parts = full.split(".") if full else []
        line = getattr(node, "lineno", 0)
        if "objects" in parts:
            method = parts[-1]
            kind = DJANGO_MANAGER_METHODS.get(method)
            if kind:
                model_index = parts.index("objects") - 1
                table = parts[model_index] if model_index >= 0 else None
                results.append(Query(kind=kind, line=line, table=table, orm="Django ORM", snippet=full))
            return results
        if len(parts) >= 2:
            receiver = parts[-2]
            method = parts[-1]
            if receiver in {"query", "session", "db", "db_session", "conn", "connection", "client"} or receiver.endswith(("_session", "_conn")):
                kind = SQLALCHEMY_SESSION_METHODS.get(method)
                if kind:
                    table = None
                    if node.args:
                        table = dotted_name(node.args[0]).split(".")[-1] or None
                        if table and table[0].islower():
                            table = table
                    results.append(Query(kind=kind, line=line, table=table, orm="SQLAlchemy", snippet=full))
        short = parts[-1] if parts else ""
        if short in {"text", "sql"} and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            value = node.args[0].value
            if _SQL_RE.search(value):
                kind = re.match(r"(?is)\s*(\w+)", value)
                results.append(Query(kind=(kind.group(1).lower() if kind else "unknown"), line=line, orm="raw SQL",
                                     snippet=truncate(value.strip(), 200)))
        if short in {"execute", "executemany", "fetchone", "fetchall"} and self.framework_hints & {"psycopg", "aiosqlite"}:
            results.append(Query(kind="raw", line=line, orm="DB-API", snippet=full))
        return results

    # -- secrets ------------------------------------------------------------
    def scan_secrets(self) -> list[dict]:
        findings: list[dict] = []
        for index, line in enumerate(self.lines, start=1):
            match = _SECRET_RE.search(line)
            if match:
                findings.append({"line": index, "kind": match.group(1).lower(), "snippet": truncate(line.strip(), 120)})
        return findings[:25]


def analyze_python(path: str, source: str) -> ParsedFile:
    analyzer = PythonAnalyzer(source, path)
    parsed = analyzer.analyze()
    try:
        tree = ast.parse(source, filename=path)
        parsed.queries = analyzer.detect_queries(tree)
    except SyntaxError:
        pass
    return parsed
