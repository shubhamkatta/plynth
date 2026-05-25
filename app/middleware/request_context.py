"""Request-scoped logging context: request_id, propagated to structlog + headers.

Also acts as the last-resort error logger: if anything escapes the FastAPI
exception handlers (e.g. a middleware itself raising), it still gets logged
with request context before being re-raised.
"""

from collections.abc import Awaitable, Callable
from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger("request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response: Response = await call_next(request)
        except Exception:
            # FastAPI handlers normally catch this; this only fires if
            # something in the middleware stack itself raised.
            log.exception(
                "middleware_unhandled_exception",
                method=request.method,
                path=request.url.path,
            )
            raise
        response.headers["X-Request-ID"] = request_id
        return response
