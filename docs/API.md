# RepoLens API reference

Base URL: `http://<host>:8000/api` (the web app reaches it through the Next proxy at `/backend/*`).
Interactive OpenAPI docs are served by FastAPI at `/docs` and the raw schema at `/openapi.json`.

Every response is JSON. Every error uses the same envelope:

```json
{
  "error": {
    "code": "analysis_failed",
    "message": "The analysis failed while embedding chunks.",
    "hint": "Re-run the analysis; if it persists, check the API logs.",
    "detail": { "statement": "…", "params": { "…": "…" } }
  },
  "request_id": "9bfcc93ab677"
}
```

`code` values in use: `invalid_url`, `repo_not_found`, `github_rate_limited`, `github_error`,
`repo_too_large`, `repo_empty`, `unsupported_language`, `analysis_failed`, `analysis_running`,
`not_found`, `validation_error`, `llm_error`, `database_error`, `internal_error`.

---

## System

### `GET /health`
```json
{ "status": "ok", "version": "0.1.0", "database": { "status": "ok", "dialect": "sqlite" } }
```

### `GET /system/capabilities`
What this instance can actually do — drives the badges in the UI.
```json
{
  "llm":        { "provider": "none", "model": null, "configured": false, "mode": "retrieval-only", "note": "…" },
  "embeddings": { "provider": "local", "model": "hashed-ngram", "dim": 1536, "neural": false, "note": "…" },
  "database":   { "dialect": "sqlite", "pgvector": false, "search_backend": "in-process", "location": "…", "note": "…" },
  "github":     { "authenticated": false, "rate_limit": "60 requests/hour (anonymous)", "note": "…" },
  "limits":     { "max_files": 4000, "max_file_bytes": 1048576, "max_repo_bytes": 268435456, "max_analysis_seconds": 1800, "analysis_workers": 2 }
}
```

### `GET /system/languages`
`{ "deep_analysis": [...], "indexed_only": [...], "limits": {...}, "note": "…" }` — which languages get
symbols and which are only text-indexed.

---

## Repositories

### `POST /repos/resolve` — validate before analysing
```json
// request
{ "url": "https://github.com/fastapi/full-stack-fastapi-template" }
// response
{
  "repo": { "owner": "fastapi", "name": "full-stack-fastapi-template", "full_name": "…", "default_branch": "master",
            "stars": 45888, "forks": 9135, "license": "MIT", "primary_language": "TypeScript", "topics": ["…"], "…": "…" },
  "branches": [ { "name": "master", "sha": "ea741e7…", "default": true } ],
  "canonical_url": "https://github.com/fastapi/full-stack-fastapi-template",
  "github_rate_limit": { "remaining": 57, "limit": 60, "reset_at": "2026-10-06T13:00:00Z" },
  "already_imported": "79d02bb9a12e1908552e"
}
```

### `GET /repos?limit=20`
`{ "repos": [ { "id", "full_name", "url", "stars", "primary_language", "last_analysis": {...} } ] }`

### `GET /repos/{repo_id}?include_analyses=true`
`{ "repo": {...}, "last_analysis": {...}, "analyses": [ ... ] }`

### `POST /repos/{repo_id}/analyse`
Body (optional): `{ "branch": "main", "force": true }` → same shape as `POST /analyses`.

### `DELETE /repos/{repo_id}` → `{ "deleted": "<repo_id>" }` (cascades to analyses and files on disk)

---

## Analyses

### `POST /analyses` — start a run
```json
// request
{ "url": "https://github.com/owner/repo", "branch": null, "force": true }
// response (202-style; poll the id)
{
  "analysis_id": "d9635833665f1cbd4855",
  "repo_id": "79d02bb9a12e1908552e",
  "status": "queued",
  "reused": false,
  "repo": { "…": "GitHub metadata" },
  "branches": ["master"],
  "analysis": { "id": "…", "status": "queued", "stage": "queued", "progress": 0.0, "stages": [ { "id": "resolve", "label": "Resolving repository", "status": "pending" } ] }
}
```
`reused: true` means an identical run was already in flight and has been handed back instead of
starting a second one.

### `GET /analyses?limit=20&repo_id=…`
`{ "analyses": [ { ...run, "repo": { "id", "full_name", "url" } } ], "in_flight": ["d9635833665f1cbd4855"] }`

### `GET /analyses/{analysis_id}?include_overview=true`
`{ "analysis": {...}, "repo": {...}, "overview": {...} }` — the run object is:

```json
{
  "id": "d9635833665f1cbd4855", "repo_id": "…", "status": "complete", "stage": "embedding",
  "progress": 1.0, "message": "Analysis complete - 202 files parsed, 23 endpoints, 23 workflows.",
  "error": null,
  "warnings": [ { "code": "parse_failures", "message": "1 file(s) could not be parsed" } ],
  "stages": [ { "id": "parse", "label": "Parsing source", "status": "done", "detail": "201 parsed", "elapsed_ms": 3210 } ],
  "branch": "master", "commit_sha": "ea741e7…", "duration_ms": 2694,
  "file_count": 202, "parsed_count": 201, "failed_count": 1, "skipped_count": 0,
  "provider_info": { "endpoints": 23, "files": 202 }
}
```

### `POST /analyses/{analysis_id}/cancel`
`{ "analysis": { "status": "cancelled", "…": "…" } }` — cancelled at the next stage boundary.

### `DELETE /analyses/{analysis_id}`
`{ "deleted": "…", "repo_id": "…", "next_analysis": { ...previous run or null } }`

### `GET /analyses/{analysis_id}/bundle`
Full export: `{ analysis, overview, architecture, endpoints, database, workflows, dependencies, quality,
frameworks, manifests }` — used by the “Full JSON bundle” button.

---

## Insights (all artefacts of a completed run)

| Endpoint | Returns |
|---|---|
| `GET /overview` | repo metadata, run, file/LOC/symbol/endpoint/workflow counts, languages, frameworks, databases, layers, hubs, manifests, top dependencies, parse failures, resolve stats, quality summary, insights, limits. `graph_stats` distinguishes `files` (code modules in the graph) from `excluded_files` (docs/data/assets) and explains the rule in `graph_note` |
| `GET /architecture` | `{ layers[], edges[], entrypoints[], notes[] }` |
| `GET /workflows?category=&q=&limit=` | `{ workflows[], categories[], total }`, each workflow with `steps[]`, `confidence`, `evidence[]`, `files[]`, `trace_truncated`, `route`, `framework`, `scope` (`application\|example\|test`) and `scope_note` |
| `GET /workflows/{workflow_id}` | `{ workflow }` |
| `GET /dependencies?view=files\|modules&limit=&layer=&kind=` | `{ view, nodes[], edges[], cycles[], hubs[], orphans[], module_stats[], stats }` (truncation reported in `stats`) |
| `GET /apis?method=&framework=&q=` | `{ endpoints[], frameworks[], stats }` — each endpoint has `method, path, handler, file_path, line, framework, controller, service, auth_required, evidence[], request_model, response_model`, plus `is_example`, `is_test` and `declarations[]` (every file that declares this method+path, primary first). `stats` adds `from_examples`, `from_tests`, `declared_in_multiple_places` |
| `GET /database` | `{ technologies[], models[], queries[], migrations[], relations[], orms[], notes[], stats }`; models carry `fields[]` (name/type/pk/fk/nullable/unique/on_delete) and `relationships[]` |
| `GET /quality` | `{ issues[], summary{issues,by_severity,by_kind,health_score,health_label}, metrics{…,thresholds}, disclaimer }`; every issue has `heuristic: true` and a `metric` object |
| `GET /frameworks` | `{ frameworks[] }` with `confidence` + `evidence[]` |
| `GET /insights` | `{ insights[], generated_from, note }` |

### Code explorer endpoints

| Endpoint | Notes |
|---|---|
| `GET /files` | `{ root, total }` — nested tree with `language, loc, layer, test, symbols, parsed, parse_error` per file |
| `GET /file?path=` | `{ path, language, content, truncated, size_bytes, loc, layer, parsed, parse_error, warnings, symbols[], imports[], dependents[] }` |
| `GET /symbols?q=&limit=` | symbol search across the run (`{ symbols[], stats }`) |
| `GET /symbols/{name}/references` | `{ name, references[] }` — callers with `path, symbol, line, via, caller_signature` |
| `POST /search` `{ query, limit, paths?, kinds? }` | semantic search: `{ query, hits[], backend, embedding }` |
| `GET /grep?q=&limit=` | exact text search over file contents and stored docs |

### `POST /impact` — impact analysis on the stored graph
```json
// request
{ "path": "backend/app/crud.py", "symbol": "get_user_by_email", "depth": 3 }
// response
{
  "target": { "path": "backend/app/crud.py", "symbol": null, "layer": "repository", "loc": 68 },
  "direct_dependencies": [ { "path", "layer", "loc", "fan_in", "fan_out", "kind", "symbols", "line" } ],
  "indirect_dependencies": [ { "path", "distance", "via" } ],
  "dependents": [ ... ],
  "indirect_dependents": [ { "path", "distance", "via" } ],
  "affected_endpoints": [ { "id", "method", "path", "handler", "file_path", "line", "auth_required" } ],
  "affected_workflows": [ { "id", "name", "category", "confidence", "impacted_steps": [ { "label", "file_path", "kind" } ] } ],
  "related_tests": [ { "path", "reason" } ],
  "risks": [ { "level": "high", "title": "Highly coupled module (20 connections)", "detail": "…", "heuristic": true } ],
  "graph": { "nodes": [...], "edges": [...] },
  "notes": [ "Impact is computed from static imports/calls plus workflow traces - dynamic dispatch … can create links this analysis cannot see." ]
}
```
Unknown paths return `error` in-body with a hint, or `404 not_found` if the file is not part of the run.

---

## Documents

### `GET /analyses/{id}/docs/{kind}` where `kind ∈ {readme, api, onboarding}`
```json
{ "kind": "readme", "title": "Repository overview", "markdown": "# …", "generated_by": "deterministic analysis" }
```

### `POST /analyses/{id}/docs` `{ "kind": "api", "use_llm": true }`
Regenerates and stores the document. `generated_by` is `"deterministic analysis"` or `"llm"` so it is
always clear whether a model rewrote the draft. `use_llm` is ignored when no key is configured.

---

## AI chat

### `POST /analyses/{id}/chat`
```json
// request
{ "question": "What could break if I modify backend/app/crud.py?",
  "history": [ { "role": "user", "content": "…" } ],
  "focus_path": "backend/app/crud.py" }
```
```json
// response
{
  "answer": "### …markdown…",
  "citations": [ { "path": "backend/app/crud.py", "line": 34, "symbol": "get_user_by_email", "reason": "symbol get_user_by_email (function)", "score": 0.5 } ],
  "retrieval": [ { "id": "…", "path": "…", "symbol": null, "kind": "file|symbol|doc", "start_line": 1, "end_line": 77, "score": 0.5069, "snippet": "…" } ],
  "trace": { "root": { "name", "path", "line", "trigger" }, "steps": [ { "id", "label", "kind", "file_path", "line", "symbol", "detail" } ], "truncated": false, "evidence": [], "files": [], "confidence": 0.95 },
  "impact": { "target": "backend/app/crud.py", "summary": ["…"], "dependents": ["…"], "indirect_dependents": ["…"], "affected_endpoints": [ { "method", "path", "file_path", "line" } ], "affected_workflows": [ { "name", "category", "impacted_steps": [] } ], "related_tests": ["…"], "risks": [ { "level", "title", "detail", "heuristic": true } ], "notes": [] },
  "model": "retrieval-only", "grounded": true, "llm_configured": false,
  "followups": ["Where is `login.py` used?", "How does this work: POST /users?"],
  "latency_ms": 519, "notes": ["No LLM key configured: this answer is composed extractively from retrieved repository evidence."],
  "intent": "impact", "evidence_count": 14
}
```
`intent` is one of `impact | how_works | what_happens | where_used | where_handled | explain_repo |
database | api | tests | security | quality | general`. `impact` is only populated when a concrete
target file could be resolved from the question (or `focus_path`).

### `GET /analyses/{id}/chat/history?limit=40`
`{ "messages": [ { "id", "role", "content", "citations", "model", "created_at" } ] }` (chronological).

### `GET /analyses/{id}/chat/suggestions`
`{ "suggestions": ["Explain this repository.", "How does authentication work?", "How does this work: POST /users?", "What does the database schema look like?", "What could break if I modify the most connected file?"] }`
— generated from what the repository actually contains.

---

## Errors you should expect while integrating

| Situation | Status | `error.code` |
|---|---|---|
| Bad URL / not a GitHub URL | 400 | `invalid_url` |
| Repo missing or private without token | 404 | `repo_not_found` |
| Anonymous rate limit hit | 429 | `github_rate_limited` (with `reset_at` in detail) |
| Archive above `MAX_REPO_BYTES` | 413 | `repo_too_large` |
| Repository has no analysable text files | 422 | `repo_empty` |
| Artefacts requested before the run finished | 409 | `analysis_running` |
| Unknown analysis/file/workflow id | 404 | `not_found` |
| LLM provider error (chat/docs) | 502 | `llm_error` |
| DB failure | 500 | `database_error` (with `detail.statement`) |
| Anything else | 500 | `internal_error` (with `request_id`) |

Every 5xx carries a `request_id` that also appears in the API logs, so a support report can be traced
back to the exact stack trace.
