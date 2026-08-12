"""The demo seed of PRD §27 (`seed-data-demo` R1-R5).

In `tests/cli/` rather than beside a domain, and that is a deliberate departure from
`steering/testing.md`'s "tests junto al dominio que cubren" (design, "Ubicación de los tests"):
the seed belongs to no single domain, it crosses five. `test_bootstrap.py` lives in
`tests/auth/` because bootstrap really is an auth concern.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.repositories import UserFilters
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyCleaningChecklistTemplateRepository,
)
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.domain.repositories import TimelineFilters
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventReader

from app.cleaning.domain.value_objects import parse_template_content
from app.cleaning.infrastructure.models import CleaningChecklistTemplateModel
from app.guests.infrastructure.models import GuestModel
from app.properties.domain.enums import PropertyOperationalState
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel

from app.cli import seed_demo
from app.audit.domain import actions
from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.enums import UserRole
from app.auth.infrastructure.models import UserModel
from app.cli.seed_demo import (
    SeedConfigurationError,
    SeedConflictError,
    SeedPreconditionError,
    apply_plan,
    build_plan,
)
from app.core.config import settings
from tests.auth.conftest import insert_tenant, insert_user
from tests.cli.conftest import BOOTSTRAPPED_TENANT_NAME

COMPLETE_ENV = {
    "BOOTSTRAP_TENANT_NAME": BOOTSTRAPPED_TENANT_NAME,
    "SEED_CLEANER_NAME": "Cleaner Person",
    "SEED_CLEANER_EMAIL": "cleaner@example.com",
    "SEED_CLEANER_PASSWORD": "cleaner-password-for-tests",
    "SEED_TECHNICIAN_NAME": "Technician Person",
    "SEED_TECHNICIAN_EMAIL": "tech@example.com",
    "SEED_TECHNICIAN_PASSWORD": "technician-password-for-tests",
}


@pytest.fixture
def complete_env(monkeypatch: pytest.MonkeyPatch):
    for name, value in COMPLETE_ENV.items():
        monkeypatch.setattr(settings, name.lower(), value)
    return COMPLETE_ENV


# --- Configuration, checked before any transaction (R1.5, R3.3, D11) -------------------


@pytest.mark.parametrize("missing", sorted(COMPLETE_ENV))
def test_a_missing_variable_is_refused_before_anything_is_written(
    monkeypatch: pytest.MonkeyPatch, complete_env, missing: str
) -> None:
    # No database in this test on purpose: R1.5 is about the check happening BEFORE a
    # transaction exists, and `build_plan` is where that property lives.
    monkeypatch.setattr(settings, missing.lower(), "")

    with pytest.raises(SeedConfigurationError) as excinfo:
        build_plan()

    assert missing in str(excinfo.value)


def test_a_whitespace_only_variable_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch, complete_env
) -> None:
    monkeypatch.setattr(settings, "seed_cleaner_password", "   ")

    with pytest.raises(SeedConfigurationError) as excinfo:
        build_plan()

    assert "SEED_CLEANER_PASSWORD" in str(excinfo.value)


def test_every_missing_variable_is_reported_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in COMPLETE_ENV:
        monkeypatch.setattr(settings, name.lower(), "")

    with pytest.raises(SeedConfigurationError) as excinfo:
        build_plan()

    for name in COMPLETE_ENV:
        assert name in str(excinfo.value)


def test_the_error_never_echoes_a_password(
    monkeypatch: pytest.MonkeyPatch, complete_env
) -> None:
    monkeypatch.setattr(settings, "seed_cleaner_email", "")

    with pytest.raises(SeedConfigurationError) as excinfo:
        build_plan()

    assert COMPLETE_ENV["SEED_CLEANER_PASSWORD"] not in str(excinfo.value)
    assert COMPLETE_ENV["SEED_TECHNICIAN_PASSWORD"] not in str(excinfo.value)


def test_two_accounts_may_not_share_one_address(
    monkeypatch: pytest.MonkeyPatch, complete_env
) -> None:
    """R1.4, found by the section 2-3 security panel.

    Not a nicety about tidy configuration: keyed by address, the two conflict lookups of
    `apply_plan` collapse into one entry that answers `None` for both accounts, the loop
    inserts twice, and the second insert dies inside `uq_users_lower_email`. A SQLAlchemy
    `IntegrityError` stringifies its statement *with* its parameters — one of which is a
    bcrypt hash. Refusing in `build_plan` means the flush never happens.
    """
    monkeypatch.setattr(settings, "seed_technician_email", COMPLETE_ENV["SEED_CLEANER_EMAIL"])

    with pytest.raises(SeedConfigurationError) as excinfo:
        build_plan()

    message = str(excinfo.value)
    assert "SEED_CLEANER_EMAIL" in message and "SEED_TECHNICIAN_EMAIL" in message
    # The address belongs to a person; naming the two variables is what fixes it.
    assert COMPLETE_ENV["SEED_CLEANER_EMAIL"] not in message


def test_two_addresses_differing_only_in_case_are_the_same_address(
    monkeypatch: pytest.MonkeyPatch, complete_env
) -> None:
    # `uq_users_lower_email` is built on `lower(email)`, so the comparison has to be too.
    monkeypatch.setattr(settings, "seed_technician_email", "  CLEANER@Example.COM ")

    with pytest.raises(SeedConfigurationError):
        build_plan()


def test_the_plan_carries_the_two_operational_roles(complete_env) -> None:
    # Two and not four: the owner and the manager are whoever `make bootstrap` created,
    # resolved by role rather than re-declared here (design D4).
    plan = build_plan()

    assert tuple(account.role for account in plan.accounts) == (
        UserRole.CLEANER,
        UserRole.TECHNICIAN,
    )


def test_the_plan_normalises_both_addresses(
    monkeypatch: pytest.MonkeyPatch, complete_env
) -> None:
    monkeypatch.setattr(settings, "seed_cleaner_email", "  Cleaner@EXAMPLE.com ")

    plan = build_plan()

    assert plan.accounts[0].email == "cleaner@example.com"


def test_an_unexpected_failure_prints_its_class_and_never_its_parameters(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """R1.4, and the second half of the same security finding as above.

    `StatementError.__str__` appends `[SQL: ...] [parameters: (...)]`, and this command's
    parameters are a bcrypt hash and two people's addresses. Stood up with a real
    `IntegrityError` rather than a stand-in, because what is under test is precisely how
    SQLAlchemy renders itself.
    """
    leak = "$2b$04$averyrealisticlookingbcrypthashvalue"
    error = IntegrityError(
        f"INSERT INTO users (password_hash) VALUES ('{leak}')", {"password_hash": leak}, Exception()
    )

    async def _explode() -> dict[str, int]:
        raise error

    monkeypatch.setattr(seed_demo, "run", _explode)

    assert seed_demo.main() == 2

    captured = capsys.readouterr()
    assert leak in str(error), "the guard is pointless if SQLAlchemy stopped embedding parameters"
    assert leak not in captured.err
    assert leak not in captured.out
    assert "IntegrityError" in captured.err


def test_an_ingest_failure_reaches_the_console_with_its_reasons(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The `SeedIngestError` branch has to stay AHEAD of the catch-all (D11).

    Both branches exit 2, so a reorder would be invisible to a test that only checked the
    code — and `SeedIngestError` subclasses `Exception`, so moving it below `except
    Exception` silently disables it and the operator loses the one detail they can act on.
    What pins the order is asserting the REASON survives.

    Safe to print, unlike the catch-all's exception: every reason `ReservationIngestor`
    produces is a fixed sentence, a field name, or the repr of one of this module's own
    literal DTO constants — no `SEED_*` value ever reaches the ingestor.
    """

    async def _explode() -> dict[str, int]:
        raise seed_demo.SeedIngestError(
            "The demo reservations could not be ingested: Unknown property 'REDES11'"
        )

    monkeypatch.setattr(seed_demo, "run", _explode)

    assert seed_demo.main() == 2

    err = capsys.readouterr().err
    assert "Unknown property 'REDES11'" in err
    assert "details withheld" not in err, "this must not fall through to the catch-all"


# --- Preconditions: the tenant and the two accounts bootstrap left (R1.3, D4) ----------


async def _row_counts(session) -> dict[str, int]:
    """Every table the seed can write, so "nothing was written" is checked and not assumed.

    All seven and not just the two the accounts step touches: an abort that happens after a
    later step had already written would leave rows this helper never looked at, and the three
    tests below would still pass. The list has to match what the isolation test enumerates.

    **Counted with raw SQL on purpose**, which limit 1 of `app/core/db.py` documents as
    bypassing the tenant listener. An ORM `select(func.count())` would not measure the same
    thing before and after: `apply_plan` marks the session, so a "before" taken while unmarked
    is a global count and an "after" is silently scoped to the seeded tenant. The two can even
    coincide — a neighbour's row dropping out as a seeded row appears — which hides exactly the
    write these tests exist to catch. The rows are flushed but uncommitted, so a second session
    cannot see them at all; it has to be this session, counted past the listener.

    **Flushed first, and that is not a formality.** `session.execute(text(...))` does not
    autoflush, where the ORM `select(func.count())` this replaced did, and not every writer
    flushes on its own — `SqlAlchemyAuditLogRepository.add` only calls `session.add`. Without
    this line the helper would be blind to a pending-but-unflushed row and would report
    "nothing written" for an implementation that had written one. Raw SQL answers the scoping
    problem above and the flush answers the pending-row one; it takes both to measure
    everything the seed can leave behind.
    """
    await session.flush()
    return {
        model.__tablename__: int(
            await session.scalar(text(f"SELECT count(*) FROM {model.__tablename__}")) or 0
        )
        for model in (
            UserModel,
            PropertyModel,
            GuestModel,
            ReservationModel,
            CleaningChecklistTemplateModel,
            AuditLogModel,
            TimelineEventModel,
        )
    }


@pytest.mark.asyncio
async def test_without_the_tenant_it_aborts_without_writing_anything(
    db_session, complete_env, hasher
) -> None:
    before = await _row_counts(db_session)

    with pytest.raises(SeedPreconditionError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    assert "make bootstrap" in str(excinfo.value)
    assert await _row_counts(db_session) == before


@pytest.mark.asyncio
async def test_without_the_owner_it_aborts_without_writing_anything(
    db_session, complete_env, hasher
) -> None:
    tenant = await insert_tenant(db_session, name=BOOTSTRAPPED_TENANT_NAME)
    await insert_user(db_session, tenant=tenant, role=UserRole.PROPERTY_MANAGER)
    before = await _row_counts(db_session)

    with pytest.raises(SeedPreconditionError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    assert "TENANT_OWNER" in str(excinfo.value)
    assert await _row_counts(db_session) == before


@pytest.mark.asyncio
async def test_without_the_manager_it_aborts_without_writing_anything(
    db_session, complete_env, hasher
) -> None:
    tenant = await insert_tenant(db_session, name=BOOTSTRAPPED_TENANT_NAME)
    await insert_user(db_session, tenant=tenant, role=UserRole.TENANT_OWNER)
    before = await _row_counts(db_session)

    with pytest.raises(SeedPreconditionError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    assert "PROPERTY_MANAGER" in str(excinfo.value)
    assert await _row_counts(db_session) == before


@pytest.mark.asyncio
async def test_the_actor_of_everything_it_writes_is_the_owner(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # D5: one actor for the whole run, and the owner rather than the manager because a tenant
    # is guaranteed to keep an owner.
    await apply_plan(db_session, build_plan(), hasher)

    owner = (
        await db_session.execute(
            select(UserModel).where(
                UserModel.tenant_id == bootstrapped_tenant.id,
                UserModel.role == UserRole.TENANT_OWNER,
            )
        )
    ).scalar_one()
    actors = (
        (await db_session.execute(select(AuditLogModel.actor_user_id))).scalars().all()
    )
    assert set(actors) == {owner.id}


# --- The two operational accounts (R3.1-R3.6, D3, D6) ---------------------------------


@pytest.mark.asyncio
async def test_it_creates_the_cleaner_and_the_technician_ready_to_work(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["users"] == 2
    seeded = (
        (
            await db_session.execute(
                select(UserModel).where(
                    UserModel.email.in_(
                        [COMPLETE_ENV["SEED_CLEANER_EMAIL"], COMPLETE_ENV["SEED_TECHNICIAN_EMAIL"]]
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    assert {user.role for user in seeded} == {UserRole.CLEANER, UserRole.TECHNICIAN}
    # R3.4: a demo that demands four password rotations before the first click is not a demo.
    assert all(user.must_change_password is False for user in seeded)
    assert all(user.password_hash.startswith("$2") for user in seeded)


@pytest.mark.asyncio
async def test_a_second_run_creates_nothing_and_keeps_the_existing_password(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    await apply_plan(db_session, build_plan(), hasher)
    before = (
        await db_session.execute(
            select(UserModel.password_hash).where(
                UserModel.email == COMPLETE_ENV["SEED_CLEANER_EMAIL"]
            )
        )
    ).scalar_one()

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["users"] == 0
    assert await db_session.scalar(select(func.count()).select_from(UserModel)) == 4
    after = (
        await db_session.execute(
            select(UserModel.password_hash).where(
                UserModel.email == COMPLETE_ENV["SEED_CLEANER_EMAIL"]
            )
        )
    ).scalar_one()
    assert after == before


@pytest.mark.asyncio
async def test_an_address_taken_by_another_tenant_is_refused(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    neighbour = await insert_tenant(db_session, name="Another Agency")
    await insert_user(
        db_session,
        tenant=neighbour,
        role=UserRole.CLEANER,
        email=COMPLETE_ENV["SEED_CLEANER_EMAIL"],
    )

    with pytest.raises(SeedConflictError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    assert "another tenant" in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_conflict_on_the_second_account_still_writes_nothing_at_all(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """D11: the exit-1 conditions hold BEFORE the first write, not thanks to the rollback.

    The contested address here is the TECHNICIAN's, so the CLEANER — first in `plan.accounts`
    — is clean and gets inserted by any implementation that judges one account per iteration
    of the write loop, refusing only on the second. That is what this pins: the refusal has to
    be settled with both answers in hand, while nothing has been written yet.
    """
    neighbour = await insert_tenant(db_session, name="Another Agency")
    await insert_user(
        db_session,
        tenant=neighbour,
        role=UserRole.TECHNICIAN,
        email=COMPLETE_ENV["SEED_TECHNICIAN_EMAIL"],
    )
    before = await _row_counts(db_session)

    with pytest.raises(SeedConflictError):
        await apply_plan(db_session, build_plan(), hasher)

    assert await _row_counts(db_session) == before


@pytest.mark.asyncio
async def test_each_new_account_gets_its_audit_row_with_the_password_redacted(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # Rule 9 of steering/security.md names "roles de User", and this is the only role
    # assignment of the run (design D6).
    await apply_plan(db_session, build_plan(), hasher)

    entries = (
        (
            await db_session.execute(
                select(AuditLogModel).where(AuditLogModel.action == actions.USER_CREATED)
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 2
    for entry in entries:
        assert entry.entity_type == actions.ENTITY_USER
        serialised = str(entry.changes)
        assert COMPLETE_ENV["SEED_CLEANER_PASSWORD"] not in serialised
        assert COMPLETE_ENV["SEED_TECHNICIAN_PASSWORD"] not in serialised
        assert "password" in serialised


# --- The console contract and tenant isolation (R1.1, R1.2, R1.4, security rule 1) -----


# The shape `main()` is driven with below. Pinned to what `apply_plan` really returns by
# `test_the_counts_apply_plan_returns_have_the_shape_the_console_prints`, which is what keeps
# the canned dict from drifting into a fiction the console never sees.
_CONSOLE_COUNTS = {
    "users": 2,
    "properties": 2,
    "guests": 3,
    "reservations": 3,
    "checklist_templates": 1,
}


def _drive_main(monkeypatch: pytest.MonkeyPatch, counts: dict[str, int]) -> int:
    """Run `main()` over a canned result, because it cannot be run over the test session.

    `main()` calls `asyncio.run(run())`, which builds its OWN event loop, while `db_session`
    is bound to the test's — the "attached to a different loop" problem `tests/conftest.py`
    documents at length. Driving it with the counts `apply_plan` returns is not a weakening:
    `main()` receives a `dict[str, int]` and nothing else, so what the console can possibly
    print is decided entirely by this dict. The counts themselves are asserted against the
    database by the tests above.
    """

    async def _canned() -> dict[str, int]:
        return counts

    monkeypatch.setattr(seed_demo, "run", _canned)
    return seed_demo.main()


def test_the_output_carries_a_count_per_entity_and_nothing_else(
    complete_env, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    # R1.1 (a count per entity type) and R1.4 (never a password, a hash or a token) over the
    # success path. The three refusal paths and the catch-all are covered separately.
    exit_code = _drive_main(monkeypatch, dict(_CONSOLE_COUNTS))

    assert exit_code == 0
    captured = capsys.readouterr()
    for entity in ("users", "properties", "guests", "reservations", "checklist_templates"):
        assert entity in captured.out
    for secret in (
        COMPLETE_ENV["SEED_CLEANER_PASSWORD"],
        COMPLETE_ENV["SEED_TECHNICIAN_PASSWORD"],
    ):
        assert secret not in captured.out
        assert secret not in captured.err
    assert "$2b$" not in captured.out, "no bcrypt hash may reach the console"


@pytest.mark.asyncio
async def test_the_counts_apply_plan_returns_have_the_shape_the_console_prints(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """Ties the canned dict above to reality, which is the one thing `_drive_main` cannot.

    `main()` receives a `dict[str, int]` and nothing else, so that dict decides entirely what
    the console can print — but only as long as it is the dict `apply_plan` really returns. If
    a future entity type were added to one and not the other, every console test above would
    keep passing while the real command printed something different.
    """
    created = await apply_plan(db_session, build_plan(), hasher)

    assert created.keys() == _CONSOLE_COUNTS.keys()
    assert all(isinstance(count, int) for count in created.values())


def test_a_run_with_nothing_to_do_prints_every_count_at_zero_and_exits_zero(
    complete_env, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    # R1.2's console half: an operator has to be able to SEE that nothing happened, which is
    # why every entity type is printed even at zero. A line that dropped the zeros would be
    # indistinguishable from a run that did only part of the work.
    exit_code = _drive_main(
        monkeypatch,
        {
            "users": 0,
            "properties": 0,
            "guests": 0,
            "reservations": 0,
            "checklist_templates": 0,
        },
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    for entity in ("users", "properties", "guests", "reservations", "checklist_templates"):
        assert f"0 {entity}" in out


@pytest.mark.asyncio
async def test_a_second_run_returns_every_count_at_zero(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # The other half of R1.2: what `main()` prints comes from here, so this is where "nothing
    # was created" has to be true rather than merely reported.
    await apply_plan(db_session, build_plan(), hasher)

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created == {
        "users": 0,
        "properties": 0,
        "guests": 0,
        "reservations": 0,
        "checklist_templates": 0,
    }


@pytest.mark.asyncio
async def test_nothing_the_seed_writes_is_reachable_from_another_tenant(
    db_session, test_engine, bootstrapped_tenant, complete_env, hasher
) -> None:
    """DoD §28.18 and rule 1 of `steering/security.md`, over everything the seed writes.

    Two halves, because they fail differently. First: every row carries the seeded tenant's
    id — a row with a NULL or foreign `tenant_id` would be invisible to its owner rather than
    visible to a stranger. Second: the neighbour cannot reach any of it through the ports.

    **Both halves run on a SEPARATE, never-marked session, and the first one has to.**
    `apply_plan` marks `db_session`, and the `do_orm_execute` listener rewrites column-only
    selects too — so `select(Model.tenant_id).distinct()` on that session compiles to
    `... WHERE tenant_id = :seeded` and can only ever answer `[seeded]` or `[]`. Asserting
    ownership there proves the tables are non-empty and nothing else: a row written with a
    foreign or NULL `tenant_id` is filtered out by the very net the assertion is meant to
    work without. The section 7 security panel caught that; it was tautological as first
    written. Unmarked, the net is off and the rows answer for themselves.

    The second half is unmarked for a related but distinct reason: a marked session would
    prove only that the listener works, when the authoritative mechanism is the explicit
    `tenant_id` every repository method takes (design D6 of `auth-tenancy`). And it could not
    be `db_session` in any case — `bind_session_to_tenant` refuses to rebind a session
    already bound to another tenant, so the test would die in that guard instead of in an
    assertion.

    `audit_logs` is covered by the first half only, and deliberately: `SqlAlchemyAuditLog
    Repository` exposes no read method at all — only `add` — so there is no port through
    which a neighbour could ask. What `tests/audit` carries for it is therefore the
    cross-tenant WRITE guard (`test_it_refuses_an_entry_of_another_tenant`), not reads;
    there are none anywhere.
    """
    await apply_plan(db_session, build_plan(), hasher)
    neighbour = await insert_tenant(db_session, name="Another Agency")
    await db_session.commit()
    seeded = bootstrapped_tenant.id
    redes = (
        await db_session.execute(
            select(PropertyModel.id).where(PropertyModel.internal_code == "REDES11")
        )
    ).scalar_one()

    async with AsyncSession(test_engine, expire_on_commit=False) as stranger:
        for model in (
            UserModel,
            PropertyModel,
            GuestModel,
            ReservationModel,
            CleaningChecklistTemplateModel,
            AuditLogModel,
            TimelineEventModel,
        ):
            owners = (
                (await stranger.execute(select(model.tenant_id).distinct())).scalars().all()
            )
            assert owners == [seeded], (
                f"{model.__tablename__} must belong to the seeded tenant and to no other"
            )

        assert (
            await SqlAlchemyPropertyRepository(stranger).find_by_internal_code(
                neighbour.id, "REDES11"
            )
            is None
        )
        assert (
            await SqlAlchemyReservationRepository(stranger).find_by_external_pms_id(
                neighbour.id, "SEED-AIRBNB-1"
            )
            is None
        )
        assert (
            await SqlAlchemyGuestRepository(stranger).find_by_email(
                neighbour.id, "john.smith@example.com"
            )
            is None
        )
        assert (
            await SqlAlchemyCleaningChecklistTemplateRepository(stranger).list(
                neighbour.id, page=1, per_page=10
            )
        ).total == 0
        roster = await SqlAlchemyUserRepository(stranger).list(
            neighbour.id, UserFilters(), page=1, per_page=50
        )
        assert roster.total == 0
        # The neighbour naming the seeded property by its real id still gets nothing: the
        # timeline is scoped by tenant first, so knowing an id buys no access. Through the
        # READER and not the writer — the port is split on purpose, because the writer's
        # signature is what states the timeline is append-only.
        events = await SqlAlchemyTimelineEventReader(stranger).list_for_property(
            neighbour.id, redes, filters=TimelineFilters(), page=1, per_page=50
        )
        assert events.total == 0


# --- The two properties (R2.1-R2.4) ---------------------------------------------------


@pytest.mark.asyncio
async def test_it_creates_the_two_properties_of_the_prd_with_their_values(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["properties"] == 2
    homes = {
        model.internal_code: model
        for model in (await db_session.execute(select(PropertyModel))).scalars().all()
    }
    assert set(homes) == {"REDES11", "PAJARITOS8"}
    redes = homes["REDES11"]
    assert redes.name == "Redes 11"
    assert redes.address_line1 == "Calle de las Redes, 11"
    assert (redes.city, redes.province) == ("Madrid", "Madrid")
    assert (redes.max_guests, redes.bedrooms, redes.bathrooms) == (4, 2, 1)
    assert redes.default_check_in_time == time(15, 0)
    assert redes.default_check_out_time == time(11, 0)
    # §27 gives no postal code, and inventing one would be dataset drift.
    assert redes.postal_code is None
    # OQ1 closed with a NO: no `pms_external_id`, so `make pms-sync` does not import the
    # mock's own copy of these reservations on top of the seed's.
    assert redes.pms_external_id is None
    pajaritos = homes["PAJARITOS8"]
    assert (pajaritos.max_guests, pajaritos.bedrooms, pajaritos.bathrooms) == (2, 1, 1)


@pytest.mark.asyncio
async def test_both_properties_are_born_vacant_ready(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # R2.2: the seed never passes nor writes `current_operational_state` — the column takes
    # its DDL default and stays where `PropertyStateMachine` governs it.
    await apply_plan(db_session, build_plan(), hasher)

    states = (
        (await db_session.execute(select(PropertyModel.current_operational_state)))
        .scalars()
        .all()
    )
    assert set(states) == {PropertyOperationalState.VACANT_READY}


@pytest.mark.asyncio
async def test_a_second_run_creates_no_third_property(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    await apply_plan(db_session, build_plan(), hasher)

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["properties"] == 0
    assert await db_session.scalar(select(func.count()).select_from(PropertyModel)) == 2


@pytest.mark.asyncio
async def test_a_second_run_leaves_an_existing_property_exactly_as_it_was(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # R2.3 asks for the existing home to be left INTACT, and a row count cannot show that: a
    # re-run that rewrote §27's values over an operator's edits would keep the count at two.
    # The users test asserts the password hash survives; a property deserves the same.
    await apply_plan(db_session, build_plan(), hasher)
    redes = (
        await db_session.execute(
            select(PropertyModel).where(PropertyModel.internal_code == "REDES11")
        )
    ).scalar_one()
    redes.name = "Renamed by whoever runs this environment"
    redes.max_guests = 9
    await db_session.flush()

    await apply_plan(db_session, build_plan(), hasher)

    refreshed = (
        await db_session.execute(
            select(PropertyModel).where(PropertyModel.internal_code == "REDES11")
        )
    ).scalar_one()
    assert refreshed.name == "Renamed by whoever runs this environment"
    assert refreshed.max_guests == 9


# --- The three reservations and their guests (R4.1-R4.6, D7, D8, D9) -------------------


async def _reservations_by_channel(session) -> dict[ReservationChannel, ReservationModel]:
    rows = (await session.execute(select(ReservationModel))).scalars().all()
    return {row.channel: row for row in rows}


@pytest.mark.asyncio
async def test_the_dates_are_anchored_to_the_tenants_day_and_not_to_utc(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R4.3's composition is about the calendar the demo is watched on.

    23:30 UTC on 15 June is already 01:30 on the **16th** in Madrid (CEST). Anchored on
    `now.date()` this run used the 15th, so every stay landed a day early — the "live" one as
    the 13th → 16th. The reasoning lives beside the `today` computation in `seed_demo.py` and
    in D9's amendment; this test only pins it, so the two do not drift. Every other date test
    uses 09:00 UTC, where the two calendars agree and this cannot show up.
    """
    await apply_plan(
        db_session, build_plan(), hasher, now=datetime(2026, 6, 15, 23, 30, tzinfo=UTC)
    )

    airbnb = (await _reservations_by_channel(db_session))[ReservationChannel.AIRBNB]
    # today = 2026-06-16 in Madrid ⇒ today−2 → today+1.
    assert airbnb.check_in_date == date(2026, 6, 14)
    assert airbnb.check_out_date == date(2026, 6, 17)


@pytest.mark.asyncio
async def test_it_creates_the_three_stays_of_the_prd_dated_from_today(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    now = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)

    created = await apply_plan(db_session, build_plan(), hasher, now=now)

    assert created["reservations"] == 3
    stays = await _reservations_by_channel(db_session)
    assert set(stays) == {
        ReservationChannel.DIRECT,
        ReservationChannel.AIRBNB,
        ReservationChannel.BOOKING,
    }
    today = now.date()
    # R4.3: past, live and upcoming, whatever day the seed runs.
    assert stays[ReservationChannel.DIRECT].check_in_date == today - timedelta(days=10)
    assert stays[ReservationChannel.DIRECT].check_out_date == today - timedelta(days=7)
    assert stays[ReservationChannel.AIRBNB].check_in_date == today - timedelta(days=2)
    assert stays[ReservationChannel.AIRBNB].check_out_date == today + timedelta(days=1)
    assert stays[ReservationChannel.BOOKING].check_in_date == today + timedelta(days=3)
    assert stays[ReservationChannel.BOOKING].check_out_date == today + timedelta(days=7)


@pytest.mark.asyncio
async def test_none_of_the_three_is_given_a_status_by_hand(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R4.4, and the single most tempting thing to get wrong in this change.

    §27 draws the three stays as `CHECKED_IN_ESTIMATED`, `CONFIRMED` and `COMPLETED`. Two of
    those are states that are REACHED — by `PropertyStateMachine` and by the scheduler of
    `celery-jobs` — not values to assign. The DIRECT path cannot express one at all
    (`CreateReservationCommand` has no `status` field); the OTA path can, through
    `ReservationDTO.status`, and leaving it `None` is what makes this hold.

    The two defaults are DIFFERENT, and that is the point rather than an inconsistency:
    `Reservation.create` starts a hand-made booking at `PENDING`, while
    `ReservationStatus.parse_ingested(None)` deliberately reads a feed row with no status as
    `CONFIRMED` — "a reservation that reaches us from a PMS feed or a CSV without a status is
    a booking somebody already accepted". Each stay is born in the default OF ITS PATH, which
    is exactly what R4.4 asks for; asserting one shared value would be asserting that the
    seed had flattened the distinction.
    """
    await apply_plan(db_session, build_plan(), hasher)

    stays = await _reservations_by_channel(db_session)
    assert stays[ReservationChannel.DIRECT].status is ReservationStatus.PENDING
    assert stays[ReservationChannel.AIRBNB].status is ReservationStatus.CONFIRMED
    assert stays[ReservationChannel.BOOKING].status is ReservationStatus.CONFIRMED
    # The two §27 values that are reached and never assigned must appear nowhere.
    assert ReservationStatus.CHECKED_IN_ESTIMATED not in {
        stay.status for stay in stays.values()
    }
    assert ReservationStatus.COMPLETED not in {stay.status for stay in stays.values()}


@pytest.mark.asyncio
async def test_the_two_ota_stays_carry_their_external_pms_id_and_the_direct_one_does_not(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # R4.2: the ingest path is what assigns `external_pms_id`, and that id is the key the
    # next sync uses to avoid re-importing the same stay. Giving the DIRECT one an id would
    # be a lie — it came from no PMS (design D8).
    await apply_plan(db_session, build_plan(), hasher)

    stays = await _reservations_by_channel(db_session)
    assert stays[ReservationChannel.AIRBNB].external_pms_id == "SEED-AIRBNB-1"
    assert stays[ReservationChannel.BOOKING].external_pms_id == "SEED-BOOKING-1"
    assert stays[ReservationChannel.DIRECT].external_pms_id is None
    assert stays[ReservationChannel.DIRECT].external_channel_id == "SEED-DIRECT-1"


@pytest.mark.asyncio
async def test_the_airbnb_stay_carries_the_money_of_the_prd_with_net_derived(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # §27's €297.50 is NOT a field of the DTO: it is gross − commission, derived by
    # `net_amount_from` inside the ingestor.
    await apply_plan(db_session, build_plan(), hasher)

    airbnb = (await _reservations_by_channel(db_session))[ReservationChannel.AIRBNB]
    assert airbnb.gross_amount == Decimal("350.00")
    assert airbnb.ota_commission == Decimal("52.50")
    assert airbnb.net_amount == Decimal("297.50")
    assert airbnb.adults == 2


@pytest.mark.asyncio
async def test_the_three_guests_are_registered_and_linked(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["guests"] == 3
    guests = {
        row.full_name: row
        for row in (await db_session.execute(select(GuestModel))).scalars().all()
    }
    assert set(guests) == {"Pedro López", "John Smith", "María García"}
    assert guests["John Smith"].email == "john.smith@example.com"
    assert guests["María García"].email == "maria.garcia@example.com"
    # §27 gives Pedro no address, and inventing one would be dataset drift.
    assert guests["Pedro López"].email is None
    stays = await _reservations_by_channel(db_session)
    assert stays[ReservationChannel.DIRECT].guest_id == guests["Pedro López"].id
    assert stays[ReservationChannel.AIRBNB].guest_id == guests["John Smith"].id


@pytest.mark.asyncio
async def test_a_second_run_a_week_later_moves_nothing(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """R1.2 over R4.3, which is the trade design D9 makes explicit.

    The ingestor's own idempotency is to UPDATE what it recognises, so handing it rows it
    already has would re-anchor the dates on every run. R4.3 describes a FRESH seed; a
    re-seed keeps the dates it was given. An environment seeded a fortnight ago shows a
    "live" stay that has already ended, and the way to refresh it is to drop the database.
    """
    first = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
    await apply_plan(db_session, build_plan(), hasher, now=first)
    before = {
        row.id: (row.check_in_date, row.check_out_date)
        for row in (await db_session.execute(select(ReservationModel))).scalars().all()
    }

    created = await apply_plan(
        db_session, build_plan(), hasher, now=first + timedelta(days=7)
    )

    assert created["reservations"] == 0
    assert created["guests"] == 0
    after = {
        row.id: (row.check_in_date, row.check_out_date)
        for row in (await db_session.execute(select(ReservationModel))).scalars().all()
    }
    assert after == before
    assert await db_session.scalar(select(func.count()).select_from(GuestModel)) == 3


@pytest.mark.asyncio
async def test_deleting_the_direct_stay_by_hand_and_reseeding_duplicates_its_guest(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """The one entity with no identity key, pinned so it cannot change in silence (D9).

    Every other entity keys on something stable; Pedro López cannot, because §27 gives him no
    email and R4.5 says "nombre y correo *donde §27 lo da*". Inventing one to buy a key would
    be drift in the dataset the PRD fixes, and the guests port offers no lookup by name.

    So his creation rides on the reservation's: an ordinary second run does not duplicate him,
    because the whole step is skipped. Hand-deleting the DIRECT stay and re-seeding does — a
    new stay and a second Pedro, the first left orphaned. This test asserts that outcome
    rather than wishing it away, and `docs/seed-demo.md` tells the reader to drop the database
    instead.
    """
    await apply_plan(db_session, build_plan(), hasher)
    direct = (await _reservations_by_channel(db_session))[ReservationChannel.DIRECT]
    await db_session.execute(
        delete(TimelineEventModel).where(TimelineEventModel.reservation_id == direct.id)
    )
    await db_session.execute(delete(ReservationModel).where(ReservationModel.id == direct.id))
    await db_session.flush()

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["reservations"] == 1
    assert created["guests"] == 1
    pedros = (
        (
            await db_session.execute(
                select(GuestModel).where(GuestModel.full_name == "Pedro López")
            )
        )
        .scalars()
        .all()
    )
    assert len(pedros) == 2, "documented consequence of the missing key, not a surprise"


@pytest.mark.asyncio
async def test_a_failure_after_the_reservations_rolls_the_whole_run_back(
    db_session, bootstrapped_tenant, complete_env, hasher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-transaction guarantee, asserted instead of assumed.

    `apply_plan` hands every composed use case a `CallerOwnedUnitOfWork`, so the only real
    commit is its own at the very end. That is what makes a mid-run failure leave nothing
    behind — and it is exactly the kind of promise that holds until somebody swaps one wiring
    back to a real unit of work, which is why it needs a test rather than a docstring.

    The failure is injected at the last step, so accounts, properties, guests and all three
    reservations have already been flushed when it fires. What proves the point is that they
    are gone AFTER the rollback: had any composed use case been wired to a real unit of work,
    its rows would have been committed and would survive.

    The tenant and its two administrative accounts go too, and that is the fixture's doing
    rather than the seed's — `bootstrapped_tenant` flushes instead of committing, so it shares
    this transaction.
    """

    async def _explode(*args, **kwargs):
        raise RuntimeError("boom-after-the-reservations")

    monkeypatch.setattr(seed_demo, "_seed_checklist_template", _explode)

    with pytest.raises(RuntimeError):
        await apply_plan(db_session, build_plan(), hasher)
    await db_session.rollback()

    for model in (PropertyModel, ReservationModel, GuestModel, AuditLogModel, UserModel):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.asyncio
async def test_an_ingest_that_skips_a_row_fails_the_command_loudly(
    db_session, bootstrapped_tenant, complete_env, hasher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ingest` reports a bad row instead of raising, which is right for an uploaded CSV and
    wrong for a dataset this module wrote itself. Without this the command would print counts
    claiming a seed that did not happen.

    Provoked by pointing one DTO at a property that does not exist — the resolver returns
    `None` and the ingestor records a skipped row.
    """
    original = seed_demo._ota_reservation_dtos

    def _one_row_points_nowhere(today):
        first, second = original(today)
        return (replace(first, property_external_id="NOSUCHCODE"), second)

    monkeypatch.setattr(seed_demo, "_ota_reservation_dtos", _one_row_points_nowhere)

    with pytest.raises(seed_demo.SeedIngestError) as excinfo:
        await apply_plan(db_session, build_plan(), hasher)

    assert "NOSUCHCODE" in str(excinfo.value)


# --- The tenant's checklist template (R5.1, R5.2, D10) --------------------------------


@pytest.mark.asyncio
async def test_it_creates_the_default_template_for_the_whole_tenant(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["checklist_templates"] == 1
    template = (
        await db_session.execute(select(CleaningChecklistTemplateModel))
    ).scalar_one()
    # No `property_id` is how the schema spells "both homes" (§7.10 declares it nullable).
    assert template.property_id is None
    assert template.active is True
    assert [item["item_id"] for item in template.items] == [
        "ventilate",
        "remove_rubbish",
        "check_fridge",
        "clean_kitchen_surfaces",
        "clean_sink",
        "clean_bathroom",
        "replace_toilet_paper",
        "replace_towels",
        "make_beds",
        "check_linen",
        "mop_floor",
        "check_sofa",
        "replenish_amenities",
        "check_wifi_router",
        "check_ac_remote",
        "check_keys",
        "report_damages",
        "upload_photos",
    ]
    assert [photo["photo_type"] for photo in template.required_photos] == [
        "living_room",
        "bedroom",
        "bathroom",
        "kitchen",
        "entrance",
        "damage_if_found",
    ]


@pytest.mark.asyncio
async def test_every_item_and_photo_is_required_and_labelled_in_spanish(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    # `required` spelled out on every entry, because `parse_template_content` reads a missing
    # one as False — and demands a real bool, so `1` would be refused (design D10).
    await apply_plan(db_session, build_plan(), hasher)

    template = (
        await db_session.execute(select(CleaningChecklistTemplateModel))
    ).scalar_one()
    assert all(item["required"] is True for item in template.items)
    assert all(photo["required"] is True for photo in template.required_photos)
    assert template.items[0]["label"] == "Ventilar la vivienda"
    assert template.required_photos[0]["label"] == "Salón"


@pytest.mark.asyncio
async def test_the_seeded_template_passes_the_value_objects_validation(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    """What the column holds must survive being read back through the parser.

    The use case parses on the way in, so this asserts the round trip rather than the input:
    a template the seed wrote but `cleaning` could not re-read would be a checklist nobody
    could complete.
    """
    await apply_plan(db_session, build_plan(), hasher)

    template = (
        await db_session.execute(select(CleaningChecklistTemplateModel))
    ).scalar_one()
    spec = parse_template_content(template.items, template.required_photos)

    assert len(spec.items) == 18
    assert len(spec.required_photos) == 6


@pytest.mark.asyncio
async def test_a_tenant_that_already_has_a_template_gets_no_second_one(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    await apply_plan(db_session, build_plan(), hasher)

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["checklist_templates"] == 0
    assert (
        await db_session.scalar(
            select(func.count()).select_from(CleaningChecklistTemplateModel)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_a_second_run_adds_no_audit_rows(
    db_session, bootstrapped_tenant, complete_env, hasher
) -> None:
    await apply_plan(db_session, build_plan(), hasher)
    before = await db_session.scalar(select(func.count()).select_from(AuditLogModel))

    await apply_plan(db_session, build_plan(), hasher)

    assert await db_session.scalar(select(func.count()).select_from(AuditLogModel)) == before
