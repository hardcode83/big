"""bcrypt adapter for the PasswordHasher port (R1.3, design D4).

The library is used directly rather than through passlib: passlib's last release
is 1.7.4, unmaintained, and it breaks against bcrypt 4.x+.

ASSUMPTION: bcrypt only reads the first 72 bytes of a password. Historically it
truncated silently, which would make "…(72 bytes)…X" and "…(72 bytes)…Y" the same
password. This adapter refuses anything longer instead of accepting a truncated
derivative as valid (design D4). bcrypt 5.x also raises on its own now, so the
guard is belt and braces rather than the only line of defence.
"""

import secrets

import bcrypt

from app.auth.domain.exceptions import PasswordTooLongError
from app.core.config import settings

BCRYPT_MAX_PASSWORD_BYTES = 72

# One dummy hash per cost, for `burn`. Not a secret: its only job is to make a
# verification against nothing cost the same as a verification against a real user.
_DUMMY_HASHES: dict[int, str] = {}


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

    def hash(self, password: str) -> str:
        encoded = password.encode("utf-8")
        if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
            # Never interpolate the password into the message: it would surface in
            # a 422 body and in logs.
            raise PasswordTooLongError(
                f"Password must not exceed {BCRYPT_MAX_PASSWORD_BYTES} bytes when UTF-8 encoded"
            )
        return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=self._rounds)).decode("utf-8")

    def verify(self, password: str, password_hash: str) -> bool:
        encoded = password.encode("utf-8")
        if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
            # No stored hash can ever match: `hash` refuses to create one. Returning
            # False keeps this indistinguishable from a wrong password (R1.4).
            return False
        try:
            return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
        except ValueError:
            # Malformed or truncated stored hash — not a match, and not a crash.
            return False

    def burn(self, password: str) -> None:
        """Spend exactly one verification's worth of work, and discard it (R1.4).

        LIMITATION worth knowing: the dummy hash carries the CONFIGURED cost, while a
        real `verify` costs whatever cost is embedded in that user's stored hash.
        Those agree as long as every hash in the database was created with the current
        `BCRYPT_ROUNDS` — which holds today, since `hash()` is the only writer and it
        always uses the configured value. Changing `BCRYPT_ROUNDS` on a populated
        database therefore reopens the latency oracle for every pre-existing user, and
        needs a rehash-on-login pass before it is safe. Documented in
        `docs/auth-tenancy.md`.
        """
        self.verify(password, self._dummy_hash())

    def _dummy_hash(self) -> str:
        # Present for the configured cost thanks to `prewarm` below; the fallback only
        # fires for a non-default cost, which is the tests.
        prewarm(self._rounds)
        return _DUMMY_HASHES[self._rounds]


# Pay for the default cost once, at import, so no request ever does.
prewarm(settings.bcrypt_rounds)
