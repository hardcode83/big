"""bcrypt hashing: the 72-byte limit refused rather than truncated (R1.3, D4),
and every call off the event loop under a bound (D21)."""

import asyncio
import threading

import pytest

from app.auth.domain.exceptions import PasswordTooLongError
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher

pytestmark = pytest.mark.asyncio

# Cheap rounds: the real default is 12, which would make this module crawl.
TEST_ROUNDS = 4
hasher = BcryptPasswordHasher(rounds=TEST_ROUNDS)


def _counting(original, calls: list[str], label: str):
    def wrapper(*args, **kwargs):
        calls.append(label)
        return original(*args, **kwargs)

    return wrapper


async def test_a_password_verifies_against_its_own_hash() -> None:
    assert await hasher.verify("correct horse", await hasher.hash("correct horse")) is True


async def test_a_wrong_password_does_not_verify() -> None:
    assert await hasher.verify("wrong horse", await hasher.hash("correct horse")) is False


async def test_hashing_the_same_password_twice_gives_different_hashes() -> None:
    # Distinct salts: identical hashes would leak that two users share a password.
    assert await hasher.hash("same") != await hasher.hash("same")


async def test_the_hash_does_not_contain_the_password() -> None:
    assert "correct horse" not in await hasher.hash("correct horse")


async def test_a_password_over_72_bytes_is_refused_not_truncated() -> None:
    # bcrypt silently ignores everything past 72 bytes, so accepting this would
    # mean "abc...(72)...X" and "abc...(72)...Y" are the same password (D4).
    with pytest.raises(PasswordTooLongError):
        await hasher.hash("a" * 73)


async def test_the_limit_counts_utf8_bytes_not_characters() -> None:
    # "é" is two bytes in UTF-8: 40 characters, 80 bytes.
    with pytest.raises(PasswordTooLongError):
        await hasher.hash("é" * 40)


async def test_a_72_byte_password_is_accepted() -> None:
    assert await hasher.verify("a" * 72, await hasher.hash("a" * 72)) is True


async def test_the_too_long_error_does_not_quote_the_password() -> None:
    secret = "z" * 100

    with pytest.raises(PasswordTooLongError) as excinfo:
        await hasher.hash(secret)

    assert secret not in str(excinfo.value)


async def test_verifying_an_over_long_password_is_false_not_an_error() -> None:
    # At login an over-long password must be indistinguishable from a wrong one
    # (R1.4), so verification returns False instead of raising a different error.
    assert await hasher.verify("a" * 200, await hasher.hash("correct horse")) is False


async def test_verifying_against_a_malformed_hash_is_false() -> None:
    assert await hasher.verify("anything", "not-a-bcrypt-hash") is False


async def test_burn_costs_one_verification_and_never_more(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cold-cache trap: `burn` must not also pay for building the dummy hash.

    Before `prewarm`, the first burn of each process did `gensalt` + `hashpw` + a
    verification — about double a real wrong-password login, which is a one-bit
    "this address does not exist" signal per process lifetime (R1.4).
    """
    from app.auth.infrastructure import password_hasher as module

    # Warm first, then start counting: that is the state every request sees, because
    # the configured cost is prewarmed at import.
    module.prewarm(TEST_ROUNDS)
    calls: list[str] = []
    monkeypatch.setattr(
        module.bcrypt, "hashpw", _counting(module.bcrypt.hashpw, calls, "hashpw")
    )
    monkeypatch.setattr(
        module.bcrypt, "checkpw", _counting(module.bcrypt.checkpw, calls, "checkpw")
    )

    await hasher.burn("whatever the caller sent")

    assert calls == ["checkpw"], f"burn did {calls}, expected exactly one verification"


async def test_burning_an_over_long_password_spends_nothing_like_verify_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shortcut has to be symmetric with `verify`'s, or it becomes an oracle.

    `verify` returns False for an over-long password without touching bcrypt, so if
    `burn` still spent a full verification the unknown-address path would be SLOWER
    than the known-address one for that input — the enumeration leak of R1.4 with the
    sign flipped, which is just as readable to an attacker.
    """
    from app.auth.infrastructure import password_hasher as module

    module.prewarm(TEST_ROUNDS)
    calls: list[str] = []
    monkeypatch.setattr(
        module.bcrypt, "hashpw", _counting(module.bcrypt.hashpw, calls, "hashpw")
    )
    monkeypatch.setattr(
        module.bcrypt, "checkpw", _counting(module.bcrypt.checkpw, calls, "checkpw")
    )

    await hasher.burn("a" * 200)
    assert calls == []

    assert await hasher.verify("a" * 200, await hasher.hash("short")) is False
    # Only the `hash` above reached bcrypt; the verify took the same shortcut.
    assert calls == ["hashpw"]


async def test_a_cold_cost_pays_for_its_dummy_hash_once_and_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the boundary of the guarantee.

    A cost that was never prewarmed does pay for its dummy hash on first use. That
    never happens for the configured cost in production (prewarmed at import), and it
    happens at most once per cost anyway — but it is worth pinning so nobody assumes
    `burn` is free for an arbitrary cost.
    """
    from app.auth.infrastructure.password_hasher import _DUMMY_HASHES
    from app.auth.infrastructure import password_hasher as module

    cold_rounds = 5
    monkeypatch.delitem(_DUMMY_HASHES, cold_rounds, raising=False)
    cold = BcryptPasswordHasher(rounds=cold_rounds)
    calls: list[str] = []
    monkeypatch.setattr(
        module.bcrypt, "hashpw", _counting(module.bcrypt.hashpw, calls, "hashpw")
    )
    monkeypatch.setattr(
        module.bcrypt, "checkpw", _counting(module.bcrypt.checkpw, calls, "checkpw")
    )

    await cold.burn("first")
    await cold.burn("second")

    assert calls == ["hashpw", "checkpw", "checkpw"]


async def test_the_dummy_hash_is_built_at_import_for_the_configured_cost() -> None:
    from app.auth.infrastructure import password_hasher as module
    from app.core.config import settings

    assert settings.bcrypt_rounds in module._DUMMY_HASHES


async def test_hashes_are_created_with_the_configured_cost() -> None:
    """`burn` assumes the population is homogeneous — this is what makes it true.

    `hash()` is the only writer of stored hashes and always uses the configured cost,
    so the dummy hash and a real verification cost the same. Changing BCRYPT_ROUNDS on
    a populated database breaks that assumption until the hashes are rebuilt.
    """
    from app.core.config import settings

    real = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)

    assert (await real.hash("x")).startswith(f"$2b${settings.bcrypt_rounds:02d}$")


# --- D21: off the event loop, and bounded -----------------------------------------


@pytest.mark.parametrize("operation", ["hash", "verify", "burn"])
async def test_no_bcrypt_call_runs_on_the_event_loop_thread(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """The property is asserted by thread identity, not by timing.

    A latency assertion would need the real cost of 12 to be measurable and would be
    flaky under load; the thread id is exact. If any of the three ever runs inline
    again, the whole process stalls ~250 ms per call (measured) and one burst of
    failed logins takes the API down — which is why all three are covered, not just
    the one login happens to use most.
    """
    from app.auth.infrastructure import password_hasher as module

    loop_thread = threading.get_ident()
    seen: list[int] = []

    def record(original):
        def wrapper(*args, **kwargs):
            seen.append(threading.get_ident())
            return original(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(module.bcrypt, "hashpw", record(module.bcrypt.hashpw))
    monkeypatch.setattr(module.bcrypt, "checkpw", record(module.bcrypt.checkpw))
    module.prewarm(TEST_ROUNDS)

    if operation == "hash":
        await hasher.hash("some password")
    elif operation == "verify":
        await hasher.verify("some password", await hasher.hash("some password"))
    else:
        await hasher.burn("some password")

    assert seen, "the operation never reached bcrypt — the test would pass vacuously"
    assert loop_thread not in seen, f"bcrypt ran on the event loop thread ({operation})"


async def test_concurrent_hashing_is_capped_at_the_configured_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound is the point of the thread pool, not a detail of it.

    Unbounded (anyio's default is 40 threads) a burst of failed logins puts 40 bcrypt
    computations on a 4-OCPU VM, and every one of them — plus every unrelated request
    — gets ~10x slower. That is the amplification D21 exists to bound, so the cap is
    asserted directly: with room for 2, exactly 2 calls may be in flight while 8 wait.
    """
    from app.auth.infrastructure import password_hasher as module

    monkeypatch.setattr(module.settings, "bcrypt_max_concurrency", 2)
    # The limiter is cached per event loop, and this test's loop may already have one
    # from an earlier test in this module.
    module._LIMITERS.clear()

    in_flight = threading.Semaphore(0)
    release = threading.Event()
    entered = 0
    lock = threading.Lock()

    def blocking_checkpw(*_args, **_kwargs):
        nonlocal entered
        with lock:
            entered += 1
        in_flight.release()
        # Held until the test says so, so "how many got in" is observable rather
        # than a race between fast calls.
        assert release.wait(timeout=10), "test never released the fake bcrypt calls"
        return False

    monkeypatch.setattr(module.bcrypt, "checkpw", blocking_checkpw)
    module.prewarm(TEST_ROUNDS)

    tasks = [asyncio.create_task(hasher.burn("x")) for _ in range(8)]
    try:
        # Wait for the bound to be reached, then give the loop room to let a third
        # through if the limiter were not doing its job.
        for _ in range(2):
            assert await asyncio.to_thread(in_flight.acquire, True, 5), "no call started"
        await asyncio.sleep(0.2)

        with lock:
            assert entered == 2, f"{entered} bcrypt calls in flight, the bound was 2"
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)


async def test_the_default_bound_follows_the_cpu_count(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.auth.infrastructure import password_hasher as module

    monkeypatch.setattr(module.settings, "bcrypt_max_concurrency", None)
    monkeypatch.setattr(module.os, "cpu_count", lambda: 4)
    assert module.max_concurrency() == 4

    # A machine that reports nothing must still allow one, not zero.
    monkeypatch.setattr(module.os, "cpu_count", lambda: None)
    assert module.max_concurrency() == 1

    monkeypatch.setattr(module.settings, "bcrypt_max_concurrency", 7)
    assert module.max_concurrency() == 7
