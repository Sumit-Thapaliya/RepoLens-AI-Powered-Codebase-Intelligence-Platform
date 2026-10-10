"""RepoLens API application."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import routes_analysis, routes_insights, routes_repos, routes_system
from .analyzers.pipeline import cleanup_orphaned_workdirs
from .core.capabilities import describe_capabilities
from .core.config import get_settings
from .core.db import init_db
from .core.errors import install_error_handlers
from .core.logging import configure_logging
from .services.analysis import get_manager

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
        logger.info("Search: %s | GitHub access: anonymous, public repositories only",
                    capabilities["search"]["ranking"])
    except Exception as exc:
        logger.error("Database initialisation failed: %s", exc)
    sweeper = asyncio.create_task(_sweep_closed_windows())
    yield
    sweeper.cancel()
    await get_manager().shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="RepoLens API",
        description=(
            "Static codebase intelligence for GitHub repositories: architecture, workflows, dependencies, "
            "APIs, database usage, code quality and ranked search. Analysis artifacts use in-memory SQLite "
            "and disappear when the API stops; temporary source checkouts are removed after each run. "
            "GitHub access is anonymous, so only public repositories are supported and GitHub's lower "
            "anonymous API rate limit applies."
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
    app.include_router(routes_insights.router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {"name": "RepoLens API", "version": "0.1.0", "docs": "/docs", "health": "/api/health"}

    @app.get("/api", include_in_schema=False)
    def api_root() -> dict:
        return {"name": "RepoLens API", "version": "0.1.0",
                "endpoints": ["/api/health", "/api/system/capabilities", "/api/repos/resolve", "/api/analyses"]}

    return app


app = create_app()
