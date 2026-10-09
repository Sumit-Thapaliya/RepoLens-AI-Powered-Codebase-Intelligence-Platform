"""Read endpoints for every dashboard page."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from repolens_shared.errors import RepoLensError
from repolens_shared.utils import stable_id

from ..analyzers.docs import generate_docs
from ..ai.llm import get_llm
from ..core.config import get_settings
from ..core.db import session_scope
from ..ai.chat import gather_context  # noqa: F401  (imported for symmetry in future endpoints)
from ..models.tables import Analysis
from ..services.store import (
    file_tree,
    get_analysis,
    get_architecture,
    get_database,
    get_dependencies,
    get_document,
    get_file,
    get_overview,
    get_quality,
    list_endpoints,
    list_frameworks,
    list_manifests,
    list_workflows,
    require_complete,
    search_symbols,
    store_document,
    symbol_count,
    symbol_references,
)
from ..services.search import search as hybrid_search, search_text
from .deps import DbSession, GenerateDocRequest, ImpactRequest, SearchRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analyses", tags=["insights"])


@router.get("/{analysis_id}/overview")
def overview(analysis_id: str, session: DbSession) -> dict:
    return get_overview(session, analysis_id)


@router.get("/{analysis_id}/architecture")
def architecture(analysis_id: str, session: DbSession) -> dict:
    return get_architecture(session, analysis_id)


@router.get("/{analysis_id}/workflows")
def workflows(analysis_id: str, session: DbSession, category: str | None = None, q: str | None = None,
              limit: int = Query(default=100, ge=1, le=300)) -> dict:
    return list_workflows(session, analysis_id, category=category, query=q, limit=limit)


@router.get("/{analysis_id}/workflows/{workflow_id}")
def workflow_detail(analysis_id: str, workflow_id: str, session: DbSession) -> dict:
    from ..services.store import get_workflow
    return get_workflow(session, analysis_id, workflow_id)


@router.get("/{analysis_id}/dependencies")
def dependencies(analysis_id: str, session: DbSession, view: str = Query(default="files", pattern="^(files|modules)$"),
                 limit: int = Query(default=400, ge=10, le=2000), layer: str | None = None,
                 kind: str | None = Query(default=None, pattern="^(import|call|require|reexport)?$")) -> dict:
    return get_dependencies(session, analysis_id, view=view, limit=limit, layer=layer, kind=kind or None)


@router.get("/{analysis_id}/apis")
def apis(analysis_id: str, session: DbSession, method: str | None = None, framework: str | None = None,
         q: str | None = None) -> dict:
    return list_endpoints(session, analysis_id, method=method, query=q, framework=framework)


@router.get("/{analysis_id}/database")
def database(analysis_id: str, session: DbSession) -> dict:
    return get_database(session, analysis_id)


@router.get("/{analysis_id}/quality")
def quality(analysis_id: str, session: DbSession) -> dict:
    return get_quality(session, analysis_id)


@router.get("/{analysis_id}/frameworks")
def frameworks(analysis_id: str, session: DbSession) -> dict:
    require_complete(session, analysis_id)
    return {"frameworks": list_frameworks(session, analysis_id), "manifests": list_manifests(session, analysis_id)}


@router.get("/{analysis_id}/files")
def files(analysis_id: str, session: DbSession) -> dict:
    return file_tree(session, analysis_id)


@router.get("/{analysis_id}/file")
def file_detail(analysis_id: str, session: DbSession, path: str = Query(..., min_length=1)) -> dict:
    analysis = require_complete(session, analysis_id)
    return get_file(session, analysis_id, path, source_root=analysis.source_root)


@router.get("/{analysis_id}/symbols")
def symbols(analysis_id: str, session: DbSession, q: str | None = None, limit: int = 50) -> dict:
    require_complete(session, analysis_id)
    stats = symbol_count(session, analysis_id)
    if q:
        return {"symbols": search_symbols(session, analysis_id, q, limit=limit), "stats": stats, "query": q}
    return {"symbols": [], "stats": stats}


@router.get("/{analysis_id}/symbols/{name}/references")
def symbol_reference_list(analysis_id: str, name: str, session: DbSession, limit: int = 60) -> dict:
    require_complete(session, analysis_id)
    return {"name": name, "references": symbol_references(session, analysis_id, name, limit=limit)}


@router.post("/{analysis_id}/search")
def semantic_search(analysis_id: str, payload: SearchRequest, session: DbSession) -> dict:
    analysis = require_complete(session, analysis_id)
    settings = get_settings()
    hits = hybrid_search(session, settings, analysis_id, payload.query, limit=payload.limit,
                         paths=payload.paths, kinds=payload.kinds)
    return {
        "query": payload.query,
        "hits": hits,
        "backend": "pgvector" if settings.pgvector_enabled else "in-process",
        "embedding": {"provider": settings.embeddings_provider,
                      "neural": settings.embeddings_provider == "openai" and bool(settings.openai_api_key)},
    }


@router.get("/{analysis_id}/grep")
def grep(analysis_id: str, session: DbSession, q: str = Query(..., min_length=2), limit: int = 60) -> dict:
    require_complete(session, analysis_id)
    return {"query": q, "matches": search_text(session, analysis_id, q, limit=limit)}


@router.post("/{analysis_id}/impact")
def impact(analysis_id: str, payload: ImpactRequest, session: DbSession) -> dict:
    """Impact analysis executed against the persisted graph (no re-analysis needed)."""
    require_complete(session, analysis_id)
    from ..services.impact import build_impact_report

    return build_impact_report(session, analysis_id, payload.path, payload.symbol, depth=payload.depth)


@router.get("/{analysis_id}/docs/{kind}")
def get_doc(analysis_id: str, kind: str, session: DbSession) -> dict:
    require_complete(session, analysis_id)
    if kind not in {"readme", "api", "onboarding"}:
        raise RepoLensError(f"Unknown document kind `{kind}`.",
                            hint="Supported: readme, api, onboarding.")
    return get_document(session, analysis_id, kind)


@router.post("/{analysis_id}/docs")
def generate_doc(analysis_id: str, payload: GenerateDocRequest, session: DbSession) -> dict:
    """Regenerate a document, optionally with LLM polishing."""
    analysis = require_complete(session, analysis_id)
    settings = get_settings()
    overview = get_overview(session, analysis_id)
    architecture = get_architecture(session, analysis_id)
    endpoints_payload = list_endpoints(session, analysis_id)
    database = get_database(session, analysis_id)
    workflows_payload = list_workflows(session, analysis_id, limit=60)
    quality_payload = get_quality(session, analysis_id)
    frameworks_payload = list_frameworks(session, analysis_id)
    document = generate_docs(
        payload.kind, overview=overview, architecture=architecture, endpoints=endpoints_payload["endpoints"],
        database=database, workflows=workflows_payload["workflows"], frameworks=frameworks_payload,
        graph_stats=overview.get("graph_stats", {}), quality=quality_payload,
        llm=get_llm(settings) if payload.use_llm else None,
    )
    with session_scope() as write_session:
        store_document(write_session, analysis_id, document)
    return document


@router.get("/{analysis_id}/insights")
def insights(analysis_id: str, session: DbSession) -> dict:
    require_complete(session, analysis_id)
    overview = get_overview(session, analysis_id)
    return {"insights": overview.get("insights", []),
            "generated_from": f"analysis:{analysis_id}",
            "note": "Insights are derived from analysis artefacts (counts, evidence, heuristics) - not from an LLM."}
