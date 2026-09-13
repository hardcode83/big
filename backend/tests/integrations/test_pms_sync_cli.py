"""The `pms_sync` console command (R3, design D10).

Argument handling is tested directly; the sync itself is covered in `test_sync.py`, so `run`
is stubbed here rather than driving the real database through a command that opens its own
session (the test session is a different one, by design).
"""

import uuid
from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import select

from app.integrations.application.ingest import IngestReport, RowError
from app.integrations.cli import pms_sync
from app.integrations.cli.pms_sync import UnknownTenantError
from app.integrations.domain.dtos import PmsFetchResult, ReservationDTO
from app.integrations.domain.enums import PMSProvider
from app.integrations.infrastructure.mock_pms import SEED_PROPERTY_CODE
from app.properties.domain.enums import PropertyOperationalState
from app.properties.infrastructure.models import PropertyStateTransitionModel
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel


def test_it_refuses_to_run_without_a_tenant(capsys) -> None:
    assert pms_sync.main([]) == 2
    assert "usage" in capsys.readouterr().err


def test_it_refuses_a_tenant_that_is_not_a_uuid(capsys) -> None:
    assert pms_sync.main(["not-a-uuid"]) == 2
    assert "not a UUID" in capsys.readouterr().err


def test_it_refuses_a_non_numeric_window(capsys) -> None:
    assert pms_sync.main([str(uuid.uuid4()), "many"]) == 2
    assert "window-days" in capsys.readouterr().err


def test_it_prints_the_report_and_exits_zero(monkeypatch, capsys) -> None:
    called = {}

    async def _fake_run(tenant_id, *, window_days, provider=pms_sync.MOCK_PROVIDER):
        called["tenant_id"] = tenant_id
        called["window_days"] = window_days
        return IngestReport(created=2, updated=1, skipped=0)

    monkeypatch.setattr(pms_sync, "run", _fake_run)
    tenant_id = uuid.uuid4()

    assert pms_sync.main([str(tenant_id), "7"]) == 0

    assert called == {"tenant_id": tenant_id, "window_days": 7}
    out = capsys.readouterr().out
    assert "created 2" in out
    assert "updated 1" in out


def test_skipped_rows_are_reported_but_do_not_fail_the_command(monkeypatch, capsys) -> None:
    """R3.4: rows the sync could not import are information, not a failed run."""

    async def _fake_run(tenant_id, *, window_days, provider=pms_sync.MOCK_PROVIDER):
        return IngestReport(
            created=1,
            skipped=1,
            errors=[RowError(reference="PMS-9", reason="Unknown property 'X' for this tenant")],
        )

    monkeypatch.setattr(pms_sync, "run", _fake_run)

    assert pms_sync.main([str(uuid.uuid4())]) == 0

    captured = capsys.readouterr()
    assert "skipped PMS-9" in captured.err
    assert "Unknown property" in captured.err


def test_the_default_window_is_used_when_not_given(monkeypatch) -> None:
    seen = {}

    async def _fake_run(tenant_id, *, window_days, provider=pms_sync.MOCK_PROVIDER):
        seen["window_days"] = window_days
        return IngestReport()

    monkeypatch.setattr(pms_sync, "run", _fake_run)

    pms_sync.main([str(uuid.uuid4())])

    assert seen["window_days"] == pms_sync.DEFAULT_WINDOW_DAYS


@pytest.mark.asyncio
async def test_it_binds_the_session_to_the_tenant(monkeypatch, db_session, tenant_a, property_a) -> None:
    """The command does not go through `get_authenticated_request`, so it must mark the session
    itself — otherwise the listener of `app/core/db.py` scopes nothing (its limit 2)."""
    from app.core import db as core_db

    marked: list[uuid.UUID] = []
    real_bind = core_db.bind_session_to_tenant

    def _spy(session, tenant_id):
        marked.append(tenant_id)
        return real_bind(session, tenant_id)

    monkeypatch.setattr(pms_sync, "bind_session_to_tenant", _spy)

    report = await pms_sync.sync_with_session(db_session, tenant_a.id)

    assert marked == [tenant_a.id]
    assert report.created == 2


@pytest.mark.asyncio
async def test_it_refuses_a_tenant_that_does_not_exist(db_session, tenant_a) -> None:
    """A typo in the UUID must not look like "the PMS had nothing for us"."""
    with pytest.raises(UnknownTenantError):
        await pms_sync.sync_with_session(db_session, uuid.uuid4())


def test_main_reports_an_unknown_tenant_as_a_failure(monkeypatch, capsys) -> None:
    async def _fake_run(tenant_id, *, window_days, provider=pms_sync.MOCK_PROVIDER):
        raise UnknownTenantError(f"No tenant with id {tenant_id}")

    monkeypatch.setattr(pms_sync, "run", _fake_run)

    assert pms_sync.main([str(uuid.uuid4())]) == 2
    assert "No tenant with id" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_a_provider_that_could_not_be_synced_exits_three_not_zero(
    db_session, tenant_a, property_a
) -> None:
    """R2.4 / design D9, and the regression the QA panel of sections 6-8 caught.

    Isolating a provider failure — so one bad provider does not cost a tenant the others — had
    the side effect that `PmsUnavailableError` stopped reaching `main`, so the command exited
    **0** with "created 0": indistinguishable from a PMS that had nothing, which is precisely
    what D9 forbids. Isolation and a loud exit are not in conflict; `provider_failures` is the
    channel that keeps both.
    """
    from app.integrations.domain.enums import PMSProvider
    from app.integrations.cli import pms_sync as cli
    from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository

    await SqlAlchemyPropertyRepository(db_session).set_pms_provider(
        tenant_a.id, property_a.id, PMSProvider.BEDS24
    )
    await db_session.flush()

    report = await cli.sync_with_session(db_session, tenant_a.id)

    assert report.provider_failures == ["BEDS24"], "the run must record which provider failed"
    assert report.created == 0


def test_main_returns_three_when_a_provider_failed(monkeypatch, capsys) -> None:
    """The EXIT CODE itself, which the test above does not check despite its name.

    The QA panel of the feature-scale review caught that: the sibling asserts
    `provider_failures` on the report and stops, so reverting `main`'s two-line mapping to
    `return 0` would leave it green — and that mapping is the entire contract D9 cares about,
    because a cron job reads the code and not the report. Fifth time in this change that a test
    of mine claimed more than its body proved, so this one drives `main` and asserts the number.
    """
    from app.integrations.application.ingest import IngestReport
    from app.integrations.cli import pms_sync as cli

    async def _fake_run(tenant_id, *, window_days, provider):
        return IngestReport(provider_failures=["BEDS24"])

    monkeypatch.setattr(cli, "run", _fake_run)

    code = cli.main([str(uuid.uuid4())])

    assert code == 3, "a provider that could not be synced is not an empty sync"
    assert "BEDS24" in capsys.readouterr().err


def test_main_returns_zero_when_every_provider_answered(monkeypatch, capsys) -> None:
    """The other half, so the assertion above cannot pass by always returning 3."""
    from app.integrations.application.ingest import IngestReport
    from app.integrations.cli import pms_sync as cli

    async def _fake_run(tenant_id, *, window_days, provider):
        return IngestReport(created=1)

    monkeypatch.setattr(cli, "run", _fake_run)

    assert cli.main([str(uuid.uuid4())]) == 0


# --- The property transition the manual sync now triggers (`pms-ingest-change-events` R3.3) --
#
# `sync_with_session` is thin: whether a cancellation frees a flat is `AdvancePropertyStates
# UseCase`'s own subject (`tests/properties/`) and the sync route's half of the wiring is
# already `test_sync.py`'s subject. What is only true HERE is that the manual CLI's own
# composition root (`sync_with_session`) supplies that collaborator too — before this change it
# did not, so an operator running the command by hand could learn a booking was cancelled and
# still leave the flat waiting for a guest who was never coming.

CLI_CANCEL_EXTERNAL_ID = "CLI-SYNC-CANCEL-1"
CLI_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _cli_stay(status: str) -> ReservationDTO:
    """A stay checking in the day after `CLI_NOW`, so it is still *before* check-in."""
    return ReservationDTO(
        external_id=CLI_CANCEL_EXTERNAL_ID,
        channel="AIRBNB",
        property_external_id=SEED_PROPERTY_CODE,
        check_in_date=date(2026, 8, 2),
        check_out_date=date(2026, 8, 5),
        check_in_time=time(15, 0),
        check_out_time=time(11, 0),
        guest_name="Ada Lovelace",
        adults=2,
        status=status,
    )


class _CliFeedAdapter:
    """A provider answering the manual sync with exactly the row the test names."""

    def __init__(self, *rows: ReservationDTO) -> None:
        self._rows = list(rows)

    async def list_reservations(self, since, property_external_id=None) -> PmsFetchResult:
        return PmsFetchResult(reservations=list(self._rows), failures=[])

    async def get_reservation(self, external_id):
        return None


class _CliFeedFactory:
    """Stands in for `SqlAlchemyPMSAdapterFactory`, structurally (the port is a Protocol).

    Only the factory is replaced. Everything `sync_with_session` wires below it — the
    repositories, the two units of work, the advancer — stays real, which is the point: a stub
    of the use case itself would pass whether or not the collaborator was supplied.
    """

    def __init__(self, adapter: _CliFeedAdapter) -> None:
        self._adapter = adapter

    def supports_messaging(self, provider) -> bool:
        return False

    def provider_for(self, property):
        return PMSProvider.MOCK

    async def reservations_for(self, property, *, read_log=None):
        return self._adapter

    async def messaging_for(self, property):
        raise AssertionError("the manual sync must never resolve messaging")


def _feed_cli(monkeypatch, status: str) -> None:
    monkeypatch.setattr(
        pms_sync,
        "SqlAlchemyPMSAdapterFactory",
        lambda **kwargs: _CliFeedFactory(_CliFeedAdapter(_cli_stay(status))),
    )


@pytest.mark.asyncio
async def test_a_cancellation_the_manual_sync_discovers_frees_the_property(
    db_session, monkeypatch, tenant_a, property_a
) -> None:
    """R3.3 through `sync_with_session`'s own composition root.

    Two runs: the first creates the booking and must move nothing, the second reports it
    CANCELLED. The flat lands in `VACANT_READY` with exactly one `PropertyStateTransition`
    row — and it can only get there through the `advance=` this command now passes.
    """
    property_a.current_operational_state = PropertyOperationalState.AWAITING_CHECKIN
    await db_session.flush()

    _feed_cli(monkeypatch, "CONFIRMED")
    created = await pms_sync.sync_with_session(db_session, tenant_a.id, now=CLI_NOW)
    assert created.created == 1
    await db_session.refresh(property_a)
    assert property_a.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN

    _feed_cli(monkeypatch, "CANCELLED")
    outcome = await pms_sync.sync_with_session(db_session, tenant_a.id, now=CLI_NOW)

    assert outcome.updated == 1
    await db_session.refresh(property_a)
    assert property_a.current_operational_state is PropertyOperationalState.VACANT_READY
    transitions = (
        await db_session.execute(
            select(PropertyStateTransitionModel).where(
                PropertyStateTransitionModel.property_id == property_a.id
            )
        )
    ).scalars().all()
    assert len(transitions) == 1
    assert transitions[0].to_state is PropertyOperationalState.VACANT_READY
    reservation = await db_session.scalar(
        select(ReservationModel).where(
            ReservationModel.external_pms_id == CLI_CANCEL_EXTERNAL_ID
        )
    )
    assert reservation.status is ReservationStatus.CANCELLED

