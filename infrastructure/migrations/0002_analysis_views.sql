-- ---------------------------------------------------------------------------
-- 0002 - analysis bookkeeping views
--
-- A read-only convenience view for operators: one row per analysis with the
-- headline counters, so `psql` inspection does not require joins by hand.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW analysis_overview AS
SELECT
    a.id                AS analysis_id,
    a.status,
    a.stage,
    a.progress,
    a.branch,
    a.commit_sha,
    a.started_at,
    a.finished_at,
    r.full_name         AS repository,
    a.file_count,
    a.parsed_count,
    a.failed_count,
    (SELECT count(*) FROM api_endpoints e WHERE e.analysis_id = a.id) AS endpoints,
    (SELECT count(*) FROM workflows w WHERE w.analysis_id = a.id)     AS workflows,
    (SELECT count(*) FROM db_models m WHERE m.analysis_id = a.id)     AS db_models,
    (SELECT count(*) FROM graph_edges g WHERE g.analysis_id = a.id)   AS graph_edges,
    (SELECT count(*) FROM quality_issues q WHERE q.analysis_id = a.id) AS quality_issues
FROM analyses a
LEFT JOIN repos r ON r.id = a.repo_id;

COMMENT ON VIEW analysis_overview IS
    'Operator convenience view: headline counters per stored analysis.';
