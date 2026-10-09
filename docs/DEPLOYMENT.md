# Deployment guide

## 1. Docker Compose (self-hosted, recommended starting point)

```bash
cp .env.example .env         # set POSTGRES_PASSWORD, GITHUB_TOKEN, and (optionally) an LLM key
docker compose -f infrastructure/docker-compose.yml up --build
```

What starts:

| Service | Purpose | Notes |
|---|---|---|
| `db` | Postgres 16 + pgvector | named volume `repolens-pgdata`, `pg_isready` healthcheck |
| `migrate` | one-shot `python -m app.migrations` | creates ORM tables, then applies `infrastructure/migrations/*.sql` |
| `api` | FastAPI + analysis engine | `/data` volume holds tarballs/checkouts, `/api/health` healthcheck |
| `web` | Next.js standalone server | proxies `/backend/*` → `http://api:8000` |

Open http://localhost:3000.

Useful commands:

```bash
docker compose -f infrastructure/docker-compose.yml logs -f api
docker compose -f infrastructure/docker-compose.yml exec api python -m app.migrations   # idempotent
docker compose -f infrastructure/docker-compose.yml exec db psql -U repolens -c 'select * from analysis_overview;'
```

## 2. Managed Postgres (Neon) + separate API/web hosts

1. Create a Neon project and database. Copy the pooled connection string.
2. Set on the API host:
   ```bash
   DATABASE_URL=postgresql+psycopg://user:pass@ep-xxx.eu-central-1.aws.neon.tech/repolens?sslmode=require
   ENABLE_PGVECTOR=true
   EMBEDDING_DIM=1536
   REPOLENS_DATA_DIR=/var/lib/repolens        # needs a persistent disk for checkouts
   CORS_ORIGINS=https://repolens.example.com  # only if the browser calls the API directly
   ```
3. Run migrations once per release: `python -m app.migrations`.
4. Build the web image with `API_INTERNAL_URL=https://api.internal.example.com` at **runtime** (it is a
   server-side value), and keep `NEXT_PUBLIC_API_BASE=/backend`. The browser then only ever talks to
   the web origin, so CORS can stay closed.

Notes specific to Postgres:

* `init_db()` switches `chunks.embedding` to a real `vector(1536)` column when the extension is
  available and records it in `/api/system/capabilities.database.pgvector`.
* `EMBEDDING_DIM` must match the embedding provider's output size. Changing it later requires a
  re-embed (`POST /analyses` on the repositories you care about).
* The HNSW index in `0001_chunk_embeddings.sql` is built with `vector_cosine_ops`; if you prefer IVFFlat
  for very large corpora, adjust the migration before first run.

## 3. Capacity planning

Per-analysis resource use is bounded by configuration, not by the repository:

| Knob | Default | Effect |
|---|---|---|
| `MAX_FILES` | 4000 | files parsed per run |
| `MAX_FILE_BYTES` | 1 MiB | larger files are skipped and reported |
| `MAX_REPO_BYTES` | 256 MiB | tarball download ceiling |
| `MAX_ANALYSIS_SECONDS` | 1800 | wall-clock budget; the run fails with a clear error rather than hanging |
| `ANALYSIS_WORKERS` | 2 | concurrent analyses per API instance |

Storage: extracted checkouts live under `REPOLENS_DATA_DIR` (`data/repos/<analysis_id>`); each analysis
keeps its own directory and is removed when the analysis is deleted. Database growth is dominated by
`chunks` and `chunk_embeddings`; pruning keeps at most 8 runs per repository.

Horizontal scaling: the API is stateless apart from the data directory (analyses run in-process). To run
multiple API replicas, either give each replica its own `REPOLENS_DATA_DIR` volume and `analysis_workers`
budget, or add a shared volume. Postgres/pgvector is shared, so reads scale freely.

## 4. GitHub and LLM credentials

* `GITHUB_TOKEN` (fine-grained, read-only public content is enough) raises the REST limit from 60/h to
  5000/h. Anonymous mode works for occasional use and the API tells you the remaining budget in
  `/api/system/capabilities`.
* `LLM_PROVIDER=openai|anthropic|azure-openai|none` with the matching key. With `none`, every AI
  surface still works in grounded, extractive mode — answers cite files instead of being generated.
* Embeddings: `EMBEDDINGS_PROVIDER=local` (deterministic hashed n-grams — good enough for lexical
  retrieval, labelled in the UI) or `openai` with `OPENAI_API_KEY` + `EMBEDDINGS_MODEL`.

## 5. Operations checklist

* **Health**: `GET /api/health` reports API + database status; both images ship healthchecks.
* **Capabilities**: `GET /api/system/capabilities` is the fastest way to confirm what a deployment
  actually has (LLM mode, embedding mode, vector backend, rate limit, limits).
* **Backups**: only Postgres holds state. `pg_dump` covers everything except the on-disk checkouts,
  which are reproducible by re-running an analysis.
* **Logs**: structured single-line logs; every 5xx response includes the `request_id` that appears in
  the logs, which makes incident triage a grep.
* **Upgrades**: rebuild images, run the `migrate` job, then start the API. SQL migrations are recorded
  in `schema_migrations`, so re-running is safe.
* **Failure modes to watch**: rate-limit 429s from GitHub (surfaced with `reset_at`), LLM 502s
  (`llm_error`, chat degrades to retrieval-only), and disk pressure from checkouts
  (`REPOLENS_DATA_DIR`).

## 6. Security notes

* No secrets in images or in the browser bundle: the LLM/GitHub/DB credentials are read from the
  environment by the API process only.
* The API container runs as a non-root user (uid 10001) and only needs write access to
  `REPOLENS_DATA_DIR`.
* Repository contents are parsed and stored; RepoLens never executes repository code, and the archive
  is extracted with path traversal protection.
* Media type of the container images is JSON only — no code execution endpoints are exposed.
