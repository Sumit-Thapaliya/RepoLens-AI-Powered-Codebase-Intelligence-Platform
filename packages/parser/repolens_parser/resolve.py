"""Resolve import specifiers to repository paths.

Resolution is intentionally conservative: an import is only marked *internal*
(and therefore part of the dependency graph) when the target file demonstrably
exists in the repository index. Unresolved specifiers are reported as external
dependencies - never invented.
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass, field

from .types import Import, ParsedFile

JS_EXTENSIONS = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".json")
PY_INIT = "__init__.py"


@dataclass
class ProjectIndex:
    """Everything import resolution needs to know about the project."""

    paths: set[str] = field(default_factory=set)
    by_stem: dict[str, list[str]] = field(default_factory=dict)
    tsconfig_paths: dict[str, list[str]] = field(default_factory=dict)
    tsconfig_base: str = ""
    #: ``[(base_dir, {alias: [roots]})]`` - one entry per tsconfig/jsconfig found.
    #: A monorepo keeps its aliases per package, so the base directory matters.
    tsconfig_aliases: list[tuple[str, dict[str, list[str]]]] = field(default_factory=list)
    go_module: str | None = None
    python_roots: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, paths: list[str]) -> "ProjectIndex":
        index = cls(paths=set(paths))
        for path in paths:
            stem = posixpath.splitext(posixpath.basename(path))[0]
            index.by_stem.setdefault(stem, []).append(path)
        for path in paths:
            if path.endswith("__init__.py"):
                index.python_roots.add(posixpath.dirname(path))
        return index

    def with_configs(self, files: dict[str, str]) -> "ProjectIndex":
        """Read tsconfig / jsconfig path aliases and go.mod module path."""
        for name in ("tsconfig.json", "jsconfig.json"):
            for config_path, raw in _find_configs(files, name):
                try:
                    data = json.loads(_strip_json_comments(raw))
                except (json.JSONDecodeError, TypeError):
                    continue
                compiler = data.get("compilerOptions", {}) or {}
                base_url = compiler.get("baseUrl", ".")
                base_dir = posixpath.normpath(posixpath.join(posixpath.dirname(config_path), base_url)).strip(".")
                aliases: dict[str, list[str]] = {}
                for alias, targets in (compiler.get("paths") or {}).items():
                    clean = alias.rstrip("/*").rstrip("*").rstrip("/")
                    resolved = []
                    for target in targets:
                        cleaned = target.lstrip("./").rstrip("/*").rstrip("*").rstrip("/")
                        resolved.append(cleaned)
                    if clean:
                        aliases[clean] = resolved
                if not aliases:
                    continue
                self.tsconfig_aliases.append((base_dir, aliases))
                # Keep the flat view for callers that only need one map.
                if not self.tsconfig_paths or config_path.count("/") == 0:
                    self.tsconfig_paths = {**self.tsconfig_paths, **aliases}
                    self.tsconfig_base = base_dir
        gomod = _find_config(files, "go.mod")
        if gomod:
            match = re.search(r"^module\s+(\S+)", gomod, re.MULTILINE)
            if match:
                self.go_module = match.group(1)
        return self


def _find_configs(files: dict[str, str], name: str) -> list[tuple[str, str]]:
    """All config files called ``name``, shallowest path first."""
    found = [(path, content) for path, content in files.items()
             if path == name or path.endswith("/" + name)]
    found.sort(key=lambda item: (item[0].count("/"), item[0]))
    return found


def _find_config(files: dict[str, str], name: str) -> str | None:
    configs = _find_configs(files, name)
    return configs[0][1] if configs else None


def _strip_json_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(^|\s)//.*$", "", text, flags=re.MULTILINE)
    return re.sub(r",\s*([}\]])", r"\1", text)


# --------------------------------------------------------------------------- #
# Python
# --------------------------------------------------------------------------- #

def python_import_roots(path: str, index: ProjectIndex) -> list[str]:
    """Candidate sys.path roots for absolute imports.

    A repository can lay its package several levels deep (``backend/app/...``),
    so every directory that contains an ``__init__.py`` contributes its ancestors
    as possible import roots - that is what makes ``from app.core import config``
    resolve inside a monorepo-style checkout.
    """
    roots: list[str] = [""]
    seen = {""}
    for package_dir in sorted(index.python_roots):
        parts = package_dir.split("/")
        for depth in range(1, min(len(parts), 4) + 1):
            candidate = "/".join(parts[:-depth]) if depth <= len(parts) else ""
            if candidate not in seen:
                seen.add(candidate)
                roots.append(candidate)
    current_dir = posixpath.dirname(path)
    for depth in range(0, 4):
        parts = current_dir.split("/")
        candidate = "/".join(parts[: len(parts) - depth]) if depth < len(parts) else ""
        if candidate not in seen:
            seen.add(candidate)
            roots.append(candidate)
    roots.sort(key=lambda item: (item.count("/"), item))
    return roots[:14]


def resolve_python(imp: Import, path: str, index: ProjectIndex) -> str | None:
    """Resolve a Python import to a repository path.

    ``from package import name`` is ambiguous in general (``name`` can be a class
    or a submodule). Submodule files are preferred because they are what call
    targets like ``users.router`` or ``crud.get_user()`` actually reference; when
    no submodule exists the module file or its ``__init__.py`` is used.
    """
    current_dir = posixpath.dirname(path)
    candidates: list[str] = []
    module_path = (imp.module or "").replace(".", "/")
    names = [name for name in (imp.names or []) if name and name != "*"]

    if imp.is_relative:
        base = current_dir
        for _ in range(max(0, imp.level - 1)):
            base = posixpath.dirname(base)
        prefix = posixpath.join(base, module_path) if module_path else base
        for name in names[:8]:
            candidates.extend([f"{prefix}/{name}.py", f"{prefix}/{name.lower()}.py",
                               posixpath.join(prefix, name, PY_INIT)])
        candidates.extend([f"{prefix}.py", posixpath.join(prefix, PY_INIT)])
    elif module_path:
        roots = python_import_roots(path, index)
        for root in roots:
            base = posixpath.normpath(posixpath.join(root, module_path) if root else module_path).lstrip("./")
            for name in names[:8]:
                candidates.extend([f"{base}/{name}.py", f"{base}/{name.lower()}.py"])
            candidates.extend([f"{base}.py", posixpath.join(base, PY_INIT)])
            head = module_path.split("/")[0]
            if root and root.split("/")[-1] == head and "/" in module_path:
                trimmed = module_path.split("/", 1)[1]
                parent = posixpath.dirname(root)
                relocated = posixpath.join(parent, head, trimmed) if parent else posixpath.join(head, trimmed)
                for name in names[:8]:
                    candidates.extend([f"{relocated}/{name}.py", f"{relocated}/{name.lower()}.py"])
                candidates.extend([f"{relocated}.py", posixpath.join(relocated, PY_INIT)])
        # repository-root style imports (`import app.core.config`)
        for name in names[:8]:
            candidates.extend([f"{module_path}/{name}.py", f"{module_path}/{name.lower()}.py"])
        candidates.extend([f"{module_path}.py", posixpath.join(module_path, PY_INIT)])

    for candidate in candidates:
        normalized = posixpath.normpath(candidate).lstrip("./")
        if normalized in index.paths:
            return normalized
    return None


# --------------------------------------------------------------------------- #
# JavaScript / TypeScript
# --------------------------------------------------------------------------- #

def resolve_js(imp: Import, path: str, index: ProjectIndex) -> str | None:
    specifier = imp.module
    if not specifier:
        return None
    current_dir = posixpath.dirname(path)
    candidates: list[str] = []

    if specifier.startswith("."):
        base = posixpath.normpath(posixpath.join(current_dir, specifier))
        candidates.extend(_js_candidates(base))
    else:
        alias_roots: list[str] = []
        maps = index.tsconfig_aliases or [(index.tsconfig_base, index.tsconfig_paths)]
        for base, aliases in maps:
            for alias, targets in aliases.items():
                if not (specifier == alias or specifier.startswith(alias + "/")):
                    continue
                remainder = specifier[len(alias):].lstrip("/")
                for target in targets:
                    alias_roots.append(posixpath.normpath(posixpath.join(base, target, remainder)))
        # next.js / vue conventional roots
        for root in ("src", "app", "lib", "server", ""):
            alias_roots.append(posixpath.normpath(posixpath.join(root, specifier)))
        for base in alias_roots:
            candidates.extend(_js_candidates(base.lstrip("./") or base))
    for candidate in candidates:
        normalized = posixpath.normpath(candidate).lstrip("./")
        if normalized in index.paths:
            return normalized
    return None


def _js_candidates(base: str) -> list[str]:
    out: list[str] = []
    for extension in JS_EXTENSIONS:
        out.append(f"{base}{extension}")
    for extension in (".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte"):
        out.append(posixpath.join(base, "index" + extension))
    out.append(base + "/index")
    return out


# --------------------------------------------------------------------------- #
# Other languages
# --------------------------------------------------------------------------- #

def resolve_go(imp: Import, path: str, index: ProjectIndex) -> str | None:
    module = index.go_module
    if not module or not imp.module.startswith(module):
        return None
    relative = imp.module[len(module):].lstrip("/")
    directory = relative or "."
    for candidate in index.paths:
        if posixpath.dirname(candidate) == directory and candidate.endswith(".go") and not candidate.endswith("_test.go"):
            return candidate
    return None


def resolve_java(imp: Import, path: str, index: ProjectIndex) -> str | None:
    class_name = imp.module.split(".")[-1]
    matches = index.by_stem.get(class_name, [])
    for match in matches:
        if match.endswith((".java", ".kt", ".scala")):
            return match
    return None


def resolve_ruby(imp: Import, path: str, index: ProjectIndex) -> str | None:
    if not imp.is_relative and not imp.module.startswith((".", "app/")):
        # `require 'app/services/auth'` style from the project root.
        candidate = imp.module + ".rb"
        if candidate in index.paths:
            return candidate
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(path), imp.module))
    for candidate in (f"{base}.rb", posixpath.join(base, "index.rb")):
        if candidate in index.paths:
            return candidate
    return None


def resolve_php(imp: Import, path: str, index: ProjectIndex) -> str | None:
    normalized = imp.module.replace("\\", "/")
    candidates = [normalized + ".php", posixpath.join(normalized, "index.php")]
    for name in ("app", "src", "lib"):
        candidates.append(posixpath.join(name, normalized) + ".php")
    class_name = normalized.split("/")[-1]
    candidates.extend(index.by_stem.get(class_name, []))
    for candidate in candidates:
        normalized_candidate = posixpath.normpath(candidate).lstrip("./")
        if normalized_candidate in index.paths:
            return normalized_candidate
    return None


def resolve_rust(imp: Import, path: str, index: ProjectIndex) -> str | None:
    module = imp.module.replace("crate::", "").replace("self::", "").replace("super::", "")
    parts = [p for p in module.split("::") if p]
    if not parts:
        return None
    src_dir = "src/" if any(p.startswith("src/") for p in index.paths) else ""
    base = posixpath.join(src_dir, *parts)
    for candidate in (f"{base}.rs", posixpath.join(base, "mod.rs")):
        if candidate in index.paths:
            return candidate
    return None


def resolve_c(imp: Import, path: str, index: ProjectIndex) -> str | None:
    base = posixpath.normpath(posixpath.join(posixpath.dirname(path), imp.module))
    if base in index.paths:
        return base
    for candidate in index.paths:
        if posixpath.basename(candidate) == posixpath.basename(imp.module):
            return candidate
    return None


_RESOLVERS = {
    "python": resolve_python,
    "typescript": resolve_js, "tsx": resolve_js, "javascript": resolve_js, "jsx": resolve_js,
    "go": resolve_go, "java": resolve_java, "ruby": resolve_ruby, "php": resolve_php, "rust": resolve_rust,
    "c": resolve_c, "cpp": resolve_c,
}


def resolve_imports(parsed_files: list[ParsedFile], index: ProjectIndex) -> dict[str, int]:
    """Attach ``resolved_path`` to every import in place. Returns counters."""
    stats = {"internal": 0, "external": 0, "unresolved_relative": 0}
    for parsed in parsed_files:
        resolver = _RESOLVERS.get(parsed.language)
        if resolver is None:
            continue
        for imp in parsed.imports:
            if not imp.module:
                continue
            resolved = None
            try:
                resolved = resolver(imp, parsed.path, index)
            except Exception:
                resolved = None
            if resolved:
                imp.resolved_path = resolved
                imp.external = False
                stats["internal"] += 1
            else:
                imp.external = True
                if imp.is_relative:
                    stats["unresolved_relative"] += 1
                else:
                    stats["external"] += 1
    return stats


def package_name(module: str, language: str) -> str:
    """Map an import specifier to its distributable package name."""
    if language == "python":
        if module.startswith("."):
            return ""
        return module.split(".")[0]
    if language in {"typescript", "tsx", "javascript", "jsx"}:
        if module.startswith((".", "/", "@/")):
            return ""
        parts = module.split("/")
        return "/".join(parts[:2]) if module.startswith("@") else parts[0]
    if language == "go":
        return module
    if language in {"java", "kotlin"}:
        parts = module.split(".")
        return ".".join(parts[:3])
    if language == "rust":
        return module.split("::")[0]
    return module.split("/")[0]
