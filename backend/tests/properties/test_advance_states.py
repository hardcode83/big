"""`AdvancePropertyStatesUseCase` — the three clock triggers (`celery-jobs` R3, R4).

Unit tests with in-memory fakes, as `steering/backend-architecture.md` asks for the
application layer: no database, no Celery, no clock of their own — `now` is a parameter,
which is also what `timeline-state-machine` demands of the domain underneath.

Zone throughout is `Europe/Madrid`, the tenant's own (PRD §1), so every "local" assertion
means something.
"""

import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.properties.application.use_cases import AdvancePropertyStatesUseCase
from app.properties.domain.entities import Property, PropertyStateTransition
from app.properties.domain.enums import (
    PropertyOperationalState,
    StateTransitionTriggeredBy,
)
from app.properties.domain.exceptions import (
    InvalidTransitionInputError,
    TransitionEvidenceError,
)
from app.properties.domain.state_machine import PropertyStateMachine
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.timeline.domain.enums import TimelineEventType
from tests.properties.doubles import (
    FakePropertyRepository,
    FakePropertyStateTransitionRepository,
    FakeReservationRepository,
    FakeTenantConfigRepository,
    FakeTimelineEventRepository,
    FakeUnitOfWork,
)

MADRID = ZoneInfo("Europe/Madrid")
TENANT = uuid.uuid4()
CREATED = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def _local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=MADRID)


def _property(
    *,
    state: PropertyOperationalState,
    tenant_id: uuid.UUID = TENANT,
    timezone: str = "Europe/Madrid",
) -> Property:
    return Property(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="REDES11",
        internal_code="REDES11",
        created_at=CREATED,
        updated_at=CREATED,
        timezone=timezone,
        current_operational_state=state,
    )


def _reservation(
    prop: Property,
    *,
    check_in: date,
    nights: int = 3,
    check_in_time: time | None = None,
    check_out_time: time | None = None,
    status: ReservationStatus = ReservationStatus.CONFIRMED,
) -> Reservation:
    return Reservation.create(
        id=uuid.uuid4(),
        tenant_id=prop.tenant_id,
        property_id=prop.id,
        channel=ReservationChannel.AIRBNB,
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=nights),
        now=CREATED,
        adults=2,
        check_in_time=check_in_time,
        check_out_time=check_out_time,
        status=status,
    )


class Harness:
    """The use case wired to fakes, plus the handles a test needs to assert on."""

    def __init__(self) -> None:
        self.properties = FakePropertyRepository()
        self.reservations = FakeReservationRepository()
        self.transitions = FakePropertyStateTransitionRepository()
        self.timeline = FakeTimelineEventRepository()
        self.configs = FakeTenantConfigRepository()
        self.uow = FakeUnitOfWork()

    def with_property(self, prop: Property) -> Property:
        self.properties.add_property(prop)
        return prop

    def with_reservation(self, reservation: Reservation) -> Reservation:
        self.reservations.reservations[reservation.id] = reservation
        return reservation

    @property
    def use_case(self) -> AdvancePropertyStatesUseCase:
        return AdvancePropertyStatesUseCase(
            properties=self.properties,
            reservations=self.reservations,
            transitions=self.transitions,
            timeline=self.timeline,
            configs=self.configs,
            uow=self.uow,
        )

    async def run(self, trigger: PropertyStateTrigger, now: datetime, tenant_id=TENANT):
        return await self.use_case.execute(tenant_id=tenant_id, trigger=trigger, now=now)


class TestCheckinWindow:
    @pytest.mark.asyncio
    async def test_it_opens_the_window_two_hours_before_check_in(self) -> None:
        harness = Harness()
        prop = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 13, 0)
        )

        assert report.transitioned == 1
        assert prop.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN

    @pytest.mark.asyncio
    async def test_one_minute_before_the_window_it_does_nothing(self) -> None:
        harness = Harness()
        prop = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 12, 59)
        )

        assert report.transitioned == 0
        assert report.not_eligible == 1
        assert prop.current_operational_state is PropertyOperationalState.VACANT_READY

    @pytest.mark.asyncio
    async def test_a_wide_window_does_not_reach_into_the_previous_day(self) -> None:
        """The clamp of design D7.

        Check-in at 01:00 with a 6-hour window would otherwise be "due" at 19:00 the day
        before — an instant the machine rejects, because its precondition is that the stay
        starts *today*. Without the clamp the job would ask and be refused every five
        minutes for six hours.
        """
        harness = Harness()
        harness.configs.set_checkin_window_hours(TENANT, 6)
        prop = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(1, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 9, 20, 0)
        )

        assert report.transitioned == 0
        assert report.not_eligible == 1

        # ...and on the day itself it fires immediately, because the window already opened.
        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 0, 5)
        )
        assert report.transitioned == 1

    @pytest.mark.asyncio
    async def test_it_also_fires_from_ready_for_next_guest(self) -> None:
        """Both source states of the policy, derived not hand-listed."""
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.READY_FOR_NEXT_GUEST)
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 14, 0)
        )

        assert report.transitioned == 1

    @pytest.mark.asyncio
    async def test_a_cancelled_reservation_never_opens_the_window(self) -> None:
        harness = Harness()
        prop = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(
                prop,
                check_in=date(2026, 8, 10),
                check_in_time=time(15, 0),
                status=ReservationStatus.CANCELLED,
            )
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 14, 0)
        )

        assert report.transitioned == 0
        assert report.not_eligible == 1

    @pytest.mark.asyncio
    async def test_without_a_check_in_time_the_property_default_applies(self) -> None:
        harness = Harness()
        prop = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        # No `check_in_time` on the reservation: `Property.default_check_in_time` is 15:00.
        harness.with_reservation(_reservation(prop, check_in=date(2026, 8, 10)))

        assert (
            await harness.run(
                PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 12, 59)
            )
        ).transitioned == 0
        assert (
            await harness.run(
                PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 13, 0)
            )
        ).transitioned == 1


class TestCheckinTimeReached:
    @pytest.mark.asyncio
    async def test_it_marks_occupied_at_the_check_in_hour(self) -> None:
        harness = Harness()
        prop = harness.with_property(_property(state=PropertyOperationalState.AWAITING_CHECKIN))
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 10, 15, 0)
        )

        assert report.transitioned == 1
        assert prop.current_operational_state is PropertyOperationalState.OCCUPIED_ESTIMATED

    @pytest.mark.asyncio
    async def test_a_minute_early_is_not_yet(self) -> None:
        harness = Harness()
        prop = harness.with_property(_property(state=PropertyOperationalState.AWAITING_CHECKIN))
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 10, 14, 59)
        )

        assert report.not_eligible == 1
        assert prop.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN


class TestCheckoutTimeReached:
    @pytest.mark.asyncio
    async def test_it_awaits_cleaning_at_the_checkout_hour(self) -> None:
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.OCCUPIED_ESTIMATED)
        )
        harness.with_reservation(
            _reservation(
                prop, check_in=date(2026, 8, 8), nights=2, check_out_time=time(11, 0)
            )
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKOUT_TIME_REACHED, _local(2026, 8, 10, 11, 0)
        )

        assert report.transitioned == 1
        assert prop.current_operational_state is PropertyOperationalState.AWAITING_CLEANING

    @pytest.mark.asyncio
    async def test_without_a_check_out_time_the_property_default_applies(self) -> None:
        """R3.8 for the checkout side.

        The property default is 11:00, so this test deliberately uses a NON-default
        explicit value in its sibling tests and none here: if the fallback broke, the two
        would stop disagreeing and only this one would notice.
        """
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.OCCUPIED_ESTIMATED)
        )
        harness.with_reservation(_reservation(prop, check_in=date(2026, 8, 8), nights=2))

        assert (
            await harness.run(
                PropertyStateTrigger.CHECKOUT_TIME_REACHED, _local(2026, 8, 10, 10, 59)
            )
        ).transitioned == 0
        assert (
            await harness.run(
                PropertyStateTrigger.CHECKOUT_TIME_REACHED, _local(2026, 8, 10, 11, 0)
            )
        ).transitioned == 1

    @pytest.mark.asyncio
    async def test_a_checkout_missed_while_the_worker_was_down_is_still_caught(self) -> None:
        """The silent miss the symmetric ±2-day window used to cause.

        `CHECKOUT_TIME_REACHED` has no day clamp, so a checkout stays due indefinitely. With
        a two-day lookbehind, an outage longer than that left the property in
        `OCCUPIED_ESTIMATED` for ever while the report said `not_eligible` — indistinguishable
        from "nothing to do". Found by the QA panel of section 3.
        """
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.OCCUPIED_ESTIMATED)
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 1), nights=2, check_out_time=time(11, 0))
        )

        # Ten days after the checkout: far outside the old window, inside the catch-up one.
        report = await harness.run(
            PropertyStateTrigger.CHECKOUT_TIME_REACHED, _local(2026, 8, 13, 9, 0)
        )

        assert report.transitioned == 1
        assert prop.current_operational_state is PropertyOperationalState.AWAITING_CLEANING

    @pytest.mark.asyncio
    async def test_before_checkout_nothing_moves(self) -> None:
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.OCCUPIED_ESTIMATED)
        )
        harness.with_reservation(
            _reservation(
                prop, check_in=date(2026, 8, 8), nights=2, check_out_time=time(11, 0)
            )
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKOUT_TIME_REACHED, _local(2026, 8, 10, 10, 30)
        )

        assert report.not_eligible == 1


class TestEvidenceAndPersistence:
    @pytest.mark.asyncio
    async def test_a_transition_writes_all_three_pieces_of_evidence(self) -> None:
        """R3.6, at the unit level: state, transition row and timeline event, correlated."""
        harness = Harness()
        prop = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        reservation = harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )

        await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 14, 0)
        )

        [transition] = harness.transitions.transitions
        [event] = harness.timeline.events
        assert transition.from_state is PropertyOperationalState.VACANT_READY
        assert transition.to_state is PropertyOperationalState.AWAITING_CHECKIN
        assert transition.triggered_by is StateTransitionTriggeredBy.SYSTEM
        assert transition.triggered_by_user_id is None
        assert transition.metadata["trigger"] == "CHECKIN_WINDOW_OPENED"
        assert transition.metadata["reservation_id"] == str(reservation.id)
        assert event.event_type is TimelineEventType.PROPERTY_STATE_CHANGED
        assert event.reservation_id == reservation.id
        # The correlation id is what ties the two rows to one decision.
        assert transition.metadata["correlation_id"] == event.metadata["correlation_id"]
        assert prop.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN

    @pytest.mark.asyncio
    async def test_it_commits_once_per_run_not_once_per_property(self) -> None:
        """Design D12: the tenant is the transaction."""
        harness = Harness()
        for _ in range(3):
            prop = harness.with_property(
                _property(state=PropertyOperationalState.VACANT_READY)
            )
            harness.with_reservation(
                _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
            )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 14, 0)
        )

        assert report.transitioned == 3
        assert harness.uow.commits == 1

    @pytest.mark.asyncio
    async def test_without_candidates_it_does_not_even_commit(self) -> None:
        harness = Harness()
        harness.with_property(_property(state=PropertyOperationalState.CRITICAL_INCIDENT))

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 14, 0)
        )

        assert report.candidates == 0
        assert harness.uow.commits == 0

    @pytest.mark.asyncio
    async def test_a_property_of_another_tenant_is_never_a_candidate(self) -> None:
        other = uuid.uuid4()
        harness = Harness()
        theirs = harness.with_property(
            _property(state=PropertyOperationalState.VACANT_READY, tenant_id=other)
        )
        harness.with_reservation(
            _reservation(theirs, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 14, 0)
        )

        assert report.candidates == 0
        assert harness.transitions.transitions == []
        assert theirs.current_operational_state is PropertyOperationalState.VACANT_READY

    @pytest.mark.asyncio
    async def test_the_transition_is_anchored_to_a_property_of_the_acting_tenant(self) -> None:
        """The port's precondition, pinned where the reference is actually resolved.

        `property_id` can only come from `list_by_state`, which is tenant-scoped, so the
        adapter's inability to verify the foreign key is not reachable from here.
        """
        harness = Harness()
        mine = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(mine, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )
        theirs = harness.with_property(
            _property(state=PropertyOperationalState.VACANT_READY, tenant_id=uuid.uuid4())
        )
        harness.with_reservation(
            _reservation(theirs, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )

        await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 14, 0)
        )

        [transition] = harness.transitions.transitions
        assert transition.property_id == mine.id
        assert transition.tenant_id == TENANT


class TestRejectionsAndFailures:
    @pytest.mark.asyncio
    async def test_a_second_run_writes_nothing(self) -> None:
        """R4.1: idempotence comes from the machine refusing a no-op destination."""
        harness = Harness()
        prop = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )
        now = _local(2026, 8, 10, 14, 0)

        first = await harness.run(PropertyStateTrigger.CHECKIN_WINDOW_OPENED, now)
        second = await harness.run(PropertyStateTrigger.CHECKIN_WINDOW_OPENED, now)

        assert first.transitioned == 1
        # The property left the source states, so it is not even a candidate any more.
        assert second.candidates == 0
        assert len(harness.transitions.transitions) == 1
        assert len(harness.timeline.events) == 1

    @pytest.mark.asyncio
    async def test_two_due_reservations_skip_the_property_instead_of_choosing(self) -> None:
        """Task 3.5: the machine accepts two bookings, so there is no honest source."""
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.OCCUPIED_ESTIMATED)
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 8), nights=2, check_out_time=time(11, 0))
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 9), nights=1, check_out_time=time(10, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKOUT_TIME_REACHED, _local(2026, 8, 10, 12, 0)
        )

        assert report.ambiguous == 1
        assert report.transitioned == 0
        assert harness.transitions.transitions == []

    @pytest.mark.asyncio
    async def test_a_local_time_that_does_not_exist_is_counted_apart(self) -> None:
        """R3.4, spring forward.

        On 2026-03-29 Madrid jumps 02:00 → 03:00, so 02:30 never happens. The domain
        refuses to invent an instant and this counts it as unresolvable, not as "not due":
        it will never become due on its own.
        """
        harness = Harness()
        prop = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 3, 29), check_in_time=time(2, 30))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 3, 29, 10, 0)
        )

        assert report.unresolvable_time == 1
        assert report.not_eligible == 0
        assert report.transitioned == 0

    @pytest.mark.asyncio
    async def test_an_ambiguous_local_time_is_counted_apart_too(self) -> None:
        """R3.4, autumn fold.

        On 2026-10-25 Madrid repeats 02:00 → 03:00. `check_in_time` is a naive `TIME`, so
        there is no `fold` to disambiguate and the domain refuses rather than picking one.
        """
        harness = Harness()
        prop = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 10, 25), check_in_time=time(2, 30))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 10, 25, 10, 0)
        )

        assert report.unresolvable_time == 1
        assert report.transitioned == 0

    @pytest.mark.asyncio
    async def test_one_unresolvable_property_does_not_stop_the_others(self) -> None:
        harness = Harness()
        broken = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(broken, check_in=date(2026, 3, 29), check_in_time=time(2, 30))
        )
        healthy = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(healthy, check_in=date(2026, 3, 29), check_in_time=time(15, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 3, 29, 14, 0)
        )

        assert report.unresolvable_time == 1
        assert report.transitioned == 1
        assert healthy.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN

    @pytest.mark.asyncio
    async def test_a_failed_evidence_write_propagates_instead_of_being_counted(self) -> None:
        """R3.3, the *write* half: a repository that cannot store the transition fails the
        tenant rather than being swallowed into a report bucket."""
        harness = Harness()
        harness.transitions.fail_with = TransitionEvidenceError()
        prop = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )

        with pytest.raises(TransitionEvidenceError):
            await harness.run(
                PropertyStateTrigger.CHECKIN_WINDOW_OPENED, _local(2026, 8, 10, 14, 0)
            )

        assert harness.uow.commits == 0

    @pytest.mark.asyncio
    async def test_a_malformed_request_propagates_from_the_machine(self) -> None:
        """R3.3, the *evaluate* half.

        A naive `now` is the realistic way this use case would build an invalid request,
        and the machine rejects it with `InvalidTransitionInputError`. That is a bug in the
        caller, not a state of the world, so it must not land in `not_eligible`.
        """
        harness = Harness()
        prop = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        )

        with pytest.raises(InvalidTransitionInputError):
            await harness.run(
                PropertyStateTrigger.CHECKIN_WINDOW_OPENED,
                datetime(2026, 8, 10, 14, 0),  # no tzinfo
            )

        assert harness.uow.commits == 0

    def test_already_there_is_unreachable_for_the_clock_triggers(self) -> None:
        """Pins the claim `AdvanceReport` makes about its own `already_there` bucket.

        The machine raises `NoOperationalStateChangeError` only when the destination equals
        the source. For the three clock triggers every policy entry moves the property
        somewhere else, so the bucket cannot be non-zero today — and R4.1's idempotence
        comes from the property leaving the source states instead. If someone adds a
        same-state destination, this fails and the docstring stops being a lie.
        """
        clock_triggers = (
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED,
            PropertyStateTrigger.CHECKIN_TIME_REACHED,
            PropertyStateTrigger.CHECKOUT_TIME_REACHED,
        )
        for (source, trigger), destinations in PropertyStateMachine._POLICY.items():
            if trigger in clock_triggers:
                assert source not in destinations, (source, trigger)


class TestBlockedTransitions:
    """R1: the flat the calendar wants to move and the state will not admit.

    The bug these pin, measured in `dev` on 2026-08-22: REDES11 stalled in
    `CLEANING_IN_PROGRESS` from the 16th while a `CONFIRMED` stay ran from the 19th, and the
    08:18 tick reported `candidates: 0 … not_eligible: 0` for both check-in jobs. The report
    was correct and empty of it — a flat whose state is not a source of the trigger never
    reaches `list_by_state`, so it incremented no bucket at all.
    """

    @pytest.mark.asyncio
    async def test_the_stalled_flat_is_counted_and_is_not_not_eligible(self) -> None:
        """R1.2: `not_eligible` means "the hour has not come", and this hour came days ago."""
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.CLEANING_IN_PROGRESS)
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 19), nights=4, check_in_time=time(15, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 22, 10, 18)
        )

        assert report.blocked == 1
        assert report.not_eligible == 0
        assert report.candidates == 0
        assert report.transitioned == 0

    @pytest.mark.asyncio
    async def test_nothing_is_written_by_the_detection_sweep(self) -> None:
        """It counts and logs; it does not transition. The exit is a human's (R3)."""
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.CLEANING_IN_PROGRESS)
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 19), nights=4, check_in_time=time(15, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 22, 10, 18)
        )

        assert report.blocked == 1
        assert harness.transitions.transitions == []
        assert harness.timeline.events == []
        assert harness.uow.commits == 0
        assert prop.current_operational_state is PropertyOperationalState.CLEANING_IN_PROGRESS

    @pytest.mark.asyncio
    async def test_an_ordinary_candidate_does_not_increment_blocked(self) -> None:
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.AWAITING_CHECKIN)
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 22), check_in_time=time(15, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 22, 16, 0)
        )

        assert report.transitioned == 1
        assert report.blocked == 0

    @pytest.mark.asyncio
    async def test_the_tick_after_a_successful_transition_reports_nothing(self) -> None:
        """The false positive that made `blocked` count the whole active portfolio.

        Tick one moves the flat `AWAITING_CHECKIN` → `OCCUPIED_ESTIMATED`. On tick two that flat
        is no longer in a source state and `is_due` for `CHECKIN_TIME_REACHED` is still true —
        it stays true for the entire stay — so the two-condition definition reported it, and
        every other correctly occupied flat with it, on every tick until checkout. What clears
        it is the transition row tick one wrote (design D1, amended after the section-3 panel).
        """
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.AWAITING_CHECKIN)
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 22), check_in_time=time(15, 0))
        )

        first = await harness.run(
            PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 22, 16, 0)
        )
        assert first.transitioned == 1
        assert prop.current_operational_state is PropertyOperationalState.OCCUPIED_ESTIMATED

        second = await harness.run(
            PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 22, 18, 0)
        )

        assert second.blocked == 0
        assert second.candidates == 0

    @pytest.mark.asyncio
    async def test_a_flat_correctly_awaiting_cleaning_is_not_blocked(self) -> None:
        """The same class of false positive on `CHECKOUT_TIME_REACHED`, which never expires.

        `is_due` for it holds forever once the checkout instant passes, so a flat sitting
        correctly in `AWAITING_CLEANING` was reported for as long as the 30-day window kept its
        stay in view.
        """
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.OCCUPIED_ESTIMATED)
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), nights=4, check_out_time=time(11, 0))
        )

        first = await harness.run(
            PropertyStateTrigger.CHECKOUT_TIME_REACHED, _local(2026, 8, 14, 12, 0)
        )
        assert first.transitioned == 1
        assert prop.current_operational_state is PropertyOperationalState.AWAITING_CLEANING

        second = await harness.run(
            PropertyStateTrigger.CHECKOUT_TIME_REACHED, _local(2026, 8, 22, 10, 18)
        )

        assert second.blocked == 0

    @pytest.mark.asyncio
    async def test_two_overlapping_stays_count_one_flat(self, caplog) -> None:
        """The double-count risk the design names: the bucket counts flats, not mismatches.

        `detect` returns one entry per `(property_id, reservation_id, trigger)` on purpose, so
        collapsing to a flat is this use case's job — the same "one bucket per property"
        precedence `AdvanceReport` already documents.
        """
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.CLEANING_IN_PROGRESS)
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 19), nights=4, check_in_time=time(15, 0))
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 20), nights=4, check_in_time=time(15, 0))
        )

        with caplog.at_level(logging.WARNING, logger="app.properties.application.use_cases"):
            report = await harness.run(
                PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 22, 10, 18)
            )

        assert report.blocked == 1
        # One flat, but two facts: D4 asks for a line per mismatch, and a person chasing one of
        # the two stays needs its reservation named. Asserted because `blocked == 1` alone would
        # stay green if the log loop were collapsed to one line per flat.
        lines = [r for r in caplog.records if r.message == "scheduler.blocked_transition"]
        assert len(lines) == 2
        assert len({r.reservation_id for r in lines}) == 2

    @pytest.mark.asyncio
    async def test_only_the_running_trigger_is_counted(self) -> None:
        """One `execute` is one trigger, so an overdue checkout is not this job's `blocked`.

        Without the filter, `mark_occupied_estimated` would report the stall that
        `process_checkouts` is responsible for, and three jobs would each count the same
        three facts.
        """
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.MAINTENANCE_REQUIRED)
        )
        harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 10), nights=4, check_out_time=time(11, 0))
        )

        checkin = await harness.run(
            PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 22, 10, 18)
        )
        checkout = await harness.run(
            PropertyStateTrigger.CHECKOUT_TIME_REACHED, _local(2026, 8, 22, 10, 18)
        )

        assert checkin.blocked == 0
        assert checkout.blocked == 1

    @pytest.mark.asyncio
    async def test_the_fake_refuses_metadata_the_real_writer_could_not_produce(self) -> None:
        """The fake must not be more forgiving than Postgres (raised by the section-3 panel).

        `metadata` is JSON and `PropertyStateMachine.evaluate` writes `str(reservation_id)`. A raw
        UUID in there would never match the fake's string keys, so the row would be dropped and
        the stay reported as never-transitioned — a quiet answer in the wrong direction, on the
        exact fake/adapter boundary `fixtures-and-real-writers-disagree` warns about.
        """
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.CLEANING_IN_PROGRESS)
        )
        stay = harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 19), nights=4, check_in_time=time(15, 0))
        )
        harness.transitions.transitions.append(
            PropertyStateTransition(
                id=uuid.uuid4(),
                tenant_id=TENANT,
                property_id=prop.id,
                from_state=PropertyOperationalState.AWAITING_CHECKIN,
                to_state=PropertyOperationalState.OCCUPIED_ESTIMATED,
                triggered_by=StateTransitionTriggeredBy.SYSTEM,
                created_at=CREATED,
                metadata={"trigger": "CHECKIN_TIME_REACHED", "reservation_id": stay.id},
            )
        )

        with pytest.raises(TypeError, match="as strings"):
            await harness.run(
                PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 22, 10, 18)
            )

    @pytest.mark.asyncio
    async def test_a_flat_of_another_tenant_is_never_blocked_here(self) -> None:
        """Rule 1 of `steering/security.md`: the sweep is a second query and it is scoped."""
        harness = Harness()
        theirs = harness.with_property(
            _property(
                state=PropertyOperationalState.CLEANING_IN_PROGRESS, tenant_id=uuid.uuid4()
            )
        )
        harness.with_reservation(
            _reservation(theirs, check_in=date(2026, 8, 19), nights=4, check_in_time=time(15, 0))
        )

        report = await harness.run(
            PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 22, 10, 18)
        )

        assert report.blocked == 0

    @pytest.mark.asyncio
    async def test_each_mismatch_logs_its_six_identifying_fields(self, caplog) -> None:
        """R1.1: "identificando la vivienda, la reserva, el trigger y el estado que lo impide".

        Same shape as `scheduler.unresolvable_reservation_time`, and one line per mismatch
        rather than per flat — two overlapping stays are two facts a person may need to chase.
        """
        harness = Harness()
        prop = harness.with_property(
            _property(state=PropertyOperationalState.CLEANING_IN_PROGRESS)
        )
        stay = harness.with_reservation(
            _reservation(prop, check_in=date(2026, 8, 19), nights=4, check_in_time=time(15, 0))
        )

        with caplog.at_level(logging.WARNING, logger="app.properties.application.use_cases"):
            await harness.run(
                PropertyStateTrigger.CHECKIN_TIME_REACHED, _local(2026, 8, 22, 10, 18)
            )

        [record] = [r for r in caplog.records if r.message == "scheduler.blocked_transition"]
        assert record.tenant_id == str(TENANT)
        assert record.property_id == str(prop.id)
        assert record.reservation_id == str(stay.id)
        assert record.trigger == "CHECKIN_TIME_REACHED"
        assert record.blocking_state == "CLEANING_IN_PROGRESS"
        assert record.due_since == _local(2026, 8, 19, 15, 0).isoformat()


class TestTimezones:
    @pytest.mark.asyncio
    async def test_each_property_is_judged_in_its_own_zone(self) -> None:
        """R3.7. Two properties of one tenant, twelve hours apart, one instant.

        Without this the whole suite runs in `Europe/Madrid` and a regression to a
        server-wide zone would pass every other test in the file.
        """
        harness = Harness()
        madrid = harness.with_property(_property(state=PropertyOperationalState.VACANT_READY))
        auckland = harness.with_property(
            _property(
                state=PropertyOperationalState.VACANT_READY, timezone="Pacific/Auckland"
            )
        )
        for prop in (madrid, auckland):
            harness.with_reservation(
                _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
            )

        # 2026-08-10 03:00 UTC is 05:00 in Madrid (too early) and 15:00 in Auckland (due).
        report = await harness.run(
            PropertyStateTrigger.CHECKIN_WINDOW_OPENED,
            datetime(2026, 8, 10, 3, 0, tzinfo=UTC),
        )

        assert report.transitioned == 1
        assert auckland.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN
        assert madrid.current_operational_state is PropertyOperationalState.VACANT_READY
