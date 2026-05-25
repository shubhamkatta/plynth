"""Sliding-window rate limit backed by Redis.

Keyed by client IP (or X-Forwarded-For if behind a trusted proxy) + route.
For per-tenant limits, swap the key builder to include `tenant_id`.

Fails open if Redis is unreachable — better to serve traffic than to outage
on a cache dependency. The Redis error is logged once per failure.
"""

from collections.abc import Awaitable, Callable
from time import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.redis import get_redis

WINDOW_SECONDS = 60

log = structlog.get_logger("rate_limit")


def _client_key(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "anon")
    return f"rl:{ip}:{request.url.path}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in {"/health", "/ready"}:
            return await call_next(request)

        try:
            redis = get_redis()
            key = _client_key(request)
            now_ms = int(time() * 1000)
            cutoff = now_ms - WINDOW_SECONDS * 1000

            async with redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, 0, cutoff)
                pipe.zadd(key, {f"{now_ms}:{id(request)}": now_ms})
                pipe.zcard(key)
                pipe.expire(key, WINDOW_SECONDS + 5)
                _, _, count, _ = await pipe.execute()
        except Exception as exc:
            # Cache outage must not become an HTTP outage.
            log.warning("rate_limit.unavailable", error=str(exc))
            return await call_next(request)

        if count > settings.rate_limit_per_minute:
            log.warning(
                "rate_limit.exceeded",
                path=request.url.path,
                count=int(count),
                limit=settings.rate_limit_per_minute,
            )
            return JSONResponse(
                {"code": "rate_limited", "message": "Too many requests", "details": {}},
                status_code=429,
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )

        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, settings.rate_limit_per_minute - int(count))
        )
        return response
