"""Build the database report: technologies, models, relationships, queries."""

from __future__ import annotations

import re
from collections import defaultdict

from repolens_parser import ParsedFile
from repolens_shared.utils import stable_id, truncate

MIGRATION_PATH_RE = re.compile(r"(^|/)(migrations?|alembic/versions|db/migrate|db/migration)(/|$)", re.IGNORECASE)


def build_database_report(parsed_files: list[ParsedFile], technologies: list[dict],
                          files: dict[str, str], scope: str = "") -> dict:
    models: list[dict] = []
    queries: list[dict] = []
    migrations: list[dict] = []
    orms: set[str] = set()

    for parsed in parsed_files:
        for model in parsed.models:
            orm = model.orm or "unknown"
            orms.add(orm)
            models.append({
                "id": stable_id("model", scope, parsed.path, model.name, model.line),
                "name": model.name,
                "table": model.table,
                "orm": orm,
                "file_path": parsed.path,
                "line": model.line,
                "fields": model.fields,
                "relationships": model.relationships,
                "source": model.source,
                "bases": model.bases,
            })
        for query in parsed.queries:
            orms.add(query.orm or "unknown")
            queries.append({
                "id": stable_id("query", scope, parsed.path, query.line, query.kind, query.table),
                "file_path": parsed.path,
                "line": query.line,
                "kind": query.kind,
                "table": query.table,
                "orm": query.orm,
                "snippet": truncate(query.snippet or "", 240),
            })

    for path, content in files.items():
        if not MIGRATION_PATH_RE.search("/" + path):
            continue
        if not re.search(r"(create_?table|add_column|alter_table|Op\.|op\.|\bCREATE TABLE\b)", content, re.IGNORECASE):
            continue
        tables = sorted({
            (match.group(1) or match.group(2))
            for match in re.finditer(
                r"create_?table\s*\(\s*['\"](\w+)['\"]|CREATE TABLE (?:IF NOT EXISTS )?[\"`]?(\w+)",
                content, re.IGNORECASE,
            )
        })
        migrations.append({
            "id": stable_id("migration", scope, path),
            "path": path,
            "tables": tables[:20],
            "framework": _migration_framework(path, content),
            "operations": len(re.findall(r"\bop\.\w+|CREATE TABLE|ALTER TABLE|createTable|addColumn", content)),
        })

    # Models discovered in migrations but not declared in code (raw SQL projects).
    known_tables = {model["table"] for model in models if model.get("table")}
    for migration in migrations:
        for table in migration["tables"]:
            if table in known_tables:
                continue
            known_tables.add(table)
            models.append({
                "id": stable_id("model-migration", scope, migration["path"], table),
                "name": _class_name(table), "table": table, "orm": "migration",
                "file_path": migration["path"], "line": None, "fields": [], "relationships": [],
                "source": "migration", "bases": [],
                "notes": "Table declared in a migration; no model class found in code.",
            })

    # Relation graph between models (for the ER view).
    relations: list[dict] = []
    table_to_model = {model["table"]: model for model in models if model.get("table")}
    model_by_name = {model["name"]: model for model in models}
    for model in models:
        for relationship in model.get("relationships", []):
            target_name = relationship.get("target")
            target = model_by_name.get(target_name) or table_to_model.get(target_name)
            relations.append({
                "source": model["name"],
                "source_table": model.get("table"),
                "target": target["name"] if target else target_name,
                "target_table": target.get("table") if target else relationship.get("target_field"),
                "kind": relationship.get("kind", "relation"),
                "field": relationship.get("field") or relationship.get("name"),
                "resolved": bool(target),
            })

    query_by_table: dict[str, int] = defaultdict(int)
    for query in queries:
        if query["table"]:
            query_by_table[query["table"]] += 1
    for model in models:
        model["query_count"] = query_by_table.get(model.get("table") or "", 0)

    notes: list[str] = []
    if not models and not migrations:
        notes.append("No ORM models, entity classes or migration files were detected. Database usage may be raw SQL "
                     "in application code, or this repository may not own its schema.")
    if any(model["orm"] == "migration" for model in models):
        notes.append("Some tables are known only from migration files - their columns could not be read statically.")
    if queries and all(query["orm"] in {"raw SQL", "SQLAlchemy", "DB-API", None} for query in queries):
        notes.append("Query extraction for this stack is best-effort: dynamic query builders can hide statements.")

    return {
        "technologies": technologies,
        "models": sorted(models, key=lambda item: (item["name"].lower(),)),
        "queries": sorted(queries, key=lambda item: (item["file_path"], item["line"] or 0))[:800],
        "migrations": sorted(migrations, key=lambda item: item["path"]),
        "relations": relations[:300],
        "orms": sorted(orms - {"unknown"}),
        "notes": notes,
        "stats": {
            "models": len(models),
            "tables": len(known_tables),
            "queries": len(queries),
            "migrations": len(migrations),
            "relations": len(relations),
            "by_kind": dict(sorted(
                ((kind, sum(1 for query in queries if query["kind"] == kind)) for kind in {query["kind"] for query in queries}),
                key=lambda item: -item[1])),
        },
    }


def _migration_framework(path: str, content: str) -> str | None:
    if "alembic" in path.lower() or "op.create_table" in content or "import op" in content:
        return "Alembic"
    if "prisma" in path.lower():
        return "Prisma Migrate"
    if "migrate" in path.lower() and "def up" in content:
        return "SQLalchemy-Migrate / Rails style"
    if path.endswith(".sql"):
        return "Raw SQL"
    return None


def _class_name(table: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_\s]+", table))
