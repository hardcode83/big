"""bcrypt adapter for the PasswordHasher port (R1.3, design D4/D21).

The library is used directly rather than through passlib: passlib's last release
is 1.7.4, unmaintained, and it breaks against bcrypt 4.x+.

Every bcrypt call runs in a worker thread with a shared concurrency bound
(design D21). Measured in this container with bcrypt 5.0.0 at cost 12: one
`checkpw` on the event loop stalls it for 250 ms, and eight of them serialise into
1.87 s during which nothing else is served; the same eight in threads finish in
271 ms with the loop never stalled beyond its own 7 ms tick. bcrypt releases the
GIL, so the threads give real parallelism rather than just moving the wait.

ASSUMPTION: bcrypt only reads the first 72 bytes of a password. Historically it
truncated silently, which would make "…(72 bytes)…X" and "…(72 bytes)…Y" the same
password. This adapter refuses anything longer instead of accepting a truncated
derivative as valid (design D4). bcrypt 5.x also raises on its own now, so the
guard is belt and braces rather than the only line of defence.
"""

import asyncio
import os
import secrets
import weakref

import anyio
import anyio.to_thread
import bcrypt

from app.auth.domain.exceptions import PasswordTooLongError
from app.core.config import settings

BCRYPT_MAX_PASSWORD_BYTES = 72

# One dummy hash per cost, for `burn`. Not a secret: its only job is to make a
# verification against nothing cost the same as a verification against a real user.
_DUMMY_HASHES: dict[int, str] = {}

# The concurrency bound lives at module level, NOT on the instance:
# `get_password_hasher()` builds a fresh BcryptPasswordHasher for every request
# (see api/dependencies.py), so a per-instance limiter would bound one request
# against itself and nothing else — no bound at all.
#
# Keyed by running event loop because anyio primitives bind to the loop that
# created them, and the suite runs one loop per test. Sharing a single limiter
# across loops raises "attached to a different loop" — the same trap the asyncpg
# engine hit in tests/conftest.py. WeakKeyDictionary so finished loops don't pile up.
_LIMITERS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, anyio.CapacityLimiter]" = (
    weakref.WeakKeyDictionary()
)


def max_concurrency() -> int:
    """How many bcrypt calls may run at once (design D21).

    Defaults to the visible CPU count: bcrypt is CPU-bound, so more threads than
    cores makes every password check slower without serving one more request, and
    anyio's own default of 40 would let a burst of failed logins take the whole
    process down to a crawl — the amplification this whole change exists to close.
    """
    configured = settings.bcrypt_max_concurrency
    if configured is not None:
        return max(1, configured)
    return os.cpu_count() or 1


def _limiter() -> anyio.CapacityLimiter:
    loop = asyncio.get_running_loop()
    limiter = _LIMITERS.get(loop)
    if limiter is None:
        limiter = anyio.CapacityLimiter(max_concurrency())
        _LIMITERS[loop] = limiter
    return limiter


def _build_dummy_hash(rounds: int) -> str:
    return bcrypt.hashpw(
        secrets.token_urlsafe(16).encode("utf-8"), bcrypt.gensalt(rounds=rounds)
    ).decode("utf-8")


def prewarm(rounds: int) -> None:
    """Build the dummy hash before any request can need it.

    Without this the FIRST unknown-address or locked-account login of each worker
    process pays `gensalt` + `hashpw` on top of the verification — roughly double the
    latency of a real wrong-password login. That is a one-bit "this address does not
    exist" leak per process lifetime, which is the very class of defect `burn` exists
    to close (R1.4). Called at import time below, so the cost lands on process start.
    """
    if rounds not in _DUMMY_HASHES:
        _DUMMY_HASHES[rounds] = _build_dummy_hash(rounds)


class BcryptPasswordHasher:
    def __init__(self, rounds: int) -> None:
        self._rounds = rounds

    async def hash(self, password: str) -> str:
        encoded = password.encode("utf-8")
        if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
            # Never interpolate the password into the message: it would surface in
            # a 422 body and in logs.
            raise PasswordTooLongError(
                f"Password must not exceed {BCRYPT_MAX_PASSWORD_BYTES} bytes when UTF-8 encoded"
            )
        return await self._offload(self._hash_sync, encoded)

    async def verify(self, password: str, password_hash: str) -> bool:
        encoded = password.encode("utf-8")
        if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
            # No stored hash can ever match: `hash` refuses to create one. Returning
            # False keeps this indistinguishable from a wrong password (R1.4).
            return False
        return await self._offload(self._verify_sync, encoded, password_hash)

    async def burn(self, password: str) -> None:
        """Spend exactly one verification's worth of work, and discard it (R1.4).

        The over-length shortcut mirrors `verify`'s on purpose: both paths return
        without spending anything, so an over-long password is equally cheap whether
        or not the address exists. Skipping it here alone would reopen the very
        latency oracle this method closes.

        LIMITATION worth knowing: the dummy hash carries the CONFIGURED cost, while a
        real `verify` costs whatever cost is embedded in that user's stored hash.
        Those agree as long as every hash in the database was created with the current
        `BCRYPT_ROUNDS` — which holds today, since `hash()` is the only writer and it
        always uses the configured value. Changing `BCRYPT_ROUNDS` on a populated
        database therefore reopens the latency oracle for every pre-existing user, and
        needs a rehash-on-login pass before it is safe. Documented in
        `docs/auth-tenancy.md`.
        """
        encoded = password.encode("utf-8")
        if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
            return
        await self._offload(self._burn_sync, encoded)

    async def _offload(self, fn, *args):
        # `abandon_on_cancel` stays False (the default): if the client disconnects
        # mid-login we still wait for the thread, because releasing the limiter slot
        # while the CPU is still busy would let the bound be exceeded by exactly the
        # abandoned calls — and a disconnect is free for an attacker to trigger.
        return await anyio.to_thread.run_sync(fn, *args, limiter=_limiter())

    def _hash_sync(self, encoded: bytes) -> str:
        return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=self._rounds)).decode("utf-8")

    def _verify_sync(self, encoded: bytes, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
        except ValueError:
            # Malformed or truncated stored hash — not a match, and not a crash.
            return False

    def _burn_sync(self, encoded: bytes) -> None:
        # `prewarm` runs INSIDE the thread: for a non-default cost (the tests) it
        # hashes, and doing that on the event loop would reintroduce exactly the
        # stall this indirection removes.
        prewarm(self._rounds)
        self._verify_sync(encoded, _DUMMY_HASHES[self._rounds])


# Pay for the default cost once, at import, so no request ever does.
prewarm(settings.bcrypt_rounds)
