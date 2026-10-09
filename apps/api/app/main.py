"""RepoLens API application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from repolens_shared.errors import DatabaseError

from .api import routes_analysis, routes_chat, routes_insights, routes_repos, routes_system
from .core.capabilities import describe_capabilities
from .core.config import get_settings
from .core.db import init_db
from .core.errors import install_error_handlers
from .core.logging import configure_logging
from .services.analysis import get_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting %s (env=%s)", settings.app_name, settings.app_env)
    try:
        info = init_db()
        logger.info("Database ready: dialect=%s pgvector=%s", info.get("dialect"), info.get("pgvector"))
        capabilities = describe_capabilities()
        logger.info("LLM: %s | embeddings: %s | GitHub authenticated: %s",
                    capabilities["llm"]["mode"], capabilities["embeddings"]["provider"],
                    capabilities["github"]["authenticated"])
    except Exception as exc:
        logger.error("Database initialisation failed: %s", exc)
    yield
    await get_manager().shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="RepoLens API",
        description=(
            "Codebase intelligence for public GitHub repositories: architecture, workflows, dependencies, "
            "APIs, database usage, code quality and grounded Q&A over real analysed artefacts."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    install_error_handlers(app)

    app.include_router(routes_system.router, prefix="/api")
    app.include_router(routes_repos.router, prefix="/api")
    app.include_router(routes_analysis.router, prefix="/api")
    app.include_router(routes_insights.router, prefix="/api")
    app.include_router(routes_chat.router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {"name": "RepoLens API", "version": "0.1.0", "docs": "/docs", "health": "/api/health"}

    @app.get("/api", include_in_schema=False)
    def api_root() -> dict:
        return {"name": "RepoLens API", "version": "0.1.0",
                "endpoints": ["/api/health", "/api/system/capabilities", "/api/repos/resolve", "/api/analyses"]}

    return app


app = create_app()
