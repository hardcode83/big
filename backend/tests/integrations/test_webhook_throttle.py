"""The two webhook limiters of rule 12(c) (`reservations-webhooks` R3.1, R3.3, R3.4, D6).

Against the real Redis of the compose stack and **without a skip**, for the reason
`tests/auth/test_throttle.py` records: a fake proves nothing about the adapter that ships, and a
skip lets the only tests of the only production implementation vanish into the skip count with
nothing red. The project's test command always has Redis, so an unreachable one is a broken
environment and should fail loudly.
"""

import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.core.config import settings
from app.integrations.infrastructure.throttle import RedisWebhookThrottle


@pytest_asyncio.fixture
async def redis_client():
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    await client.ping()
    yield client
    await client.aclose()


@pytest.fixture
def unique_token() -> str:
    # Keys are shared with the dev stack, so every test invents its own subject.
    return uuid.uuid4().hex


@pytest.fixture
def unique_ip() -> str:
    return f"198.51.100.{uuid.uuid4().int % 250}-{uuid.uuid4().hex[:8]}"


def _throttle(redis_client, **overrides) -> RedisWebhookThrottle:
    values = {"deliveries_per_minute": 120, "probes_per_minute": 20}
    values.update(overrides)
    return RedisWebhookThrottle(redis_client, **values)


# --- The per-token limit (R3.1) ---


@pytest.mark.asyncio
async def test_deliveries_are_allowed_up_to_the_limit_and_refused_after(
    redis_client, unique_token
) -> None:
    throttle = _throttle(redis_client, deliveries_per_minute=3)

    assert [await throttle.delivery_allowed(unique_token) for _ in range(3)] == [
        True,
        True,
        True,
    ]
    assert await throttle.delivery_allowed(unique_token) is False


@pytest.mark.asyncio
async def test_one_tenants_flood_does_not_refuse_another(redis_client) -> None:
    """The limit is keyed by token, so its blast radius is one tenant.

    This is the property that makes a *generous* per-token limit the right instrument: a runaway
    provider loop costs its own tenant and nobody else.
    """
    throttle = _throttle(redis_client, deliveries_per_minute=2)
    flooded, quiet = uuid.uuid4().hex, uuid.uuid4().hex

    for _ in range(5):
        await throttle.delivery_allowed(flooded)

    assert await throttle.delivery_allowed(flooded) is False
    assert await throttle.delivery_allowed(quiet) is True


# --- The per-IP probe limit (R3.4) ---


@pytest.mark.asyncio
async def test_probing_is_refused_once_the_failures_pile_up(redis_client, unique_ip) -> None:
    """Guessing a route token has to cost something."""
    throttle = _throttle(redis_client, probes_per_minute=3)

    assert await throttle.probe_allowed(unique_ip) is True
    for _ in range(3):
        await throttle.record_failed_attempt(unique_ip)

    assert await throttle.probe_allowed(unique_ip) is False


@pytest.mark.asyncio
async def test_legitimate_traffic_from_a_busy_provider_ip_is_never_probe_limited(
    redis_client, unique_ip
) -> None:
    """**The test D6 exists for.** A provider sends from few IPs for MANY tenants.

    So the per-IP limit must count only what a legitimate provider never does: fail. Two hundred
    successful deliveries from one address — far past the strict probe ceiling of 20 — must leave
    that address entirely unthrottled. A limiter that counted requests instead of failures would
    throttle every tenant of that provider at once, which is the failure mode D6 rejects by name.
    """
    throttle = _throttle(redis_client, probes_per_minute=3)

    for _ in range(200):
        await throttle.delivery_allowed(uuid.uuid4().hex)

    assert await throttle.probe_allowed(unique_ip) is True


@pytest.mark.asyncio
async def test_asking_whether_a_probe_is_allowed_does_not_itself_count(
    redis_client, unique_ip
) -> None:
    """`probe_allowed` is a question, not an attempt.

    If asking incremented, the check that runs on every request would consume the budget meant
    for failures, and a provider's ordinary traffic would lock out its own IP.
    """
    throttle = _throttle(redis_client, probes_per_minute=2)

    for _ in range(50):
        assert await throttle.probe_allowed(unique_ip) is True


@pytest.mark.asyncio
async def test_the_two_limits_do_not_share_a_counter(redis_client, unique_ip) -> None:
    """Exhausting one must leave the other untouched — they are different defences."""
    throttle = _throttle(redis_client, deliveries_per_minute=1, probes_per_minute=1)
    token = uuid.uuid4().hex

    await throttle.record_failed_attempt(unique_ip)
    assert await throttle.probe_allowed(unique_ip) is False

    assert await throttle.delivery_allowed(token) is True


# --- The window (R3.3, and the lost-EXPIRE failure the login throttle already paid for) ---


@pytest.mark.asyncio
async def test_every_counter_carries_an_expiry(redis_client, unique_ip) -> None:
    """A counter without a TTL never lapses, and refuses that subject forever.

    Recoverable only by deleting a Redis key by hand — for the delivery limit that means a
    tenant's webhooks silently dropped until somebody notices. Pinned because the failure is
    invisible until it is severe.
    """
    throttle = _throttle(redis_client)
    token = uuid.uuid4().hex

    await throttle.delivery_allowed(token)
    await throttle.record_failed_attempt(unique_ip)

    assert 0 < await redis_client.ttl(f"webhook:token:{token}") <= 60
    assert 0 < await redis_client.ttl(f"webhook:probe:{unique_ip}") <= 60


@pytest.mark.asyncio
async def test_the_window_does_not_slide_forward_on_each_hit(redis_client) -> None:
    """`nx` on the EXPIRE: a steady stream must not push the window ahead of itself.

    Without it a caller sending continuously would reset the TTL on every request and the counter
    would never reset — the limit would become permanent rather than per-minute.
    """
    throttle = _throttle(redis_client)
    token = uuid.uuid4().hex

    await throttle.delivery_allowed(token)
    first = await redis_client.pttl(f"webhook:token:{token}")
    await throttle.delivery_allowed(token)
    second = await redis_client.pttl(f"webhook:token:{token}")

    assert second <= first


# --- Configuration, not scattered literals (R3.3) ---


def test_both_limits_are_configuration_with_defaults() -> None:
    """R3.3, and rule 8: neither is a secret, so both carry a default."""
    assert settings.webhook_rate_limit_per_minute == 120
    assert settings.webhook_probe_limit_per_minute == 20


def test_the_generous_limit_is_the_per_token_one() -> None:
    """The direction of the asymmetry, pinned.

    Swapping the two numbers would leave every test above green while making the per-IP limit the
    generous one — which is precisely the configuration D6 rejects, because it throttles a
    provider's legitimate multi-tenant traffic and makes probing cheap.
    """
    assert settings.webhook_rate_limit_per_minute > settings.webhook_probe_limit_per_minute
