"""Uniform error envelopes: every failure the client sees has this shape."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from repolens_shared.errors import RepoLensError

logger = logging.getLogger(__name__)


def error_payload(code: str, message: str, hint: str | None = None, *, request_id: str | None = None,
                  detail: object | None = None) -> dict:
    return {
        "error": {"code": code, "message": message, "hint": hint, "detail": detail},
        "request_id": request_id,
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RepoLensError)
    async def _repolens_error(_request: Request, exc: RepoLensError):
        request_id = uuid.uuid4().hex[:12]
        logger.warning("[%s] %s: %s", request_id, exc.code, exc.message)
        payload = exc.to_dict()
        payload["request_id"] = request_id
        return JSONResponse(status_code=exc.http_status, content={"error": payload, "request_id": request_id})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        request_id = uuid.uuid4().hex[:12]
        return JSONResponse(
            status_code=422,
            content=error_payload("validation_error", "The request payload is invalid.",
                                  "Check the field names and types accepted by this endpoint.",
                                  request_id=request_id, detail=exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        request_id = uuid.uuid4().hex[:12]
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(f"http_{exc.status_code}", str(exc.detail or "Request failed."), None, request_id=request_id),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # pragma: no cover - safety net
        request_id = uuid.uuid4().hex[:12]
        logger.exception("[%s] Unhandled error on %s", request_id, request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_payload("internal_error", f"Unexpected server error: {type(exc).__name__}",
                                  "This has been logged. Retry; if it persists, check the API logs.",
                                  request_id=request_id),
        )
