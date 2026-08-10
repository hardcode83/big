"""A webhook that changes a property's state, end to end (R5.6, R5.7, R6.1, D12, D13).

Nothing is faked below the provider. The transition is performed by the real
`AdvancePropertyStatesUseCase` — D12's whole point is that this change invokes it **unmodified**
and becomes the first production caller of `RESERVATION_CANCELLED_BEFORE_CHECKIN` — so what
these tests read back is what Postgres actually holds after a notice has been processed.

The chain they assert is the one R5.6 describes and D12 defends: a row in `webhook_events`, then
the ingest's own `TimelineEvent` with actor `WEBHOOK` carrying the CAUSE, then the transition
with actor `SYSTEM` carrying the ACT. No `WEBHOOK` actor ever reaches
`property_state_transitions`, which is what keeps the clause of rule 9 that names it from being
activated at all.
"""

import uuid
from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.models import AuditLogModel
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.use_cases import (
    WEBHOOK_SOURCE,
    SyncReservationsFromPmsUseCase,
)
from app.integrations.application.webhooks import ProcessTenantWebhookEventsUseCase
from app.integrations.domain.dtos import PmsFetchResult, ReservationDTO
from app.integrations.domain.entities import QueuedWebhookEvent
from app.integrations.domain.enums import PMSProvider
from app.integrations.infrastructure.models import WebhookEventModel
from app.integrations.infrastructure.repositories import SqlAlchemyWebhookEventRepository
from app.properties.application.use_cases import AdvancePropertyStatesUseCase
from app.properties.domain.enums import (
    PropertyOperationalState,
    StateTransitionTriggeredBy,
)
from app.properties.infrastructure.models import PropertyModel, PropertyStateTransitionModel
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
EXTERNAL_ID = "PMS-CANCELLED-1"
PROPERTY_CODE = "PMS-AWAITING"


class _AdapterReturning:
    """A provider that answers the re-read with exactly what the test wants it to say."""

    def __init__(self, *rows: ReservationDTO) -> None:
        self._rows = list(rows)
        self.calls = 0

    async def list_reservations(self, since, property_external_id=None):
        self.calls += 1
        return PmsFetchResult(reservations=list(self._rows), failures=[])

    async def get_reservation(self, external_id):
        raise AssertionError("the re-read is a list per destination, not a fetch per notice")


class _Factory:
    def __init__(self, adapter: _AdapterReturning) -> None:
        self._adapter = adapter

    def supports_messaging(self, provider) -> bool:
        return False

    def provider_for(self, property):
        return PMSProvider.MOCK

    async def reservations_for(self, property, *, read_log):
        return self._adapter

    async def messaging_for(self, property):
        raise AssertionError("the webhook job must never resolve messaging")


def _row(status: str) -> ReservationDTO:
    """One reservation as the provider reports it right now.

    `check_in_date` is tomorrow, so "before check-in" is true at `NOW` — which is the machine's
    own precondition for `RESERVATION_CANCELLED_BEFORE_CHECKIN`, not something this test
    arranges around it.
    """
    return ReservationDTO(
        external_id=EXTERNAL_ID,
        channel="AIRBNB",
        property_external_id=PROPERTY_CODE,
        check_in_date=date(2026, 8, 10),
        check_out_date=date(2026, 8, 13),
        check_in_time=time(15, 0),
        check_out_time=time(11, 0),
        guest_name="Ada Lovelace",
        adults=2,
        status=status,
    )


async def _awaiting_checkin_property(session: AsyncSession, tenant_id: uuid.UUID):
    prop = PropertyModel(
        tenant_id=tenant_id,
        name="Redes 11",
        internal_code="REDES11",
        pms_external_id=PROPERTY_CODE,
        timezone="Europe/Madrid",
        current_operational_state=PropertyOperationalState.AWAITING_CHECKIN,
    )
    session.add(prop)
    await session.flush()
    return prop


async def _notice(session: AsyncSession, tenant_id: uuid.UUID) -> QueuedWebhookEvent:
    event = WebhookEventModel(
        tenant_id=tenant_id,
        provider="MOCK",
        event_type="booking.cancelled",
        # Deliberately a lie. D13: the body says *look*, never *what* — so a notice claiming
        # the booking is CONFIRMED must not stop the cancellation the re-read reports.
        payload={"status": "CONFIRMED", "reservation_id": EXTERNAL_ID},
        received_at=NOW,
    )
    session.add(event)
    await session.flush()
    return QueuedWebhookEvent(
        id=event.id,
        tenant_id=tenant_id,
        provider="MOCK",
        received_at=NOW,
        attempts=0,
    )


def _use_case(
    db_session: AsyncSession, adapter: _AdapterReturning
) -> ProcessTenantWebhookEventsUseCase:
    return ProcessTenantWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(db_session),
        sync=SyncReservationsFromPmsUseCase(
            factory=_Factory(adapter),
            reservations=SqlAlchemyReservationRepository(db_session),
            properties=SqlAlchemyPropertyRepository(db_session),
            guests=SqlAlchemyGuestRepository(db_session),
            timeline=SqlAlchemyTimelineEventRepository(db_session),
            uow=SqlAlchemyUnitOfWork(db_session),
            audit=SqlAlchemyAuditLogRepository(db_session),
        ),
        advance=AdvancePropertyStatesUseCase(
            properties=SqlAlchemyPropertyRepository(db_session),
            reservations=SqlAlchemyReservationRepository(db_session),
            transitions=SqlAlchemyPropertyStateTransitionRepository(db_session),
            timeline=SqlAlchemyTimelineEventRepository(db_session),
            configs=SqlAlchemyTenantConfigRepository(db_session),
            uow=SqlAlchemyUnitOfWork(db_session),
        ),
        uow=SqlAlchemyUnitOfWork(db_session),
    )


@pytest.mark.asyncio
async def test_a_cancellation_notice_moves_the_property_and_records_both_writes(
    db_session: AsyncSession, tenant_a
) -> None:
    """R5.6: the transition persists its `PropertyStateTransition` AND its `TimelineEvent`.

    Both, in the same transaction, because they come out of `PropertyStateMachine.evaluate`
    together and the use case that owns it writes them together — which is exactly why D12
    invokes that use case instead of transitioning from `integrations`.
    """
    prop = await _awaiting_checkin_property(db_session, tenant_a.id)
    notice = await _notice(db_session, tenant_a.id)
    adapter = _AdapterReturning(_row("CANCELLED"))

    await _use_case(db_session, adapter).execute(
        tenant_id=tenant_a.id, events=[notice], now=NOW
    )

    await db_session.refresh(prop)
    assert prop.current_operational_state is PropertyOperationalState.VACANT_READY
    transitions = (
        await db_session.execute(
            select(PropertyStateTransitionModel).where(
                PropertyStateTransitionModel.property_id == prop.id
            )
        )
    ).scalars().all()
    assert len(transitions) == 1
    # Actor `SYSTEM`, not `WEBHOOK` (D12). The actor of a transition is who PERFORMS it, not
    # who changed the datum it is deduced from — and rule 9 exempts exactly this actor from an
    # `AuditLog` row, which the assertion further down relies on.
    assert transitions[0].triggered_by is StateTransitionTriggeredBy.SYSTEM
    assert transitions[0].to_state is PropertyOperationalState.VACANT_READY
    transition_events = (
        await db_session.execute(
            select(TimelineEventModel).where(
                TimelineEventModel.event_type == TimelineEventType.PROPERTY_STATE_CHANGED
            )
        )
    ).scalars().all()
    assert len(transition_events) == 1


@pytest.mark.asyncio
async def test_the_causal_chain_is_readable_end_to_end(
    db_session: AsyncSession, tenant_a
) -> None:
    """R5.6's "registrar la causa un paso antes": notice → ingest event → transition.

    A person asking *why did this home free up* follows three rows, and every hop is a real
    foreign key or a real actor rather than a coincidence of timestamps.
    """
    prop = await _awaiting_checkin_property(db_session, tenant_a.id)
    notice = await _notice(db_session, tenant_a.id)

    await _use_case(db_session, _AdapterReturning(_row("CANCELLED"))).execute(
        tenant_id=tenant_a.id, events=[notice], now=NOW
    )

    queued = await db_session.get(WebhookEventModel, notice.id)
    await db_session.refresh(queued)
    assert queued.processed is True

    reservation = await db_session.scalar(
        select(ReservationModel).where(ReservationModel.external_pms_id == EXTERNAL_ID)
    )
    assert reservation is not None

    ingest_event = await db_session.scalar(
        select(TimelineEventModel).where(
            TimelineEventModel.event_type == TimelineEventType.RESERVATION_IMPORTED
        )
    )
    assert ingest_event.actor_type is TimelineActorType.WEBHOOK
    assert ingest_event.metadata_["source"] == WEBHOOK_SOURCE
    assert ingest_event.reservation_id == reservation.id

    transition_event = await db_session.scalar(
        select(TimelineEventModel).where(
            TimelineEventModel.event_type == TimelineEventType.PROPERTY_STATE_CHANGED
        )
    )
    assert transition_event.actor_type is TimelineActorType.SYSTEM
    assert transition_event.property_id == prop.id


@pytest.mark.asyncio
async def test_the_transition_writes_no_audit_row(
    db_session: AsyncSession, tenant_a
) -> None:
    """The first named exception of rule 9, still standing after this change.

    It is exempt because the actor is `SYSTEM`; the clause immediately after it says a `WEBHOOK`
    actor would NOT be exempt. D12 keeps that clause dormant by never producing one, and this
    is the assertion that would break the day something started to.
    """
    await _awaiting_checkin_property(db_session, tenant_a.id)
    notice = await _notice(db_session, tenant_a.id)

    await _use_case(db_session, _AdapterReturning(_row("CANCELLED"))).execute(
        tenant_id=tenant_a.id, events=[notice], now=NOW
    )

    rows = (await db_session.execute(select(AuditLogModel))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_the_body_does_not_decide_anything(
    db_session: AsyncSession, tenant_a
) -> None:
    """D13 and R6.1, stated as a contrast.

    The notice's body claims `CONFIRMED` in both runs. What differs is only what the provider
    answers when re-read, and that is what the property's state follows.
    """
    prop = await _awaiting_checkin_property(db_session, tenant_a.id)
    notice = await _notice(db_session, tenant_a.id)

    await _use_case(db_session, _AdapterReturning(_row("CONFIRMED"))).execute(
        tenant_id=tenant_a.id, events=[notice], now=NOW
    )

    await db_session.refresh(prop)
    assert prop.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN


# --- Out of order (R5.7, D13) ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_notices_processed_in_reverse_order_reach_the_same_state(
    db_session: AsyncSession, tenant_a
) -> None:
    """R5.7: ADR 0006 records that providers deliver notices out of order, so arrival order
    must not be read as the order of events.

    Nothing in the implementation sorts or sequences: what makes this hold is that the body is
    never applied (D13) and the re-read always answers with the CURRENT state, so the second
    processing of an object writes what the first one would have. The idempotency of
    `(tenant_id, external_pms_id)` is what turns "writes the same thing" into "creates nothing
    twice", which is the second assertion below.
    """
    prop = await _awaiting_checkin_property(db_session, tenant_a.id)
    older = await _notice(db_session, tenant_a.id)
    newer = await _notice(db_session, tenant_a.id)
    # The provider's answer is the current truth on both passes — that is what a re-read IS.
    adapter = _AdapterReturning(_row("CANCELLED"))

    # Reverse order on purpose: the notice that arrived second is handled first.
    await _use_case(db_session, adapter).execute(
        tenant_id=tenant_a.id, events=[newer], now=NOW
    )
    await db_session.refresh(prop)
    after_first = prop.current_operational_state

    await _use_case(db_session, adapter).execute(
        tenant_id=tenant_a.id, events=[older], now=NOW
    )
    await db_session.refresh(prop)

    assert after_first is PropertyOperationalState.VACANT_READY
    assert prop.current_operational_state is PropertyOperationalState.VACANT_READY
    reservations = (
        await db_session.execute(
            select(ReservationModel.id).where(
                ReservationModel.external_pms_id == EXTERNAL_ID
            )
        )
    ).scalars().all()
    assert len(reservations) == 1, "the re-read must upsert, never duplicate"
    transitions = (
        await db_session.execute(
            select(PropertyStateTransitionModel.id).where(
                PropertyStateTransitionModel.property_id == prop.id
            )
        )
    ).scalars().all()
    assert len(transitions) == 1, "the second pass had nothing left to transition"
