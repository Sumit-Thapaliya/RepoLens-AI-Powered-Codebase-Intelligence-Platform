# Development guide

## Prerequisites

| Tool | Version used | Notes |
|---|---|---|
| Python | 3.12 / 3.13 | 3.11+ required (`requires-python`) |
| Node.js | 20 LTS | matches the web Dockerfile |
| npm | 10+ | lockfile committed |
| Docker + Compose | optional | only for the Postgres/pgvector stack |

## First run

```bash
git clone <repo> repolens && cd repolens
cp .env.example .env

python -m venv .venv && source .venv/bin/activate
pip install -e packages/shared -e packages/parser -e packages/graph -e packages/embeddings -e apps/api

cd apps/api && REPOLENS_DATA_DIR=../../data python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd apps/web && npm install
API_INTERNAL_URL=http://127.0.0.1:8000 NEXT_PUBLIC_API_BASE=/backend npm run dev   # :3000
```

Sanity checks:

```bash
curl -s localhost:8000/api/health | jq
curl -s localhost:8000/api/system/capabilities | jq
curl -s -X POST localhost:8000/api/analyses -H 'content-type: application/json' \
  -d '{"url":"https://github.com/fastapi/full-stack-fastapi-template"}' | jq
```

## Tests

```bash
# Parser suite: tree-sitter + Python AST extraction, import resolution, layer heuristic
.venv/bin/python -m pytest packages/parser/tests -q      # 10 passed

# Syntax check everything you touched
.venv/bin/python -c "import ast,pathlib,sys; [ast.parse(p.read_text()) for p in pathlib.Path('apps/api/app').rglob('*.py')]"

# Import the app the way uvicorn does (catches broken imports early)
cd apps/api && ../../.venv/bin/python -c "from app.main import app; print(len(app.routes), 'routes')"

# Frontend
cd apps/web && npx tsc --noEmit && npm run build
```

When you touch the shared vocabulary (`repolens_shared.constants`), re-check the three language sets —
`TREE_SITTER_LANGUAGES` (parsed), `TEXT_INDEXED_LANGUAGES` (indexed) and `GRAPH_LANGUAGES` (dependency
graph nodes) — and the frontend's `LANGUAGE_COLORS` / `monacoLanguage` maps, which fall back to grey /
plaintext when an entry is missing.

Test suites for `packages/graph` and `apps/api` are not written yet — when you add them, put them in
`packages/graph/tests/` and `apps/api/tests/` with an isolated `DATABASE_URL` so they never touch a
developer's database.

Conventions worth keeping:

* **Parser tests are the spec.** If you change a parser, add the smallest possible fixture that fails
  before the change and passes after.
* **Never write to the dev database from a test.** Point `DATABASE_URL` at a temp file or use
  `session_scope` against a fresh engine.
* **Analysis ids are part of every generated id.** `stable_id("file", analysis_id, path)` and friends —
  dropping the scope reintroduces a UNIQUE-constraint crash on the second run of the same repository.

## Frontend conventions

* `lib/api.ts` is the only place that knows about HTTP. Pages call typed helpers and never build URLs
  by hand.
* Loading, empty and error states come from `components/ui/states.tsx`; a page that fetches must render
  all three (`SkeletonCard`, `EmptyState`/`ErrorState` + retry).
* Anything that could be a lie is labelled: `heuristic`, `confidence`, `trace_truncated`,
  `retrieval-only mode`, `generated_by`.
* Types in `lib/types.ts` mirror the API payloads; when you change a serializer in
  `apps/api/app/analyzers/*` or `services/store.py`, update the type in the same commit.
* Graph views use `@xyflow/react`; keep node components in the same file as their layout function so
  the mapping stays obvious.

## Schema changes on a live database

Analysis payloads grow over time (`api_endpoints.declarations`, `workflows.scope`, …). To keep existing
databases working, additive columns are declared once in `apps/api/app/core/db.py`:

```python
ADDITIVE_COLUMNS = {
    "api_endpoints": {"is_example": "BOOLEAN DEFAULT false", "declarations": "JSON"},
    "workflows": {"scope": "VARCHAR(20)", "scope_note": "TEXT"},
}
```

`init_db()` (run on every API start) calls `_ensure_columns()`, which checks `information_schema`
(Postgres) or `PRAGMA table_info` (SQLite) and issues `ALTER TABLE … ADD COLUMN` only for missing
columns. Destructive changes still belong in `infrastructure/migrations/*.sql` for Postgres; the
additive path exists so a developer's SQLite file never has to be deleted.

## Adding a language



1. `packages/shared/repolens_shared/constants.py`: add the extension mapping and, if it gets deep
   parsing, list it in `TREE_SITTER_LANGUAGES` (`LANGUAGE_LABELS` too).
2. `packages/parser/repolens_parser/tslang.py`: register the grammar name and any query tweaks.
3. `packages/parser/repolens_parser/generic_analyzer.py`: only if the language needs syntax-specific
   handling (routes, models, queries).
4. Add a fixture + test, then re-run one real analysis and check the Overview language mix.

## Adding an analysis artefact

1. Compute it in `apps/api/app/analyzers/` (pure function over parsed files/graph).
2. Persist it in `app/services/store.py` (a typed payload helper) — never compute during a GET.
3. Expose it under `/analyses/{id}/…` in `app/api/routes_insights.py`.
4. Add the type to `apps/web/lib/types.ts`, a client helper in `lib/api.ts`, and a view.
5. Include it in `GET /bundle` so exports stay complete.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `IMPORTANT: reached the end of the log` on re-analysis | stale record ids — ids must be analysis-scoped (`stable_id(..., analysis_id, ...)`) |
| Analysis stuck at `download` | anonymous GitHub rate limit (60/h). Set `GITHUB_TOKEN`; the error detail carries `reset_at` |
| `1 file(s) could not be parsed` for one file | expected: the parser uses the running Python's AST and a tree-sitter grammar. The file is skipped, the run continues; check `/overview.parse_failures` |
| Chat says `retrieval-only mode` | no LLM key. Set `LLM_PROVIDER=openai` + `OPENAI_API_KEY` (or `anthropic`) and restart |
| `/backend/*` returns 502 in the web app | `API_INTERNAL_URL` is wrong for the server process (compose: `http://api:8000`) |
| Monaco does not render | it is client-only (`next/dynamic({ ssr: false })`); check the browser console for worker errors |
| Postgres connect errors on boot | run `python -m app.migrations` (compose does this in its `migrate` service) and verify `DATABASE_URL` |
| Dev server killed while compiling | Next.js needs ~1.5 GB free RAM; `NODE_OPTIONS=--max-old-space-size=1024` keeps it lean, and `npm run build` + `npm run start` is cheaper than the dev compiler for repeated browsing |

## Code style

* Python: 4-space indent, type hints on public functions, `from __future__ import annotations`,
  docstrings that explain *why*. No bare `except:` — catch, log, and degrade.
* TypeScript: strict mode is on; no `any` in `lib/` or components (`unknown` + narrowing instead).
* Comments explain intent and contracts, not syntax.
* Keep the packages free of framework imports; that boundary is what makes them testable.
