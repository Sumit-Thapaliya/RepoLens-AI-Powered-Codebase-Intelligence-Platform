# RepoLens architecture

> How a repository becomes a navigable model, and why each part is built the way it is.

---

## 1. System shape

```
┌───────────────────────────── browser ──────────────────────────────┐
│  Next.js 15 (App Router, TypeScript, Tailwind, React Flow, Monaco) │
│  · server-side proxy:  /backend/*  →  API_INTERNAL_URL/api/*       │
└──────────────────────────────────┬─────────────────────────────────┘
                                   │  JSON (uniform error envelope)
┌──────────────────────────────────▼─────────────────────────────────┐
│                        FastAPI  apps/api/app                        │
│  api/         routes: system · repos · analyses · insights · chat   │
│  services/    github · analysis manager · store · search · impact   │
│  analyzers/   pipeline · endpoints · database · insights · docs     │
│  ai/          llm client · tracer · grounded chat                   │
│  core/        config · db · logging · errors · capabilities         │
└───────┬───────────────────────────────────────────────┬────────────┘
        │ imports                                        │ SQLAlchemy 2.x
┌───────▼───────────── packages (pure Python, no web) ──┐│
│  shared      constants · schemas · errors · utils      ││
│  parser      tree-sitter + Python AST · resolvers      ││
│  graph       dependency graph · layers · workflows ·   ││
│              impact · quality                          ││
│  embeddings  embedder (local / OpenAI) · vector store  ││
└────────────────────────────────────────────────────────┘│
                                                          │
                    ┌─────────────────────────────────────▼──────────────┐
                    │ Postgres + pgvector (Neon)  —  SQLite for offline   │
                    │ 19 analysis-scoped tables + chunk_embeddings        │
                    └─────────────────────────────────────────────────────┘
```

Design constraints that drove this shape:

* **The browser never talks to the API host directly.** `NEXT_PUBLIC_API_BASE=/backend` and a Next
  rewrite forward requests to `API_INTERNAL_URL` server-side, so deployments are single-origin (no
  CORS, no host baked into the bundle) and the API can stay on a private network.
* **Packages are framework-free.** `packages/*` are plain dataclasses and pure functions with no
  FastAPI/SQLAlchemy imports, so they are testable in isolation (`pytest packages/parser/tests`) and
  reusable from a CLI or worker later.
* **Everything is analysis-scoped.** Every row and every generated id includes the analysis id, so the
  same repository can be analysed repeatedly, side by side, without collisions or cross-talk.

---

## 2. The analysis pipeline

`apps/api/app/analyzers/pipeline.py` drives 14 weighted stages (defined in
`packages/shared/repolens_shared/constants.py`). Each stage updates `analyses.stage`, `progress`
(weighted), `message` and `stages[]`, which is exactly what the progress panel renders.

| Stage | What happens | Failure behaviour |
|---|---|---|
| `resolve` | Validate URL, fetch metadata + branches (GitHub REST) | fatal with actionable hint |
| `download` | GET `/repos/{o}/{r}/tarball/{ref}` (fallback: git clone) | fatal; rate-limit errors carry `reset_at` |
| `extract` | Untar into `data/repos/<analysis_id>/` | fatal |
| `scan` | Walk tree: skip VCS/build/binary/large, respect `MAX_FILES` | skipped files recorded |
| `parse` | Per-file parse (tree-sitter / Python AST) | **per-file warning, never fatal** |
| `resolve` (imports) | Internal/external/unresolved classification, router prefixes | partial results kept |
| `graph` | File nodes + import/call edges, cycles (Tarjan), hubs, orphans | empty graph allowed |
| `endpoints` | Route detection + URL reconstruction from mounts/prefixes | per-file |
| `database` | Models, fields, queries, migrations, technologies | per-file |
| `workflows` | Trace from entry points through services to data | depth-limited, flagged |
| `quality` | Complexity, coupling, cycles, duplication, missing tests | heuristic labels |
| `embed` | Chunking + embeddings + vector persistence | falls back to in-process ranking |
| `insights` | Deterministic findings from the artefacts | never fails the run |
| `finalize` | Summary message, counters, pruning of old runs | — |

Guarantees:

1. **A single bad file cannot fail an analysis.** Parse errors are captured per file
   (`files.parse_error`) and summarised in `warnings` + the Overview diagnostics card.
2. **A run is cancellable** at stage boundaries (`POST /analyses/{id}/cancel`).
3. **Re-running is cheap and safe.** `_prune_history(session, repo_id, keep=8)` deletes the oldest
   runs across all 15 child tables, and new runs use fresh analysis-scoped ids.
4. **Nothing is trusted from the model.** The LLM only ever sees retrieved evidence and is instructed
   to answer from it; the extractive engine is the default fallback.

---

## 3. Parsing and resolution

### Languages

Every file gets a language from a two-step lookup (`repolens_shared.utils.language_for_path`): the
file *name* first (so `Dockerfile`, `Makefile`, `.editorconfig`, `Gemfile`, `.pem` and friends are not
"unknown"), then the extension. That lookup feeds three sets in `repolens_shared.constants`:

* **Deep parse** (`TREE_SITTER_LANGUAGES`) — tree-sitter grammars for Python, TypeScript/TSX,
  JavaScript/JSX, Go, Java, Ruby, PHP, Rust, C#, C/C++ (+ Vue/Svelte for structure, and Python's own
  `ast` module, which is more accurate than the grammar for decorators/annotations).
* **Indexed only** (`TEXT_INDEXED_LANGUAGES`) — SQL, Prisma, GraphQL, Proto, YAML, JSON, TOML, INI,
  Markdown, reStructuredText, plain text, shell, batch, Dockerfiles, Makefiles, HTML/CSS/XML. These
  are stored, searchable and shown in the tree; no symbols are invented for them. The UI dims them in
  the Languages card, and `GET /system/languages` reports the split.
* **Graph scope** (`GRAPH_LANGUAGES`) — deep-parse languages plus Vue/Svelte. Only these files become
  dependency-graph nodes, so orphans/hubs/cycles describe the code rather than the docs folder. A file
  outside the set is still admitted when a resolved edge points at it, and `graph_stats.excluded_files`
  reports the rest. Documentation (including `docs/*.py` tooling) is excluded via `is_doc_path`.

### What a parse produces (`packages/parser/repolens_parser/types.py`)

`ParsedFile(path, language, loc, symbols[], imports[], routes[], models[], queries[], router_prefixes,
router_includes, framework_hints, parse_error)` where symbols carry line ranges, params, decorators,
bases, docstring, complexity, call sites (`Call(name, line, qualifier, full, receiver)`) and a
normalised body shingle used for duplicate detection.

### Import resolution (`resolve.py`)

Resolution is the heart of the graph, so it is deliberately conservative:

* Python: import roots are derived from `pyproject/setup.py` layout and the deepest common package
  directory; submodule-first matching beats package-`__init__` matching.
* JS/TS: relative specifiers, `tsconfig` path aliases, index files and extension expansion.
* Anything unresolvable stays `external` or `unresolved_relative` and is *counted* (the Overview shows
  the resolve stats), never guessed.

### Layers (`layer_for_path`)

`layer_for_path(path, is_test)` decides a file's architectural layer. Order matters:

1. test detection (path markers) → `test`
1b. documentation (a prose language, or any file under `docs/`, `doc/`, `documentation/`, `website/`,
   `book/`) → `docs` — prose is not an architectural layer
2. filename stem, including strong entry-point stems (`main`, `server`, `manage`, `wsgi`, `asgi`…)
3. deepest directory segment (route/api/controller → `route`, service → `service`, model/repo/dao →
   `repository`, middleware/security/core → `middleware`, components/pages/hooks → `ui`, …)
4. weak entry-point stems (`app`, `index`) only *after* no directory matched — this is what keeps
   `frontend/src/routes/_layout/index.tsx` a route instead of an entry point.

Layers are used by the architecture graph, the dependency lanes, and every "service attribution" in
the API table, so the heuristic lives in exactly one function and is unit-tested.

---

## 4. Derived intelligence

| Artefact | Module | Notes |
|---|---|---|
| File/module dependency graph | `packages/graph/dependency.py` | import + call edges, fan-in/out, coupling, orphans, Tarjan cycles |
| Architecture layers + inter-layer edges | `packages/graph/layers.py` | aggregated from the graph, with sample files per edge |
| Endpoints & URL reconstruction | `apps/api/app/analyzers/endpoints.py` | follows `include_router(prefix=…)` / `app.mount()` chains across files, then attributes a service by resolving the handler's first cross-file call into a service/repository/middleware module. Declarations are deduplicated by `method + path` with ranking (application > example > test, known framework > unknown, shallower path first); the winner becomes the row and every other declaration is preserved in `declarations[]` with `is_example` / `is_test` flags |
| Database model | `apps/api/app/analyzers/database.py` | models/fields/relations/queries/migrations + technology confidence with evidence |
| Workflows | `packages/graph/workflows.py` | seeds from routes, UI handlers and background hooks (docs/test/example files never seed a step); walks the call graph depth-first with per-analysis step ids, a truncation flag, and `scope` + `scope_note` describing whether the entry point is shipped code (`application`) or lives in an `example`/`test` app |
| Impact | `packages/graph/impact.py` | BFS over dependents, maps affected endpoints/workflows/tests, computes risks |
| Quality | `packages/graph/quality.py` | thresholds in `QUALITY_THRESHOLDS`; every issue carries `metric` + `heuristic: true`. Code-only heuristics: documentation is skipped, re-export barrels with no symbols are not "high coupling", test/example files are not "isolated modules", and a `.env` in a test fixture is `low` severity with a note |
| Insights | `apps/api/app/analyzers/insights.py` | deterministic findings with evidence and navigation actions |
| Documents | `apps/api/app/analyzers/docs.py` | README/API/onboarding drafts from artefacts; optional LLM polish records `generated_by` |

Workflow tracing, in one sentence: **an entry point is a route or handler; each step is a resolved
call to another file's symbol; the tracer keeps going while it can resolve a target and stops with
`trace_truncated=true` when it cannot.** That is why every step has a file, line and evidence string.

---

## 5. Storage model

19 tables, each keyed by `analysis_id` (see `apps/api/app/models/tables.py`):

```
repos ─┬─ analyses ─┬─ files ─┬─ symbols ── chunks ── (chunk_embeddings)
       │            │         ├─ api_endpoints
       │            │         ├─ db_models / db_queries / db_technologies
       │            │         ├─ workflows / graph_nodes / graph_edges / cycles
       │            │         ├─ frameworks / manifests / quality_issues
       │            │         ├─ analysis_artifacts (overview, architecture, docs…)
       │            │         └─ chat_messages
       │            └─ (status, stage, progress, warnings, stages[], counters, commit_sha)
```

* `analysis_artifacts` stores the serialised JSON for `overview|architecture|dependency_graph|
  module_graph|database|quality|insights|doc:{readme,api,onboarding}` — the UI reads them directly, so
  opening a view is a single indexed query and never re-computes anything.
* `chunks.embedding` is a real `vector(1536)` column when pgvector is present (schema switch happens
  in `core/db.init_db`), otherwise a JSON column ranked in-process. `GET /system/capabilities` reports
  which mode is live, and the UI shows it.
* Deleting an analysis deletes its child rows and its extracted checkout; deleting a repository
  cascades to all analyses.

---

## 6. AI layer

```
question ─▶ intent + entities ─▶ retrieval (vectors + lexical blend)
          ─▶ structured evidence: endpoints, symbols/references, workflows, artifacts
          ─▶ impact computation when the question is about change risk
          ─▶ trace (workflow trace or call-graph walk from the best symbol)
          ─▶ compose:  LLM (grounded prompt) | extractive engine (no key)
          ─▶ { answer, citations[], retrieval[], trace, impact, followups, notes, model, grounded }
```

* **Intent detection** (`detect_intent`) routes to `impact | how_works | where_used | security | …`;
  domain hints map vocabulary like *authentication* onto the traced **sign-in** workflow rather than
  any flow that merely contains the word "password".
* **Impact questions compute a real report** and embed it in the answer (`impact` field), so
  "what could break if I modify `crud.py`" returns the same numbers as the Impact page.
* **Every claim is attributable.** Citations carry `path`, `line`, `symbol` and a reason; the UI links
  each one into the Code Explorer at the exact line.
* **No key? No pretending.** `LLM_PROVIDER=none` switches to the extractive engine and the UI labels
  the answer `retrieval-only mode`; the same grounding rules apply.

---

## 7. Deployment topology

* `db` — `pgvector/pgvector:pg16`, persistent volume, health-checked.
* `migrate` — one-shot `python -m app.migrations`: creates ORM tables, then applies
  `infrastructure/migrations/*.sql` (extension, `chunk_embeddings`, HNSW index, operator view) and
  records them in `schema_migrations`. Idempotent, safe to re-run.
* `api` — uvicorn, non-root user, `/data` volume for checkouts/tarballs, health endpoint
  `/api/health`.
* `web` — Next.js standalone server; proxies `/backend/*` to `http://api:8000` inside the compose
  network.

Everything is environment-driven (`docs/DEPLOYMENT.md`), and the API's own
`/api/system/capabilities` tells you what the running instance actually has (LLM mode, embedding
mode, vector backend, GitHub rate limit, limits).
