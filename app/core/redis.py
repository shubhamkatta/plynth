from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis

from app.core.config import settings

# `redis.asyncio.{Redis,ConnectionPool}` are generic in the type stubs
# (so the stricter mypy gating can express `Redis[Any]`) but they're not
# generic at runtime — subscripting them with `[Any]` raises TypeError.
# Use `from __future__ import annotations` so the function signatures stay
# strings, and gate any value-position generic uses (e.g. `cast(...)`)
# behind TYPE_CHECKING.
if TYPE_CHECKING:
    RedisClient = aioredis.Redis[Any]
    RedisPool = aioredis.ConnectionPool[Any]
else:
    RedisClient = aioredis.Redis
    RedisPool = aioredis.ConnectionPool


_pool: RedisPool | None = None


def get_pool() -> RedisPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            str(settings.redis_url), decode_responses=True, max_connections=64
        )
    return _pool


def get_redis() -> RedisClient:
    return aioredis.Redis(connection_pool=get_pool())


async def redis_dep() -> AsyncIterator[RedisClient]:
    client = get_redis()
    try:
        yield client
    finally:
        # `aclose()` exists on redis-py 5.x AsyncRedis but isn't in the
        # type stubs yet; fall back to `close()` for the type checker.
        aclose = getattr(client, "aclose", client.close)
        await aclose()
