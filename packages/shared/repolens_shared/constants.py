"""Language, framework and analysis-stage knowledge base.

Nothing in here is repository specific - it is the vocabulary the analyzers use
to describe what they found in a real repository.
"""

from __future__ import annotations

from enum import Enum

# --------------------------------------------------------------------- stages
class Stage(str, Enum):
    QUEUED = "queued"
    RESOLVING = "resolving"
    FETCHING = "fetching"
    DETECTING = "detecting"
    PARSING = "parsing"
    EXTRACTING_APIS = "extracting_apis"
    EXTRACTING_DATABASE = "extracting_database"
    GRAPHING = "graphing"
    WORKFLOWS = "workflows"
    QUALITY = "quality"
    EMBEDDING = "embedding"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Ordered pipeline description used for progress reporting and the UI stepper.
ANALYSIS_STAGES: list[dict] = [
    {"id": Stage.QUEUED, "label": "Queued", "weight": 0.02},
    {"id": Stage.RESOLVING, "label": "Resolving repository", "weight": 0.06},
    {"id": Stage.FETCHING, "label": "Fetching sources", "weight": 0.20},
    {"id": Stage.DETECTING, "label": "Detecting languages & frameworks", "weight": 0.08},
    {"id": Stage.PARSING, "label": "Parsing with tree-sitter", "weight": 0.24},
    {"id": Stage.EXTRACTING_APIS, "label": "Extracting API surface", "weight": 0.08},
    {"id": Stage.EXTRACTING_DATABASE, "label": "Extracting database layer", "weight": 0.08},
    {"id": Stage.GRAPHING, "label": "Building dependency graph", "weight": 0.10},
    {"id": Stage.WORKFLOWS, "label": "Detecting workflows", "weight": 0.06},
    {"id": Stage.QUALITY, "label": "Code quality analysis", "weight": 0.05},
    {"id": Stage.EMBEDDING, "label": "Generating embeddings", "weight": 0.03},
]

STAGE_RANK: dict[str, int] = {str(s["id"].value if isinstance(s["id"], Stage) else s["id"]): i for i, s in enumerate(ANALYSIS_STAGES)}


# ------------------------------------------------------------------ languages
class Language(str, Enum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    TSX = "tsx"
    JAVASCRIPT = "javascript"
    JSX = "jsx"
    GO = "go"
    JAVA = "java"
    RUBY = "ruby"
    PHP = "php"
    RUST = "rust"
    CSHARP = "csharp"
    C = "c"
    CPP = "cpp"
    KOTLIN = "kotlin"
    SWIFT = "swift"
    SCALA = "scala"
    SQL = "sql"
    PRISMA = "prisma"
    GRAPHQL = "graphql"
    PROTO = "proto"
    SHELL = "shell"
    YAML = "yaml"
    JSON = "json"
    MARKDOWN = "markdown"
    HTML = "html"
    CSS = "css"
    XML = "xml"
    RESTRUCTUREDTEXT = "restructuredtext"
    TEXT = "text"
    TOML = "toml"
    INI = "ini"
    BATCH = "batch"
    DOCKER = "docker"
    MAKE = "make"
    VUE = "vue"
    SVELTE = "svelte"
    UNKNOWN = "unknown"


LANGUAGE_LABELS: dict[str, str] = {
    "python": "Python", "typescript": "TypeScript", "tsx": "TypeScript (TSX)",
    "javascript": "JavaScript", "jsx": "JavaScript (JSX)", "go": "Go", "java": "Java",
    "ruby": "Ruby", "php": "PHP", "rust": "Rust", "csharp": "C#", "c": "C", "cpp": "C++",
    "kotlin": "Kotlin", "swift": "Swift", "scala": "Scala", "sql": "SQL", "prisma": "Prisma",
    "graphql": "GraphQL", "proto": "Protocol Buffers", "shell": "Shell", "yaml": "YAML",
    "json": "JSON", "markdown": "Markdown", "html": "HTML", "css": "CSS",
    "xml": "XML", "restructuredtext": "reStructuredText", "text": "Plain text",
    "toml": "TOML", "ini": "INI / config", "batch": "Batch", "docker": "Dockerfile",
    "make": "Make", "vue": "Vue", "svelte": "Svelte", "unknown": "Other (unrecognised)",
}

#: Only these languages have tree-sitter parsers wired up in `packages/parser`.
TREE_SITTER_LANGUAGES: set[str] = {
    "python", "typescript", "tsx", "javascript", "jsx", "go", "java", "ruby", "php", "rust",
    "c", "cpp", "csharp",
}

#: Languages we can read and index, but not deep-parse. Recorded honestly as
#: "indexed, symbols unavailable" rather than silently pretending to parse.
TEXT_INDEXED_LANGUAGES: set[str] = {
    "sql", "prisma", "graphql", "proto", "shell", "yaml", "json", "markdown", "html", "css",
    "xml", "restructuredtext", "text", "toml", "ini", "batch", "docker", "make", "vue", "svelte",
}

#: Languages whose files can carry dependencies, i.e. they take part in the
#: dependency graph. Documentation, data files and assets are excluded from the
#: graph so orphans, hubs and cycles describe the code rather than the docs
#: folder. A file outside this set is still included when a resolved edge points
#: at it (for example a stylesheet imported by a component).
GRAPH_LANGUAGES: set[str] = set(TREE_SITTER_LANGUAGES) | {"vue", "svelte"}

#: Languages that are prose, not code - used to keep documentation out of code
#: heuristics (workflow seeds, quality findings, graph nodes).
DOC_LANGUAGES: set[str] = {"markdown", "restructuredtext", "text"}

#: Path fragments that mark example / demo / sample code, which is useful context
#: but should never be mistaken for the application's real surface.
EXAMPLE_PATH_PATTERNS: tuple[str, ...] = (
    "examples/", "example/", "samples/", "sample/", "demos/", "demo/", "snippets/", "tutorials/",
)

#: Files without a useful extension, matched on their (lower-cased) name.
LANGUAGE_BY_NAME: dict[str, str] = {
    "dockerfile": "docker", "docker-compose.yml": "yaml", "docker-compose.yaml": "yaml",
    "makefile": "make", "gnumakefile": "make", "cmakelists.txt": "make",
    ".editorconfig": "ini", ".flake8": "ini", ".pylintrc": "ini", ".babelrc": "json",
    ".gitignore": "text", ".dockerignore": "text", ".npmignore": "text", ".gitattributes": "text",
    ".env": "ini", ".env.example": "ini", ".env.local": "ini", ".env.sample": "ini",
    ".prettierrc": "json", ".eslintrc": "json", ".eslintrc.json": "json", ".gitkeep": "text",
    ".coveragerc": "ini", ".nojekyll": "text", ".git-blame-ignore-revs": "text", ".hgignore": "text",
    "gemfile": "ruby", "rakefile": "ruby", "vagrantfile": "ruby", "brewfile": "ruby", "guardfile": "ruby",
    "procfile": "text", "jenkinsfile": "text", "pipfile": "toml", "pipfile.lock": "json",
}

LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "python", ".pyi": "python", ".pyx": "python",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".tsx": "tsx", ".jsx": "jsx",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby", ".rake": "ruby", ".gemspec": "ruby",
    ".php": "php",
    ".rs": "rust",
    ".cs": "csharp",
    ".c": "c", ".h": "cpp",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".sql": "sql",
    ".prisma": "prisma",
    ".graphql": "graphql", ".gql": "graphql",
    ".proto": "proto",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".fish": "shell",
    ".yml": "yaml", ".yaml": "yaml",
    ".json": "json", ".jsonc": "json", ".json5": "json",
    ".md": "markdown", ".mdx": "markdown",
    ".rst": "restructuredtext", ".rest": "restructuredtext",
    ".txt": "text", ".text": "text",
    ".toml": "toml",
    ".ini": "ini", ".cfg": "ini", ".conf": "ini", ".properties": "ini", ".editorconfig": "ini",
    ".env": "ini", ".env.example": "ini", ".flake8": "ini", ".pylintrc": "ini",
    ".bat": "batch", ".cmd": "batch",
    ".vue": "vue", ".svelte": "svelte",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "css", ".sass": "css", ".less": "css",
    ".xml": "xml", ".xsd": "xml", ".xsl": "xml", ".plist": "xml", ".pom": "xml",
    ".csproj": "xml", ".props": "xml", ".targets": "xml", ".svg": "xml",
    ".mk": "make", ".mak": "make", ".dockerfile": "docker",
    # Certificates, keystores, templates and other plain-text assets: indexed,
    # never parsed, but no longer reported as "unrecognised".
    ".pem": "text", ".crt": "text", ".cer": "text", ".key": "text", ".csr": "text",
    ".srl": "text", ".cnf": "ini", ".in": "text", ".j2": "text", ".jinja": "text",
    ".jinja2": "text", ".mustache": "text", ".erb": "text", ".tmpl": "text", ".tpl": "text",
    ".mako": "text", ".stub": "text", "._tmpl": "text",
}

BINARY_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".svgz", ".pdf", ".zip", ".gz",
    ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war", ".class", ".pyc", ".pyo", ".so",
    ".dylib", ".dll", ".exe", ".bin", ".o", ".a", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".mov", ".avi", ".wav", ".ogg", ".webm", ".sqlite", ".db", ".parquet",
    ".onnx", ".pt", ".pth", ".h5", ".pkl", ".npy", ".npz", ".wasm", ".node", ".map", ".lock",
}

DEFAULT_IGNORED_DIRS: set[str] = {
    ".git", ".github/ISSUE_TEMPLATE", "node_modules", ".next", ".nuxt", ".svelte-kit",
    "dist", "build", "out", "target", "bin", "obj", "vendor", "__pycache__", ".venv", "venv",
    "env", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".cache", "coverage",
    ".idea", ".vscode", "site-packages", ".terraform", ".gradle", ".mvn", ".dart_tool",
    "Pods", "DerivedData", ".angular", ".expo", ".turbo", "storybook-static", "htmlcov",
}

DEFAULT_IGNORED_FILE_SUFFIXES: tuple[str, ...] = (
    ".min.js", ".min.css", ".bundle.js", ".map", ".lock", "-lock.json", "package-lock.json",
    "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "uv.lock", "Cargo.lock",
    "composer.lock", "Gemfile.lock",
)

#: Directories whose contents are considered tests (used by impact analysis and
#: the "missing tests" heuristic).
TEST_PATH_PATTERNS: tuple[str, ...] = (
    "test/", "tests/", "__tests__/", "spec/", "specs/", "e2e/", "cypress/",
)


# ----------------------------------------------------------------- frameworks
#: (framework, ecosystem, [dependency names / config files / code markers])
FRAMEWORK_MARKERS: list[tuple[str, str, tuple[str, ...]]] = [
    # --- Python
    ("FastAPI", "python", ("fastapi", "from fastapi import", "FastAPI(")),
    ("Django", "python", ("django", "from django", "manage.py")),
    ("Django REST Framework", "python", ("rest_framework", "from rest_framework")),
    ("Flask", "python", ("flask", "from flask import", "Flask(__name__)")),
    ("SQLAlchemy", "python", ("sqlalchemy", "from sqlalchemy", "__tablename__")),
    ("Alembic", "python", ("alembic", "alembic.ini")),
    ("Celery", "python", ("celery",)),
    ("Pydantic", "python", ("pydantic", "BaseModel")),
    ("Pytest", "python", ("pytest",)),
    ("Starlette", "python", ("starlette",)),
    ("Gunicorn", "python", ("gunicorn",)),
    ("Uvicorn", "python", ("uvicorn",)),
    # --- JavaScript / TypeScript
    ("Next.js", "javascript", ("next", "next.config.js", "next.config.mjs", "next.config.ts")),
    ("React", "javascript", ("react", "\"react\":", "from 'react'", 'from "react"')),
    ("Vue", "javascript", ("vue",)),
    ("Nuxt", "javascript", ("nuxt",)),
    ("Angular", "javascript", ("@angular/core", "angular.json")),
    ("Svelte", "javascript", ("svelte", "@sveltejs/kit")),
    ("Express", "javascript", ("express", "require('express')")),
    ("NestJS", "javascript", ("@nestjs/core", "@Controller(", "@Injectable()")),
    ("Fastify", "javascript", ("fastify",)),
    ("Koa", "javascript", ("koa",)),
    ("Prisma", "javascript", ("prisma", "@prisma/client", "schema.prisma")),
    ("TypeORM", "javascript", ("typeorm",)),
    ("Sequelize", "javascript", ("sequelize",)),
    ("Mongoose", "javascript", ("mongoose",)),
    ("Knex", "javascript", ("knex",)),
    ("Drizzle ORM", "javascript", ("drizzle-orm",)),
    ("tRPC", "javascript", ("@trpc/server",)),
    ("GraphQL (Apollo)", "javascript", ("@apollo/server", "apollo-server", "graphql")),
    ("Redux", "javascript", ("redux", "@reduxjs/toolkit")),
    ("TanStack Query", "javascript", ("@tanstack/react-query", "react-query")),
    ("Tailwind CSS", "javascript", ("tailwindcss",)),
    ("Jest", "javascript", ("jest",)),
    ("Vitest", "javascript", ("vitest",)),
    ("Playwright", "javascript", ("@playwright/test", "playwright")),
    ("Cypress", "javascript", ("cypress",)),
    ("Zustand", "javascript", ("zustand",)),
    ("Vite", "javascript", ("vite",)),
    # --- Other ecosystems
    ("Spring Boot", "java", ("spring-boot", "@RestController", "@SpringBootApplication")),
    ("Gin", "go", ("github.com/gin-gonic/gin",)),
    ("Echo", "go", ("github.com/labstack/echo",)),
    ("GORM", "go", ("gorm.io/gorm",)),
    ("Rails", "ruby", ("rails", "gem \"rails\"")),
    ("Sinatra", "ruby", ("sinatra",)),
    ("Laravel", "php", ("laravel", "Illuminate\\\\")),
    ("Symfony", "php", ("symfony/",)),
    ("Actix", "rust", ("actix-web",)),
    ("Axum", "rust", ("axum",)),
    ("Tauri", "rust", ("tauri",)),
    ("Docker", "infra", ("Dockerfile", "docker-compose.yml", "docker-compose.yaml")),
    ("GitHub Actions", "infra", (".github/workflows",)),
    ("Kubernetes", "infra", ("k8s/", "kubernetes/", "Chart.yaml")),
    ("Terraform", "infra", (".tf", "terraform")),
]

MANIFEST_FILES: dict[str, str] = {
    "package.json": "npm",
    "requirements.txt": "pip",
    "pyproject.toml": "python",
    "setup.py": "python",
    "Pipfile": "pipenv",
    "poetry.lock": "poetry",
    "go.mod": "go",
    "Cargo.toml": "cargo",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "composer.json": "composer",
    "Gemfile": "bundler",
    "pubspec.yaml": "pub",
    "mix.exs": "mix",
    "docker-compose.yml": "docker",
    "docker-compose.yaml": "docker",
    "Dockerfile": "docker",
}

#: Databases / datastores we can recognise from dependency + code evidence.
DATABASE_MARKERS: list[tuple[str, str, tuple[str, ...]]] = [
    ("PostgreSQL", "relational", ("postgres", "postgresql", "psycopg", "asyncpg", "pg", "\"pg\"", "libpq")),
    ("MySQL", "relational", ("mysql", "mysqlclient", "pymysql", "mariadb")),
    ("SQLite", "relational", ("sqlite", "aiosqlite", "better-sqlite3")),
    ("MongoDB", "document", ("mongodb", "mongoose", "pymongo", "motor")),
    ("Redis", "key-value", ("redis", "ioredis", "aioredis")),
    ("Elasticsearch", "search", ("elasticsearch", "@elastic/elasticsearch")),
    ("DynamoDB", "key-value", ("boto3", "dynamodb", "@aws-sdk/client-dynamodb")),
    ("Cassandra", "wide-column", ("cassandra", "scylla")),
    ("ClickHouse", "columnar", ("clickhouse",)),
    ("Neo4j", "graph", ("neo4j",)),
    ("Supabase", "baas", ("@supabase/supabase-js",)),
    ("Firebase Firestore", "document", ("firebase", "firestore")),
    ("Prisma", "orm", ("@prisma/client",)),
    ("pgvector", "vector", ("pgvector", "vector(")),
]

# ------------------------------------------------------------------ heuristics
#: Thresholds for the *heuristic* code-quality report. Every finding the UI
#: shows is labelled with the threshold that produced it.
QUALITY_THRESHOLDS: dict[str, float] = {
    "high_complexity": 15,        # cyclomatic complexity per function
    "large_module_loc": 700,      # lines of code per file
    "high_coupling_degree": 12,   # fan-in + fan-out
    "duplicate_min_lines": 8,     # function size before it is duplicate-checked
    "god_class_methods": 20,      # methods per class
}

#: Keywords used by workflow inference when naming/classifying a flow.
WORKFLOW_SIGNALS: dict[str, tuple[str, ...]] = {
    "auth": ("auth", "login", "signin", "sign-in", "session", "token", "jwt", "oauth", "password", "credential", "logout"),
    "signup": ("register", "signup", "sign-up", "onboard", "create_user", "createuser"),
    "payment": ("payment", "billing", "invoice", "checkout", "stripe", "subscription", "order", "cart", "purchase"),
    "upload": ("upload", "file", "attachment", "media", "asset", "storage", "s3"),
    "search": ("search", "query", "filter", "lookup"),
    "notification": ("notification", "email", "mail", "sms", "webhook", "push"),
    "crud": ("create", "update", "delete", "list", "get", "post", "put", "patch"),
    "realtime": ("websocket", "socket", "sse", "eventsource", "subscribe", "channel"),
}

#: Files that indicate CI / delivery workflows (surface in overview).
CI_PATH_HINTS: tuple[str, ...] = (".github/workflows", ".gitlab-ci.yml", "Jenkinsfile", ".circleci", "azure-pipelines", "bitbucket-pipelines")
