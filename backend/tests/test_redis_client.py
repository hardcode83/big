"""The shared Redis client must be lazy: importing must not connect (R5.4)."""

import pytest

from app.core import redis as core_redis


@pytest.fixture(autouse=True)
def _reset_client():
    core_redis._client = None
    yield
    core_redis._client = None


def test_importing_the_module_does_not_build_a_client() -> None:
    assert core_redis._client is None


def test_the_client_is_built_once_and_reused() -> None:
    first = core_redis.get_redis()
    second = core_redis.get_redis()

    assert first is second


@pytest.mark.asyncio
async def test_closing_releases_the_client() -> None:
    core_redis.get_redis()

    await core_redis.close_redis()

    assert core_redis._client is None
