"""R3.6 against a real database: the three writes of a transition are one transaction.

The unit tests of `test_advance_states.py` prove the orchestration with fakes; this proves
the part fakes cannot — that a failure halfway leaves Postgres with nothing, not with a
property in a state whose transition row was never written.
"""

import uuid
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.properties.application.use_cases import AdvancePropertyStatesUseCase
from app.properties.domain.enums import PropertyOperationalState
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.infrastructure.models import PropertyModel, PropertyStateTransitionModel
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.models import TenantModel
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.domain.exceptions import TimelineMetadataNotSerialisableError
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

MADRID = ZoneInfo("Europe/Madrid")
CREATED = datetime(2026, 8, 1, tzinfo=UTC)


class ExplodingTimelineRepository:
    """Fails exactly where R3.6 says the other two writes must not survive."""

    async def add(self, tenant_id, event) -> None:
        raise TimelineMetadataNotSerialisableError("boom")


async def _seed(db_session):
    tenant = TenantModel(name="TenantA", billing_email="a@example.com")
    db_session.add(tenant)
    await db_session.flush()
    prop = PropertyModel(
        tenant_id=tenant.id,
        name="REDES11",
        internal_code="REDES11",
        timezone="Europe/Madrid",
        current_operational_state=PropertyOperationalState.VACANT_READY,
    )
    db_session.add(prop)
    await db_session.flush()
    reservation = Reservation.create(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        channel=ReservationChannel.AIRBNB,
        check_in_date=date(2026, 8, 10),
        check_out_date=date(2026, 8, 13),
        now=CREATED,
        adults=2,
        check_in_time=time(15, 0),
        # Not the default (`PENDING`): the machine's precondition for opening a check-in
        # window is a CONFIRMED reservation.
        status=ReservationStatus.CONFIRMED,
    )
    await SqlAlchemyReservationRepository(db_session).add(tenant.id, reservation)
    return tenant, prop, reservation


def _use_case(db_session, *, timeline=None):
    return AdvancePropertyStatesUseCase(
        properties=SqlAlchemyPropertyRepository(db_session),
        reservations=SqlAlchemyReservationRepository(db_session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(db_session),
        timeline=timeline or SqlAlchemyTimelineEventRepository(db_session),
        configs=SqlAlchemyTenantConfigRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )


@pytest.mark.asyncio
async def test_a_transition_persists_all_three_writes_correlated(db_session) -> None:
    tenant, prop, reservation = await _seed(db_session)

    report = await _use_case(db_session).execute(
        tenant_id=tenant.id,
        trigger=PropertyStateTrigger.CHECKIN_WINDOW_OPENED,
        now=datetime(2026, 8, 10, 14, 0, tzinfo=MADRID),
    )

    assert report.transitioned == 1

    stored_property = (
        await db_session.execute(select(PropertyModel).where(PropertyModel.id == prop.id))
    ).scalar_one()
    transition = (
        await db_session.execute(
            select(PropertyStateTransitionModel).where(
                PropertyStateTransitionModel.property_id == prop.id
            )
        )
    ).scalar_one()
    event = (
        await db_session.execute(
            select(TimelineEventModel).where(TimelineEventModel.property_id == prop.id)
        )
    ).scalar_one()

    assert stored_property.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN
    assert transition.from_state is PropertyOperationalState.VACANT_READY
    assert transition.to_state is PropertyOperationalState.AWAITING_CHECKIN
    assert event.reservation_id == reservation.id
    assert transition.metadata_["correlation_id"] == event.metadata_["correlation_id"]


@pytest.mark.asyncio
async def test_a_failed_event_write_leaves_no_trace_of_the_other_two(db_session) -> None:
    tenant, prop, _ = await _seed(db_session)
    # Captured before the rollback below: `rollback()` expires every loaded ORM object
    # regardless of `expire_on_commit`, and touching one afterwards would trigger a lazy
    # refresh from a sync context (`MissingGreenlet`) rather than test anything.
    tenant_id, property_id = tenant.id, prop.id
    await db_session.commit()

    with pytest.raises(TimelineMetadataNotSerialisableError):
        await _use_case(db_session, timeline=ExplodingTimelineRepository()).execute(
            tenant_id=tenant_id,
            trigger=PropertyStateTrigger.CHECKIN_WINDOW_OPENED,
            now=datetime(2026, 8, 10, 14, 0, tzinfo=MADRID),
        )

    # What the scheduler's runner does for a failing tenant (design D12).
    await db_session.rollback()

    stored_property = (
        await db_session.execute(select(PropertyModel).where(PropertyModel.id == property_id))
    ).scalar_one()
    transitions = await db_session.scalar(
        select(func.count()).select_from(PropertyStateTransitionModel)
    )
    events = await db_session.scalar(select(func.count()).select_from(TimelineEventModel))

    assert stored_property.current_operational_state is PropertyOperationalState.VACANT_READY
    assert transitions == 0
    assert events == 0
