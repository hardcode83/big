"""Login throttling and account lockout (R5.1-R5.4, design D13).

The Redis adapter is exercised against the real Redis of the compose stack — it is
the store the requirement is about, and a fake would not prove the counters are
shared across processes. Skipped when Redis is unreachable so the suite still runs.
"""

import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.auth.infrastructure.throttle import RedisLoginThrottle
from app.core.config import settings
from tests.auth.doubles import InMemoryLoginThrottle


@pytest_asyncio.fixture
async def redis_client():
    """Requires a reachable Redis, deliberately without a skip.

    An earlier version skipped when Redis was unreachable. That made the only tests
    of the only production implementation of R5.1-R5.4 able to vanish into the skip
    count with nothing red — and `InMemoryLoginThrottle` passing says nothing about
    the Redis adapter. The project's own test command is
    `docker compose exec backend uv run pytest`, which always has Redis, so an
    unreachable Redis is a broken environment and should fail loudly.
    """
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    await client.ping()
    yield client
    await client.aclose()


@pytest.fixture
def unique_ip() -> str:
    # Keys are shared with the dev stack; a unique IP keeps runs independent.
    return f"203.0.113.{uuid.uuid4().int % 250}-{uuid.uuid4().hex[:8]}"


def _throttle(redis_client, **overrides) -> RedisLoginThrottle:
    values = {"attempts_per_minute": 10, "max_failures": 10, "lockout_minutes": 15}
    values.update(overrides)
    return RedisLoginThrottle(redis_client, **values)


@pytest.mark.asyncio
async def test_the_tenth_attempt_is_still_allowed_and_the_eleventh_is_not(
    redis_client, unique_ip
) -> None:
    throttle = _throttle(redis_client)

    allowed = [await throttle.ip_attempt_allowed(unique_ip) for _ in range(11)]

    assert allowed[:10] == [True] * 10
    assert allowed[10] is False


@pytest.mark.asyncio
async def test_the_ip_counter_expires(redis_client, unique_ip) -> None:
    throttle = _throttle(redis_client)

    await throttle.ip_attempt_allowed(unique_ip)

    ttl = await redis_client.ttl(f"login:ip:{unique_ip}")
    assert 0 < ttl <= 60


@pytest.mark.asyncio
async def test_a_counter_left_without_a_ttl_gets_one_on_the_next_attempt(
    redis_client, unique_ip
) -> None:
    """Design D20: the TTL is re-asserted on every attempt, not only the first.

    The pre-fix code only set it when INCR returned 1, so a lost EXPIRE left the key
    permanently without a TTL and that IP was refused forever. Simulated here by
    incrementing the key directly, exactly as a crashed first attempt would leave it.
    """
    key = f"login:ip:{unique_ip}"
    await redis_client.incr(key)
    assert await redis_client.ttl(key) == -1  # no expiry

    await _throttle(redis_client).ip_attempt_allowed(unique_ip)

    assert 0 < await redis_client.ttl(key) <= 60


@pytest.mark.asyncio
async def test_the_window_does_not_slide_forward_on_later_attempts(
    redis_client, unique_ip
) -> None:
    """`EXPIRE ... NX` only sets a TTL when there is none, so the minute is fixed."""
    key = f"login:ip:{unique_ip}"
    throttle = _throttle(redis_client)
    await throttle.ip_attempt_allowed(unique_ip)
    await redis_client.expire(key, 5)

    await throttle.ip_attempt_allowed(unique_ip)

    assert await redis_client.ttl(key) <= 5


@pytest.mark.asyncio
async def test_the_failure_counter_also_recovers_a_missing_ttl(redis_client) -> None:
    user_id = uuid.uuid4()
    key = f"login:fail:{user_id}"
    await redis_client.incr(key)
    assert await redis_client.ttl(key) == -1

    await _throttle(redis_client, max_failures=10).record_failure(user_id)

    assert await redis_client.ttl(key) > 0


@pytest.mark.asyncio
async def test_different_ips_have_independent_budgets(redis_client, unique_ip) -> None:
    throttle = _throttle(redis_client, attempts_per_minute=1)
    other_ip = f"{unique_ip}-other"

    assert await throttle.ip_attempt_allowed(unique_ip) is True
    assert await throttle.ip_attempt_allowed(unique_ip) is False
    assert await throttle.ip_attempt_allowed(other_ip) is True


@pytest.mark.asyncio
async def test_an_account_locks_after_the_configured_failures(redis_client) -> None:
    throttle = _throttle(redis_client, max_failures=10)
    user_id = uuid.uuid4()

    for _ in range(9):
        await throttle.record_failure(user_id)
    assert await throttle.is_account_locked(user_id) is False

    await throttle.record_failure(user_id)

    assert await throttle.is_account_locked(user_id) is True


@pytest.mark.asyncio
async def test_the_lock_expires_rather_than_being_permanent(redis_client) -> None:
    # R5.2 assumption: a temporary lock, so no manual unlock endpoint is needed.
    throttle = _throttle(redis_client, max_failures=1, lockout_minutes=15)
    user_id = uuid.uuid4()

    await throttle.record_failure(user_id)

    ttl = await redis_client.ttl(f"login:lock:{user_id}")
    assert 0 < ttl <= 15 * 60


@pytest.mark.asyncio
async def test_a_successful_login_clears_the_failure_count(redis_client) -> None:
    throttle = _throttle(redis_client, max_failures=3)
    user_id = uuid.uuid4()
    await throttle.record_failure(user_id)
    await throttle.record_failure(user_id)

    await throttle.reset_failures(user_id)
    await throttle.record_failure(user_id)

    # Had the counter survived, this third failure would have locked the account.
    assert await throttle.is_account_locked(user_id) is False


@pytest.mark.asyncio
async def test_accounts_lock_independently(redis_client) -> None:
    throttle = _throttle(redis_client, max_failures=1)
    locked_user, other_user = uuid.uuid4(), uuid.uuid4()

    await throttle.record_failure(locked_user)

    assert await throttle.is_account_locked(locked_user) is True
    assert await throttle.is_account_locked(other_user) is False


@pytest.mark.asyncio
async def test_two_throttle_instances_share_state(redis_client, unique_ip) -> None:
    """R5.4: the counters must hold across processes, not per instance."""
    first = _throttle(redis_client, attempts_per_minute=1)
    second = _throttle(redis_client, attempts_per_minute=1)

    assert await first.ip_attempt_allowed(unique_ip) is True

    assert await second.ip_attempt_allowed(unique_ip) is False


@pytest.mark.asyncio
async def test_the_in_memory_double_matches_the_adapter_contract() -> None:
    double = InMemoryLoginThrottle(attempts_per_minute=2, max_failures=2)
    user_id = uuid.uuid4()

    assert [await double.ip_attempt_allowed("ip") for _ in range(3)] == [True, True, False]
    await double.record_failure(user_id)
    assert await double.is_account_locked(user_id) is False
    await double.record_failure(user_id)
    assert await double.is_account_locked(user_id) is True
