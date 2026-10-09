# ---------------------------------------------------------------------------
# RepoLens API image - FastAPI analysis engine + Python packages
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libpq is needed by psycopg; git is used to fetch repository tarballs/checkouts.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq5 ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/repolens

# 1. dependencies first (better layer caching)
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml
COPY packages/parser/pyproject.toml packages/parser/pyproject.toml
COPY packages/graph/pyproject.toml packages/graph/pyproject.toml
COPY packages/embeddings/pyproject.toml packages/embeddings/pyproject.toml
COPY apps/api/requirements.txt apps/api/requirements.txt
RUN pip install --upgrade pip && pip install -r apps/api/requirements.txt

# 2. sources (migrations are copied so `python -m app.migrations` can run in-image)
COPY packages packages
COPY apps/api apps/api
COPY infrastructure/migrations infrastructure/migrations
RUN pip install -e packages/shared -e packages/parser -e packages/graph -e packages/embeddings -e apps/api

# 3. runtime
RUN useradd --create-home --uid 10001 repolens \
 && mkdir -p /data && chown -R repolens:repolens /data /srv/repolens
USER repolens

ENV REPOLENS_DATA_DIR=/data \
    APP_ENV=production

EXPOSE 8000

WORKDIR /srv/repolens/apps/api
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
