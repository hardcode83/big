"""The four end-to-end scenarios of R4 against the real CLI (`sim-advance` R4.1-R4.4).

`sim_advance._run(argv)` is the testable entry point: it returns the exit code (0/1/2) and
prints the now line + one report line per job on success, or a failure line per failed job
on stderr. The CLI's `worker_session_factory()` is bound to `settings.database_url` —
**the dev database**, which `tests/conftest.py` deliberately leaves alone (it builds its own
`<db>_test_<suffix>` and tears it down). Without a redirect, every test would issue its
`INSERT`s against the dev schema and read against a fresh per-test database, finding nothing.

The redirect is the same one `tests/auth/test_reset_password_cli.py` uses for the same reason
(its own module note): `monkeypatch.setattr` the binding **in `app.cli.sim_advance`**, where
the name was imported, against an `async_sessionmaker(test_engine, expire_on_commit=False)`
so each CLI session sits on the test engine. Verification uses a fresh `AsyncSession` on the
same engine — `db_session` shares one transaction for the whole test, and a row written by
the CLI's other session needs that fresh eye to be visible without re-querying.
"""

import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cleaning.infrastructure.models import CleaningChecklistTemplateModel
from app.cli import sim_advance as cli
from app.core.config import settings
from app.properties.domain.enums import PropertyOperationalState
from app.properties.infrastructure.models import (
    PropertyModel,
    PropertyStateTransitionModel,
)
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.models import TenantConfigModel
from app.timeline.infrastructure.models import TimelineEventModel
from tests.auth.conftest import insert_tenant

MADRID = ZoneInfo("Europe/Madrid")


def _local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Build a tz-aware Madrid instant — the property's zone, the one `opens_checkin_window`
    clamps to. Convert to UTC before passing as `--at` so the CLI's `astimezone(UTC)` is a
    no-op rather than a conversion that hides a bug."""
    return datetime(year, month, day, hour, minute, tzinfo=MADRID)


def _at_utc(dt_local: datetime) -> str:
    """Render a Madrid instant as the ISO 8601 string the CLI's `--at` accepts."""
    return dt_local.astimezone(UTC).isoformat()


@pytest.fixture
def test_factory(test_engine, monkeypatch: pytest.MonkeyPatch):
    """An `async_sessionmaker` on the test engine, mounted into the CLI module.

    `cli.worker_session_factory` is the name the CLI imports into its own namespace
    (`from app.scheduler.runner import worker_session_factory`); patching the binding
    there, not on `app.scheduler.runner`, is what makes the CLI's own `worker_session_factory()()`
    calls land on the test database. The sessionmaker itself holds only configuration —
    it does not bind to a loop until a session is opened — so reusing the test_engine
    across loops is safe (NullPool, no cached connection).
    """
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(cli, "worker_session_factory", lambda: factory)
    yield factory


async def _insert_property(
    db_session: AsyncSession, *, tenant_id: uuid.UUID, code: str = "REDES11"
) -> PropertyModel:
    prop = PropertyModel(
        tenant_id=tenant_id,
        name=f"Property {code}",
        internal_code=code,
        timezone="Europe/Madrid",
        max_guests=4,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


async def _insert_reservation(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    property_id: uuid.UUID,
    check_in: datetime,
    nights: int,
    status: ReservationStatus = ReservationStatus.CONFIRMED,
) -> ReservationModel:
    reservation = ReservationModel(
        tenant_id=tenant_id,
        property_id=property_id,
        channel=ReservationChannel.AIRBNB,
        status=status,
        check_in_date=check_in.date(),
        check_out_date=(check_in + timedelta(days=nights)).date(),
        check_in_time=check_in.time(),
        check_out_time=time(11, 0),
        nights=nights,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation


async def _insert_cleaning_template(
    db_session: AsyncSession, *, tenant_id: uuid.UUID, property_id: uuid.UUID
) -> CleaningChecklistTemplateModel:
    template = CleaningChecklistTemplateModel(
        tenant_id=tenant_id,
        property_id=property_id,
        name="Estándar",
        items=[{"item_id": "kitchen", "label": "Cocina", "required": True}],
        required_photos=[],
        active=True,
    )
    db_session.add(template)
    await db_session.flush()
    return template


def _report_line_for(captured: str, trigger_value: str) -> str:
    """Find the line of the CLI's stdout that reports on a given trigger.

    The CLI prints one summary line per job in this fixed shape
    (`sim_advance.py::_format_report_line`); a test that asserts on a single substring of
    that line is asserting on whether a job ran, not on which job produced which count —
    ambiguous once two jobs can both transition.
    """
    for line in captured.splitlines():
        if f"trigger={trigger_value}" in line:
            return line
    raise AssertionError(
        f"no report line for trigger={trigger_value!r} in stdout:\n{captured}"
    )


# --- R4.1 — check-in time reached drives VACANT_READY -> OCCUPIED_ESTIMATED --------


@pytest.mark.asyncio
async def test_r41_checkin_time_advances_vacant_ready_to_occupied_estimated(
    db_session, test_engine, test_factory, capsys: pytest.CaptureFixture[str]
) -> None:
    """R4.1: CONFIRMED reservation, check-in today at 15:00 local, check-out in two days;
    CLI with `--at` at check-in + 1 minute; the property reaches `OCCUPIED_ESTIMATED`, the
    `CHECKIN_TIME_REACHED` job reports `transitioned: 1`.

    The first job (`CHECKIN_WINDOW_OPENED`) also fires in this run — the window opens 2 h
    before the local check-in hour, and `now = 15:01` is well inside it — so the report
    contains two transition lines. The state assertion is about the FINAL state of the
    property (the committed `OCCUPIED_ESTIMATED`); the `transitioned: 1` assertion is
    pinned to the `CHECKIN_TIME_REACHED` line, where the `AWAITING_CHECKIN -> OCCUPIED_ESTIMATED`
    transition lives. Without that scoping, "transitioned: 1" matches the
    `CHECKIN_WINDOW_OPENED` line too and a regression in the second job is invisible.
    """
    tenant = await insert_tenant(db_session)
    await db_session.commit()  # the CLI reads through its own session
    prop = await _insert_property(db_session, tenant_id=tenant.id)
    check_in_local = _local(2026, 9, 10, 15, 0)
    reservation = await _insert_reservation(
        db_session,
        tenant_id=tenant.id,
        property_id=prop.id,
        check_in=check_in_local,
        nights=2,
    )
    check_in_date_before = reservation.check_in_date
    check_out_date_before = reservation.check_out_date
    await db_session.commit()

    rc = await cli._run(
        ["--tenant", str(tenant.id), "--at", _at_utc(check_in_local + timedelta(minutes=1))]
    )
    captured = capsys.readouterr()

    assert rc == 0, f"unexpected non-zero exit; stderr:\n{captured.err}\nstdout:\n{captured.out}"

    async with AsyncSession(test_engine, expire_on_commit=False) as fresh:
        prop_row = (
            await fresh.execute(select(PropertyModel).where(PropertyModel.id == prop.id))
        ).scalar_one()
        assert prop_row.current_operational_state is PropertyOperationalState.OCCUPIED_ESTIMATED

        res_row = (
            await fresh.execute(
                select(ReservationModel).where(ReservationModel.id == reservation.id)
            )
        ).scalar_one()
        assert res_row.check_in_date == check_in_date_before
        assert res_row.check_out_date == check_out_date_before

    line = _report_line_for(captured.out, "CHECKIN_TIME_REACHED")
    assert "transitioned=1" in line
    assert "candidates=1" in line


# --- R4.2 — checkout drives OCCUPIED_ESTIMATED -> AWAITING_CLEANING ----------------


@pytest.mark.asyncio
async def test_r42_checkout_advances_to_awaiting_cleaning_without_moving_dates(
    db_session, test_engine, test_factory, capsys: pytest.CaptureFixture[str]
) -> None:
    """R4.2: a property already in `OCCUPIED_ESTIMATED`; CLI with `--at` at check-out
    instant; transitions to `AWAITING_CLEANING`; `transitioned: 1`; `transitioned_without_task: 0`
    (with `auto_create_cleaning_task` on by default and a resolvable template); the
    reservation's dates do not move.

    `transitioned_without_task` is the bucket that goes non-zero when the provisioner
    creates no `CleaningTask` (R2.4, design D1). With the default `TenantConfig.auto_create_cleaning_task
    = True` and a cleaning checklist template bound to the property, `provision_for_checkout`
    writes the task; without the template the run counts a `None` and the bucket increments.
    The test exercises the success path, which is the contract the operator relies on —
    the failure path is the seed's `R2.4` regression.
    """
    tenant = await insert_tenant(db_session)
    await db_session.commit()
    prop = await _insert_property(db_session, tenant_id=tenant.id)
    check_in_local = _local(2026, 9, 10, 15, 0)
    check_out_local = check_in_local + timedelta(days=2, hours=-4)  # day + 2 at 11:00 local
    # Seed the property in OCCUPIED_ESTIMATED and the reservation in CHECKED_IN_ESTIMATED so
    # the third job's source-state query finds it. This mirrors the live state at 10:59 on
    # day + 2 — the property has the booking, the booking is in the flat, and `now` is the
    # checkout instant.
    prop.current_operational_state = PropertyOperationalState.OCCUPIED_ESTIMATED
    reservation = await _insert_reservation(
        db_session,
        tenant_id=tenant.id,
        property_id=prop.id,
        check_in=check_in_local,
        nights=2,
        status=ReservationStatus.CHECKED_IN_ESTIMATED,
    )
    check_in_date_before = reservation.check_in_date
    check_out_date_before = reservation.check_out_date
    await _insert_cleaning_template(db_session, tenant_id=tenant.id, property_id=prop.id)
    await db_session.commit()

    rc = await cli._run(
        ["--tenant", str(tenant.id), "--at", _at_utc(check_out_local)]
    )
    captured = capsys.readouterr()

    assert rc == 0, f"unexpected non-zero exit; stderr:\n{captured.err}\nstdout:\n{captured.out}"

    async with AsyncSession(test_engine, expire_on_commit=False) as fresh:
        prop_row = (
            await fresh.execute(select(PropertyModel).where(PropertyModel.id == prop.id))
        ).scalar_one()
        assert prop_row.current_operational_state is PropertyOperationalState.AWAITING_CLEANING

        res_row = (
            await fresh.execute(
                select(ReservationModel).where(ReservationModel.id == reservation.id)
            )
        ).scalar_one()
        assert res_row.check_in_date == check_in_date_before
        assert res_row.check_out_date == check_out_date_before

    line = _report_line_for(captured.out, "CHECKOUT_TIME_REACHED")
    assert "transitioned=1" in line
    assert "transitioned_without_task=0" in line


# --- R4.3 — pre-window `now` reports not_eligible and does not transition -----------


@pytest.mark.asyncio
async def test_r43_three_hours_before_checkin_does_not_transition(
    db_session, test_engine, test_factory, capsys: pytest.CaptureFixture[str]
) -> None:
    """R4.3: `--at` 3 hours before the local check-in hour; the property stays in
    `VACANT_READY`; the first job (`CHECKIN_WINDOW_OPENED`) reports `not_eligible: 1` —
    the bucket `clock_triggers.opens_checkin_window` falls into when the operator's window
    has not yet opened (the only pre-judgement the use case makes, design D7).

    The check-in window is 2 hours by default (`TenantConfig.checkin_window_hours_before`);
    3 hours before the local hour is OUTSIDE the window, so `opens_checkin_window` returns
    False, the reservation is skipped, and the loop increments `not_eligible`. The other two
    jobs have no candidate (the property is still `VACANT_READY`), so their lines carry
    nothing — what the task pins is the first job's bucket.
    """
    tenant = await insert_tenant(db_session)
    await db_session.commit()
    prop = await _insert_property(db_session, tenant_id=tenant.id)
    check_in_local = _local(2026, 9, 10, 15, 0)
    await _insert_reservation(
        db_session,
        tenant_id=tenant.id,
        property_id=prop.id,
        check_in=check_in_local,
        nights=2,
    )
    await db_session.commit()

    three_hours_before = check_in_local - timedelta(hours=3)
    rc = await cli._run(
        ["--tenant", str(tenant.id), "--at", _at_utc(three_hours_before)]
    )
    captured = capsys.readouterr()

    assert rc == 0, f"unexpected non-zero exit; stderr:\n{captured.err}\nstdout:\n{captured.out}"

    async with AsyncSession(test_engine, expire_on_commit=False) as fresh:
        prop_row = (
            await fresh.execute(select(PropertyModel).where(PropertyModel.id == prop.id))
        ).scalar_one()
        assert prop_row.current_operational_state is PropertyOperationalState.VACANT_READY

    line = _report_line_for(captured.out, "CHECKIN_WINDOW_OPENED")
    assert "not_eligible=1" in line


# --- R4.4 — environment guard fires before any DB write -----------------------------


@pytest.mark.asyncio
async def test_r44_environment_staging_is_refused_before_any_write(
    db_session, test_engine, test_factory, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R4.4: `settings.environment = "staging"`; CLI exits 1; the guard message names the
    value and the accepted set; no row of `property_state_transitions` or `timeline_events`
    written.

    The guard in `_env_guard` fires BEFORE the tenant check and BEFORE the first session is
    opened (`_run` prints the `now` line, then guards, then checks the tenant, then runs
    the jobs). The tenant here exists only to keep the test self-contained; an empty
    database would still exit 1 with the guard message and write nothing. The row counts
    are taken on a fresh session — the per-test vacuum of `conftest.py` ran before this
    test, so `0` is the truth at start.
    """
    tenant = await insert_tenant(db_session)
    prop = await _insert_property(db_session, tenant_id=tenant.id)
    await _insert_reservation(
        db_session,
        tenant_id=tenant.id,
        property_id=prop.id,
        check_in=_local(2026, 9, 10, 15, 0),
        nights=2,
    )
    await db_session.commit()

    async def _count_rows() -> tuple[int, int]:
        async with AsyncSession(test_engine, expire_on_commit=False) as fresh:
            transitions = (
                await fresh.execute(
                    select(func.count())
                    .select_from(PropertyStateTransitionModel)
                    .where(PropertyStateTransitionModel.tenant_id == tenant.id)
                )
            ).scalar_one()
            events = (
                await fresh.execute(
                    select(func.count())
                    .select_from(TimelineEventModel)
                    .where(TimelineEventModel.tenant_id == tenant.id)
                )
            ).scalar_one()
        return int(transitions), int(events)

    transitions_before, events_before = await _count_rows()
    assert transitions_before == 0
    assert events_before == 0

    # Patched at call time, not import time: the CLI reads `settings.environment` inside
    # `_env_guard`, so monkeypatching the field on the live instance is what the section 2
    # implementation promises.
    monkeypatch.setattr(settings, "environment", "staging")

    rc = await cli._run(["--tenant", str(tenant.id)])
    captured = capsys.readouterr()

    assert rc == 1
    assert "staging" in captured.err
    assert "local" in captured.err and "dev" in captured.err
    # Sanity: the field actually read at call time — proves the guard is not caching the
    # import-time value.
    assert settings.environment == "staging"

    transitions_after, events_after = await _count_rows()
    assert transitions_after == 0, (
        f"guard ran after a transition; rows: {transitions_after}\nstdout:\n{captured.out}\nstderr:\n{captured.err}"
    )
    assert events_after == 0, (
        f"guard ran after a timeline event; rows: {events_after}\nstdout:\n{captured.out}\nstderr:\n{captured.err}"
    )
