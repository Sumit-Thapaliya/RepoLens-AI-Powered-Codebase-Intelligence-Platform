"""Generic tree-sitter analyzer for languages other than Python / JS / TS.

Coverage is intentionally honest: symbols and imports for Go, Java, Ruby, PHP,
Rust, C and C#. Deeper framework knowledge (Spring beans, Rails controllers) is
expressed as *hints* rather than claims, and the UI labels the confidence.
"""

from __future__ import annotations

import re

from repolens_shared.utils import shingle_hash, truncate

from .tslang import end_line_of, get_parser, line_of, node_text
from .types import Call, Import, ParsedFile, Route, Symbol

_SPECS: dict[str, dict] = {
    "go": {
        "function_nodes": {"function_declaration", "method_declaration"},
        "class_nodes": {"type_declaration", "type_spec"},
        "import_nodes": {"import_spec", "import_declaration"},
        "call_nodes": {"call_expression"},
        "name_field": "name",
        "kind_map": {"function_declaration": "function", "method_declaration": "method", "type_spec": "type"},
    },
    "java": {
        "function_nodes": {"method_declaration", "constructor_declaration"},
        "class_nodes": {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"},
        "import_nodes": {"import_declaration"},
        "call_nodes": {"method_invocation", "object_creation_expression"},
        "name_field": "name",
        "kind_map": {"method_declaration": "method", "constructor_declaration": "constructor",
                     "class_declaration": "class", "interface_declaration": "interface",
                     "enum_declaration": "enum", "record_declaration": "record"},
    },
    "ruby": {
        "function_nodes": {"method", "singleton_method"},
        "class_nodes": {"class", "module"},
        "import_nodes": {"call"},
        "call_nodes": {"call", "method_call"},
        "name_field": "name",
        "kind_map": {"method": "function", "singleton_method": "method", "class": "class", "module": "module"},
    },
    "php": {
        "function_nodes": {"function_definition", "method_declaration"},
        "class_nodes": {"class_declaration", "interface_declaration", "trait_declaration"},
        "import_nodes": {"namespace_use_declaration"},
        "call_nodes": {"function_call_expression", "member_call_expression", "scoped_call_expression"},
        "name_field": "name",
        "kind_map": {"function_definition": "function", "method_declaration": "method",
                     "class_declaration": "class", "interface_declaration": "interface", "trait_declaration": "trait"},
    },
    "rust": {
        "function_nodes": {"function_item"},
        "class_nodes": {"struct_item", "enum_item", "trait_item", "impl_item"},
        "import_nodes": {"use_declaration"},
        "call_nodes": {"call_expression", "macro_invocation"},
        "name_field": "name",
        "kind_map": {"function_item": "function", "struct_item": "struct", "enum_item": "enum",
                     "trait_item": "trait", "impl_item": "impl"},
    },
    "c": {
        "function_nodes": {"function_definition"},
        "class_nodes": {"struct_specifier", "union_specifier"},
        "import_nodes": {"preproc_include"},
        "call_nodes": {"call_expression"},
        "name_field": "declarator",
        "kind_map": {"function_definition": "function", "struct_specifier": "struct", "union_specifier": "union"},
    },
    "csharp": {
        "function_nodes": {"method_declaration", "constructor_declaration"},
        "class_nodes": {"class_declaration", "interface_declaration", "struct_declaration", "record_declaration"},
        "import_nodes": {"using_directive"},
        "call_nodes": {"invocation_expression", "object_creation_expression"},
        "name_field": "name",
        "kind_map": {"method_declaration": "method", "constructor_declaration": "constructor",
                     "class_declaration": "class", "interface_declaration": "interface"},
    },
}
_SPECS["cpp"] = _SPECS["c"]

SPRING_METHOD_ANNOTATIONS = {"GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
                             "PatchMapping": "PATCH", "DeleteMapping": "DELETE", "RequestMapping": "ANY"}
RAILS_HTTP_METHODS = {"get": "GET", "post": "POST", "put": "PUT", "patch": "PATCH", "delete": "DELETE"}
GO_ROUTER_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "Any", "Handle"}


def _text(node) -> str:
    return node_text(node)


def _find_name(node, spec: dict) -> str:
    for field in ("name", spec.get("name_field") or "name"):
        child = node.child_by_field_name(field)
        if child is not None:
            text = _text(child)
            if field == "declarator":
                match = re.search(r"(\w+)\s*\(", text)
                return match.group(1) if match else text
            return text
    for child in node.named_children:
        if child.type in {"identifier", "type_identifier", "field_identifier", "simple_identifier", "constant"}:
            return _text(child)
    return ""


class GenericAnalyzer:
    def __init__(self, source: str, path: str, language: str):
        self.source = source
        self.path = path
        self.language = language
        self.spec = _SPECS.get(language, _SPECS["c"])
        self.parser = get_parser(language)
        self.framework_hints: set[str] = set()

    def analyze(self) -> ParsedFile:
        parsed = ParsedFile(path=self.path, language=self.language, loc=len(self.source.splitlines()),
                            size=len(self.source.encode("utf-8")))
        if self.parser is None:
            parsed.parse_error = f"No tree-sitter grammar available for {self.language}"
            return parsed
        try:
            tree = self.parser.parse(self.source.encode("utf-8"))
        except Exception as exc:  # pragma: no cover
            parsed.parse_error = f"{type(exc).__name__}: {exc}"
            return parsed
        if tree.root_node.has_error:
            parsed.warnings.append("Source contains syntax errors; analysis is partial for this file.")
        self._walk(tree.root_node, parsed, parent=None)
        self._language_specific(tree.root_node, parsed)
        parsed.framework_hints = sorted(self.framework_hints)
        parsed.exports = sorted({s.name for s in parsed.symbols if not s.name.startswith("_")})
        return parsed

    def _walk(self, node, parsed: ParsedFile, parent: str | None) -> None:
        spec = self.spec
        if node.type in spec["function_nodes"]:
            name = _find_name(node, spec)
            if name:
                parsed.symbols.append(self._symbol(node, name, spec["kind_map"].get(node.type, "function"), parent))
            self._scan_calls(node, parsed, name or None)
        elif node.type in spec["class_nodes"]:
            name = _find_name(node, spec)
            if name and node.type in {"class_declaration", "interface_declaration", "struct_item", "class", "module", "type_spec", "trait_item", "enum_declaration", "record_declaration", "struct_specifier"}:
                parsed.symbols.append(self._symbol(node, name, spec["kind_map"].get(node.type, "class"), parent))
                for child in node.children:
                    self._walk(child, parsed, parent=name)
                return
        elif node.type in spec["import_nodes"]:
            self._import(node, parsed)
        for child in node.children:
            self._walk(child, parsed, parent)

    def _symbol(self, node, name: str, kind: str, parent: str | None) -> Symbol:
        decorators = self._annotations(node)
        params: list[str] = []
        params_node = node.child_by_field_name("parameters")
        if params_node is not None:
            for child in params_node.named_children:
                text = _text(child)
                if text:
                    params.append(text.split(":")[0].strip()[:40])
        first_line = _text(node).split("\n")[0]
        return Symbol(
            name=name, kind=kind, start_line=line_of(node), end_line=end_line_of(node),
            params=params[:15], signature=truncate(first_line, 220), decorators=decorators, parent=parent,
            complexity=self._complexity(node), exported=True, is_async="async" in first_line,
            calls=self._calls(node), shingle=shingle_hash(_text(node)[:4000]),
            docstring=self._leading_comment(node),
        )

    def _annotations(self, node) -> list[str]:
        annotations: list[str] = []
        previous = node.prev_sibling
        while previous is not None and previous.type in {"annotation", "attribute_item", "decorator", "marker_annotation"}:
            annotations.append(_text(previous).lstrip("@#[").rstrip("]").strip())
            previous = previous.prev_sibling
        return list(reversed(annotations))[:10]

    def _leading_comment(self, node) -> str | None:
        previous = node.prev_sibling
        chunks: list[str] = []
        while previous is not None and previous.type in {"comment", "line_comment", "block_comment", "documentation_comment"}:
            chunks.append(_text(previous))
            previous = previous.prev_sibling
        if not chunks:
            return None
        cleaned = re.sub(r"^\s*(///|//|#|/\*\*?|\*)\s?", "", "\n".join(reversed(chunks)), flags=re.MULTILINE).strip()
        return truncate(cleaned, 500) or None

    def _complexity(self, node) -> int:
        score = 1
        stack = [node]
        while stack:
            current = stack.pop()
            for child in current.children:
                if child.type in {"if_statement", "for_statement", "while_statement", "switch_expression",
                                  "case_clause", "catch_clause", "match_arm", "conditional_expression",
                                  "else_clause", "when", "elsif", "except", "rescue", "try_statement"}:
                    score += 1
                stack.append(child)
        return score

    def _calls(self, node, limit: int = 120) -> list[Call]:
        if not self.spec["call_nodes"]:
            return []
        calls: list[Call] = []
        stack = [node]
        while stack:
            current = stack.pop()
            for child in current.children:
                if child.type in self.spec["call_nodes"]:
                    text = _text(child).split("\n")[0]
                    name_match = re.search(r"([A-Za-z_][\w:.]*)\s*\(", text)
                    if name_match:
                        full = name_match.group(1)
                        parts = full.split("::")[-1].split(".")
                        calls.append(Call(name=parts[-1], line=line_of(child), full=full,
                                          qualifier=".".join(parts[:-1]) or None,
                                          receiver=parts[0] if len(parts) > 1 else None))
                    if len(calls) >= limit:
                        break
                stack.append(child)
        return calls[:limit]

    def _scan_calls(self, node, parsed: ParsedFile, symbol: str | None) -> None:
        return

    def _import(self, node, parsed: ParsedFile) -> None:
        raw = _text(node)
        module = ""
        if self.language == "go":
            match = re.search(r"\"([^\"]+)\"", raw)
            module = match.group(1) if match else ""
        elif self.language in {"java", "csharp"}:
            module = raw.replace("import", "").replace("using", "").strip().rstrip(";").replace("static ", "")
        elif self.language == "ruby":
            if node.type == "call":
                text = raw.split("\n")[0]
                match = re.match(r"(require_relative|require)\s*\(?\s*['\"]([^'\"]+)['\"]", text.strip())
                if not match:
                    return
                module = match.group(2)
        elif self.language == "php":
            module = raw.replace("use", "").strip().rstrip(";").split(" as ")[0]
        elif self.language == "rust":
            module = raw.replace("use", "").strip().rstrip(";")
        elif self.language in {"c", "cpp"}:
            match = re.search(r"[<\"]([^>\"]+)[>\"]", raw)
            module = match.group(1) if match else ""
        if not module:
            return
        parsed.imports.append(
            Import(raw=truncate(raw, 200), module=module, line=line_of(node),
                   is_relative=module.startswith((".", "internal/")), kind="import")
        )
        self._note_frameworks(module, parsed)

    def _note_frameworks(self, module: str, parsed: ParsedFile) -> None:
        lowered = module.lower()
        mapping = {
            "spring": "Spring Boot", "springframework": "Spring Boot", "gin-gonic": "Gin", "labstack/echo": "Echo",
            "gorm.io": "GORM", "database/sql": "database/sql", "rails": "Rails", "sinatra": "Sinatra",
            "illuminate": "Laravel", "symfony": "Symfony", "actix": "Actix", "axum": "Axum", "serde": "Serde",
            "gorm": "GORM", "sqlx": "sqlx", "tokio": "Tokio",
        }
        for marker, label in mapping.items():
            if marker in lowered:
                self.framework_hints.add(label)

    def _language_specific(self, root, parsed: ParsedFile) -> None:
        if self.language == "java":
            self._java_routes(root, parsed)
        elif self.language == "go":
            self._go_routes(root, parsed)
        elif self.language == "ruby":
            self._rails_routes(root, parsed)
        elif self.language == "php":
            self._php_routes(root, parsed)

    def _java_routes(self, root, parsed: ParsedFile) -> None:
        source = self.source
        class_name = None
        class_match = re.search(r"(?:public\s+)?(?:final\s+)?class\s+(\w+)", source)
        if class_match:
            class_name = class_match.group(1)
        base_path = ""
        if "@RequestMapping" in source:
            self.framework_hints.add("Spring Boot")
            base_match = re.search(r"@RequestMapping\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']*)", source)
            if base_match:
                base_path = base_match.group(1)
        for annotation, method in SPRING_METHOD_ANNOTATIONS.items():
            for match in re.finditer(rf"@{annotation}\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?[\"']([^\"']*)[\"']", source):
                line = source[: match.start()].count("\n") + 1
                tail = source[match.end(): match.end() + 400]
                handler_match = re.search(r"(?:public|private|protected)?\s*[\w<>\[\],\s]+\s+(\w+)\s*\(", tail)
                self.framework_hints.add("Spring Boot")
                parsed.routes.append(
                    Route(method=method, path=(base_path + match.group(1)) or "/",
                          handler=handler_match.group(1) if handler_match else None, line=line,
                          framework="Spring Boot", controller=class_name,
                          auth_hint="PreAuthorize" in tail[:300] or "Secured" in tail[:300])
                )

    def _go_routes(self, root, parsed: ParsedFile) -> None:
        for match in re.finditer(r"(\w+)\.(GET|POST|PUT|PATCH|DELETE|Any|Handle)\s*\(\s*[\"']([^\"']+)[\"']", self.source):
            receiver, method, path = match.group(1), match.group(2), match.group(3)
            if method not in GO_ROUTER_METHODS:
                continue
            line = self.source[: match.start()].count("\n") + 1
            tail = self.source[match.end(): match.end() + 300]
            handler_match = re.search(r"(\w+)\s*[),]", tail)
            framework = "Gin" if "gin" in self.source[:2000].lower() or "gin-gonic" in self.source else "net/http router"
            self.framework_hints.add(framework)
            parsed.routes.append(
                Route(method=method.upper(), path=path, handler=handler_match.group(1) if handler_match else None,
                      line=line, framework=framework, controller=receiver,
                      auth_hint="auth" in tail[:200].lower() or "Auth" in tail[:200])
            )

    def _rails_routes(self, root, parsed: ParsedFile) -> None:
        if "config/routes.rb" not in self.path and "Rails.application.routes" not in self.source:
            return
        self.framework_hints.add("Rails")
        for match in re.finditer(r"^\s*(get|post|put|patch|delete)\s+[\"']([^\"']+)[\"']", self.source, re.MULTILINE):
            line = self.source[: match.start()].count("\n") + 1
            tail = self.source[match.end(): match.end() + 160]
            to_match = re.search(r"to:\s*[\"']([\w#/]+)[\"']", tail)
            controller, action = (to_match.group(1).split("#", 1) + [None])[:2] if to_match else (None, None)
            parsed.routes.append(
                Route(method=RAILS_HTTP_METHODS[match.group(1)], path=match.group(2), handler=action,
                      line=line, framework="Rails", controller=controller, decorators=[])
            )
        for match in re.finditer(r"resources\s+:(\w+)", self.source):
            line = self.source[: match.start()].count("\n") + 1
            resource = match.group(1)
            for method, suffix in (("GET", ""), ("POST", ""), ("GET", "/:id"), ("PUT", "/:id"), ("DELETE", "/:id")):
                parsed.routes.append(
                    Route(method=method, path=f"/{resource}{suffix}", handler=f"{resource}#{'index' if method == 'GET' and not suffix else 'show' if method == 'GET' else 'create' if method == 'POST' else 'update' if method == 'PUT' else 'destroy'}",
                          line=line, framework="Rails", controller=resource, notes="generated by `resources`")
                )

    def _php_routes(self, root, parsed: ParsedFile) -> None:
        for match in re.finditer(r"Route::(get|post|put|patch|delete|any|match)\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(?:\[)?['\"]?([\w\\@:]+)", self.source):
            line = self.source[: match.start()].count("\n") + 1
            self.framework_hints.add("Laravel")
            parsed.routes.append(
                Route(method=match.group(1).upper(), path=match.group(2), handler=match.group(3),
                      line=line, framework="Laravel", decorators=[])
            )


def analyze_generic(path: str, source: str, language: str) -> ParsedFile:
    return GenericAnalyzer(source, path, language).analyze()
