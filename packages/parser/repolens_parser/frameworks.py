"""Manifest parsing, framework/database detection and language statistics."""

from __future__ import annotations

import json
import re
import tomllib
from collections import defaultdict
from typing import Iterable

from repolens_shared.constants import DATABASE_MARKERS, FRAMEWORK_MARKERS, LANGUAGE_LABELS, MANIFEST_FILES
from repolens_shared.utils import language_label
from repolens_shared.utils import truncate

from .types import ParsedFile


# --------------------------------------------------------------------------- #
# Manifests
# --------------------------------------------------------------------------- #

def _clean_package_name(spec: str) -> str:
    name = spec.strip()
    name = re.split(r"[<>=!~;\[\s(]", name)[0]
    return name.strip().strip("\"',")


def parse_package_json(content: str) -> dict:
    data = json.loads(content)
    deps: list[dict] = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for name, version in (data.get(section) or {}).items():
            deps.append({"name": name, "version": str(version), "kind": section.replace("Dependencies", "").lower() or "dependency",
                         "ecosystem": "npm"})
    scripts = data.get("scripts") or {}
    return {
        "ecosystem": "npm",
        "name": data.get("name"),
        "version": data.get("version"),
        "dependencies": deps,
        "scripts": {k: truncate(str(v), 160) for k, v in list(scripts.items())[:40]},
        "engines": data.get("engines") or {},
        "package_manager": data.get("packageManager"),
    }


def parse_requirements(content: str) -> dict:
    deps: list[dict] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-", "git+", "http")):
            if line.startswith(("-e ", "--editable")) and "=" in line:
                pass
            continue
        name = _clean_package_name(line)
        if not name or name.startswith("."):
            continue
        version = line[len(name):].strip() if len(line) > len(name) else ""
        deps.append({"name": name, "version": version.strip(), "kind": "dependency", "ecosystem": "pip"})
    return {"ecosystem": "pip", "dependencies": deps, "scripts": {}}


def parse_pyproject(content: str) -> dict:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return {"ecosystem": "python", "dependencies": [], "scripts": {}, "error": "pyproject.toml could not be parsed"}
    project = data.get("project") or {}
    deps: list[dict] = []
    for spec in project.get("dependencies") or []:
        name = _clean_package_name(str(spec))
        if name:
            deps.append({"name": name, "version": str(spec)[len(name):].strip(), "kind": "dependency", "ecosystem": "pip"})
    for group, items in (project.get("optional-dependencies") or {}).items():
        for spec in items:
            name = _clean_package_name(str(spec))
            if name:
                deps.append({"name": name, "version": str(spec)[len(name):].strip(), "kind": f"optional:{group}", "ecosystem": "pip"})
    poetry = ((data.get("tool") or {}).get("poetry") or {})
    for name, version in (poetry.get("dependencies") or {}).items():
        if name.lower() == "python":
            continue
        deps.append({"name": name, "version": str(version) if not isinstance(version, dict) else str(version.get("version", "")),
                     "kind": "dependency", "ecosystem": "pip"})
    scripts = {**(poetry.get("scripts") or {}), **((data.get("tool") or {}).get("poetry", {}).get("plugins") or {})}
    return {"ecosystem": "python", "name": project.get("name") or poetry.get("name"),
            "version": project.get("version"), "dependencies": deps,
            "scripts": {k: truncate(str(v), 160) for k, v in list(scripts.items())[:40]}}


def parse_go_mod(content: str) -> dict:
    deps: list[dict] = []
    module = None
    for match in re.finditer(r"^\s*(?:require\s+)?([\w.\-]+\.[\w.\-]+/\S+)\s+(v\S+)", content, re.MULTILINE):
        deps.append({"name": match.group(1), "version": match.group(2), "kind": "dependency", "ecosystem": "go"})
    module_match = re.search(r"^module\s+(\S+)", content, re.MULTILINE)
    if module_match:
        module = module_match.group(1)
    return {"ecosystem": "go", "name": module, "dependencies": deps, "scripts": {}}


def parse_cargo_toml(content: str) -> dict:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return {"ecosystem": "cargo", "dependencies": [], "scripts": {}}
    deps: list[dict] = []
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        for name, spec in (data.get(section) or {}).items():
            version = spec if isinstance(spec, str) else str(spec.get("version", "")) if isinstance(spec, dict) else ""
            deps.append({"name": name, "version": version, "kind": section.replace("-dependencies", ""), "ecosystem": "cargo"})
    package = data.get("package") or {}
    return {"ecosystem": "cargo", "name": package.get("name"), "version": package.get("version"),
            "dependencies": deps, "scripts": {}}


def parse_composer_json(content: str) -> dict:
    data = json.loads(content)
    deps: list[dict] = []
    for section in ("require", "require-dev"):
        for name, version in (data.get(section) or {}).items():
            deps.append({"name": name, "version": str(version), "kind": section.replace("require", "").strip("-") or "dependency",
                         "ecosystem": "composer"})
    return {"ecosystem": "composer", "name": data.get("name"), "dependencies": deps,
            "scripts": data.get("scripts") or {}}


def parse_gemfile(content: str) -> dict:
    deps = [{"name": m.group(1), "version": m.group(2) or "", "kind": "dependency", "ecosystem": "gem"}
            for m in re.finditer(r"gem\s+['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?", content)]
    return {"ecosystem": "gem", "dependencies": deps, "scripts": {}}


def parse_maven(content: str) -> dict:
    deps = [{"name": f"{m.group(1)}:{m.group(2)}", "version": m.group(3) or "", "kind": "dependency", "ecosystem": "maven"}
            for m in re.finditer(r"<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>\s*(?:<version>([^<]+)</version>)?", content)]
    return {"ecosystem": "maven", "dependencies": deps, "scripts": {}}


def parse_gradle(content: str) -> dict:
    deps: list[dict] = []
    for match in re.finditer(r"(implementation|api|compileOnly|testImplementation)\s*[('\"]\s*([\w.\-]+):([\w.\-]+):?([\w.\-]*)", content):
        deps.append({"name": f"{match.group(2)}:{match.group(3)}", "version": match.group(4),
                     "kind": match.group(1), "ecosystem": "gradle"})
    return {"ecosystem": "gradle", "dependencies": deps, "scripts": {}}


PARSERS = {
    "package.json": parse_package_json,
    "requirements.txt": parse_requirements,
    "pyproject.toml": parse_pyproject,
    "setup.py": lambda content: parse_requirements(re.sub(r"[^\w\n.,=<>\"'-]", "\n", content)),
    "go.mod": parse_go_mod,
    "Cargo.toml": parse_cargo_toml,
    "composer.json": parse_composer_json,
    "Gemfile": parse_gemfile,
    "pom.xml": parse_maven,
    "build.gradle": parse_gradle,
}


def detect_manifests(files: dict[str, str]) -> list[dict]:
    """Parse every recognised manifest found in the repository (including
    nested ones, e.g. monorepo workspaces - capped for sanity)."""
    manifests: list[dict] = []
    budget = 12
    for path, content in sorted(files.items()):
        name = path.rsplit("/", 1)[-1]
        if name not in MANIFEST_FILES or name == "Dockerfile":
            continue
        parser = PARSERS.get(name)
        if parser is None:
            continue
        if budget <= 0:
            break
        try:
            parsed = parser(content)
        except Exception as exc:  # a broken manifest must not fail the run
            parsed = {"ecosystem": MANIFEST_FILES.get(name, "unknown"), "dependencies": [], "scripts": {},
                      "error": f"{type(exc).__name__}: {exc}"}
        parsed["path"] = path
        parsed["kind"] = MANIFEST_FILES.get(name, "unknown")
        parsed["dependencies"] = parsed.get("dependencies", [])[:400]
        manifests.append(parsed)
        budget -= 1
    return manifests


def dependency_map(manifests: Iterable[dict]) -> dict[str, dict]:
    """name -> {version, ecosystem, declared_in: [...]}"""
    out: dict[str, dict] = {}
    for manifest in manifests:
        for dep in manifest.get("dependencies", []):
            key = str(dep.get("name", "")).lower()
            if not key:
                continue
            entry = out.setdefault(key, {"name": dep["name"], "version": dep.get("version") or "",
                                         "ecosystem": dep.get("ecosystem") or manifest.get("ecosystem"),
                                         "declared_in": []})
            if manifest["path"] not in entry["declared_in"]:
                entry["declared_in"].append(manifest["path"])
            if not entry["version"] and dep.get("version"):
                entry["version"] = dep["version"]
    return out


# --------------------------------------------------------------------------- #
# Framework & database detection
# --------------------------------------------------------------------------- #

def _evidence_label(source: str, value: str) -> str:
    return f"{source}: {truncate(value, 70)}"


def detect_frameworks(manifests: list[dict], parsed_files: list[ParsedFile], files: dict[str, str]) -> list[dict]:
    dependencies = dependency_map(manifests)
    file_names = {path.rsplit("/", 1)[-1] for path in files}
    code_hints: dict[str, set[str]] = defaultdict(set)  # framework -> file paths

    # lightweight textual markers, sampled across at most 400 files
    sampled = list(parsed_files)[:400]
    for parsed in sampled:
        for hint in parsed.framework_hints:
            code_hints[hint].add(parsed.path)

    found: dict[str, dict] = {}
    for framework, ecosystem, markers in FRAMEWORK_MARKERS:
        evidence: list[str] = []
        score = 0.0
        for marker in markers:
            if marker in dependencies:
                entry = dependencies[marker]
                evidence.append(f"dependency `{marker}`{(' ' + entry['version']) if entry['version'] else ''} ({entry['declared_in'][0]})")
                score += 0.75
            elif marker in file_names:
                evidence.append(f"file `{marker}` present")
                score += 0.7
            elif marker.endswith("/") and any(marker.rstrip("/") in path.split("/") for path in files):
                evidence.append(f"directory `{marker}` present")
                score += 0.6
            elif "." in marker and marker.count(".") == 1 and marker.split(".")[-1] in {"js", "ts", "json", "yml", "yaml", "ini", "toml"}:
                if marker in file_names or any(p.endswith(marker) for p in files):
                    evidence.append(f"config file `{marker}` present")
                    score += 0.6
        for hint, paths in code_hints.items():
            if hint == framework or hint.startswith(framework):
                evidence.append(f"code usage in {next(iter(sorted(paths)))}" + (f" (+{len(paths) - 1} more)" if len(paths) > 1 else ""))
                score += 0.55
                break
        if score <= 0:
            continue
        confidence = min(0.99, round(min(1.0, score), 2))
        found[framework] = {
            "name": framework,
            "ecosystem": ecosystem,
            "confidence": confidence,
            "evidence": sorted(set(evidence))[:4],
        }

    # Filter weak, overlapping python-ecosystem noise (e.g. "Pydantic" via BaseModel only)
    ordered = sorted(found.values(), key=lambda item: (-item["confidence"], item["name"]))
    return ordered[:40]


def detect_databases(manifests: list[dict], parsed_files: list[ParsedFile], files: dict[str, str]) -> list[dict]:
    dependencies = dependency_map(manifests)
    lowered_paths = [path.lower() for path in files]
    found: dict[str, dict] = {}
    for name, kind, markers in DATABASE_MARKERS:
        evidence: list[str] = []
        score = 0.0
        for marker in markers:
            key = marker.lower().strip("\"'")
            if key in dependencies:
                entry = dependencies[key]
                evidence.append(f"dependency `{entry['name']}` ({entry['declared_in'][0]})")
                score += 0.7
        if name == "PostgreSQL":
            if any("docker-compose" in path for path in lowered_paths) and "postgres" in "".join(
                files.get(path, "") for path in files if "docker-compose" in path.title().lower()
            ).lower():
                evidence.append("docker-compose service references postgres")
                score += 0.5
            if any(re.search(r"postgres(ql)?://", files.get(path, "")) for path in files if path.endswith((".env.example", ".env.sample", "settings.py", "config.py", "database.py"))):
                evidence.append("postgres connection string found in configuration")
                score += 0.5
        if name == "SQLite":
            if any(re.search(r"sqlite:///|:\s*['\"]?sqlite", files.get(path, "")) for path in files if path.endswith((".py", ".ts", ".js", ".env.example", ".yaml", ".yml"))):
                evidence.append("sqlite connection string found")
                score += 0.5
        if score <= 0:
            continue
        found[name] = {"name": name, "kind": kind, "confidence": round(min(1.0, score), 2), "evidence": sorted(set(evidence))[:4]}

    for parsed in parsed_files[:400]:
        for hint in parsed.framework_hints:
            if hint in {"Prisma", "TypeORM", "Sequelize", "Mongoose", "Knex", "Drizzle ORM", "SQLAlchemy", "Django ORM", "SQLModel", "MongoEngine", "GORM"}:
                key = hint
                entry = found.setdefault(key, {"name": hint, "kind": "orm", "confidence": 0.6, "evidence": []})
                entry["confidence"] = min(0.95, round(entry["confidence"] + 0.25, 2))
                marker = f"ORM usage detected in {parsed.path}"
                if marker not in entry["evidence"] and len(entry["evidence"]) < 4:
                    entry["evidence"].append(marker)
    return sorted(found.values(), key=lambda item: (-item["confidence"], item["name"]))


# --------------------------------------------------------------------------- #
# Language statistics
# --------------------------------------------------------------------------- #

def language_stats(parsed_files: list[ParsedFile]) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(lambda: {"files": 0, "loc": 0})
    for parsed in parsed_files:
        bucket = buckets[parsed.language]
        bucket["files"] += 1
        bucket["loc"] += parsed.loc
    total_loc = sum(b["loc"] for b in buckets.values()) or 1
    stats = []
    for language, bucket in buckets.items():
        stats.append({
            "language": language,
            "label": LANGUAGE_LABELS.get(language, language_label(language)),
            "files": bucket["files"],
            "loc": bucket["loc"],
            "percent": round(bucket["loc"] / total_loc * 100, 1),
        })
    return sorted(stats, key=lambda item: (-item["loc"], item["language"]))
