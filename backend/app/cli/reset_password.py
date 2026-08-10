"""Rescue path for an account nobody else can recover (R6.5, design D12).

    python -m app.cli.reset_password --email <address>

**Why this exists at all.** The recovery mail reaches nobody until a real SMTP adapter
arrives with `hardening-release`: `EMAIL` resolves to `ConsoleEmailAdapter`, which
`specs/access-notifications.md` forbids from logging content or recipient, so not even a
developer can read the link out of the log (R6.4, EXTERNAL_DEPENDENCY). And the only
`TENANT_OWNER` of a tenant has no other way back — only `TENANT_OWNER` holds `MANAGE_USERS`,
so nobody else can reset them, and they would have to authenticate to reset themselves.
Until this command, the answer was hand-written SQL against the database.

**Why it is not new attack surface.** Whoever can run it already has a shell on the host and
therefore full access to the database. What it adds over an `UPDATE` by hand is that the
operation goes through the entity, revokes the sessions, lifts the account lock and leaves an
audit row — four things a manual statement does not do.

Deliberately NOT a Makefile target (design D12, open question 4): this is a rescue operation,
and a `make` verb would make it look like part of normal development.

The temporary password is printed ONCE to stdout, and printing it is the whole point — there
is no other channel. It is never logged: `logger` calls here carry the user id, never the
secret.
"""

import argparse
import asyncio
import logging
import sys
import uuid

import app.core.models_registry  # noqa: F401
from app.audit.domain import actions
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.domain.enums import SessionRevokedReason
from app.auth.domain.passwords import generate_temporary_password
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.repositories import (
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
from app.auth.infrastructure.throttle import RedisLoginThrottle
from app.core.config import settings
from app.core.db import async_session_factory
from app.core.redis import get_redis

logger = logging.getLogger("app.auth")


class AccountNotFoundError(Exception):
    """No account carries that address anywhere in the installation."""


async def apply_reset(session, hasher, email: str) -> tuple[uuid.UUID, str]:
    """The database half: issue the temporary password and record everything.

    Takes the session and the hasher rather than building them, the same split
    `app.cli.bootstrap` uses (`build_plan`/`apply_plan`) and for the same reason — it is what
    lets this be tested against the test database instead of the developer's dev stack.

    Resolved with `find_by_email_globally`, the same unscoped lookup login uses, because an
    operator running a rescue knows the address and not the tenant. Everything after that is
    scoped by the `tenant_id` the row carries, exactly as the API paths are.
    """
    users = SqlAlchemyUserRepository(session)
    user = await users.find_by_email_globally(email)
    if user is None:
        raise AccountNotFoundError(f"No account exists for {email}")

    was_temporary = user.must_change_password
    temporary = generate_temporary_password()
    # `temporary=True` (design D5): what this hands out has to be changed before the account
    # can operate, exactly like an administrator's reset. Without it the rescue would leave a
    # permanent password that travelled through a terminal and somebody's chat history.
    user.set_password_hash(await hasher.hash(temporary), temporary=True)

    await users.apply_changes(
        user.tenant_id,
        user.id,
        {
            "password_hash": user.password_hash,
            "must_change_password": user.must_change_password,
        },
    )

    changes = ChangeSet(actions.ENTITY_USER).redacted("password")
    if not was_temporary:
        changes = changes.diff("must_change_password", False, True)
    await SqlAlchemyAuditLogRepository(session).add(
        user.tenant_id,
        AuditLogFactory.build(
            tenant_id=user.tenant_id,
            # Reuses the existing action rather than inventing a fourth: this IS an assisted
            # reset, just through another door (design D12).
            action=actions.USER_PASSWORD_RESET,
            entity_type=actions.ENTITY_USER,
            entity_id=user.id,
            # No actor, like the rows of `pms-provider-resolution`: a command line has no
            # identity to record, and `actor_ip` has no request to come from.
            actor_user_id=None,
            actor_ip=None,
            changes=changes,
            now=_now(),
        ),
    )
    # A rescue that left the old sessions alive would not have recovered the account, it
    # would have added a credential to it.
    await SqlAlchemySessionRepository(session).revoke_all_for_user(
        user.tenant_id, user.id, SessionRevokedReason.PASSWORD_RESET, _now()
    )
    await session.commit()
    return user.id, temporary


async def clear_lock(user_id: uuid.UUID) -> bool:
    """Lift the login lockout; report whether it worked. Never raises.

    Called AFTER the commit and outside it, for the same reason as design D8 on the R3 path:
    Redis and Postgres share no transaction, so one has to be able to fail alone. A lock that
    expires by itself in fifteen minutes over an already-rescued account is the benign
    degradation; a rescue that reports failure after changing the password is not.
    """
    try:
        throttle = RedisLoginThrottle(
            get_redis(),
            attempts_per_minute=settings.login_rate_limit_per_minute,
            max_failures=settings.login_max_failed_attempts,
            lockout_minutes=settings.login_lockout_minutes,
        )
        await throttle.clear_account_lock(user_id)
        return True
    except Exception:
        logger.warning("auth.rescue_lock_not_cleared", extra={"user_id": str(user_id)})
        return False


async def reset_password(email: str) -> tuple[uuid.UUID, str, bool]:
    """Open a session and run the rescue. Returns `(user_id, password, lock_cleared)`."""
    hasher = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)
    # `async_session_factory` IS the sessionmaker, so it is called ONCE — the same line as
    # `app/cli/bootstrap.py:172`. This read `async_session_factory()()` until the review panel
    # ran the command for real: the extra call lands on the `AsyncSession` the first one
    # returns, and `TypeError: 'AsyncSession' object is not callable` killed the rescue before
    # it touched anything. The whole suite was green, because every test called `apply_reset`
    # directly and nothing exercised this function.
    async with async_session_factory() as session:
        user_id, temporary = await apply_reset(session, hasher, email)
    return user_id, temporary, await clear_lock(user_id)


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.reset_password",
        description=(
            "Issue a temporary password for an account that cannot recover itself. "
            "Prints the password once; the holder must change it on first use."
        ),
    )
    parser.add_argument("--email", required=True, help="the account's email address")
    args = parser.parse_args(argv)

    try:
        user_id, temporary, lock_cleared = asyncio.run(reset_password(args.email))
    except AccountNotFoundError as exc:
        print(f"reset_password: {exc}", file=sys.stderr)
        return 1

    if not lock_cleared:
        print(
            "reset_password: the account lock could not be cleared (Redis unreachable). "
            "The password WAS reset; the lock expires on its own within the lockout window.",
            file=sys.stderr,
        )
    print(f"reset_password: temporary password for {args.email} (user {user_id}):")
    print(temporary)
    print(
        "reset_password: hand it over through a channel you trust. The account must change "
        "it before it can do anything else.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
