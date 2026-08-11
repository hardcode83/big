"""The guest portal's two limiters (R2.4, design D6).

Against the real Redis of the compose stack and **without a skip**, following
`tests/integrations/test_webhook_throttle.py`: a fake proves nothing about the adapter that
ships, and a skip lets the only tests of the only production implementation vanish into the
skip count with nothing red. The project's test command always has Redis, so an unreachable
one is a broken environment and should fail loudly.
"""

import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.core.config import settings
from app.guests.infrastructure.portal_throttle import RedisGuestPortalThrottle


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


def _throttle(redis_client, **overrides) -> RedisGuestPortalThrottle:
    values = {"requests_per_minute": 60, "probes_per_minute": 20}
    values.update(overrides)
    return RedisGuestPortalThrottle(redis_client, **values)


# --- The per-token limit (R2.4, and the only bound on `POST /guest/incident`) ---------


@pytest.mark.asyncio
async def test_requests_are_allowed_up_to_the_limit_and_refused_after(
    redis_client, unique_token
) -> None:
    """`<=`, so exactly `limit` requests fit in a window.

    This limit matters more here than its webhook sibling does: a valid token can open
    incidents indefinitely and the endpoint is deliberately not idempotent (D13), so this is
    what bounds how many rows one stay produces.
    """
    throttle = _throttle(redis_client, requests_per_minute=3)

    assert [await throttle.request_allowed(unique_token) for _ in range(3)] == [True] * 3
    assert await throttle.request_allowed(unique_token) is False


@pytest.mark.asyncio
async def test_two_stays_have_separate_budgets(redis_client) -> None:
    """Keyed by the digest, so one guest cannot exhaust another's portal."""
    throttle = _throttle(redis_client, requests_per_minute=1)
    first, second = uuid.uuid4().hex, uuid.uuid4().hex

    assert await throttle.request_allowed(first) is True
    assert await throttle.request_allowed(first) is False
    assert await throttle.request_allowed(second) is True


@pytest.mark.asyncio
async def test_the_token_key_carries_the_digest_and_never_the_token(
    redis_client, unique_token
) -> None:
    """R1.2 reaches Redis too.

    These keys can end up in a `KEYS` dump, a `MONITOR` stream or a memory snapshot. The
    caller passes the digest the authoriser already resolved — and this asserts the adapter
    does not helpfully re-derive anything else on the way in.
    """
    throttle = _throttle(redis_client)

    await throttle.request_allowed(unique_token)

    keys = [key async for key in redis_client.scan_iter(match=f"*{unique_token}*")]
    assert keys == [f"guest_portal:token:{unique_token}"]


@pytest.mark.asyncio
async def test_the_window_does_not_slide_forward_on_each_hit(
    redis_client, unique_token
) -> None:
    """`expire(..., nx=True)`, and the reason the TTL is re-asserted rather than set once.

    Without `nx` every hit would push the expiry out, so a stay under steady traffic would
    never see its counter lapse — a fixed window silently becoming a permanent quota. The
    sibling throttle has this test; the section 5 QA panel noticed this file mirrored it
    test-for-test except for this one, which is exactly the edit `_hit` is most likely to
    lose.
    """
    throttle = _throttle(redis_client)
    key = f"guest_portal:token:{unique_token}"

    await throttle.request_allowed(unique_token)
    await redis_client.expire(key, 5)
    await throttle.request_allowed(unique_token)

    assert await redis_client.ttl(key) <= 5


@pytest.mark.asyncio
async def test_the_counter_expires_so_a_stay_is_not_locked_out_for_ever(
    redis_client, unique_token
) -> None:
    """The TTL is what makes this a *rate* limit rather than a quota.

    Asserted because the failure is silent and permanent: a key that outlived its window
    would refuse a guest their own check-in until somebody deleted it by hand.
    """
    throttle = _throttle(redis_client)

    await throttle.request_allowed(unique_token)

    assert 0 < await redis_client.ttl(f"guest_portal:token:{unique_token}") <= 60


# --- The per-IP probe limit (R2.4) ----------------------------------------------------


@pytest.mark.asyncio
async def test_probing_is_allowed_until_the_failures_run_out(redis_client, unique_ip) -> None:
    """Strictly `<`: after `limit` failures the budget is spent, not `limit + 1`."""
    throttle = _throttle(redis_client, probes_per_minute=2)

    assert await throttle.probe_allowed(unique_ip) is True
    await throttle.record_failed_authorisation(unique_ip)
    assert await throttle.probe_allowed(unique_ip) is True
    await throttle.record_failed_authorisation(unique_ip)
    assert await throttle.probe_allowed(unique_ip) is False


@pytest.mark.asyncio
async def test_asking_does_not_spend_the_budget(redis_client, unique_ip) -> None:
    """`probe_allowed` is a question, not an attempt — the distinction D6 rests on.

    If asking also incremented, a guest's ordinary successful traffic would count against the
    probe limit, and the two limits would collapse into the single per-IP one that puts a
    hotel's whole WiFi in one bucket.
    """
    throttle = _throttle(redis_client, probes_per_minute=2)

    for _ in range(10):
        assert await throttle.probe_allowed(unique_ip) is True


@pytest.mark.asyncio
async def test_only_failures_are_counted(redis_client, unique_ip, unique_token) -> None:
    """A guest who succeeds never approaches the probe ceiling, however much they use it."""
    throttle = _throttle(redis_client, probes_per_minute=1)

    for _ in range(5):
        await throttle.request_allowed(unique_token)

    assert await throttle.probe_allowed(unique_ip) is True


@pytest.mark.asyncio
async def test_two_addresses_have_separate_probe_budgets(redis_client) -> None:
    """A guest behind one address must not be locked out by a guesser behind another."""
    throttle = _throttle(redis_client, probes_per_minute=1)
    first = f"198.51.100.10-{uuid.uuid4().hex[:8]}"
    second = f"198.51.100.11-{uuid.uuid4().hex[:8]}"

    await throttle.record_failed_authorisation(first)

    assert await throttle.probe_allowed(first) is False
    assert await throttle.probe_allowed(second) is True


@pytest.mark.asyncio
async def test_the_probe_counter_expires(redis_client, unique_ip) -> None:
    """Otherwise a shared address — the hotel WiFi D6 names — is banned permanently."""
    throttle = _throttle(redis_client)

    await throttle.record_failed_authorisation(unique_ip)

    assert 0 < await redis_client.ttl(f"guest_portal:probe:{unique_ip}") <= 60


# --- The two limits are independent (D6) ----------------------------------------------


@pytest.mark.asyncio
async def test_the_two_limits_do_not_share_a_key(redis_client) -> None:
    """Separate namespaces, so exhausting one says nothing about the other.

    Worth pinning as a key-shape assertion: a collision here would be invisible in behaviour
    until a token hash happened to equal an IP string, and would then be inexplicable.
    """
    throttle = _throttle(redis_client, requests_per_minute=1, probes_per_minute=1)
    subject = uuid.uuid4().hex

    await throttle.request_allowed(subject)

    assert await throttle.probe_allowed(subject) is True
