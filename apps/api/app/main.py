"""RepoLens API application."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import routes_analysis, routes_chat, routes_insights, routes_repos, routes_system
from .analyzers.pipeline import cleanup_orphaned_workdirs
from .core.capabilities import describe_capabilities
from .core.config import get_settings
from .core.db import init_db
from .core.errors import install_error_handlers
from .core.logging import configure_logging
from .services.analysis import get_manager
from .services.rag import RagService

logger = logging.getLogger(__name__)


async def _sweep_closed_windows() -> None:
    """Discard runs whose browser windows have closed or whose session expired."""
    sweep_seconds = max(5, get_settings().window_sweep_seconds)
    while True:
        await asyncio.sleep(sweep_seconds)
        try:
            removed = get_manager().sweep_windows()
            if removed:
                logger.info("Discarded %d run(s) from closed windows", len(removed))
        except Exception:
            logger.warning("Window sweep failed", exc_info=True)


async def _sweep_expired_rag_chunks() -> None:
    """Delete Neon source excerpts older than the configured TTL, retaining metadata."""
    while True:
        settings = get_settings()
        if settings.rag_database_url:
            try:
                removed = await asyncio.to_thread(RagService(settings).delete_expired_chunks)
                if removed:
                    logger.info("Deleted %d expired Neon RAG chunk row(s)", removed)
            except Exception as exc:
                logger.warning("Neon RAG expiry sweep failed (%s)", type(exc).__name__)
        await asyncio.sleep(900)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting %s (env=%s)", settings.app_name, settings.app_env)
    try:
        cleanup_orphaned_workdirs()
        info = init_db()
        logger.info("Storage ready: %s (dialect=%s)", info.get("storage"), info.get("dialect"))
        capabilities = describe_capabilities()
        github_access = "authenticated" if settings.github_token else "anonymous"
        logger.info("Search: %s | GitHub access: %s, public repositories only | RAG chat: %s",
                    capabilities["search"]["ranking"], github_access,
                    "configured" if settings.rag_enabled else "not configured")
    except Exception as exc:
        logger.error("Database initialisation failed: %s", exc)
    sweepers = [
        asyncio.create_task(_sweep_closed_windows()),
        asyncio.create_task(_sweep_expired_rag_chunks()),
    ]
    try:
        yield
    finally:
        for sweeper in sweepers:
            sweeper.cancel()
        await asyncio.gather(*sweepers, return_exceptions=True)
        await get_manager().shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="RepoLens API",
        description=(
            "Static codebase intelligence and optional, source-grounded repository chat for public GitHub repositories. "
            "Analysis artifacts use in-memory SQLite and disappear when the API stops; temporary source checkouts are "
            "removed after each run. When RAG is configured, a bounded set of code excerpts and embeddings is stored "
            "in Neon pgvector, and retrieved excerpts are sent server-side to the configured model for chat. "
            "Only public repositories are supported. GitHub API access is anonymous by default; an optional server-side "
            "GITHUB_TOKEN can authenticate public-data requests for a higher rate limit."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def _disable_private_api_caching(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
            vary = {item.strip() for item in response.headers.get("Vary", "").split(",") if item.strip()}
            vary.update({"Cookie", "X-Window-Id", "Origin"})
            response.headers["Vary"] = ", ".join(sorted(vary, key=str.lower))
        return response

    app.include_router(routes_system.router, prefix="/api")
    app.include_router(routes_repos.router, prefix="/api")
    app.include_router(routes_analysis.router, prefix="/api")
    app.include_router(routes_chat.router, prefix="/api")
    app.include_router(routes_insights.router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {"name": "RepoLens API", "version": "0.1.0", "docs": "/docs", "health": "/api/health"}

    @app.get("/api", include_in_schema=False)
    def api_root() -> dict:
        return {"name": "RepoLens API", "version": "0.1.0",
                "endpoints": ["/api/health", "/api/system/capabilities", "/api/repos/resolve",
                              "/api/analyses", "/api/analyses/{analysis_id}/chat"]}

    return app


app = create_app()
