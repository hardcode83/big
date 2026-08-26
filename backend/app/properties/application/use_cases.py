"""Clock-driven operational state transitions (`celery-jobs` R3, design D6).

The first use case `properties` has ever had. Until now `PropertyStateMachine` was a pure
decision with nobody to act on it: nothing in the system wrote `current_operational_state`
or a row of `property_state_transitions`.

One use case parameterised by trigger rather than three (design D6): the three clock
triggers share the whole loop — candidates, evaluation, persistence, report — and differ
only in their source states, which `PropertyStateMachine.source_states_for` derives.

**The machine decides eligibility, this only asks** (design D3, D10). Every reservation in
the window is put to `PropertyStateMachine.evaluate` and classified by its verdict; this
module never pre-judges "not due" with comparisons of its own. That is also where the
ambiguity of task 3.5 comes from — two accepted verdicts for one property, not a second opinion about
which reservation counts.

**The transaction is the tenant, not the property** (design D5, "cada tenant es su propia
transacción"): one `commit` at the end, so a failure leaves the tenant untouched and the
scheduler's runner moves to the next one (design D12). That is strictly stronger than
R3.6, which only requires the three writes of a single transition to be all-or-nothing.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.cleaning.domain.ports import CleaningProvisioningPort
from app.core.unit_of_work import UnitOfWork
from app.properties.domain.clock_triggers import (
    candidate_window,
    effective_bounds,
    opens_checkin_window,
)
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.properties.domain.exceptions import (
    IncompatibleTransitionContextError,
    NoOperationalStateChangeError,
)
from app.properties.domain.repositories import (
    PropertyRepository,
    PropertyStateTransitionRepository,
)
from app.properties.domain.stalls import BlockedTransition
from app.properties.domain.stalls import detect
from app.properties.domain.state_machine import PropertyStateMachine
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.domain.value_objects import (
    PropertyStateChangeRequest,
    PropertyStateChangeResult,
    PropertyTransitionContext,
    TransitionActor,
    TransitionEvidenceIds,
)
from app.reservations.domain.entities import Reservation
from app.reservations.domain.repositories import ReservationRepository
from app.tenants.domain.repositories import TenantConfigRepository
from app.timeline.domain.repositories import TimelineEventRepository
from app.properties.application.action_id_resolver import ActionIdResolver

logger = logging.getLogger(__name__)


@dataclass
class AdvanceReport:
    """What one run did, in terms an operator can act on.

    The buckets are not decoration. `not_eligible` is the ordinary case — the hour has not
    come — while `unresolvable_time` and `ambiguous` are properties that will **never**
    advance on their own and need a person, so collapsing them into one count would hide
    exactly the rows worth looking at.

    Each candidate property increments exactly one bucket, by this precedence:
    `transitioned` > `ambiguous` > `already_there` > `unresolvable_time` > `not_eligible`.
    A reservation whose local time cannot be materialised is logged either way, so a
    property that transitions on one booking does not bury a broken one.

    **`already_there` cannot currently be non-zero, and that is a property of the policy,
    not an accident**: every `(source state, clock trigger)` entry of
    `PropertyStateMachine._POLICY` has a destination different from its source, so the
    machine's `NoOperationalStateChangeError` is unreachable for these three triggers.
    R4.1's idempotence is delivered one step earlier — a transitioned property leaves the
    source states and stops being a candidate at all. The bucket and its handler stay
    because the day a trigger gains a same-state destination, silently counting it as a
    transition would be the wrong answer. `test_already_there_is_unreachable_for_the_clock_triggers`
    pins the claim so it cannot rot into a lie.
    """

    trigger: str
    candidates: int = 0
    transitioned: int = 0
    already_there: int = 0
    not_eligible: int = 0
    unresolvable_time: int = 0
    ambiguous: int = 0
    #: Flats the calendar wanted to move and their state would not admit
    #: (`cleaning-stall-blocks-next-stay` R1.2, design D3). **Outside `candidates` on
    #: purpose**: a candidate is a flat in a source state of the trigger, and a blocked one is
    #: by definition not — it never reaches `list_by_state`, which is why the 2026-08-22 tick
    #: reported `candidates: 0 … not_eligible: 0` while REDES11 had been stuck since the 16th.
    #: Counting it as a candidate would also break the precedence documented above, since it
    #: increments no other bucket.
    #:
    #: And emphatically **not** `not_eligible`, which keeps its exact meaning of "the hour has
    #: not come". Folding the two together is the confusion that hid this case: one is a flat
    #: waiting for its moment, the other a flat whose moment passed days ago and cannot act on
    #: it. One bucket per flat, like every other count here — two overlapping stays on one flat
    #: are one blocked flat, though they are two logged mismatches.
    blocked: int = 0
    #: Transitioned to `AWAITING_CLEANING` but no `CleaningTask` was created (`cleaning` R2.4).
    #: A separate bucket from `transitioned` for the same reason `ambiguous` is separate from
    #: `not_eligible`: the ordinary causes are a tenant-level configuration choice
    #: (`auto_create_cleaning_task` off, `cleaning_required` false) and one that needs a person
    #: (no resolvable checklist template), and folding them into the success count hides
    #: exactly the rows worth looking at. Always 0 for the other two clock triggers, which
    #: are constructed without a provisioner.
    transitioned_without_task: int = 0


class AdvancePropertyStatesUseCase:
    def __init__(
        self,
        *,
        properties: PropertyRepository,
        reservations: ReservationRepository,
        transitions: PropertyStateTransitionRepository,
        timeline: TimelineEventRepository,
        configs: TenantConfigRepository,
        uow: UnitOfWork,
        provisioner: CleaningProvisioningPort | None = None,
    ) -> None:
        self._properties = properties
        self._reservations = reservations
        self._transitions = transitions
        self._timeline = timeline
        self._configs = configs
        self._uow = uow
        # Optional on purpose (`cleaning` design D1): only `process_checkouts` passes one, so
        # `check_checkin_windows` and `mark_occupied_estimated` are byte-for-byte the jobs
        # `celery-jobs` shipped. A single collaborator rather than a hook, so the type says
        # what it does.
        self._provisioner = provisioner

    async def execute(
        self, *, tenant_id: uuid.UUID, trigger: PropertyStateTrigger, now: datetime
    ) -> AdvanceReport:
        report = AdvanceReport(trigger=trigger.value)
        candidates = await self._properties.list_by_state(
            tenant_id, PropertyStateMachine.source_states_for(trigger)
        )
        config = await self._configs.get_or_create(tenant_id, now)
        checkin_window = timedelta(hours=config.checkin_window_hours_before)

        # Before the transitions, so detection describes the tick's starting state. It writes
        # nothing, so the transaction does not care where it sits.
        #
        # This ordering used to be load-bearing and no longer is, which is worth saying because
        # the comment here previously claimed otherwise: with only the first two conditions, a
        # flat that transitioned earlier in this same tick landed in the complement with its
        # stay still due and was reported as the very thing the job had just fixed. The
        # `applied` evidence (design D1, amended) rules that out on its own — the row written by
        # the transition is exactly what marks the pair as applied. The order is kept anyway,
        # because a pre-write snapshot does not depend on when a flush makes that row visible.
        await self._count_blocked(
            tenant_id=tenant_id,
            trigger=trigger,
            now=now,
            checkin_window=checkin_window,
            report=report,
        )

        # The config read above is now unconditional, where it used to sit behind this guard:
        # detection needs the check-in window whether or not the trigger has candidates, and
        # the whole point of R1 is the tick that has none.
        if not candidates:
            return report

        by_property = await self._reservations_by_property(tenant_id, candidates, now)

        for property in candidates:
            report.candidates += 1
            await self._advance_one(
                tenant_id=tenant_id,
                property=property,
                reservations=by_property.get(property.id, ()),
                trigger=trigger,
                now=now,
                checkin_window=checkin_window,
                report=report,
            )

        await self._uow.commit()
        return report

    async def _count_blocked(
        self,
        *,
        tenant_id: uuid.UUID,
        trigger: PropertyStateTrigger,
        now: datetime,
        checkin_window: timedelta,
        report: AdvanceReport,
    ) -> None:
        """Count and log the flats this trigger cannot move — exactly the ones the candidate
        query cannot see (R1.3).

        The query is the **complement** of the candidate query: every state that is *not* a
        source of the trigger. The two together cover the tenant's portfolio once, with no
        overlap and no gap, which is what makes "it never entered the report" impossible from
        here on. Nothing is written — the exit from a stall belongs to a person (R3), and a job
        that resolved it on its own would be guessing at why the flat was stuck.
        """
        blocked_states = set(PropertyOperationalState) - PropertyStateMachine.source_states_for(
            trigger
        )
        stalled = await self._properties.list_by_state(tenant_id, blocked_states)
        if not stalled:
            return
        by_property = await self._reservations_by_property(tenant_id, stalled, now)
        # The evidence that separates "never advanced" from "advanced and moved on" (design D1
        # as amended). Asked once for every stay in the window rather than per flat: it is one
        # query either way, and per flat it would be one per flat.
        applied = frozenset(
            await self._transitions.applied_clock_triggers(
                tenant_id,
                [
                    reservation.id
                    for reservations in by_property.values()
                    for reservation in reservations
                ],
            )
        )
        for property in stalled:
            # Filtered to the running trigger (design D1): one `execute` is one trigger, while
            # `detect` answers for all three. Without the filter each of the three clock jobs
            # would report all three mismatches and one fact would be counted three times.
            mismatches = [
                mismatch
                for mismatch in detect(
                    property,
                    tuple(by_property.get(property.id, ())),
                    now,
                    checkin_window,
                    applied,
                )
                if mismatch.trigger is trigger
            ]
            if not mismatches:
                continue
            report.blocked += 1
            # One line per mismatch, not per flat: two overlapping stays are two facts, and a
            # person chasing one of them needs its reservation named. Same *style* as
            # `scheduler.unresolvable_reservation_time` below — the tenant, property and
            # reservation it names, plus the trigger — and two fields it does not have, because
            # "what is in the way" and "since when" are the whole point of this one.
            for mismatch in mismatches:
                logger.warning(
                    "scheduler.blocked_transition",
                    extra={
                        "tenant_id": str(tenant_id),
                        "property_id": str(mismatch.property_id),
                        "reservation_id": str(mismatch.reservation_id),
                        "trigger": mismatch.trigger.value,
                        "blocking_state": mismatch.blocking_state.value,
                        "due_since": mismatch.due_since.isoformat(),
                    },
                )

    async def _advance_one(
        self,
        *,
        tenant_id: uuid.UUID,
        property: Property,
        reservations: Sequence[Reservation],
        trigger: PropertyStateTrigger,
        now: datetime,
        checkin_window: timedelta,
        report: AdvanceReport,
    ) -> None:
        # Paired with the reservation that produced each verdict: the provisioner needs the
        # *source* stay to know which booking the cleaning belongs to (`cleaning` R2.1), and
        # `reservations[0]` is not it — a property can carry several in the window.
        accepted: list[tuple[PropertyStateChangeResult, Reservation]] = []
        unresolvable = False
        already_there = False

        for reservation in reservations:
            try:
                effective_bounds(property, reservation)
            except IncompatibleTransitionContextError:
                # R3.4. The local time does not exist, is ambiguous without a fold, or the
                # checkout is not after the check-in. None of those fix themselves with
                # time, which is why they are not folded into "not due yet". Logged even if
                # a sibling reservation goes on to transition the property.
                unresolvable = True
                logger.warning(
                    "scheduler.unresolvable_reservation_time",
                    extra={
                        "tenant_id": str(tenant_id),
                        "property_id": str(property.id),
                        "reservation_id": str(reservation.id),
                        "trigger": trigger.value,
                    },
                )
                continue

            if trigger is PropertyStateTrigger.CHECKIN_WINDOW_OPENED and not opens_checkin_window(
                property, reservation, now, checkin_window
            ):
                # The only pre-judgement this module makes, and it is the operator's
                # policy rather than the machine's (design D7).
                continue

            try:
                accepted.append(
                    (
                        PropertyStateMachine.evaluate(
                            self._request_for(property, reservation, trigger, now)
                        ),
                        reservation,
                    )
                )
            except NoOperationalStateChangeError:
                already_there = True
            except IncompatibleTransitionContextError:
                # The machine's own precondition: wrong status, or the hour has not come.
                continue
            # `InvalidTransitionInputError` and `TransitionEvidenceError` are deliberately
            # NOT caught (R3.3): they mean this use case built the request wrong, which is
            # a bug in us and not a state of the world. Letting them escape fails the
            # tenant loudly instead of hiding in a report bucket.

        if len(accepted) > 1:
            # Task 3.5: the machine says two bookings both justify the move, so there is no
            # honest source entity. Picking one would anchor the transition — and the
            # timeline event recording it — to the wrong guest.
            report.ambiguous += 1
            logger.warning(
                "scheduler.ambiguous_due_reservation",
                extra={
                    "tenant_id": str(tenant_id),
                    "property_id": str(property.id),
                    "trigger": trigger.value,
                    "accepted": len(accepted),
                },
            )
            return
        if not accepted:
            if already_there:
                report.already_there += 1
            elif unresolvable:
                report.unresolvable_time += 1
            else:
                report.not_eligible += 1
            return

        result, source_reservation = accepted[0]
        await self._transitions.add(tenant_id, result.transition)
        await self._timeline.add(tenant_id, result.timeline_event)
        property.current_operational_state = result.transition.to_state
        await self._properties.save(tenant_id, property)
        report.transitioned += 1

        # `cleaning` R2.3, design D1: inside this transaction, after the state has advanced —
        # the provisioner may perform the `CLEANER_ASSIGNED` transition on the same entity, and
        # the machine reads the state off it — and before the single `commit` at the end of
        # `execute`. A `None` is an ordinary outcome the report counts (R2.4), not a failure.
        if self._provisioner is not None and trigger is PropertyStateTrigger.CHECKOUT_TIME_REACHED:
            provisioned = await self._provisioner.provision_for_checkout(
                tenant_id=tenant_id,
                property=property,
                reservation=source_reservation,
                known_reservations=reservations,
                now=now,
            )
            if provisioned is None:
                report.transitioned_without_task += 1
                logger.info(
                    "scheduler.checkout_without_cleaning_task",
                    extra={
                        "tenant_id": str(tenant_id),
                        "property_id": str(property.id),
                    },
                )

    @staticmethod
    def _request_for(
        property: Property,
        reservation: Reservation,
        trigger: PropertyStateTrigger,
        now: datetime,
    ) -> PropertyStateChangeRequest:
        # Fresh evidence ids per attempt. The losers are discarded with their request, and
        # that is cheaper than deferring their creation: `TransitionEvidenceIds` validates
        # that the two ids differ, so building them late would move a guarantee out of the
        # request's own construction.
        return PropertyStateChangeRequest(
            property=property,
            trigger=trigger,
            context=PropertyTransitionContext(reservations=(reservation,)),
            actor=TransitionActor(triggered_by=StateTransitionTriggeredBy.SYSTEM),
            reference_instant=now,
            evidence_ids=TransitionEvidenceIds(
                transition_id=uuid.uuid4(), timeline_event_id=uuid.uuid4()
            ),
            source_entity_id=reservation.id,
            reservation_id=reservation.id,
            correlation_id=str(uuid.uuid4()),
        )

    async def _reservations_by_property(
        self, tenant_id: uuid.UUID, candidates: Sequence[Property], now: datetime
    ) -> dict[uuid.UUID, list[Reservation]]:
        return await reservations_by_property(self._reservations, tenant_id, candidates, now)


async def reservations_by_property(
    reservations: ReservationRepository,
    tenant_id: uuid.UUID,
    properties: Sequence[Property],
    now: datetime,
) -> dict[uuid.UUID, list[Reservation]]:
    """The stays of `properties` inside `candidate_window`, grouped by property.

    Module-level and shared rather than a method, because `ListBlockedTransitionsUseCase` needs
    the same window as the job: R1.4 fixes the detection horizon at `candidate_window` and D1
    promises one definition of "mismatch" for the count and for the collection. Two copies of the
    window would let the two disagree about which stalls exist — the failure `clock_triggers.py`
    already records for the due-ness comparison.
    """
    date_from, date_to = candidate_window(now)
    rows = await reservations.list_for_properties(
        tenant_id, [property.id for property in properties], date_from, date_to
    )
    grouped: dict[uuid.UUID, list[Reservation]] = {}
    for reservation in rows:
        grouped.setdefault(reservation.property_id, []).append(reservation)
    return grouped


@dataclass(frozen=True)
class BlockedTransitionRow:
    """One stall, paired with the code an operator recognises the flat by.

    `BlockedTransition` deliberately carries ids only — it is a domain value object and knows
    nothing about presentation — while a person reading the collection needs "REDES11", not a
    UUID. Paired here, in `application/`, rather than by widening the value object.

    The two action ids (`cleaning_task_id`, `incident_id`) are **populated by the action id
    resolver** (R2.1, R2.2 of `blocked-transition-response-ids`), never derived from
    `BlockedTransition` itself — the latter is a pure domain value object that the proposal
    keeps that way (§Out of scope: "Persistencia de los ids en `BlockedTransition`").
    They start as `None` and are filled in batch before the response is built, so the
    `from_row` factory on the response schema can read them without a separate query path.
    """

    mismatch: BlockedTransition
    property_code: str
    cleaning_task_id: uuid.UUID | None = None
    incident_id: uuid.UUID | None = None


@dataclass(frozen=True)
class BlockedTransitionPage:
    items: tuple[BlockedTransitionRow, ...]
    total: int


class ListBlockedTransitionsUseCase:
    """The stalls of one tenant, derived on every read and never stored (R2, design D5).

    **Nothing is persisted**, and that is what makes R2.4 free: the collection is recomputed from
    the flats' states and their stays, so a stall stops being listed the moment it is resolved.
    There is no row to close, and therefore no row that someone forgets to close — which is the
    very failure mode this change exists to fix.

    **The pagination is of the result, not of the source.** Every flat of the tenant is examined
    and the *stalls* are paged. Paging the source would reproduce the original bug: a stalled flat
    on page 3 would be invisible again. `total` is then the number an operator wants — how many
    stalls there are.

    The window and the evidence are the job's (R1.4, D1): the same `candidate_window` through
    `reservations_by_property`, and the same `applied_clock_triggers`. If this use case computed
    either differently, the report and the screen would disagree about what is stuck.
    """

    def __init__(
        self,
        *,
        properties: PropertyRepository,
        reservations: ReservationRepository,
        transitions: PropertyStateTransitionRepository,
        configs: TenantConfigRepository,
        action_ids: ActionIdResolver,
    ) -> None:
        self._properties = properties
        self._reservations = reservations
        self._transitions = transitions
        self._configs = configs
        self._action_ids = action_ids

    async def execute(
        self, *, tenant_id: uuid.UUID, now: datetime, page: int, per_page: int
    ) -> BlockedTransitionPage:
        # `list_all` is unpaginated by design and declared as debt (design *Risks*): the lever, if
        # a tenant's portfolio ever makes it hurt, is to filter by the complement of the source
        # states per trigger the way the job does.
        properties = await self._properties.list_all(tenant_id)
        if not properties:
            return BlockedTransitionPage(items=(), total=0)

        # `checkin_window_hours`, not `get_or_create`: this is a `GET`, and the sibling upsert
        # stages an `INSERT` for a tenant whose config row does not exist yet — which would make
        # D5's "nada se guarda" false, on a path a role without `MANAGE_TENANT_SETTINGS` can reach.
        # Found by the architect and the security reviewer independently in the section-4 panel.
        checkin_window = timedelta(hours=await self._configs.checkin_window_hours(tenant_id))
        by_property = await reservations_by_property(
            self._reservations, tenant_id, properties, now
        )
        applied = frozenset(
            await self._transitions.applied_clock_triggers(
                tenant_id,
                [
                    reservation.id
                    for reservations in by_property.values()
                    for reservation in reservations
                ],
            )
        )

        rows: list[BlockedTransitionRow] = []
        for property in properties:
            for mismatch in detect(
                property,
                tuple(by_property.get(property.id, ())),
                now,
                checkin_window,
                applied,
            ):
                rows.append(
                    BlockedTransitionRow(mismatch=mismatch, property_code=property.internal_code)
                )

        # Resolve the action ids (`cleaning_task_id`, `incident_id`) for the whole page in
        # ONE batch call per port (R3.4) and rebuild the rows with the ids populated.
        # The resolver returns a `{property_id: (cleaning_id, incident_id)}` mapping; the
        # page here is at most ~100 rows, so this is one dictionary lookup per row, not a
        # second query. `BlockedTransitionRow` is `frozen`, so we replace rather than
        # mutate.
        if rows:
            action_id_by_property = await self._action_ids.resolve(
                [(row.mismatch.property_id, row.mismatch.blocking_state) for row in rows],
                tenant_id,
            )
            no_action_ids = (None, None)
            rows = [
                BlockedTransitionRow(
                    mismatch=row.mismatch,
                    property_code=row.property_code,
                    cleaning_task_id=action_id_by_property.get(
                        row.mismatch.property_id, no_action_ids
                    )[0],
                    incident_id=action_id_by_property.get(
                        row.mismatch.property_id, no_action_ids
                    )[1],
                )
                for row in rows
            ]

        # Oldest stall first, which is the order an operator triages in, with the ids as
        # tiebreakers so a page boundary cannot repeat or skip a row when two stalls share an
        # instant — the same reason `PropertyRepository.list` promises a stable sort.
        rows.sort(
            key=lambda row: (
                row.mismatch.due_since,
                str(row.mismatch.property_id),
                str(row.mismatch.reservation_id),
                row.mismatch.trigger.value,
            )
        )
        start = (page - 1) * per_page
        return BlockedTransitionPage(
            items=tuple(rows[start : start + per_page]), total=len(rows)
        )
