"""Public entry point of the parser package.

``analyze_source`` never raises for source-level problems: every failure is
recorded on the returned ``ParsedFile`` so one broken file can never abort a
repository analysis (see the grounding rules in the README).
"""

from __future__ import annotations

import logging

from repolens_shared.constants import TEXT_INDEXED_LANGUAGES, TREE_SITTER_LANGUAGES

from .frameworks import (  # noqa: F401  (re-exported for the analyzer package)
    dependency_map,
    detect_databases,
    detect_frameworks,
    detect_manifests,
    language_stats,
)
from .generic_analyzer import analyze_generic
from .javascript_analyzer import analyze_javascript
from .python_analyzer import (  # noqa: F401
    PythonAnalyzer,
    analyze_python,
    is_entrypoint,
    is_test_path,
    layer_for_path,
)
from .resolve import ProjectIndex, package_name, resolve_imports
from .tslang import available_languages, is_supported  # noqa: F401
from .types import Call, Import, Model, ParsedFile, Query, Route, Symbol  # noqa: F401

logger = logging.getLogger(__name__)

__all__ = [
    "analyze_source", "analyze_python", "analyze_javascript", "analyze_generic",
    "ProjectIndex", "resolve_imports", "package_name",
    "detect_manifests", "detect_frameworks", "detect_databases", "language_stats", "dependency_map",
    "ParsedFile", "Symbol", "Import", "Route", "Model", "Query", "Call",
    "layer_for_path", "is_test_path", "is_entrypoint",
    "available_languages", "is_supported",
]


def analyze_source(path: str, source: str, language: str) -> ParsedFile:
    """Parse a single file. Errors are captured, never raised."""
    try:
        if not source.strip():
            parsed = ParsedFile(path=path, language=language, loc=0, size=0)
            parsed.warnings.append("File is empty.")
            return parsed
        if language == "python":
            return analyze_python(path, source)
        if language in {"typescript", "tsx", "javascript", "jsx"}:
            return analyze_javascript(path, source, language)
        if language in TREE_SITTER_LANGUAGES:
            return analyze_generic(path, source, language)
        if language in TEXT_INDEXED_LANGUAGES:
            from repolens_shared.utils import language_label
            parsed = ParsedFile(path=path, language=language, loc=len(source.splitlines()),
                                size=len(source.encode("utf-8")))
            parsed.warnings.append(
                f"{language_label(language)} is indexed for search but does not have a deep symbol parser; "
                "symbols, routes and models are unavailable for this file."
            )
            return parsed
        parsed = ParsedFile(path=path, language=language, loc=len(source.splitlines()),
                            size=len(source.encode("utf-8")))
        parsed.warnings.append(f"Unsupported language '{language}' - file is indexed as plain text.")
        return parsed
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Parser crashed for %s", path)
        parsed = ParsedFile(path=path, language=language,
                            loc=len(source.splitlines()) if source else 0,
                            size=len(source.encode("utf-8")) if source else 0)
        parsed.parse_error = f"{type(exc).__name__}: {exc}"
        return parsed
