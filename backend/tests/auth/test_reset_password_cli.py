"""The rescue command of R6.5 / design D12.

Against the real database, because what this command buys over hand-written SQL is exactly
the four side effects a manual `UPDATE` does not have: the entity's invariant, the revoked
sessions, the lifted lock and the audit row. A test with fakes would exercise the code path
and none of the value.

`apply_reset` takes the session, so these run on the test database — the same split
`app.cli.bootstrap` uses for the same reason.
"""

import logging
import uuid

import pytest
from sqlalchemy import select

from app.audit.domain import actions
from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.password_policy import assert_password_acceptable
from app.auth.infrastructure.models import UserModel, UserSessionModel
from app.cli.reset_password import AccountNotFoundError, apply_reset, main, reset_password
from tests.auth.conftest import PASSWORD, insert_user


@pytest.mark.asyncio
async def test_the_printed_password_is_the_one_that_works(
    db_session, tenant_a, hasher
) -> None:
    """The whole point of the command: the operator can hand over something usable."""
    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)

    user_id, temporary = await apply_reset(db_session, hasher, user.email)

    assert user_id == user.id
    row = (
        await db_session.execute(select(UserModel).where(UserModel.id == user.id))
    ).scalar_one()
    assert await hasher.verify(temporary, row.password_hash)
    # And the old one stops working, which is what makes it a rescue rather than an addition.
    assert not await hasher.verify(PASSWORD, row.password_hash)


@pytest.mark.asyncio
async def test_the_password_it_issues_satisfies_the_policy(
    db_session, tenant_a, hasher
) -> None:
    """R1.6's coupling reaching the rescue path too: the account must be able to CHANGE this
    password afterwards, and it cannot if the policy would reject what we handed out."""
    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)

    _user_id, temporary = await apply_reset(db_session, hasher, user.email)

    assert_password_acceptable(temporary)


@pytest.mark.asyncio
async def test_the_account_must_change_it(db_session, tenant_a, hasher) -> None:
    """R5.2 / design D5 — a password that travelled through a terminal must not become
    permanent."""
    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)

    await apply_reset(db_session, hasher, user.email)

    row = (
        await db_session.execute(select(UserModel).where(UserModel.id == user.id))
    ).scalar_one()
    assert row.must_change_password is True


@pytest.mark.asyncio
async def test_the_previous_sessions_are_revoked(db_session, tenant_a, hasher) -> None:
    """One of the four things a hand-written UPDATE does not do."""
    from datetime import timedelta

    from app.auth.domain.entities import UserSession
    from app.auth.infrastructure.repositories import SqlAlchemySessionRepository
    from tests.auth.conftest import utc_now

    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)
    family = uuid.uuid4()
    await SqlAlchemySessionRepository(db_session).add(
        tenant_a.id,
        UserSession(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            user_id=user.id,
            family_id=family,
            expires_at=utc_now() + timedelta(days=7),
        ),
    )
    await db_session.flush()

    await apply_reset(db_session, hasher, user.email)

    rows = (
        await db_session.execute(
            select(UserSessionModel).where(UserSessionModel.user_id == user.id)
        )
    ).scalars().all()
    assert rows
    assert all(row.revoked_at is not None for row in rows)


@pytest.mark.asyncio
async def test_it_writes_an_audit_row_with_no_actor(db_session, tenant_a, hasher) -> None:
    """Design D12: a command line has no identity to record, like the rows of
    `pms-provider-resolution`. But the operation itself must still leave a trail — that is
    the difference from SQL by hand."""
    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)

    await apply_reset(db_session, hasher, user.email)

    row = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.entity_id == user.id)
        )
    ).scalar_one()
    assert row.action == actions.USER_PASSWORD_RESET
    assert row.actor_user_id is None
    assert row.actor_ip is None
    assert row.tenant_id == tenant_a.id


@pytest.mark.asyncio
async def test_the_audit_row_carries_neither_the_password_nor_its_hash(
    db_session, tenant_a, hasher
) -> None:
    """R4.3 reaches this path too."""
    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)

    _user_id, temporary = await apply_reset(db_session, hasher, user.email)

    row = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.entity_id == user.id)
        )
    ).scalar_one()
    recorded = str(row.changes)
    assert temporary not in recorded
    assert row.changes["password"] == {"changed": True}
    assert row.changes["must_change_password"] == {"old": False, "new": True}


@pytest.mark.asyncio
async def test_rescuing_an_account_that_already_owed_a_change_records_no_false_diff(
    db_session, tenant_a, hasher
) -> None:
    """The flag did not move, so the trail must not claim it did."""
    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)
    user.must_change_password = True
    await db_session.flush()

    await apply_reset(db_session, hasher, user.email)

    row = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.entity_id == user.id)
        )
    ).scalar_one()
    assert "must_change_password" not in row.changes


@pytest.mark.asyncio
async def test_an_unknown_address_changes_nothing(db_session, tenant_a, hasher) -> None:
    """R6.5's "un email inexistente falla con un mensaje claro sin tocar nada"."""
    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)
    before = user.password_hash

    with pytest.raises(AccountNotFoundError, match="nobody@example.test"):
        await apply_reset(db_session, hasher, "nobody@example.test")

    row = (
        await db_session.execute(select(UserModel).where(UserModel.id == user.id))
    ).scalar_one()
    assert row.password_hash == before
    assert (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.entity_id == user.id)
        )
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_it_finds_an_account_in_any_tenant(db_session, tenant_a, tenant_b, hasher) -> None:
    """An operator running a rescue knows the address, not the tenant — so the lookup is the
    same unscoped one login uses, and everything after it is scoped by the row's tenant."""
    user_b = await insert_user(db_session, tenant=tenant_b, hasher=hasher)

    user_id, _temporary = await apply_reset(db_session, hasher, user_b.email)

    assert user_id == user_b.id
    row = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.entity_id == user_b.id)
        )
    ).scalar_one()
    assert row.tenant_id == tenant_b.id, "the audit row landed in the wrong tenant"


@pytest.mark.asyncio
async def test_the_address_is_matched_case_insensitively(
    db_session, tenant_a, hasher
) -> None:
    """An operator typing an address from a support ticket should not have to match case."""
    user = await insert_user(db_session, tenant=tenant_a, email="Ana@Example.com", hasher=hasher)

    user_id, _temporary = await apply_reset(db_session, hasher, "  ANA@example.COM ")

    assert user_id == user.id


@pytest.mark.asyncio
async def test_two_rescues_produce_two_different_passwords(
    db_session, tenant_a, hasher
) -> None:
    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)

    _first_id, first = await apply_reset(db_session, hasher, user.email)
    _second_id, second = await apply_reset(db_session, hasher, user.email)

    assert first != second


# NO test asserts the absence of a Makefile target, and that is a limit of the environment
# rather than an oversight. Design D12 (open question 4) decided against one — a rescue
# operation should not look like part of the normal development flow — but the root `Makefile`
# is **unreachable from inside the container**, which mounts only `backend/` at `/app`. That is
# the same constraint `app/main.py` records for the root `VERSION` file. A first version of
# this guard asserted `pathlib.Path("/Makefile").exists()` and failed for exactly that reason.
# Verified by hand from the host instead: `grep -c reset_password Makefile` → 0.


@pytest.mark.asyncio
async def test_the_temporary_password_reaches_no_application_log(
    db_session, tenant_a, hasher, caplog
) -> None:
    """R4.3 on this path too: the password in "el log de la aplicación" in no form.

    Until the review panel asked, the issued password was only proven absent from
    `audit_logs.changes`, so a `logger.info("issued %s", temporary)` added to `apply_reset`
    later would have shipped green — and whoever can read backend logs would be reading a live
    credential. The absence is asserted against the value that was actually issued, and the
    capture is proved to work first: `caplog` with zero records makes any absence trivially
    true, which is the shape of vacuous guard this change has already hit three times.
    """
    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)

    with caplog.at_level("DEBUG"):
        logging.getLogger("app.auth").debug("the instrument works")
        _user_id, temporary = await apply_reset(db_session, hasher, user.email)

    assert any("the instrument works" in r.getMessage() for r in caplog.records), (
        "caplog captured nothing from app.auth, so the absence below proves nothing"
    )
    logged = "\n".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    assert temporary not in logged
    # And no fragment either: half a password is still a lead.
    for start in range(len(temporary) - 7):
        assert temporary[start : start + 8] not in logged


@pytest.mark.asyncio
async def test_the_function_the_command_calls_opens_a_working_session(
    test_engine, db_session, tenant_a, hasher, monkeypatch
) -> None:
    """The layer every other test in this file skipped — and where the bug was.

    The twelve tests above call `apply_reset` with a session handed to them, which is what
    makes them runnable against the test database. `reset_password()` is the half that opens
    its own, and it read `async_session_factory()()`: one call too many, landing on the
    `AsyncSession` the first returned. Every real invocation died with `TypeError:
    'AsyncSession' object is not callable` while the suite stayed green, because nothing
    reached this function. The review panel found it by running the command.

    `async_session_factory` is rebound to the test engine — patched **in the CLI module**,
    where the name was imported, not in `app.core.db`. A reintroduced double call fails here
    for the same reason it failed in production.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.cli.reset_password as module

    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)
    # Committed, because `reset_password` reads through a session of its own.
    await db_session.commit()

    monkeypatch.setattr(
        module,
        "async_session_factory",
        async_sessionmaker(test_engine, expire_on_commit=False),
    )
    from sqlalchemy.ext.asyncio import AsyncSession

    before = user.password_hash
    cleared: list[uuid.UUID] = []
    committed_when_called: list[bool] = []

    async def capture_clear_lock(user_id: uuid.UUID) -> bool:
        cleared.append(user_id)
        # Witnesses D8's ORDER, which `cleared == [user.id]` alone does not: a session that
        # never saw this transaction reads the row as it stands right now, so a new hash here
        # means the commit already happened. The first version of this test asserted the
        # ordering in a comment and checked only the user id — the security panel called that
        # an unearned claim, and it was.
        async with AsyncSession(test_engine, expire_on_commit=False) as spy:
            row = (
                await spy.execute(select(UserModel).where(UserModel.id == user_id))
            ).scalar_one()
            committed_when_called.append(row.password_hash != before)
        return True

    monkeypatch.setattr(module, "clear_lock", capture_clear_lock)

    user_id, temporary, lock_cleared = await reset_password(user.email)

    assert user_id == user.id
    assert lock_cleared is True
    assert cleared == [user.id]
    assert committed_when_called == [True], (
        "D8: `clear_lock` ran before the write was committed"
    )

    async with AsyncSession(test_engine, expire_on_commit=False) as fresh:
        row = (
            await fresh.execute(select(UserModel).where(UserModel.id == user.id))
        ).scalar_one()
    assert await hasher.verify(temporary, row.password_hash), (
        "the committed row does not carry the password the function returned"
    )
    assert row.must_change_password is True


@pytest.mark.asyncio
async def test_it_really_lifts_the_lock_in_redis(
    test_engine, db_session, tenant_a, hasher, monkeypatch
) -> None:
    """D8's other half at this call site, with nothing mocked away.

    The test above patches `clear_lock` out to observe the ordering, so it proves that
    `reset_password` calls *whatever* `clear_lock` is — not that `clear_lock`'s own
    composition line works. That is precisely the shape of the bug this file just fixed one
    line above it (`async_session_factory()()` was also a composition line no test reached),
    and the review panel asked for it by name. So: a real lock in the real Redis of the compose
    stack, `reset_password()` un-mocked, and the lock asserted gone.

    Against real Redis for the same reason `test_throttle.py` gives: it is the store the
    requirement is about, and a fake would not prove this glue holds.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.cli.reset_password as module
    from app.auth.infrastructure.throttle import RedisLoginThrottle
    from app.core.redis import get_redis

    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)
    await db_session.commit()

    throttle = RedisLoginThrottle(
        get_redis(), attempts_per_minute=10, max_failures=2, lockout_minutes=15
    )
    await throttle.record_failure(user.id)
    await throttle.record_failure(user.id)
    assert await throttle.is_account_locked(user.id) is True, (
        "the account never locked, so the assertion below would be trivially true"
    )

    monkeypatch.setattr(
        module,
        "async_session_factory",
        async_sessionmaker(test_engine, expire_on_commit=False),
    )

    _user_id, _temporary, lock_cleared = await reset_password(user.email)

    assert lock_cleared is True
    assert await throttle.is_account_locked(user.id) is False, (
        "R3.5(c) on the rescue path: the lock survived the reset"
    )


def test_main_prints_the_password_once_and_reports_success(monkeypatch, capsys) -> None:
    """D12: "la imprime **una sola vez** por salida estándar" — there is no other channel."""
    import app.cli.reset_password as module

    async def issue(email: str) -> tuple[uuid.UUID, str, bool]:
        assert email == "ana@example.test"
        return uuid.UUID(int=7), "printed-once-passphrase", True

    monkeypatch.setattr(module, "reset_password", issue)

    exit_code = main(["--email", "ana@example.test"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.count("printed-once-passphrase") == 1
    assert "printed-once-passphrase" not in captured.err
    assert captured.err == ""


def test_main_says_the_password_changed_when_redis_is_unreachable(
    monkeypatch, capsys
) -> None:
    """Design D8's benign degradation, as the operator sees it.

    Reporting a failure after the credential already changed is the outcome that gets a
    rescue abandoned half-done, so the warning has to say the reset stood.
    """
    import app.cli.reset_password as module

    async def issue(email: str) -> tuple[uuid.UUID, str, bool]:
        return uuid.UUID(int=7), "printed-once-passphrase", False

    monkeypatch.setattr(module, "reset_password", issue)

    exit_code = main(["--email", "ana@example.test"])

    captured = capsys.readouterr()
    assert exit_code == 0, "a lock that could not be cleared is not a failed rescue"
    assert "WAS reset" in captured.err
    assert captured.out.count("printed-once-passphrase") == 1


def test_main_reports_an_unknown_address_without_printing_anything(
    monkeypatch, capsys
) -> None:
    """R6.5's "un email inexistente falla con un mensaje claro sin tocar nada", at the shell."""
    import app.cli.reset_password as module

    async def refuse(email: str) -> tuple[uuid.UUID, str, bool]:
        raise AccountNotFoundError(f"No account exists for {email}")

    monkeypatch.setattr(module, "reset_password", refuse)

    exit_code = main(["--email", "nobody@example.test"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "nobody@example.test" in captured.err
    assert captured.out == ""


def test_the_console_email_adapter_was_not_touched() -> None:
    """Task 9.3 / design D12: the rescue exists BECAUSE the adapter may not log the link.

    D12 explicitly rejected a `--print-link` flag or a `DEV_LOG_RECOVERY_LINK` variable — "un
    interruptor que imprime credenciales es un interruptor que acabará puesto en un entorno
    que no es dev". This is the grep that keeps that true.
    """
    import pathlib

    backend = pathlib.Path(__file__).resolve().parents[2]
    adapter = (backend / "app/notifications/infrastructure/adapters.py").read_text(
        encoding="utf-8"
    )

    # The adapter still logs only lengths, never content or recipient.
    assert "subject_length" in adapter
    assert "body_length" in adapter
    for leak in ("print_link", "PRINT_LINK", "DEV_LOG_RECOVERY", "recovery_link"):
        assert leak not in adapter, f"the adapter gained {leak!r}"

    # And no setting anywhere would turn link logging on.
    config = (backend / "app/core/config.py").read_text(encoding="utf-8")
    for leak in ("print_link", "log_recovery", "recovery_link"):
        assert leak not in config, f"config gained {leak!r}"
