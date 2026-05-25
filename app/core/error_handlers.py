"""Global exception handlers + structured error logging.

The handlers map every exception type the platform cares about to a uniform
JSON envelope:

    {"code": "<machine_code>", "message": "<human>", "details": {...}}

and emit a structlog event at the right severity. The severity rules:

    AppError 4xx (client error)     → log.warning
    AppError 5xx (programmer error) → log.error
    RequestValidationError          → log.info  (just bad input)
    IntegrityError                  → log.warning  (mostly UNIQUE collisions)
    OperationalError                → log.error    (db unavailable)
    Unhandled Exception             → log.exception (with stack)

Every event carries request_id, method, path; user_id and tenant_id are added
by `bind_request_user_context` once the auth dependency has run.
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError

log = structlog.get_logger("error")


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details or {}}


def _ctx(request: Request) -> dict[str, Any]:
    return {
        "method": request.method,
        "path": request.url.path,
        "client": request.client.host if request.client else None,
    }


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        level = log.warning if exc.status_code < 500 else log.error
        level(
            "app_error",
            code=exc.code,
            status=exc.status_code,
            message=exc.message,
            details=exc.details,
            **_ctx(request),
        )
        return JSONResponse(
            _envelope(exc.code, exc.message, exc.details), status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Strip out unserialisable bits (e.g. raw bytes) but keep loc + msg + type.
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        log.info("validation_failed", errors=errors, **_ctx(request))
        return JSONResponse(
            _envelope("validation_failed", "Request payload failed validation",
                      {"errors": errors}),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = (exc.detail if isinstance(exc.detail, str) else "http_error").lower().replace(" ", "_")
        log.info(
            "http_error", status=exc.status_code, detail=str(exc.detail), **_ctx(request)
        ) if exc.status_code < 500 else log.error(
            "http_error", status=exc.status_code, detail=str(exc.detail), **_ctx(request)
        )
        return JSONResponse(
            _envelope(code, str(exc.detail) or "Error"), status_code=exc.status_code
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        # Most often: UNIQUE / FK violation surfaced from a race or bad input.
        log.warning(
            "db_integrity_error",
            error=str(exc.orig) if exc.orig else str(exc),
            **_ctx(request),
        )
        return JSONResponse(
            _envelope("conflict", "Resource already exists or violates a constraint"),
            status_code=409,
        )

    @app.exception_handler(OperationalError)
    async def _operational_error(request: Request, exc: OperationalError) -> JSONResponse:
        # DB unavailable, connection reset, etc. Caller should retry.
        log.error(
            "db_operational_error",
            error=str(exc.orig) if exc.orig else str(exc),
            **_ctx(request),
        )
        return JSONResponse(
            _envelope("service_unavailable", "Datastore temporarily unavailable"),
            status_code=503,
        )

    @app.exception_handler(SQLAlchemyError)
    async def _sqla_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        log.exception("db_error", error=str(exc), **_ctx(request))
        return JSONResponse(
            _envelope("internal_error", "Database error"), status_code=500
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Last resort. structlog.exception captures the full stack.
        log.exception("unhandled_exception", error_type=type(exc).__name__, **_ctx(request))
        return JSONResponse(
            _envelope("internal_error", "Internal server error"), status_code=500
        )
