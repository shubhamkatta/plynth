from collections.abc import AsyncIterator
from typing import cast

import redis.asyncio as aioredis

from app.core.config import settings

_pool: aioredis.ConnectionPool | None = None


def get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            str(settings.redis_url), decode_responses=True, max_connections=64
        )
    return _pool


def get_redis() -> aioredis.Redis:
    return cast(aioredis.Redis, aioredis.Redis(connection_pool=get_pool()))


async def redis_dep() -> AsyncIterator[aioredis.Redis]:
    client = get_redis()
    try:
        yield client
    finally:
        await client.aclose()
