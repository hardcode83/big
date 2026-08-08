"""The chain end to end: proxy header → `get_client_ip` → the Redis bucket (R5.1, R5.2).

Exists because a QA review found that task 1.2 **claimed** to close R5.1/R5.2 and did not.
`test_client_ip.py` stops at address resolution; `test_throttle.py` drives the throttle with
synthetic keys that never came from the proxy-trust chain. Both are correct and neither
proves the property the requirement is actually about: that with a proxy in the middle, the
10/min limit discriminates by the **real** client.

So this file joins the two halves — uvicorn's `ProxyHeadersMiddleware` resolving the address,
and the real `RedisLoginThrottle` counting against it.
"""

import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.auth.api.dependencies import get_client_ip
from app.auth.infrastructure.throttle import RedisLoginThrottle
from app.core.config import settings

# The frontend container's address in the deploy compose: the one trusted peer.
PROXY = "10.89.0.10"
# Anything else on `private`, or the bridge gateway a published-port caller is SNATed to.
UNTRUSTED_PEER = "10.89.0.99"


@pytest_asyncio.fixture
async def redis_client():
    """Requires a reachable Redis, deliberately without a skip — same rationale as
    `test_throttle.py`: the project's test command always has one, so unreachable Redis is a
    broken environment and must fail loudly rather than vanish into the skip count."""
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    await client.ping()
    yield client
    await client.aclose()


async def _resolved_client_ip(forwarded_for: str, *, peer: str, trusted: str = PROXY) -> str:
    """What `get_client_ip` returns once uvicorn's middleware has had its say."""
    seen: dict[str, str] = {}

    async def app(scope, receive, send) -> None:
        seen["ip"] = get_client_ip(Request(scope, receive))

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        return None

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "headers": [(b"x-forwarded-for", forwarded_for.encode())],
        "client": (peer, 4242),
    }
    await ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, receive, send)
    return seen["ip"]


def _throttle(redis_client, attempts_per_minute: int) -> RedisLoginThrottle:
    return RedisLoginThrottle(
        redis_client,
        attempts_per_minute=attempts_per_minute,
        max_failures=10,
        lockout_minutes=15,
    )


# The Redis keys are shared with the dev stack, so every test namespaces its own run.
def _run_suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest.mark.asyncio
async def test_two_real_clients_behind_the_proxy_get_independent_budgets(
    redis_client,
) -> None:
    """R5.2 through the real chain.

    The socket peer is the SAME for both requests — that is what makes this the property
    worth testing. Before the trust list existed both resolved to the frontend container, so
    one attacker exhausted the only bucket there was and locked everybody out of login.
    """
    suffix = _run_suffix()
    first = await _resolved_client_ip("198.51.100.7", peer=PROXY)
    second = await _resolved_client_ip("203.0.113.9", peer=PROXY)

    assert first == "198.51.100.7"
    assert second == "203.0.113.9"

    throttle = _throttle(redis_client, attempts_per_minute=3)
    first_key, second_key = f"{first}-{suffix}", f"{second}-{suffix}"

    for _ in range(3):
        assert await throttle.ip_attempt_allowed(first_key) is True

    assert await throttle.ip_attempt_allowed(first_key) is False, (
        "the real client spent its own budget"
    )
    assert await throttle.ip_attempt_allowed(second_key) is True, (
        "and did not spend the other client's"
    )


@pytest.mark.asyncio
async def test_a_spoofing_caller_cannot_buy_itself_a_fresh_budget(redis_client) -> None:
    """R5.1 from the attacker's side, with the control alongside it.

    From an untrusted peer the middleware ignores the header, so every forged value
    collapses onto the peer's own bucket and the limit still bites. The control matters:
    the same four values DO produce four buckets when they come from the trusted proxy, so
    the test is measuring the trust decision and not merely a broken header parser.
    """
    forged = ["198.51.100.1", "198.51.100.2", "198.51.100.3", "198.51.100.4"]

    from_proxy = {await _resolved_client_ip(v, peer=PROXY) for v in forged}
    from_attacker = {await _resolved_client_ip(v, peer=UNTRUSTED_PEER) for v in forged}

    assert len(from_proxy) == 4, "control: from the trusted proxy these are four clients"
    assert from_attacker == {UNTRUSTED_PEER}, "from an untrusted peer they are one"

    throttle = _throttle(redis_client, attempts_per_minute=3)
    key = f"{UNTRUSTED_PEER}-{_run_suffix()}"

    for _ in range(3):
        assert await throttle.ip_attempt_allowed(key) is True

    assert await throttle.ip_attempt_allowed(key) is False, (
        "rotating the header bought no extra attempts"
    )


@pytest.mark.asyncio
async def test_a_rotating_zone_id_does_not_multiply_buckets_in_redis(redis_client) -> None:
    """The scoped-IPv6 hole, asserted where it would actually have hurt.

    A zone identifier is nearly-free-form text, so `fe80::1%<anything>` was a distinct
    string — and therefore a distinct Redis key — for every request. This checks the fix at
    the throttle rather than only at the resolver.
    """
    suffix = _run_suffix()
    resolved = {
        await _resolved_client_ip(f"fe80::1%zone{n}", peer=PROXY) for n in range(6)
    }

    assert resolved == {"127.0.0.1"}, "all six collapse onto the fail-closed fallback"

    throttle = _throttle(redis_client, attempts_per_minute=3)
    key = f"{next(iter(resolved))}-{suffix}"

    for _ in range(3):
        assert await throttle.ip_attempt_allowed(key) is True

    assert await throttle.ip_attempt_allowed(key) is False
