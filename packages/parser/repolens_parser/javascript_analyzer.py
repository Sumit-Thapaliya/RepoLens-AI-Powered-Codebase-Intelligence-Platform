"""JavaScript / TypeScript analysis with tree-sitter.

Covers the patterns that actually identify architecture in JS/TS repositories:

* symbol extraction (functions, arrow-function consts, classes, methods,
  interfaces, types, enums, React components, exported flags)
* import / require / re-export edges
* HTTP routes for Express, Fastify, Next.js App + Pages router, NestJS and Koa
* ORM models & queries for Prisma, Sequelize, TypeORM, Mongoose and Knex
"""

from __future__ import annotations

import re

from repolens_shared.utils import shingle_hash, truncate

from .python_analyzer import LAYER_RULES, is_entrypoint, is_test_path, layer_for_path  # noqa: F401  (re-exported)
from .tslang import end_line_of, get_parser, line_of, node_text
from .types import Call, Import, Model, ParsedFile, Query, Route, Symbol

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "all", "use", "route", "del", "any"}
ROUTER_OBJECTS = {"app", "router", "server", "api", "fastify", "route", "routes", "apiRouter", "appRouter", "httpServer"}
NEST_METHOD_DECORATORS = {
    "Get": "GET", "Post": "POST", "Put": "PUT", "Patch": "PATCH", "Delete": "DELETE",
    "Options": "OPTIONS", "Head": "HEAD", "All": "ALL",
}
NEST_CLASS_DECORATORS = {"Controller", "RestController"}

FUNCTION_NODE_TYPES = {"function_declaration", "generator_function_declaration", "function_expression", "arrow_function", "function"}
CLASS_NODE_TYPES = {"class_declaration", "class", "abstract_class_declaration"}
TS_TYPE_NODE_TYPES = {"interface_declaration", "type_alias_declaration", "enum_declaration"}
DECLARATION_NODE_TYPES = FUNCTION_NODE_TYPES | CLASS_NODE_TYPES | TS_TYPE_NODE_TYPES | {
    "lexical_declaration", "variable_declaration", "export_statement", "public_field_definition",
    "property_signature", "method_definition", "pair",
}

ORM_CALL_PATTERNS: list[tuple[str, str, str]] = [
    # (orm, method, query kind)
    ("Prisma", "findMany", "select"), ("Prisma", "findUnique", "select"), ("Prisma", "findFirst", "select"),
    ("Prisma", "findUniqueOrThrow", "select"), ("Prisma", "findFirstOrThrow", "select"), ("Prisma", "count", "select"),
    ("Prisma", "aggregate", "select"), ("Prisma", "groupBy", "select"),
    ("Prisma", "create", "insert"), ("Prisma", "createMany", "insert"),
    ("Prisma", "update", "update"), ("Prisma", "updateMany", "update"), ("Prisma", "upsert", "upsert"),
    ("Prisma", "delete", "delete"), ("Prisma", "deleteMany", "delete"),
    ("Sequelize", "findAll", "select"), ("Sequelize", "findOne", "select"), ("Sequelize", "findByPk", "select"),
    ("Sequelize", "create", "insert"), ("Sequelize", "bulkCreate", "insert"), ("Sequelize", "update", "update"),
    ("Sequelize", "destroy", "delete"),
    ("Mongoose", "find", "select"), ("Mongoose", "findOne", "select"), ("Mongoose", "findById", "select"),
    ("Mongoose", "findByIdAndUpdate", "update"), ("Mongoose", "findOneAndUpdate", "update"),
    ("Mongoose", "save", "insert"), ("Mongoose", "create", "insert"), ("Mongoose", "deleteOne", "delete"),
    ("Mongoose", "deleteMany", "delete"),
    ("TypeORM", "find", "select"), ("TypeORM", "findOne", "select"), ("TypeORM", "findOneBy", "select"),
    ("TypeORM", "save", "upsert"), ("TypeORM", "insert", "insert"), ("TypeORM", "update", "update"),
    ("TypeORM", "remove", "delete"), ("TypeORM", "delete", "delete"),
    ("Knex", "select", "select"), ("Knex", "insert", "insert"), ("Knex", "update", "update"), ("Knex", "del", "delete"),
    ("Drizzle", "select", "select"), ("Drizzle", "insert", "insert"), ("Drizzle", "update", "update"), ("Drizzle", "delete", "delete"),
]

SEQUELIZE_MODEL_FUNCS = {"define", "init"}
TYPEORM_DECORATORS = {"Entity", "Column", "PrimaryGeneratedColumn", "PrimaryColumn", "OneToMany", "ManyToOne", "ManyToMany", "OneToOne", "CreateDateColumn", "UpdateDateColumn", "JoinColumn"}
MONGOOSE_SCHEMA_CALLS = {"Schema", "model"}


def _ts_code(node) -> str:
    return node_text(node)


class JavaScriptAnalyzer:
    def __init__(self, source: str, path: str, language: str = "typescript"):
        self.source = source
        self.path = path
        self.language = language
        self.lines = source.splitlines()
        self.framework_hints: set[str] = set()
        self.parser = get_parser(language)
        self.import_sources: set[str] = set()

    # ------------------------------------------------------------------ main
    def analyze(self) -> ParsedFile:
        parsed = ParsedFile(path=self.path, language=self.language, loc=len(self.lines),
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
        self._detect_backend_routes(tree.root_node, parsed)
        self._detect_next_routes(parsed)
        self._detect_orm(tree.root_node, parsed)
        parsed.framework_hints = sorted(self.framework_hints)
        parsed.exports = sorted({s.name for s in parsed.symbols if s.exported})
        return parsed

    # ------------------------------------------------------------- traversal
    def _walk(self, node, parsed: ParsedFile, parent: str | None, exported: bool = False) -> None:
        node_type = node.type

        if node_type == "import_statement":
            self._read_import(node, parsed)
            return
        if node_type == "export_statement":
            self._read_export(node, parsed)
            return
        if node_type in {"call_expression", "new_expression"}:
            self._read_require(node, parsed)
        if node_type == "class_declaration" or node_type == "class" or node_type == "abstract_class_declaration":
            self._read_class(node, parsed, exported)
            return
        if node_type in FUNCTION_NODE_TYPES:
            name = self._name_of_function_node(node)
            if name:
                parsed.symbols.append(self._function_symbol(node, name, parent=None, exported=exported))
            # Do not descend further: nested arrow functions inside a function body
            # are captured by call analysis, not as separate module symbols.
            return
        if node_type in TS_TYPE_NODE_TYPES:
            self._read_type_declaration(node, parsed, exported)
            return
        if node_type in {"lexical_declaration", "variable_declaration"}:
            self._read_variable_declaration(node, parsed, exported)
            return
        for child in node.children:
            self._walk(child, parsed, parent, exported)

    def _read_import(self, node, parsed: ParsedFile) -> None:
        source_node = node.child_by_field_name("source")
        if source_node is None:
            # Fallback: first string child
            for child in node.children:
                if child.type == "string":
                    source_node = child
                    break
        if source_node is None:
            return
        raw = _ts_code(source_node).strip()
        module = raw.strip("'\"`")
        names: list[str] = []
        for child in node.children:
            if child.type == "import_clause":
                names.extend(self._collect_identifiers(child))
        line = line_of(node)
        self.import_sources.add(module)
        parsed.imports.append(
            Import(raw=_ts_code(node).strip(), module=module, line=line, names=names[:12],
                   is_relative=module.startswith("."), kind="import")
        )
        self._note_framework_from_module(module, names)

    def _read_export(self, node, parsed: ParsedFile) -> None:
        # `export { a, b } from './x'`
        source_node = node.child_by_field_name("source")
        if source_node is not None:
            module = _ts_code(source_node).strip().strip("'\"`")
            parsed.imports.append(
                Import(raw=_ts_code(node).strip(), module=module, line=line_of(node),
                       is_relative=module.startswith("."), kind="reexport")
            )
        declaration = node.child_by_field_name("declaration")
        if declaration is not None:
            self._walk(declaration, parsed, parent=None, exported=True)
            return
        # `export default function() {}` / `export const x = () => {}`
        for child in node.children:
            if child.type in DECLARATION_NODE_TYPES or child.type in FUNCTION_NODE_TYPES:
                self._walk(child, parsed, parent=None, exported=True)

    def _read_require(self, node, parsed: ParsedFile) -> None:
        func = node.child_by_field_name("function") or (node.children[0] if node.children else None)
        if func is None:
            return
        func_name = _ts_code(func)
        if func_name not in {"require", "import"}:
            return
        args = node.child_by_field_name("arguments")
        if args is None:
            return
        for child in args.children:
            if child.type == "string":
                module = _ts_code(child).strip().strip("'\"`")
                parsed.imports.append(
                    Import(raw=_ts_code(node).strip(), module=module, line=line_of(node),
                           is_relative=module.startswith("."), kind="require")
                )
                self._note_framework_from_module(module, [])
                break

    def _read_class(self, node, parsed: ParsedFile, exported: bool) -> None:
        name_node = node.child_by_field_name("name")
        class_name = _ts_code(name_node) if name_node is not None else "(anonymous class)"
        decorators = self._decorators_of(node)
        base = ""
        heritage = None
        for child in node.children:
            if child.type == "class_heritage":
                heritage = child
        if heritage is not None:
            base = _ts_code(heritage).replace("extends", "").strip()
        methods = []
        for child in node.children:
            if child.type == "class_body":
                for member in child.children:
                    if member.type in {"method_definition", "method_signature"}:
                        methods.append(member)
                    elif member.type == "public_field_definition":
                        field_name = member.child_by_field_name("name")
                        value = member.child_by_field_name("value")
                        if field_name is not None and value is not None and value.type in FUNCTION_NODE_TYPES:
                            methods.append(member)
        parsed.symbols.append(
            Symbol(
                name=class_name, kind="class", start_line=line_of(node), end_line=end_line_of(node),
                params=[self._method_name(m) for m in methods], signature=f"class {class_name}{(' extends ' + base) if base else ''}",
                decorators=decorators, bases=[base] if base else [], docstring=self._leading_comment(node),
                complexity=max(1, sum(self._complexity(m) for m in methods)), exported=exported,
                shingle=shingle_hash(_ts_code(node)[:4000]),
            )
        )
        self._note_framework_from_decorators(decorators)
        for member in methods:
            method_name = self._method_name(member)
            if not method_name:
                continue
            value = member.child_by_field_name("value")
            body_node = value if value is not None and value.type in FUNCTION_NODE_TYPES else member
            symbol = self._function_symbol(body_node, method_name, parent=class_name, exported=False, declaration=member)
            parsed.symbols.append(symbol)
            self._detect_nest_route(member, parsed, controller=class_name)

    def _read_type_declaration(self, node, parsed: ParsedFile, exported: bool) -> None:
        name_node = node.child_by_field_name("name")
        name = _ts_code(name_node) if name_node is not None else ""
        if not name:
            return
        kind = {"interface_declaration": "interface", "type_alias_declaration": "type", "enum_declaration": "enum"}[node.type]
        parsed.symbols.append(
            Symbol(
                name=name, kind=kind, start_line=line_of(node), end_line=end_line_of(node),
                signature=truncate(_ts_code(node).split("\n")[0], 200), exported=exported,
                docstring=self._leading_comment(node), complexity=1,
            )
        )

    def _read_variable_declaration(self, node, parsed: ParsedFile, exported: bool) -> None:
        for declarator in node.named_children:
            if declarator.type != "variable_declarator":
                continue
            name_node = declarator.child_by_field_name("name")
            value = declarator.child_by_field_name("value")
            if name_node is None or value is None:
                continue
            name = _ts_code(name_node)
            if value.type in FUNCTION_NODE_TYPES:
                symbol = self._function_symbol(value, name, parent=None, exported=exported)
                symbol.kind = "component" if self._looks_like_component(value, name) else symbol.kind
                parsed.symbols.append(symbol)
            elif value.type in {"call_expression", "new_expression"}:
                called = _ts_code(value.child_by_field_name("function") or value.children[0])
                if called.split(".")[-1] in {"createContext", "createSlice", "createApi", "createAsyncThunk"}:
                    parsed.symbols.append(
                        Symbol(name=name, kind="state", start_line=line_of(declarator), end_line=end_line_of(declarator),
                               signature=truncate(_ts_code(declarator), 160), exported=exported, complexity=1)
                    )
                elif called in {"Router", "express.Router", "express"} or called.endswith(".Router"):
                    parsed.symbols.append(
                        Symbol(name=name, kind="router", start_line=line_of(declarator), end_line=end_line_of(declarator),
                               signature=truncate(_ts_code(declarator), 160), exported=exported, complexity=1)
                    )
                    parsed.router_prefixes[name] = ""
                    self.framework_hints.add("Express")
            elif value.type in {"object", "array", "string", "number", "template_string", "true", "false", "null"}:
                if name.isupper() or re.match(r"^[A-Z][A-Za-z0-9_]*$", name):
                    parsed.symbols.append(
                        Symbol(name=name, kind="constant", start_line=line_of(declarator), end_line=end_line_of(declarator),
                               signature=truncate(_ts_code(declarator), 160), exported=exported, complexity=1)
                    )

    # ------------------------------------------------------------- utilities
    def _name_of_function_node(self, node) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return _ts_code(name_node)
        parent = node.parent
        if parent is not None and parent.type in {"variable_declarator", "public_field_definition"}:
            parent_name = parent.child_by_field_name("name")
            if parent_name is not None:
                return _ts_code(parent_name)
        if parent is not None and parent.type == "pair":
            key = parent.child_by_field_name("key")
            if key is not None:
                return _ts_code(key)
        return None

    def _method_name(self, member) -> str | None:
        name_node = member.child_by_field_name("name")
        return _ts_code(name_node) if name_node is not None else None

    def _function_symbol(self, node, name: str, parent: str | None, exported: bool, declaration=None) -> Symbol:
        target = declaration if declaration is not None else node
        params = self._params_of(node)
        async_prefix = "async " if any(c.type == "async" for c in (declaration or node).children) else ""
        kind = "method" if parent else "function"
        signature = f"{async_prefix}{'function ' if kind == 'function' else ''}{name}({', '.join(params)})"
        return Symbol(
            name=name, kind=kind, start_line=line_of(target), end_line=end_line_of(target),
            params=params, signature=truncate(signature, 250), decorators=self._decorators_of(target),
            parent=parent, exported=exported, is_async=bool(async_prefix), complexity=self._complexity(node),
            docstring=self._leading_comment(target), calls=self._calls_in(node), shingle=shingle_hash(_ts_code(node)[:4000]),
        )

    def _params_of(self, node) -> list[str]:
        params_node = node.child_by_field_name("parameter") or node.child_by_field_name("parameters")
        if params_node is None:
            for child in node.children:
                if child.type in {"formal_parameters", "parameters"}:
                    params_node = child
                    break
        if params_node is None:
            single = node.child_by_field_name("parameter")
            return [_ts_code(single)] if single is not None else []
        names: list[str] = []
        for child in params_node.named_children:
            text = _ts_code(child)
            if child.type in {"required_parameter", "optional_parameter"}:
                pattern = child.child_by_field_name("pattern")
                text = _ts_code(pattern) if pattern is not None else text
            text = text.split(":")[0].strip()
            if text:
                names.append(text)
        return names[:20]

    def _calls_in(self, node, limit: int = 200) -> list[Call]:
        calls: list[Call] = []
        stack = [node]
        seen: set[tuple[str, int]] = set()
        while stack:
            current = stack.pop()
            for child in current.children:
                if child.type == "call_expression":
                    func = child.child_by_field_name("function")
                    text = _ts_code(func) if func is not None else ""
                    text = text.replace("await ", "").strip()
                    if text:
                        parts = text.split(".")
                        key = (text, line_of(child))
                        if key not in seen:
                            seen.add(key)
                            calls.append(Call(name=parts[-1], line=line_of(child), qualifier=".".join(parts[:-1]) or None,
                                             full=text, receiver=parts[0] if len(parts) > 1 else None))
                if child.type in FUNCTION_NODE_TYPES and child is not node:
                    continue  # don't attribute nested function calls to the parent symbol
                stack.append(child)
            if len(calls) >= limit:
                break
        return calls[:limit]

    def _complexity(self, node) -> int:
        score = 1
        stack = [node]
        counting = {"if_statement", "for_statement", "for_in_statement", "while_statement", "catch_clause",
                    "ternary_expression", "binary_expression", "switch_case", "switch_default"}
        while stack:
            current = stack.pop()
            for child in current.children:
                if child.type in counting:
                    if child.type == "binary_expression":
                        operator = child.child_by_field_name("operator")
                        if operator is not None and _ts_code(operator) in {"&&", "||", "??"}:
                            score += 1
                    else:
                        score += 1
                stack.append(child)
        return score

    def _decorators_of(self, node) -> list[str]:
        decorators: list[str] = []
        for child in node.children:
            if child.type == "decorator":
                decorators.append(_ts_code(child).lstrip("@").strip())
        return decorators

    def _leading_comment(self, node) -> str | None:
        """JSDoc/`//` comment directly above a declaration."""
        previous = node.prev_sibling
        chunks: list[str] = []
        while previous is not None and previous.type == "comment":
            chunks.append(_ts_code(previous))
            previous = previous.prev_sibling
        if not chunks:
            return None
        text = "\n".join(reversed(chunks))
        cleaned = re.sub(r"^\s*(/\*\*?|\*|//)\s?", "", text, flags=re.MULTILINE).strip()
        return truncate(cleaned, 700) if cleaned else None

    def _collect_identifiers(self, node, depth: int = 0) -> list[str]:
        if depth > 4:
            return []
        names: list[str] = []
        if node.type in {"identifier", "shorthand_property_identifier", "property_identifier"}:
            return [_ts_code(node)]
        for child in node.named_children:
            names.extend(self._collect_identifiers(child, depth + 1))
        return names

    def _looks_like_component(self, value, name: str) -> bool:
        if name[:1].isupper() and re.search(r"return\s*\(?\s*<", _ts_code(value)):
            return True
        if name[:1].isupper() and re.search(r"use[A-Z]", _ts_code(value)):
            return True
        return False

    def _note_framework_from_module(self, module: str, names: list[str]) -> None:
        lowered = module.lower()
        mapping = {
            "next": "Next.js", "react": "React", "express": "Express", "@nestjs": "NestJS", "fastify": "Fastify",
            "koa": "Koa", "@prisma/client": "Prisma", "prisma": "Prisma", "sequelize": "Sequelize", "typeorm": "TypeORM",
            "mongoose": "Mongoose", "knex": "Knex", "drizzle-orm": "Drizzle ORM", "@trpc/server": "tRPC",
            "graphql": "GraphQL (Apollo)", "apollo-server": "GraphQL (Apollo)", "@apollo/server": "GraphQL (Apollo)",
            "redux": "Redux", "@reduxjs/toolkit": "Redux", "zustand": "Zustand", "vue": "Vue", "svelte": "Svelte",
            "axios": "Axios", "jsonwebtoken": "JWT", "bcrypt": "bcrypt", "passport": "Passport", "cors": "CORS",
            "zod": "Zod", "ws": "WebSockets", "socket.io": "Socket.IO", "ioredis": "Redis", "redis": "Redis",
            "pg": "PostgreSQL (node-postgres)", "mongodb": "MongoDB", "mysql2": "MySQL", "better-sqlite3": "SQLite",
            "@trpc/client": "tRPC", "@tanstack/react-query": "TanStack Query", "tailwind-merge": "Tailwind CSS",
        }
        for marker, label in mapping.items():
            if lowered == marker or lowered.startswith(marker + "/") or lowered.split("/")[0] == marker:
                self.framework_hints.add(label)
        if lowered in {"next"}:
            self.framework_hints.add("Next.js")

    def _note_framework_from_decorators(self, decorators: list[str]) -> None:
        for decorator in decorators:
            head = decorator.split("(")[0].strip()
            if head in NEST_CLASS_DECORATORS:
                self.framework_hints.add("NestJS")
                if head == "Controller":
                    self.framework_hints.add("NestJS Controller")
            if head in TYPEORM_DECORATORS:
                self.framework_hints.add("TypeORM")

    # ------------------------------------------------------------ API routes
    def _detect_mounts(self, root, parsed: ParsedFile) -> None:
        """``app.use('/api/users', usersRouter)`` and ``router.use('/:id', child)``."""
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type == "call_expression":
                func = node.child_by_field_name("function")
                text = _ts_code(func) if func is not None else ""
                if text.endswith(".use"):
                    receiver = text.split(".")[-2] if "." in text else ""
                    args = node.child_by_field_name("arguments")
                    if args is not None and args.named_children:
                        first = args.named_children[0]
                        if first.type in {"string", "template_string"}:
                            prefix = _ts_code(first).strip("'\"`")
                            if prefix.startswith("/"):
                                target = None
                                if len(args.named_children) >= 2:
                                    target = _ts_code(args.named_children[1]).strip()
                                parsed.router_includes.append({
                                    "target": target or "(middleware)",
                                    "prefix": prefix.rstrip("/"),
                                    "parent": receiver or None,
                                })
            for child in node.children:
                stack.append(child)

    def _detect_backend_routes(self, root, parsed: ParsedFile) -> None:
        self._detect_mounts(root, parsed)
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type == "call_expression":
                func = node.child_by_field_name("function")
                text = _ts_code(func) if func is not None else ""
                parts = text.split(".")
                if len(parts) >= 2:
                    obj, method = parts[-2], parts[-1]
                    args = node.child_by_field_name("arguments")
                    path = None
                    if args is not None and args.named_children:
                        first = args.named_children[0]
                        if first.type in {"string", "template_string"}:
                            path = _ts_code(first).strip("'\"`")
                    if path is not None and path.startswith("/"):
                        if obj in ROUTER_OBJECTS or obj[0].isupper() or obj.endswith(("Router", "router", "App", "Server")):
                            if method in HTTP_METHODS:
                                is_webhook = "webhook" in path or "webhook" in obj.lower()
                                frame = self._frame_from_module()
                                if self.import_sources & {"fastify"} or obj in {"fastify", "server"} and method in {"get", "post"}:
                                    frame = frame or "Fastify"
                                parsed.routes.append(
                                    Route(
                                        method=self._normalize_method(method, obj, path),
                                        path=self._normalize_path(path),
                                        handler=self._route_handler_name(node, args),
                                        line=line_of(node),
                                        framework=frame or ("Express" if self._is_express() else "JS HTTP framework"),
                                        auth_hint=self._has_auth_marker(node) or bool(re.search(r"auth|login|token|session", path, re.I)),
                                        decorators=[],
                                        notes="webhook endpoint" if is_webhook else None,
                                        request_model=None,
                                        router_object=obj,
                                    )
                                )
            if node.type == "method_definition":
                decorators = self._decorators_of(node)
                if decorators:
                    self._detect_nest_route(node, parsed, controller=None)
            for child in node.children:
                stack.append(child)

    def _normalize_method(self, method: str, obj: str, path: str) -> str:
        if method == "use":
            return "USE"
        if obj and obj[0].isupper():
            return method.upper()
        return method.upper()

    def _normalize_path(self, path: str) -> str:
        return "/" + path.strip("/") if path.strip("/") else "/"

    def _route_handler_name(self, node, args) -> str | None:
        if args is None:
            return None
        named = args.named_children
        if len(named) >= 2:
            last = named[-1]
            if last.type in FUNCTION_NODE_TYPES:
                name = self._name_of_function_node(last)
                return name or "(inline handler)"
            if last.type == "identifier":
                return _ts_code(last)
            if last.type == "member_expression":
                return _ts_code(last)
        return "(inline handler)"

    def _detect_nest_route(self, node, parsed: ParsedFile, controller: str | None) -> None:
        decorators = self._decorators_of(node)
        method_name = self._method_name(node)
        for decorator in decorators:
            head = decorator.split("(")[0].strip()
            if head not in NEST_METHOD_DECORATORS:
                continue
            path = ""
            match = re.search(r"\(\s*['\"`]([^'\"`]*)['\"`]", decorator)
            if match:
                path = match.group(1)
            base = ""
            parent = node.parent
            if parent is not None and parent.parent is not None:
                for cls_decorator in self._decorators_of(parent.parent):
                    base_match = re.search(r"\(\s*['\"`]([^'\"`]*)['\"`]", cls_decorator)
                    if cls_decorator.split("(")[0].strip() in NEST_CLASS_DECORATORS and base_match:
                        base = base_match.group(1)
            full_path = "/" + "/".join(part.strip("/") for part in (base, path) if part.strip("/"))
            self.framework_hints.add("NestJS")
            parsed.routes.append(
                Route(method=NEST_METHOD_DECORATORS[head], path=full_path or "/",
                      handler=method_name, line=line_of(node), framework="NestJS",
                      auth_hint=self._has_auth_marker(node) or any("Auth" in d or "Guard" in d for d in decorators),
                      decorators=decorators, controller=controller)
            )

    def _detect_next_routes(self, parsed: ParsedFile) -> None:
        """Next.js App Router (route.ts) and Pages Router (pages/api/**.ts)."""
        path = self.path
        app_route = re.search(r"(?:^|/)app/(.*)/route\.(ts|js|tsx|jsx)$", path)
        pages_route = re.search(r"(?:^|/)pages/api/(.*)\.(ts|js|tsx|jsx)$", path)
        if app_route:
            route_path = "/" + app_route.group(1).replace("/", "/")
            route_path = re.sub(r"\[([^\]]+)\]", r":\1", route_path).replace("/(.)", "/")
            for symbol in parsed.symbols:
                if symbol.name.lower() in {"get", "post", "put", "patch", "delete", "head", "options"}:
                    parsed.routes.append(
                        Route(method=symbol.name.upper(), path=route_path.rstrip("/") or "/", handler=symbol.name,
                              line=symbol.start_line, framework="Next.js App Router",
                              auth_hint=bool(re.search(r"auth|session|token", self.source[:4000], re.I)),
                              notes=f"exported {symbol.name.upper()} handler")
                    )
                    self.framework_hints.add("Next.js App Router")
            if not parsed.routes:
                parsed.routes.append(
                    Route(method="ANY", path=route_path.rstrip("/") or "/", handler=self.path.rsplit("/", 1)[-1],
                          line=1, framework="Next.js App Router",
                          notes="route handler (HTTP methods could not be resolved statically)")
                )
        elif pages_route:
            segments = pages_route.group(1)
            route_path = "/api/" + re.sub(r"\[([^\]]+)\]", r":\1", segments).replace("/index", "")
            self.framework_hints.add("Next.js Pages Router")
            handler = None
            for symbol in parsed.symbols:
                if symbol.name == "handler":
                    handler = "handler"
                    break
            parsed.routes.append(
                Route(method="ANY", path=route_path, handler=handler or "default export", line=1,
                      framework="Next.js Pages Router", notes="handler switches on req.method")
            )
        self._detect_trpc_router(parsed)
        self._detect_server_actions(parsed)

    def _detect_trpc_router(self, parsed: ParsedFile) -> None:
        """tRPC routers are recognised from the library import and procedure syntax
        only - a generic ``createRouter()`` call is not evidence of tRPC."""
        if not any("trpc" in module.lower() for module in self.import_sources):
            return
        self.framework_hints.add("tRPC")
        if re.search(r"(\w+)\s*:\s*(?:publicProcedure|protectedProcedure|procedure)", self.source):
            parsed.framework_hints.append("tRPC procedure map detected")

    def _detect_server_actions(self, parsed: ParsedFile) -> None:
        if "'use server'" not in self.source and '"use server"' not in self.source:
            return
        self.framework_hints.add("Next.js Server Actions")
        for symbol in parsed.symbols:
            if symbol.kind == "function" and symbol.is_async:
                parsed.routes.append(
                    Route(method="ACTION", path=f"server-action:{symbol.name}", handler=symbol.name,
                          line=symbol.start_line, framework="Next.js Server Actions",
                          notes="'use server' module - callable directly from components")
                )

    def _frame_from_module(self) -> str | None:
        for module, label in (("express", "Express"), ("fastify", "Fastify"), ("koa", "Koa"), ("@nestjs/common", "NestJS")):
            if module in self.import_sources:
                return label
        return None

    def _is_express(self) -> bool:
        return "express" in self.import_sources or "express.Router()" in self.source or "Router()" in self.source

    def _has_auth_marker(self, node) -> bool:
        text = _ts_code(node)[:600].lower()
        return any(marker in text for marker in ("requireauth", "isauthenticated", "verifytoken", "authmiddleware", "withauth", "getsession", "authguard", "passport.authenticate", "jwt.verify"))

    # ------------------------------------------------------------------- ORM
    def _detect_orm(self, root, parsed: ParsedFile) -> None:
        # Prisma model declarations (schema.prisma is handled separately).
        if self.path.endswith(".prisma"):
            self._detect_prisma_schema(parsed)
            return
        if "model(" in self.source or ".model(" in self.source or "Schema(" in self.source:
            self._detect_mongoose(parsed)
        self._detect_class_orm_models(parsed)
        self._detect_orm_queries(parsed)

    def _detect_mongoose(self, parsed: ParsedFile) -> None:
        for match in re.finditer(r"new\s+Schema\s*\(", self.source):
            line = self.source[: match.start()].count("\n") + 1
            # find enclosing `const X = ...`
            line_text = self.lines[line - 1] if line - 1 < len(self.lines) else ""
            assign_match = re.match(r"\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=", line_text)
            name = assign_match.group(1) if assign_match else "Schema"
            fields = self._mongoose_fields(match.start())
            parsed.models.append(Model(name=name, line=line, orm="Mongoose", table=self._pluralize(name), fields=fields))
            self.framework_hints.add("Mongoose")
        for match in re.finditer(r"mongoose\.model\s*\(\s*['\"`](\w+)['\"`]", self.source):
            table = match.group(1)
            line = self.source[: match.start()].count("\n") + 1
            parsed.models.append(Model(name=table.title().replace("_", ""), line=line, orm="Mongoose", table=table, fields=[]))

    def _mongoose_fields(self, offset: int) -> list[dict]:
        snippet = self.source[offset: offset + 2000]
        fields: list[dict] = []
        for match in re.finditer(r"(\w+)\s*:\s*\{?\s*(?:type\s*:\s*)?(?:\w+\.)?(\w+)\s*\(?", snippet):
            name, type_name = match.group(1), match.group(2)
            if name in {"type", "required", "default"} or name.startswith("_"):
                continue
            if type_name in {"String", "Number", "Boolean", "Date", "ObjectId", "Buffer", "Mixed", "Array", "Decimal128", "Map"}:
                fields.append({"name": name, "type": type_name.lower(), "nullable": name != "_id",
                               "primary_key": name == "_id"})
            if len(fields) >= 30:
                break
        return fields

    def _detect_class_orm_models(self, parsed: ParsedFile) -> None:
        if not (TYPEORM_DECORATORS & {d.split("(")[0].strip() for d in re.findall(r"@\w+", self.source)}):
            return
        for symbol in parsed.symbols:
            if symbol.kind != "class":
                continue
            heads = {d.split("(")[0].strip() for d in symbol.decorators}
            if "Entity" not in heads:
                continue
            table = None
            match = re.search(r"@Entity\s*\(\s*['\"`]([^'\"`]+)['\"`]", self.source)
            if match:
                table = match.group(1)
            fields: list[dict] = []
            body = self.source.split("\n")[symbol.start_line - 1: symbol.end_line]
            column_re = re.compile(r"@(Column|PrimaryGeneratedColumn|PrimaryColumn|CreateDateColumn|UpdateDateColumn)\s*\(([^)]*)\)\s*\n?\s*(\w+)[?!]?\s*:\s*([\w<>\[\]|]+)")
            for match in column_re.finditer("\n".join(body)):
                fields.append({
                    "name": match.group(3), "type": match.group(4), "primary_key": match.group(1).startswith("Primary"),
                    "nullable": "nullable: false" not in match.group(2),
                })
            rel_re = re.compile(r"@(OneToMany|ManyToOne|ManyToMany|OneToOne)\s*\(\s*\(?\)?\s*=>\s*(\w+)")
            relationships = [{"kind": kind.lower(), "target": target, "name": f"{target.lower()}_relation"}
                             for kind, target in rel_re.findall("\n".join(body))]
            parsed.models.append(Model(name=symbol.name, line=symbol.start_line, orm="TypeORM",
                                       table=table or self._pluralize(symbol.name.lower()), fields=fields,
                                       relationships=relationships))
            self.framework_hints.add("TypeORM")

    #: module specifier -> ORM name, used to gate query detection
    ORM_MODULES = {
        "prisma": "Prisma", "@prisma/client": "Prisma", "sequelize": "Sequelize", "mongoose": "Mongoose",
        "typeorm": "TypeORM", "knex": "Knex", "drizzle-orm": "Drizzle", "@nestjs/typeorm": "TypeORM",
    }
    #: receivers that are conventionally an ORM client even without an import in the file
    ORM_CLIENT_RECEIVERS = {"prisma", "db", "tx", "knex", "client", "orm", "dataSource", "connection"}

    def _active_orms(self) -> set[str]:
        active: set[str] = set()
        for module in self.import_sources:
            head = module.split("/")[0] if not module.startswith("@") else "/".join(module.split("/")[:2])
            if head in self.ORM_MODULES:
                active.add(self.ORM_MODULES[head])
            if module in self.ORM_MODULES:
                active.add(self.ORM_MODULES[module])
        if "sequelize" in self.source.lower() and "sequelize" in " ".join(self.import_sources):
            active.add("Sequelize")
        return active

    def _detect_orm_queries(self, parsed: ParsedFile) -> None:
        active_orms = self._active_orms()
        if not active_orms:
            return
        text = self.source
        for orm, method, kind in ORM_CALL_PATTERNS:
            if orm not in active_orms and orm != "Drizzle":
                continue
            for match in re.finditer(rf"(?<![\w$])([A-Za-z_$][\w$]*)\.{method}\s*\(", text):
                receiver = match.group(1)
                if orm not in active_orms and receiver not in self.ORM_CLIENT_RECEIVERS:
                    continue
                line = text[: match.start()].count("\n") + 1
                table = None
                if orm == "Prisma" or method in {"findMany", "findUnique", "create", "update", "delete"}:
                    table = receiver
                elif receiver not in {"prisma", "db", "tx", "client", "Repository", "repo"}:
                    table = receiver
                parsed.queries.append(Query(kind=kind, line=line, table=table, orm=orm,
                                            snippet=text[match.start(): match.start() + 160].split("\n")[0]))
        if "Repository" in text and "typeorm" in " ".join(self.import_sources):
            self.framework_hints.add("TypeORM")
        if "knex" in self.import_sources or "knex(" in text:
            for match in re.finditer(r"knex\s*\(\s*['\"`](\w+)['\"`]", text):
                line = text[: match.start()].count("\n") + 1
                parsed.queries.append(Query(kind="select", line=line, table=match.group(1), orm="Knex", snippet=match.group(0)))
        for orm_name in active_orms:
            self.framework_hints.add(orm_name)

    def _detect_prisma_schema(self, parsed: ParsedFile) -> None:
        self.framework_hints.add("Prisma")
        provider = None
        provider_match = re.search(r"datasource\s+\w+\s*\{[^}]*provider\s*=\s*\"(\w+)\"", self.source, re.S)
        if provider_match:
            provider = provider_match.group(1)
            parsed.framework_hints.append(f"Prisma datasource: {provider}")
        for match in re.finditer(r"model\s+(\w+)\s*\{([^}]*)\}", self.source):
            name = match.group(1)
            body = match.group(2)
            line = self.source[: match.start()].count("\n") + 1
            fields: list[dict] = []
            relationships: list[dict] = []
            for raw_line in body.split("\n"):
                stripped = raw_line.strip()
                if not stripped or stripped.startswith("//") or stripped.startswith("@@"):
                    continue
                parts = stripped.split()
                if len(parts) < 2:
                    continue
                field_name, field_type = parts[0], parts[1]
                field: dict = {
                    "name": field_name,
                    "type": field_type.rstrip("?[]"),
                    "nullable": field_type.endswith("?") or field_type.endswith("[]") is False,
                    "primary_key": "@id" in stripped,
                    "unique": "@unique" in stripped,
                }
                relation_target = re.search(r"@relation\([^)]*fields:\s*\[[^\]]*\][^)]*references:\s*\[[^\]]*\]", stripped)
                if field_type[:1].isupper():
                    relationships.append({"kind": "relation", "name": field_name, "field": field_name,
                                          "target": field_type.rstrip("?[]"), "target_field": "id"})
                if relation_target:
                    field["relation_detail"] = truncate(stripped, 120)
                fields.append(field)
            parsed.models.append(Model(name=name, line=line, orm="Prisma", table=name, fields=fields,
                                       relationships=relationships, source="prisma"))

    @staticmethod
    def _pluralize(name: str) -> str:
        if name.endswith(("s", "x", "z", "ch", "sh")):
            return name + "es"
        if name.endswith("y") and len(name) > 1 and name[-2] not in "aeiou":
            return name[:-1] + "ies"
        return name + "s"


# --------------------------------------------------------------------------- #
# Sequelize `Model.init` / `sequelize.define` schema extraction
# --------------------------------------------------------------------------- #

def _detect_sequelize_models(path: str, source: str, parsed: ParsedFile) -> None:
    for match in re.finditer(r"(sequelize\.define|Model\.init|class\s+\w+\s+extends\s+Model)\s*\(", source):
        line = source[: match.start()].count("\n") + 1
        name_match = re.search(r"(?:sequelize\.define|Model\.init)\s*\(\s*['\"](\w+)['\"]", source[match.start(): match.start() + 200])
        class_match = re.search(r"class\s+(\w+)\s+extends\s+Model", source[match.start(): match.start() + 200])
        name = name_match.group(1) if name_match else (class_match.group(1) if class_match else "Model")
        parsed.models.append(Model(name=name, line=line, orm="Sequelize", table=name.lower() + "s"
                                   if not name.endswith("s") else name.lower(), fields=[]))
        parsed.framework_hints.append("Sequelize")


def analyze_javascript(path: str, source: str, language: str) -> ParsedFile:
    analyzer = JavaScriptAnalyzer(source, path, language)
    parsed = analyzer.analyze()
    if "_sequelize" in source or "extends Model" in source or "sequelize.define" in source:
        _detect_sequelize_models(path, source, parsed)
        if "Sequelize" not in parsed.framework_hints:
            parsed.framework_hints.append("Sequelize")
    return parsed
