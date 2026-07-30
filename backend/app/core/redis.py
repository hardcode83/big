"""Shared async Redis client (design D13).

Redis is the only store shared across the `backend` and `worker` processes, which
is what makes the login throttle correct with more than one uvicorn worker (R5.4).
The client is built lazily so importing this module never opens a connection —
tests and Alembic must not need a running Redis.
"""

from redis.asyncio import Redis

from app.core.config import settings

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
