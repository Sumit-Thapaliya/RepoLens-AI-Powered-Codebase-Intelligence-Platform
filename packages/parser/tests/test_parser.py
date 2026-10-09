"""Parser smoke tests - run with `pytest` from packages/parser."""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from repolens_parser import analyze_source, resolve_imports  # noqa: E402
from repolens_parser.resolve import ProjectIndex  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_python_symbols_routes_and_models():
    source = (FIXTURES / "sample_python.py").read_text()
    parsed = analyze_source("app/api/auth.py", source, "python")
    assert parsed.parse_error is None
    names = {s.name for s in parsed.symbols}
    assert {"User", "AuthService", "login", "get_user", "authenticate"} <= names
    routes = {(r.method, r.path) for r in parsed.routes}
    assert ("POST", "/api/login") in routes
    assert ("GET", "/api/users/{user_id}") in routes
    models = {m.name: m for m in parsed.models}
    assert "User" in models
    assert models["User"].table == "users"
    fields = {f["name"]: f for f in models["User"].fields}
    assert fields["id"]["primary_key"] is True
    assert any(r["target"] == "Order" for r in models["User"].relationships)
    queries = parsed.queries
    assert any(q.table == "User" and q.orm == "Django ORM" for q in queries) is False  # SQLAlchemy, not Django
    assert any(q.orm == "SQLAlchemy" for q in queries)
    login = next(s for s in parsed.symbols if s.name == "login")
    assert login.is_async
    assert any(c.name == "authenticate" for c in login.calls)
    assert "FastAPI" in parsed.framework_hints


def test_python_syntax_error_is_captured_not_raised():
    parsed = analyze_source("broken.py", "def oops(:\n  pass\n", "python")
    assert parsed.parse_error is not None
    assert parsed.symbols == []


def test_typescript_routes_and_orm():
    source = (FIXTURES / "sample_ts.ts").read_text()
    parsed = analyze_source("src/routes/auth.ts", source, "typescript")
    assert parsed.parse_error is None
    names = {s.name for s in parsed.symbols}
    assert {"loginHandler", "LoginPayload"} <= names
    login = next(s for s in parsed.symbols if s.name == "loginHandler")
    assert login.is_async
    assert any(c.name == "findUnique" for c in login.calls)
    routes = {(r.method, r.path) for r in parsed.routes}
    assert ("POST", "/api/login") in routes
    assert any(q.orm == "Prisma" for q in parsed.queries)
    assert "Express" in parsed.framework_hints


def test_import_resolution_internal_and_external():
    files = {
        "src/routes/auth.ts": (FIXTURES / "sample_ts.ts").read_text(),
        "src/services/authService.ts": "export function verifyPassword() {}\nexport function createToken() {}\n",
        "src/repositories/userRepository.ts": "export class UserRepository {}\n",
        "tsconfig.json": '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}',
    }
    parsed = analyze_source("src/routes/auth.ts", files["src/routes/auth.ts"], "typescript")
    index = ProjectIndex.build(list(files)).with_configs(files)
    stats = resolve_imports([parsed], index)
    resolved = {i.module: i.resolved_path for i in parsed.imports}
    assert resolved["../services/authService"] == "src/services/authService.ts"
    assert resolved["@prisma/client"] is None
    assert stats["internal"] == 2
    assert stats["external"] >= 1


def test_unsupported_language_is_indexed_not_parsed():
    parsed = analyze_source("schema.sql", "SELECT 1;", "sql")
    assert parsed.parse_error is None
    assert any("indexed" in w for w in parsed.warnings)


@pytest.mark.parametrize("path,expected_layer", [
    ("src/routes/users.ts", "route"),
    ("app/services/auth_service.py", "service"),
    ("internal/repositories/user_repo.go", "repository"),
    ("tests/test_auth.py", "test"),
    ("src/utils/format.ts", "util"),
])
def test_layer_classification(path, expected_layer):
    from repolens_parser import layer_for_path
    assert layer_for_path(path) == expected_layer
