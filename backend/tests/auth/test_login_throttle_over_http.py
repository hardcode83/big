"""The login throttle over HTTP, with uvicorn's proxy middleware in the path (R5.1, R5.2).

This is the test task 1.2 said it had written and had not. Its description claimed "contra
la app real con `httpx AsyncClient` para que el middleware de uvicorn no quede fuera del
camino"; what it produced wrapped a bespoke inline ASGI function, so the real dependency
wiring (`app/auth/api/router.py`, `get_client_ip`, `get_login_throttle`) was never in the
path. A QA review caught the gap twice — first as "no integration test at all", then as
"the integration test does not reach HTTP fidelity". This closes it.

What is real here, and it is everything the requirement is about: `ProxyHeadersMiddleware`
wrapping `create_app()` exactly as uvicorn wraps it, the socket peer chosen per request
(`ASGITransport(client=...)`), the real `get_client_ip`, the real `RedisLoginThrottle`
against real Redis, and the real endpoint answering over HTTP.

What is swapped, following this package's own convention (`test_api.py`): the database
session and the bcrypt cost. Neither participates in deciding which bucket an attempt is
counted against, which is the property under test. The Redis client is built per test
rather than taken from `app.core.redis.get_redis`, whose module-level memoisation binds a
connection pool to the first event loop that touches it.

The failure this catches and none of the earlier tests could: if `router.py` passed the
wrong value as `client_ip`, or stopped passing it, every other test would stay green.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.auth.api.dependencies import get_login_throttle, get_password_hasher
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.throttle import RedisLoginThrottle
from app.core.config import settings
from app.core.db import get_db_session
from app.main import create_app
from tests.auth.conftest import TEST_BCRYPT_ROUNDS

# The frontend container's address in the deploy compose: the one trusted peer.
PROXY = "10.89.0.10"
# Anything else that can open a socket to the backend.
UNTRUSTED_PEER = "10.89.0.99"

LOGIN = "/api/v1/auth/login"
RATE_LIMITED = 429
BUDGET = 3


@pytest_asyncio.fixture
async def redis_client():
    """A client bound to THIS test's event loop. No skip when Redis is unreachable —
    same reasoning as `test_throttle.py`: the project's test command always has one."""
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    await client.ping()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def stack(db_session, redis_client):
    """`ProxyHeadersMiddleware` → `create_app()`, with a factory for per-peer clients."""
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_login_throttle] = lambda: RedisLoginThrottle(
        redis_client,
        attempts_per_minute=BUDGET,
        max_failures=10,
        lockout_minutes=15,
    )
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )

    # Imported here so the module still imports without uvicorn present.
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=PROXY)

    class _Stack:
        @staticmethod
        async def attempt(forwarded_for: str, *, peer: str = PROXY):
            transport = ASGITransport(app=wrapped, client=(peer, 4242))
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                return await client.post(
                    LOGIN,
                    json={"email": "nobody@example.test", "password": "wrong"},
                    headers={"x-forwarded-for": forwarded_for},
                )

        @staticmethod
        async def refresh_attempt(forwarded_for: str, *, peer: str = PROXY):
            transport = ASGITransport(app=wrapped, client=(peer, 4242))
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": "not-a-real-token"},
                    headers={"x-forwarded-for": forwarded_for},
                )

        @classmethod
        async def exhaust(cls, forwarded_for: str, *, peer: str = PROXY) -> int:
            for _ in range(BUDGET):
                await cls.attempt(forwarded_for, peer=peer)
            response = await cls.attempt(forwarded_for, peer=peer)
            return response.status_code

    yield _Stack


def _unique_client_ip() -> str:
    """A distinct address per run: the throttle's Redis keys are shared with the dev
    stack, so a fixed one would make runs interfere."""
    return f"198.51.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"


@pytest.mark.asyncio
async def test_a_real_client_behind_the_proxy_is_throttled_on_its_own_address(
    stack,
) -> None:
    """R5.1 end to end: the 429 comes from the real endpoint, keyed on the real client."""
    assert await stack.exhaust(_unique_client_ip()) == RATE_LIMITED


@pytest.mark.asyncio
async def test_the_throttled_response_carries_the_documented_envelope(stack) -> None:
    """`specs/auth-tenancy.md`: `429` with `{"error": {"code": "RATE_LIMITED", ...}}`."""
    client_ip = _unique_client_ip()
    for _ in range(BUDGET):
        await stack.attempt(client_ip)

    response = await stack.attempt(client_ip)

    assert response.status_code == RATE_LIMITED
    assert response.json()["error"]["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_one_client_exhausting_its_budget_does_not_lock_out_another(stack) -> None:
    """R5.2 end to end, and the property the whole change exists to protect.

    Both requests arrive from the SAME socket peer — the proxy — so before the trust list
    existed they shared one bucket and a single attacker denied login to everybody.
    """
    victim, attacker = _unique_client_ip(), _unique_client_ip()

    assert await stack.exhaust(attacker) == RATE_LIMITED
    assert (await stack.attempt(victim)).status_code != RATE_LIMITED


@pytest.mark.asyncio
async def test_a_caller_that_is_not_the_proxy_cannot_rotate_out_of_its_budget(
    stack,
) -> None:
    """R4.2/R5.1 end to end: from an untrusted peer the header is ignored, so every forged
    value lands in the peer's own bucket and the limit still bites."""
    for index in range(BUDGET):
        await stack.attempt(f"203.0.113.{index}", peer=UNTRUSTED_PEER)

    response = await stack.attempt("203.0.113.200", peer=UNTRUSTED_PEER)

    assert response.status_code == RATE_LIMITED


@pytest.mark.asyncio
async def test_refresh_is_rate_limited_per_client_too(stack) -> None:
    """R8: `/auth/refresh` is anonymous — the token IS the credential — and this change
    makes it reachable from the internet, where it mints access tokens.

    Before R8 it consulted no throttle at all, so an anonymous caller had an unlimited
    grinder against a credential operation while this change's own documents described the
    public surface as bounded by "throttle + Bearer".

    The tokens are deliberately invalid: what is under test is that the limit is consulted
    BEFORE the token is looked at, which is what makes it a mitigation rather than a
    courtesy — the same ordering `test_the_refusal_precedes_authentication` asserts for the
    body ceiling.
    """
    client_ip = _unique_client_ip()
    for _ in range(BUDGET):
        await stack.refresh_attempt(client_ip)

    response = await stack.refresh_attempt(client_ip)

    assert response.status_code == RATE_LIMITED
    assert response.json()["error"]["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_refresh_and_login_share_one_budget_per_client(stack) -> None:
    """Deliberate, and worth pinning: one bucket, not two.

    What the limit protects is the cost of anonymous credential work per client, so
    splitting it would let a caller spend two budgets from one address.
    """
    client_ip = _unique_client_ip()
    for _ in range(BUDGET):
        await stack.attempt(client_ip)

    response = await stack.refresh_attempt(client_ip)

    assert response.status_code == RATE_LIMITED, (
        "refresh should be refused on a budget already spent by login"
    )
