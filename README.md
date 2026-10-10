# RepoLens

**Codebase intelligence for any public GitHub repository.** Paste a GitHub URL and get a navigable model
of how the repository works: architecture layers, traced workflows, the API surface, the data model,
the dependency graph, quality signals, ranked code search and impact analysis.

RepoLens is not a GitHub viewer. It downloads the source through the GitHub API, parses every supported
file with tree-sitter (and Python's AST for `.py`), resolves imports and calls across files, builds a
graph, and detects routes, models, queries and workflows. Every number on screen comes from that parsed
evidence. Anything heuristic is labelled as such.

![Overview](docs/screenshots/overview.png)

| Screen | What it shows |
|---|---|
| **Architecture** | Layer graph from frontend to API, services and data, with per-layer detail |
| **Workflows** | Auto-traced flows with step and sequence views |
| **Dependencies** | Module graph, cycles, hubs and isolated modules |
| **APIs** | Routes with method, handler, service, auth and provenance badges |
| **Database** | Models, fields, relations and the query inventory |
| **Code Explorer** | Source with symbols, references and jump-to-file |
| **Quality** | Complexity, coupling, cycles and missing tests (labelled as heuristics) |
| **Impact** | Dependents, affected endpoints and workflows, related tests and risks |
| **Reports** | README, API and onboarding drafts and a JSON export |

## How storage works

RepoLens never saves a repository to your disk.

* **Results are held in memory** by default. Nothing is written to a file, so the app uses almost no
  disk space. Results are cleared when the API restarts.
* **Optional hosted database.** Set `DATABASE_URL` to a Postgres URL (for example a free Neon database)
  to keep results across restarts. Nothing is stored locally in this mode either.
* **Source code is not kept.** The repository is downloaded to a temporary folder, analysed, and deleted
  when the run ends. The Code Explorer fetches a file from GitHub when you open it.
* **Overwrite, not history.** Re-analysing a repository replaces its previous result. Only the newest
  `MAX_STORED_RUNS` analyses (default 8) are kept across all repositories.
* **No AI.** Analysis, search and impact are deterministic. Nothing is sent to a language model.

## Quick start (local)

Requirements: Python 3.11+ and Node.js 20+.

```bash
git clone <this repo> repolens && cd repolens

# 1. API
python -m venv .venv && source .venv/bin/activate
pip install -e packages/shared -e packages/parser -e packages/graph -e apps/api
cp .env.example .env                  # optional: add GITHUB_TOKEN, or DATABASE_URL for Neon
cd apps/api && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. Web app (second terminal)
cd apps/web && npm install
API_INTERNAL_URL=http://127.0.0.1:8000 npm run dev      # http://localhost:3000
```

Paste `https://github.com/fastapi/full-stack-fastapi-template` into the header and press **Analyze**.

## Quick start (Docker)

```bash
cp .env.example .env          # optional
docker compose up --build     # web on http://localhost:3000, API on http://localhost:8000
```

The stack has two services, `api` and `web`. The web server proxies `/backend/*` to the API on the
internal network, so the browser only talks to one origin. There are no volumes, because nothing is
written to disk.

## Features

| Area | What you get |
|---|---|
| **Overview** | Languages, frameworks, counts, database technologies, run status, insights |
| **Architecture** | Layer graph (frontend → API → services → data) with per-layer files and connections |
| **Workflows** | Auto-traced flows from routes and UI entry points through services to data, with step and sequence views |
| **Dependencies** | Module graph, import and call edges, cycles, hubs, isolated modules |
| **APIs** | Method, path, handler, service, auth, provenance badges, Markdown export |
| **Database** | Technologies, models and fields, relations, query inventory |
| **Code Explorer** | Source viewer with symbols, references, imports and dependents |
| **Search** | Ranked keyword search over symbols, file paths and code, plus exact text search |
| **Quality** | Complexity, coupling, cycles, large modules, duplication, missing tests (heuristics, labelled) |
| **Impact Analysis** | Dependents, transitive reach, affected endpoints and workflows, related tests, risks |
| **Reports** | README, API and onboarding drafts built from the analysis, plus a full JSON bundle |

## How an analysis runs

```
GitHub URL ──▶ validate + metadata (GitHub API)
            ──▶ download sources to a temporary folder (deleted at the end of the run)
            ──▶ walk files (limits, ignores, binary and large-file skip)
            ──▶ parse each file      tree-sitter for 20+ languages, Python AST for .py
                                     └─ per-file failures are warnings, never fatal
            ──▶ resolve imports      internal / external / unresolved, router prefixes
            ──▶ build graph          code-module nodes, import + call edges, cycles, hubs
            ──▶ detect               frameworks, endpoints, DB models/queries, layers
            ──▶ trace workflows      from entry points through services to data
            ──▶ quality + insights   complexity, coupling, duplication, missing tests
            ──▶ index for search     symbol, file and doc chunks (text only)
            ──▶ store results        in memory, or in DATABASE_URL when set
```

Every stage reports progress and can be cancelled. A run that exceeds `MAX_ANALYSIS_SECONDS` (default
30 minutes) fails with a clear message.

### Scope rules (what is *not* counted)

* **Documentation and assets stay out of the graph.** Only files that can carry dependencies become
  graph nodes. `docs/`, `.rst`, Markdown, data and image files are indexed and searchable, but they are
  never counted as isolated modules or hubs.
* **Endpoints are deduplicated by `method + path`.** When the same URL is declared in several files, the
  application's own declaration wins. Other declarations are kept with an `is_example` / `is_test` flag,
  so a library repository reports "33 endpoints, all declared in example or test applications" instead
  of inventing an API surface.
* **Workflows are scoped the same way** (`application`, `example` or `test`, with a `scope_note`).
* **Large files are skipped.** Files over `MAX_FILE_BYTES` (default 1 MiB) are not parsed, because minified
  or generated files slow parsing and produce meaningless symbols. Skipped files are counted in the run summary.

### Grounding rules

* Counts, paths, line numbers, endpoints, models and workflows come from parser output.
* Detections carry `confidence` and `evidence[]`. Quality findings are marked `heuristic: true`. Traces
  flag `trace_truncated` when static resolution runs out of road.
* Impact analysis runs on the stored graph, so the numbers are the same everywhere they appear.

## Repository layout

```
repolens/
├── apps/
│   ├── api/                        FastAPI service
│   │   └── app/
│   │       ├── api/                routes: system, repos, analyses, insights
│   │       ├── analyzers/          endpoints, database, insights, docs, pipeline
│   │       ├── core/               config, db (memory or DATABASE_URL), logging, errors, capabilities
│   │       ├── models/tables.py    analysis-scoped tables
│   │       └── services/           github, store, search (lexical), analysis manager, impact
│   └── web/                        Next.js 15 + Tailwind UI
│       ├── app/                    one route per product area
│       ├── components/             UI primitives, graphs, explorer
│       └── lib/                    typed API client, hooks, types
├── packages/
│   ├── shared/                     constants, schemas, errors
│   ├── parser/                     tree-sitter and Python AST analyzers, import resolvers, framework detection
│   └── graph/                      dependency graph, layers, workflow tracer, impact, quality
├── infrastructure/docker/          api.Dockerfile, web.Dockerfile
├── docker-compose.yml              api + web
└── .env.example                    every setting, documented
```

## Configuration

Everything is set through environment variables. See [`.env.example`](.env.example) for the full list.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | empty (in memory) | Optional Postgres URL, for example Neon |
| `MAX_STORED_RUNS` | `8` | Newest analyses kept across all repositories |
| `GITHUB_TOKEN` | empty | Higher GitHub rate limit and private repositories you can access |
| `MAX_ANALYSIS_SECONDS` | `1800` | Time limit per analysis (`0` = none) |
| `MAX_REPO_BYTES` | `0` | Optional download size cap (`0` = none) |
| `MAX_FILES` / `MAX_FILE_BYTES` | `4000` / `1048576` | Files parsed per run, and the per-file size skip |
| `ANALYSIS_WORKERS` | `2` | Concurrent analyses |
| `CORS_ORIGINS` | localhost:3000 | Allowed browser origins when calling the API directly |

`GET /api/system/capabilities` reports what the running service is actually doing, including the
storage mode.

## API reference

While the API is running, every endpoint, with request and response shapes, is listed at
`http://localhost:8000/docs` (generated by FastAPI). `GET /api/health` reports whether the service is up.

## Limits and honesty notes

* Static analysis cannot see dynamic dispatch, dependency-injection containers, string-based routing or
  reflection. Each view says where its knowledge stops.
* Layers are derived from path conventions and resolvable edges, and are marked *heuristic*.
* Language depth: Python, TypeScript, JavaScript, Go, Java, Ruby, PHP, Rust, C#, C/C++, and Vue/Svelte are
  parsed into symbols and edges. SQL, GraphQL, Proto, YAML/JSON/TOML, Markdown, shell and Dockerfiles are
  indexed for search but not parsed into symbols.
* The app runs as a single API process, because results are held by that process. Scale out only with
  `DATABASE_URL` set and a plan for shared analysis workers.
* Not implemented: notifications and pull-request or branch diffing.
