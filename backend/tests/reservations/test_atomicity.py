"""R2.6 against a real Postgres: the reservation and its event are one transaction.

This one cannot be done with fakes. What is being proved is that nothing reaches the
database when the second write of the operation fails — and "nothing reaches the database"
is a property of the transaction, not of the orchestration. The use-case level version of
this check (no `commit()` call) lives in `test_use_cases.py`; this is the half that would
catch a repository that committed on its own.
"""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.application.resolution import ManualGuestIdentityInput
from app.guests.infrastructure.models import GuestModel
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.guests.infrastructure.postgres_guest_email_exclusion import PostgresGuestEmailExclusion
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.application.use_cases import (
    CancelReservationUseCase,
    CreateReservationCommand,
    CreateReservationUseCase,
    UpdateReservationUseCase,
)
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.models import TenantModel
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


class _ExplodingTimelineRepository(SqlAlchemyTimelineEventRepository):
    """The real adapter, made to fail exactly where the second write happens."""

    async def add(self, tenant_id, event) -> None:  # noqa: ANN001
        raise RuntimeError("timeline storage is unavailable")


class _ExplodingReservationRepository(SqlAlchemyReservationRepository):
    async def add(self, tenant_id, reservation) -> None:  # noqa: ANN001
        raise RuntimeError("reservation storage is unavailable")


class _ExplodingCommitUnitOfWork(SqlAlchemyUnitOfWork):
    async def commit(self) -> None:
        # Flush first so this exercises rollback after all three rows reached the database
        # transaction, rather than only testing that pending ORM objects are discarded.
        await self._session.flush()
        raise RuntimeError("commit is unavailable")


async def _tenant_property_and_user(db_session) -> tuple[TenantModel, PropertyModel, UserModel]:
    """A REAL user, not a random UUID.

    `timeline_events.actor_user_id` is a foreign key to `users`, so the actor of a `USER`
    event has to exist — a detail the fake-based tests cannot show and this one must respect
    to be testing the transaction rather than a constraint violation.
    """
    tenant = TenantModel(name="TenantA", billing_email="a@example.com")
    db_session.add(tenant)
    await db_session.flush()
    prop = PropertyModel(tenant_id=tenant.id, name="Redes 11", internal_code="REDES11")
    db_session.add(prop)
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Manager",
        email=f"manager-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role=UserRole.PROPERTY_MANAGER,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return tenant, prop, user


def _command(prop: PropertyModel) -> CreateReservationCommand:
    return CreateReservationCommand(
        property_id=prop.id,
        channel=ReservationChannel.DIRECT,
        check_in_date=date(2026, 8, 1),
        check_out_date=date(2026, 8, 4),
        adults=2,
    )


@pytest.mark.parametrize("failure_stage", ["reservation", "timeline", "commit"])
@pytest.mark.asyncio
async def test_a_failure_during_creation_rolls_back_guest_reservation_and_timeline(
    db_session, failure_stage
) -> None:
    tenant, prop, user = await _tenant_property_and_user(db_session)
    repositories = {
        "reservation": _ExplodingReservationRepository(db_session),
        "timeline": _ExplodingTimelineRepository(db_session),
        "commit": SqlAlchemyReservationRepository(db_session),
    }
    timeline = (
        SqlAlchemyTimelineEventRepository(db_session)
        if failure_stage == "commit"
        else _ExplodingTimelineRepository(db_session)
    )
    uow = (
        _ExplodingCommitUnitOfWork(db_session)
        if failure_stage == "commit"
        else SqlAlchemyUnitOfWork(db_session)
    )
    use_case = CreateReservationUseCase(
        reservations=repositories[failure_stage],
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=timeline,
        uow=uow,
        guest_email_exclusion=PostgresGuestEmailExclusion(db_session),
    )

    with pytest.raises(RuntimeError):
        await use_case.execute(
            tenant_id=tenant.id,
            actor_user_id=user.id,
            command=replace(
                _command(prop),
                guest=ManualGuestIdentityInput(
                    full_name="New Guest", email="new-guest@example.com"
                ),
            ),
            now=NOW,
        )

    # What `get_db_session` does when a request ends in an exception.
    await db_session.rollback()

    guests = await db_session.scalar(select(func.count()).select_from(GuestModel))
    reservations = await db_session.scalar(select(func.count()).select_from(ReservationModel))
    events = await db_session.scalar(select(func.count()).select_from(TimelineEventModel))
    assert guests == 0
    assert reservations == 0
    assert events == 0


@pytest.mark.asyncio
async def test_the_successful_path_persists_both_rows_together(db_session) -> None:
    """The mirror image: without it, the test above would also pass on a use case that
    never writes anything at all."""
    tenant, prop, user = await _tenant_property_and_user(db_session)
    use_case = CreateReservationUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        guest_email_exclusion=PostgresGuestEmailExclusion(db_session),
    )

    reservation = await use_case.execute(
        tenant_id=tenant.id,
        actor_user_id=user.id,
        command=_command(prop),
        now=NOW,
    )

    stored = await db_session.scalar(
        select(ReservationModel).where(ReservationModel.id == reservation.id)
    )
    event = await db_session.scalar(
        select(TimelineEventModel).where(TimelineEventModel.reservation_id == reservation.id)
    )
    assert stored is not None
    assert event is not None
    # Both rows carry the same instant: the one the use case decided on.
    assert event.created_at == NOW
    assert stored.nights == 3


@pytest.mark.asyncio
async def test_a_failing_timeline_write_rolls_back_an_update_too(db_session) -> None:
    """The other two mutating paths share the pattern, so they share the guarantee (R2.6).

    Covered explicitly rather than by inspection: `save` already wrote to the session by the
    time the event fails, so this is where a stray commit inside a repository would show.
    """
    tenant, prop, user = await _tenant_property_and_user(db_session)
    reservation = await CreateReservationUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        guest_email_exclusion=PostgresGuestEmailExclusion(db_session),
    ).execute(
        tenant_id=tenant.id, actor_user_id=user.id, command=_command(prop), now=NOW
    )
    await db_session.commit()

    update = UpdateReservationUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=_ExplodingTimelineRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )
    with pytest.raises(RuntimeError):
        await update.execute(
            tenant_id=tenant.id,
            actor_user_id=user.id,
            reservation_id=reservation.id,
            changes={"adults": 9},
            now=NOW + timedelta(hours=1),
        )
    await db_session.rollback()

    adults = await db_session.scalar(
        select(ReservationModel.adults).where(ReservationModel.id == reservation.id)
    )
    assert adults == 2


@pytest.mark.asyncio
async def test_a_failing_timeline_write_rolls_back_a_cancellation_too(db_session) -> None:
    tenant, prop, user = await _tenant_property_and_user(db_session)
    reservation = await CreateReservationUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        guest_email_exclusion=PostgresGuestEmailExclusion(db_session),
    ).execute(
        tenant_id=tenant.id, actor_user_id=user.id, command=_command(prop), now=NOW
    )
    await db_session.commit()

    cancel = CancelReservationUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        timeline=_ExplodingTimelineRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )
    with pytest.raises(RuntimeError):
        await cancel.execute(
            tenant_id=tenant.id,
            actor_user_id=user.id,
            reservation_id=reservation.id,
            now=NOW + timedelta(days=1),
        )
    await db_session.rollback()

    status = await db_session.scalar(
        select(ReservationModel.status).where(ReservationModel.id == reservation.id)
    )
    assert status is not ReservationStatus.CANCELLED


@pytest.mark.asyncio
async def test_an_unstorable_metadata_value_also_leaves_nothing_behind(db_session) -> None:
    """The failure mode QA found on section 1, now checked end to end.

    A `date` left unconverted in `metadata` fails the event write, and the reservation must
    not survive it either.
    """

    class _RawDateTimeline(SqlAlchemyTimelineEventRepository):
        async def add(self, tenant_id, event) -> None:  # noqa: ANN001
            event.metadata = {"check_in_date": date(2026, 8, 1)}
            await super().add(tenant_id, event)

    tenant, prop, user = await _tenant_property_and_user(db_session)
    use_case = CreateReservationUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=_RawDateTimeline(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        guest_email_exclusion=PostgresGuestEmailExclusion(db_session),
    )

    with pytest.raises(Exception) as raised:
        await use_case.execute(
            tenant_id=tenant.id,
            actor_user_id=user.id,
            command=_command(prop),
            now=NOW + timedelta(minutes=1),
        )
    assert "check_in_date" in str(raised.value)

    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(ReservationModel)) == 0
