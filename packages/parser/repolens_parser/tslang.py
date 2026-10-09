"""Lazy, cached tree-sitter language loading.

Only grammars that install cleanly are registered. A missing grammar degrades a
language to "indexed, not parsed" instead of crashing an analysis run.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, object] = {}
_loaders: dict[str, Callable[[], object]] = {}


def _register() -> None:
    if _loaders:
        return
    try:
        import tree_sitter_python as m
        _loaders["python"] = m.language
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.warning("tree-sitter-python unavailable: %s", exc)
    try:
        import tree_sitter_javascript as m
        _loaders["javascript"] = m.language
        _loaders["jsx"] = m.language
    except Exception as exc:  # pragma: no cover
        logger.warning("tree-sitter-javascript unavailable: %s", exc)
    try:
        import tree_sitter_typescript as m
        _loaders["typescript"] = m.language_typescript
        _loaders["tsx"] = m.language_tsx
    except Exception as exc:  # pragma: no cover
        logger.warning("tree-sitter-typescript unavailable: %s", exc)
    try:
        import tree_sitter_go as m
        _loaders["go"] = m.language
    except Exception as exc:  # pragma: no cover
        logger.info("tree-sitter-go unavailable: %s", exc)
    try:
        import tree_sitter_java as m
        _loaders["java"] = m.language
    except Exception as exc:  # pragma: no cover
        logger.info("tree-sitter-java unavailable: %s", exc)
    try:
        import tree_sitter_ruby as m
        _loaders["ruby"] = m.language
    except Exception as exc:  # pragma: no cover
        logger.info("tree-sitter-ruby unavailable: %s", exc)
    try:
        import tree_sitter_php as m
        _loaders["php"] = m.language_php
    except Exception as exc:  # pragma: no cover
        logger.info("tree-sitter-php unavailable: %s", exc)
    try:
        import tree_sitter_rust as m
        _loaders["rust"] = m.language
    except Exception as exc:  # pragma: no cover
        logger.info("tree-sitter-rust unavailable: %s", exc)
    try:
        import tree_sitter_cpp as m
        _loaders["cpp"] = m.language
        _loaders["c"] = m.language
    except Exception as exc:  # pragma: no cover
        logger.info("tree-sitter-cpp unavailable: %s", exc)
    try:
        import tree_sitter_c_sharp as m
        _loaders["csharp"] = m.language
    except Exception as exc:  # pragma: no cover
        logger.info("tree-sitter-c-sharp unavailable: %s", exc)


def available_languages() -> list[str]:
    _register()
    return sorted(_loaders)


def is_supported(language: str) -> bool:
    _register()
    return language in _loaders


def get_language(language: str):
    """Return a tree-sitter ``Language`` or ``None`` when unavailable."""
    _register()
    if language in _cache:
        return _cache[language]
    with _lock:
        if language in _cache:
            return _cache[language]
        loader = _loaders.get(language)
        if loader is None:
            return None
        try:
            from tree_sitter import Language
            lang = Language(loader())
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load tree-sitter grammar for %s: %s", language, exc)
            return None
        _cache[language] = lang
        return lang


def get_parser(language: str):
    """Return a configured ``Parser`` or ``None``."""
    lang = get_language(language)
    if lang is None:
        return None
    try:
        from tree_sitter import Parser
        return Parser(lang)
    except Exception:  # pragma: no cover
        try:  # older tree-sitter (<=0.21) API
            from tree_sitter import Parser  # type: ignore
            parser = Parser()  # type: ignore[call-arg]
            parser.set_language(lang)  # type: ignore[attr-defined]
            return parser
        except Exception as exc:
            logger.warning("Failed to create parser for %s: %s", language, exc)
            return None


def node_text(node) -> str:
    try:
        return node.text.decode("utf-8", "replace")
    except Exception:  # pragma: no cover
        return ""


def line_of(node) -> int:
    return int(node.start_point[0]) + 1


def end_line_of(node) -> int:
    return int(node.end_point[0]) + 1
