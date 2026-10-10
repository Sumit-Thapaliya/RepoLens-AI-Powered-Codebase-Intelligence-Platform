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

## How storage and sessions work

RepoLens downloads source into a per-analysis temporary directory, parses it without running repository code, and removes the checkout when analysis ends. A startup sweep also removes checkouts left by an ungraceful restart.

* **RAM-only by default.** With no `DATABASE_URL`, normalized analysis artifacts are held in an in-memory SQLite database and are cleared when the API process restarts.
* **Optional Postgres.** Setting `DATABASE_URL` retains completed analysis artifacts across restarts. Because the worker queue is process-local, queued/running rows are marked interrupted on startup; users can reanalyse. The same inactivity cleanup deletes expired artifacts from Postgres.
* **Session isolation.** The server issues an opaque `HttpOnly` cookie; only its SHA-256 digest is stored. Analysis leases are bound to that session and a browser tab. Caller-supplied analysis IDs alone do not grant access.
* **Automatic expiry.** Results are deleted after the last owning tab stops heartbeating for `WINDOW_TTL_SECONDS` (default 30 minutes), plus at most one cleanup interval. The UI explains when a run has expired or disappeared after a restart and lets the user reanalyse.
* **Source retention.** Full file contents are not stored with analysis records. By default, persisted search chunks contain deduplicated identifier terms, not source excerpts; the Code Explorer fetches the requested file from GitHub on demand. Set `STORE_SOURCE_SNIPPETS=true` only in a trusted deployment if retaining short excerpts until expiry is acceptable.
* **Private repositories are opt-in.** `ALLOW_PRIVATE_REPOS=false` by default. A server-side `GITHUB_TOKEN` is shared by the service, so do not enable private-repo access on a multi-user public service without per-user GitHub OAuth.
* **No AI.** Analysis, search and impact are deterministic. Nothing is sent to a language model.

## Dashboard data loading

Overview, Architecture, Dependencies, APIs, Database and Workflows use keyed SWR requests. Each page asks for its own analysis artifact; a bounded 32 MiB in-tab GET cache deduplicates requests and warms the principal dashboard results after a run completes. Switching pages never starts a new analysis. Route changes keep the current page visible and use only a thin progress bar; a real data miss gets a local skeleton rather than a full-page spinner.

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
internal network, so the browser only talks to one origin. There are no host volumes; checkouts use
container-local temporary storage during analysis and are removed after each run or on startup. For an HTTPS deployment, set `APP_ENV=production` (to enable Secure session cookies) and set `CORS_ORIGINS` to only the origins you operate.

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
| **Search** | Ranked search over paths, symbols and identifier terms; source snippets are opt-in |
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
            ──▶ index for search     symbol, file and doc identifiers (no source excerpts by default)
            ──▶ store results        in memory, or in DATABASE_URL when set; expire by session lease
```

Every stage reports progress and can be cancelled. A run that exceeds `MAX_ANALYSIS_SECONDS` (default
30 minutes) fails with a clear message.

### Scope rules (what is *not* counted)

* **Documentation and assets stay out of the graph.** Only files that can carry dependencies become
  graph nodes. `docs/`, `.rst`, Markdown, data and image files are never counted as isolated modules or
  hubs. By default their paths are searchable without retaining body text; setting
  `STORE_SOURCE_SNIPPETS=true` also indexes short excerpts.
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
| `DATABASE_URL` | empty (in memory) | Optional Postgres URL; retained records are still expired by the session lease sweeper |
| `GITHUB_TOKEN` | empty | Higher GitHub API rate limit; private repos remain denied unless explicitly enabled |
| `ALLOW_PRIVATE_REPOS` | `false` | Allow private repositories visible to the server token; only for trusted single-tenant deployments |
| `MAX_ANALYSIS_SECONDS` | `1800` | Maximum repository-download time plus cooperative analysis deadline |
| `MAX_REPO_BYTES` | `104857600` | 100 MiB cap on downloaded and expanded source (`0` disables the cap and clone fallback guard) |
| `MAX_FILES` / `MAX_FILE_BYTES` | `4000` / `1048576` | Maximum indexed text files and per-file size threshold |
| `MAX_ACTIVE_ANALYSES_PER_SESSION` | `2` | Limit concurrent jobs per browser session |
| `MAX_ANALYSES_PER_HOUR` | `20` | Limit job submissions per browser session |
| `WINDOW_TTL_SECONDS` | `1800` | Idle time after which a tab's analysis lease expires |
| `SESSION_TTL_SECONDS` | `2592000` | Sliding lifetime for the HttpOnly browser session |
| `STORE_SOURCE_SNIPPETS` | `false` | Opt in to persisting short source excerpts until analysis expiry |
| `ANALYSIS_WORKERS` | `2` | Concurrent analyses per API process |
| `CORS_ORIGINS` | localhost:3000 | Allowed browser origins for direct API calls with credentials |

`GET /api/system/capabilities` reports the running storage mode, effective limits, and source/private-repo policy. Per-session quotas are guardrails, not a full abuse-prevention system; public deployments should also apply edge/IP rate limiting and monitoring.

## API reference

While the API is running, every endpoint, with request and response shapes, is listed at
`http://localhost:8000/docs` (generated by FastAPI). `GET /api/health` reports whether the service is up.

## Limits and honesty notes

* Static analysis cannot see dynamic dispatch, dependency-injection containers, string-based routing or
  reflection. Each view says where its knowledge stops.
* Layers are derived from path conventions and resolvable edges, and are marked *heuristic*.
* Language depth: Python, TypeScript, JavaScript, Go, Java, Ruby, PHP, Rust, C#, C/C++, and Vue/Svelte are
  parsed into symbols and edges. SQL, GraphQL, Proto, YAML/JSON/TOML, Markdown, shell and Dockerfiles are
  not parsed into symbols; paths remain searchable by default, while body text is indexed only when
  `STORE_SOURCE_SNIPPETS=true`.
* Run one API process/replica. Analysis tasks are process-local; `DATABASE_URL` persists completed artifacts but does not provide a shared job queue. Horizontal scaling needs a distributed worker system (not included).
* Not implemented: notifications and pull-request or branch diffing.
