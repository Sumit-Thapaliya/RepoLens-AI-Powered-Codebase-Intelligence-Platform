-- ---------------------------------------------------------------------------
-- 0001 - vector storage for code chunks
--
-- Applied by `python -m app.migrations` (see apps/api/app/migrations.py).
-- Safe to run repeatedly: every statement is guarded.
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;

-- Chunk embeddings live in their own table keyed by (analysis_id, chunk_id) so a
-- fresh analysis can be re-embedded without touching the larger chunk rows.
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    analysis_id  VARCHAR(32)  NOT NULL,
    chunk_id     VARCHAR(40)  NOT NULL,
    path         VARCHAR(700) NOT NULL,
    provider     VARCHAR(40)  NOT NULL DEFAULT 'local',
    model        VARCHAR(120),
    dim          INTEGER      NOT NULL,
    embedding    vector(1536) NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (analysis_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_analysis ON chunk_embeddings (analysis_id);
CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_path ON chunk_embeddings (analysis_id, path);

-- HNSW gives good recall/latency for the few-thousand-vector scale of a single
-- repository analysis. Built with cosine distance to match the query operator.
CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_hnsw
    ON chunk_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

COMMENT ON TABLE chunk_embeddings IS
    'Dense vectors for RepoLens code chunks; queried with the <=> (cosine) operator when pgvector is enabled.';
