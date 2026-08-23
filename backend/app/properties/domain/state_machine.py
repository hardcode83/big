from datetime import timezone

from app.cleaning.domain.enums import CleaningTaskStatus
from app.maintenance.domain.enums import IncidentSeverity, IncidentStatus
from app.properties.domain.entities import PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.reservations.domain.enums import ReservationStatus
from app.timeline.domain.services import TimelineEventFactory

from .exceptions import (
    IncompatibleTransitionContextError,
    InvalidStateTransitionError,
    InvalidTransitionInputError,
    NoOperationalStateChangeError,
    TransitionEvidenceError,
    TransitionScopeMismatchError,
)
from app.timeline.domain.exceptions import TimelineDomainError
from .state_resolution import ContextualStateResolver
from .transition_enums import PropertyStateTrigger
from .value_objects import PropertyStateChangeRequest, PropertyStateChangeResult


class PropertyStateMachine:
    _POLICY = {
        (PropertyOperationalState.VACANT_READY, PropertyStateTrigger.CHECKIN_WINDOW_OPENED): {PropertyOperationalState.AWAITING_CHECKIN},
        (PropertyOperationalState.VACANT_READY, PropertyStateTrigger.OWNER_BLOCKED): {PropertyOperationalState.BLOCKED_BY_OWNER},
        (PropertyOperationalState.VACANT_READY, PropertyStateTrigger.PROPERTY_MARKED_OUT_OF_SERVICE): {PropertyOperationalState.OUT_OF_SERVICE},
        (PropertyOperationalState.VACANT_READY, PropertyStateTrigger.INCIDENT_HIGH): {PropertyOperationalState.MAINTENANCE_REQUIRED},
        # Added by `maintenance` (design D8). Until then a CRITICAL fault in an empty, ready
        # flat left it in `VACANT_READY` — that is, bookable — while every other state
        # already routed `INCIDENT_CRITICAL` to `CRITICAL_INCIDENT`. An omission of the
        # matrix, not a decision: `VACANT_READY` accepted `INCIDENT_HIGH` all along.
        (PropertyOperationalState.VACANT_READY, PropertyStateTrigger.INCIDENT_CRITICAL): {PropertyOperationalState.CRITICAL_INCIDENT},
        (PropertyOperationalState.AWAITING_CHECKIN, PropertyStateTrigger.CHECKIN_TIME_REACHED): {PropertyOperationalState.OCCUPIED_ESTIMATED},
        (PropertyOperationalState.AWAITING_CHECKIN, PropertyStateTrigger.INCIDENT_HIGH): {PropertyOperationalState.MAINTENANCE_REQUIRED},
        (PropertyOperationalState.AWAITING_CHECKIN, PropertyStateTrigger.INCIDENT_CRITICAL): {PropertyOperationalState.CRITICAL_INCIDENT},
        (PropertyOperationalState.AWAITING_CHECKIN, PropertyStateTrigger.OWNER_BLOCKED): {PropertyOperationalState.BLOCKED_BY_OWNER},
        (PropertyOperationalState.AWAITING_CHECKIN, PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN): {PropertyOperationalState.VACANT_READY},
        (PropertyOperationalState.OCCUPIED_ESTIMATED, PropertyStateTrigger.CHECKOUT_TIME_REACHED): {PropertyOperationalState.AWAITING_CLEANING},
        (PropertyOperationalState.OCCUPIED_ESTIMATED, PropertyStateTrigger.INCIDENT_CRITICAL): {PropertyOperationalState.CRITICAL_INCIDENT},
        (PropertyOperationalState.OCCUPIED_ESTIMATED, PropertyStateTrigger.INCIDENT_HIGH): {PropertyOperationalState.MAINTENANCE_REQUIRED},
        (PropertyOperationalState.AWAITING_CLEANING, PropertyStateTrigger.CLEANER_ASSIGNED): {PropertyOperationalState.CLEANING_SCHEDULED},
        (PropertyOperationalState.AWAITING_CLEANING, PropertyStateTrigger.INCIDENT_CRITICAL): {PropertyOperationalState.CRITICAL_INCIDENT},
        (PropertyOperationalState.AWAITING_CLEANING, PropertyStateTrigger.INCIDENT_HIGH): {PropertyOperationalState.MAINTENANCE_REQUIRED},
        (PropertyOperationalState.AWAITING_CLEANING, PropertyStateTrigger.OWNER_BLOCKED): {PropertyOperationalState.BLOCKED_BY_OWNER},
        (PropertyOperationalState.CLEANING_SCHEDULED, PropertyStateTrigger.CLEANING_STARTED): {PropertyOperationalState.CLEANING_IN_PROGRESS},
        (PropertyOperationalState.CLEANING_SCHEDULED, PropertyStateTrigger.CLEANER_REJECTED): {PropertyOperationalState.AWAITING_CLEANING},
        (PropertyOperationalState.CLEANING_SCHEDULED, PropertyStateTrigger.INCIDENT_CRITICAL): {PropertyOperationalState.CRITICAL_INCIDENT},
        # Added by `maintenance` (design D8), the second of the same pair of omissions:
        # `CLEANING_SCHEDULED` admitted `INCIDENT_CRITICAL` and not `INCIDENT_HIGH`, while
        # `AWAITING_CLEANING` and `CLEANING_IN_PROGRESS` both admitted the two.
        (PropertyOperationalState.CLEANING_SCHEDULED, PropertyStateTrigger.INCIDENT_HIGH): {PropertyOperationalState.MAINTENANCE_REQUIRED},
        (PropertyOperationalState.CLEANING_IN_PROGRESS, PropertyStateTrigger.CLEANING_COMPLETED): {PropertyOperationalState.READY_FOR_NEXT_GUEST, PropertyOperationalState.AWAITING_CHECKIN, PropertyOperationalState.VACANT_READY},
        (PropertyOperationalState.CLEANING_IN_PROGRESS, PropertyStateTrigger.INCIDENT_HIGH): {PropertyOperationalState.MAINTENANCE_REQUIRED},
        (PropertyOperationalState.CLEANING_IN_PROGRESS, PropertyStateTrigger.INCIDENT_CRITICAL): {PropertyOperationalState.CRITICAL_INCIDENT},
        (PropertyOperationalState.AWAITING_CLEANING, PropertyStateTrigger.CLEANING_CANCELLED): (
            set(ContextualStateResolver.CANCELLATION_STATES) - {PropertyOperationalState.AWAITING_CLEANING}
        ),
        (PropertyOperationalState.CLEANING_SCHEDULED, PropertyStateTrigger.CLEANING_CANCELLED): (
            set(ContextualStateResolver.CANCELLATION_STATES)
        ),
        (PropertyOperationalState.CLEANING_IN_PROGRESS, PropertyStateTrigger.CLEANING_CANCELLED): (
            set(ContextualStateResolver.CANCELLATION_STATES) - {PropertyOperationalState.CLEANING_IN_PROGRESS}
        ),
        (PropertyOperationalState.READY_FOR_NEXT_GUEST, PropertyStateTrigger.CHECKIN_WINDOW_OPENED): {PropertyOperationalState.AWAITING_CHECKIN},
        (PropertyOperationalState.READY_FOR_NEXT_GUEST, PropertyStateTrigger.INCIDENT_HIGH): {PropertyOperationalState.MAINTENANCE_REQUIRED},
        (PropertyOperationalState.READY_FOR_NEXT_GUEST, PropertyStateTrigger.INCIDENT_CRITICAL): {PropertyOperationalState.CRITICAL_INCIDENT},
        (PropertyOperationalState.READY_FOR_NEXT_GUEST, PropertyStateTrigger.OWNER_BLOCKED): {PropertyOperationalState.BLOCKED_BY_OWNER},
        (PropertyOperationalState.MAINTENANCE_REQUIRED, PropertyStateTrigger.INCIDENT_RESOLVED): (
            set(ContextualStateResolver.CONTEXTUAL_STATES) - {PropertyOperationalState.MAINTENANCE_REQUIRED}
        ),
        (PropertyOperationalState.MAINTENANCE_REQUIRED, PropertyStateTrigger.INCIDENT_CRITICAL): {PropertyOperationalState.CRITICAL_INCIDENT},
        (PropertyOperationalState.MAINTENANCE_REQUIRED, PropertyStateTrigger.OWNER_BLOCKED): {PropertyOperationalState.BLOCKED_BY_OWNER},
        (PropertyOperationalState.CRITICAL_INCIDENT, PropertyStateTrigger.INCIDENT_HIGH): {PropertyOperationalState.MAINTENANCE_REQUIRED},
        (PropertyOperationalState.CRITICAL_INCIDENT, PropertyStateTrigger.INCIDENT_RESOLVED): (
            set(ContextualStateResolver.CONTEXTUAL_STATES) - {PropertyOperationalState.CRITICAL_INCIDENT}
        ),
        (PropertyOperationalState.CRITICAL_INCIDENT, PropertyStateTrigger.OWNER_BLOCKED): {PropertyOperationalState.BLOCKED_BY_OWNER},
        (PropertyOperationalState.BLOCKED_BY_OWNER, PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED): {
            state for state in PropertyOperationalState if state is not PropertyOperationalState.BLOCKED_BY_OWNER
        },
        (PropertyOperationalState.OUT_OF_SERVICE, PropertyStateTrigger.PROPERTY_REACTIVATED): {PropertyOperationalState.VACANT_READY},
    }

    @classmethod
    def source_states_for(cls, trigger: PropertyStateTrigger) -> frozenset[PropertyOperationalState]:
        """Which current states admit `trigger`, derived from the policy above.

        Added by `celery-jobs` so its scheduled jobs can narrow their candidates (design
        D3) **without writing a second copy of the matrix**. A hand-kept list would drift
        from `_POLICY` the first time a transition is added, and it would drift silently:
        the job would simply stop considering a state that had become legal.
        """
        return frozenset(state for state, candidate in cls._POLICY if candidate is trigger)

    @classmethod
    def is_due(cls, request: PropertyStateChangeRequest) -> bool:
        """Whether the clock says this transition should happen, ignoring whether it may.

        Added by `cleaning-stall-blocks-next-stay` (design D2) because `evaluate` cannot
        answer it: `evaluate` consults `_POLICY` **before** `_validate_trigger_preconditions`,
        so for a state that is not a source of the trigger it raises
        `InvalidStateTransitionError` and never reaches the question. That ordering is right
        for a caller performing a transition and useless for one detecting a mismatch — which
        is exactly why a flat stuck in `CLEANING_IN_PROGRESS` with a stay already running went
        unreported: nobody could ask the second question separately.

        **`_POLICY` is deliberately not consulted here.** The legality half is the caller's to
        ask, with `source_states_for`; folding both into one answer would collapse "not due"
        and "not legal" back into the single verdict whose ambiguity this exists to break.

        Only `IncompatibleTransitionContextError` means "not due". `InvalidTransitionInputError`
        and `TransitionScopeMismatchError` mean the caller built the request wrong, and they
        escape for the same reason `AdvancePropertyStatesUseCase` refuses to catch them: a bug
        in us must not read as a fact about the world.
        """
        cls._validate_request(request)
        try:
            cls._validate_trigger_preconditions(request)
        except IncompatibleTransitionContextError:
            return False
        return True

    @classmethod
    def evaluate(cls, request: PropertyStateChangeRequest) -> PropertyStateChangeResult:
        cls._validate_request(request)
        current = request.property.current_operational_state
        trigger = request.trigger
        allowed = cls._POLICY.get((current, trigger))
        if allowed is None:
            raise InvalidStateTransitionError("No policy entry for source state and trigger", from_state=current.value, trigger=trigger.value)
        cls._validate_trigger_preconditions(request)
        destination = cls._destination(request, allowed)
        if request.requested_state is not None and request.requested_state != destination:
            raise InvalidStateTransitionError("requested_state does not match resolved destination")
        if destination is current:
            raise NoOperationalStateChangeError(from_state=current.value, to_state=destination.value)
        if destination not in allowed:
            raise InvalidStateTransitionError("Destination is not allowed by policy", from_state=current.value, to_state=destination.value)
        transition_metadata = {
            "trigger": trigger.value,
        }
        if request.source_entity_id is not None:
            transition_metadata["source_entity_id"] = str(request.source_entity_id)
        if request.reservation_id is not None:
            transition_metadata["reservation_id"] = str(request.reservation_id)
        if request.correlation_id is not None:
            transition_metadata["correlation_id"] = request.correlation_id
        transition = PropertyStateTransition(
            id=request.evidence_ids.transition_id,
            tenant_id=request.property.tenant_id,
            property_id=request.property.id,
            from_state=current,
            to_state=destination,
            triggered_by=request.actor.triggered_by,
            triggered_by_user_id=request.actor.user_id,
            reason=request.reason,
            created_at=request.reference_instant,
            metadata=transition_metadata,
        )
        try:
            event = TimelineEventFactory.property_state_changed(
                transition=transition,
                trigger=trigger,
                timeline_event_id=request.evidence_ids.timeline_event_id,
                source_entity_id=request.source_entity_id,
                reservation_id=request.reservation_id,
                correlation_id=request.correlation_id,
            )
        except TimelineDomainError as exc:
            raise TransitionEvidenceError() from exc
        return PropertyStateChangeResult(transition=transition, timeline_event=event)

    @classmethod
    def _validate_request(cls, request: PropertyStateChangeRequest) -> None:
        if not isinstance(request.trigger, PropertyStateTrigger):
            raise InvalidTransitionInputError("trigger must be PropertyStateTrigger")
        if request.requested_state is not None and not isinstance(request.requested_state, PropertyOperationalState):
            raise InvalidTransitionInputError("requested_state must be canonical")
        if not isinstance(request.property.current_operational_state, PropertyOperationalState):
            raise InvalidTransitionInputError("property state is not canonical")
        for collection in (request.context.reservations, request.context.cleaning_tasks, request.context.incidents):
            for entity in collection:
                if entity.tenant_id != request.property.tenant_id or entity.property_id != request.property.id:
                    raise TransitionScopeMismatchError()
        manual = request.trigger in {
            PropertyStateTrigger.OWNER_BLOCKED,
            PropertyStateTrigger.PROPERTY_MARKED_OUT_OF_SERVICE,
            PropertyStateTrigger.PROPERTY_REACTIVATED,
            PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED,
        }
        if manual:
            if request.actor.triggered_by is not StateTransitionTriggeredBy.USER or request.actor.user_id is None:
                raise InvalidTransitionInputError("Manual transitions require a USER actor")
            if request.reason is None or not request.reason.strip():
                raise InvalidTransitionInputError("Manual transitions require a non-empty reason")
        if request.trigger is PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED and request.requested_state is None:
            raise InvalidTransitionInputError("Unblock requires explicit requested_state")
        if request.reservation_id is not None:
            matches = [r for r in request.context.reservations if r.id == request.reservation_id]
            if len(matches) != 1:
                raise IncompatibleTransitionContextError("reservation_id is missing from context")
            if request.source_entity_id is not None and request.trigger in {
                PropertyStateTrigger.CHECKIN_WINDOW_OPENED,
                PropertyStateTrigger.CHECKIN_TIME_REACHED,
                PropertyStateTrigger.CHECKOUT_TIME_REACHED,
                PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN,
            } and request.source_entity_id != request.reservation_id:
                raise IncompatibleTransitionContextError("reservation_id must match reservation source entity")
        if request.source_entity_id is not None and request.trigger in {
            PropertyStateTrigger.OWNER_BLOCKED,
            PropertyStateTrigger.PROPERTY_MARKED_OUT_OF_SERVICE,
            PropertyStateTrigger.PROPERTY_REACTIVATED,
            PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED,
        }:
            raise InvalidTransitionInputError("Manual transitions do not accept source_entity_id")

    @classmethod
    def _destination(cls, request: PropertyStateChangeRequest, allowed: set[PropertyOperationalState]) -> PropertyOperationalState:
        trigger = request.trigger
        contextual_triggers = {
            PropertyStateTrigger.CLEANING_COMPLETED,
            PropertyStateTrigger.CLEANING_CANCELLED,
            PropertyStateTrigger.INCIDENT_RESOLVED,
        }
        if trigger is PropertyStateTrigger.CLEANING_COMPLETED:
            return ContextualStateResolver.after_cleaning_completion(request.property, request.context, request.reference_instant)
        if trigger is PropertyStateTrigger.CLEANING_CANCELLED:
            return ContextualStateResolver.after_cleaning_cancellation(request.property, request.context, request.reference_instant)
        if trigger is PropertyStateTrigger.INCIDENT_RESOLVED:
            return ContextualStateResolver.after_incident_resolution(request.property, request.context, request.reference_instant)
        if (
            trigger is PropertyStateTrigger.INCIDENT_HIGH
            and request.property.current_operational_state is PropertyOperationalState.CRITICAL_INCIDENT
        ):
            return ContextualStateResolver.after_incident_resolution(
                request.property,
                request.context,
                request.reference_instant,
            )
        if trigger is PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED:
            if request.requested_state is None:
                return ContextualStateResolver.after_incident_resolution(request.property, request.context, request.reference_instant)
            destination = request.requested_state
            if not isinstance(destination, PropertyOperationalState):
                raise InvalidTransitionInputError("requested_state must be canonical")
            if trigger is PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED:
                ContextualStateResolver.validate_explicit_target(destination, request.property, request.context, request.reference_instant)
            return destination
        if trigger in contextual_triggers:
            raise InvalidStateTransitionError("Contextual policy requires an explicit resolver", trigger=trigger.value)
        if len(allowed) != 1:
            raise InvalidStateTransitionError("Fixed policy must contain exactly one destination", trigger=trigger.value)
        destination, = allowed
        return destination

    @classmethod
    def _validate_trigger_preconditions(cls, request: PropertyStateChangeRequest) -> None:
        trigger = request.trigger
        if trigger in (PropertyStateTrigger.CHECKIN_WINDOW_OPENED, PropertyStateTrigger.CHECKIN_TIME_REACHED, PropertyStateTrigger.CHECKOUT_TIME_REACHED, PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN):
            reservation = cls._source_reservation(request)
            start, end = ContextualStateResolver._effective_bounds(request.property, reservation)
            instant = request.reference_instant.astimezone(ContextualStateResolver._zone(request.property))
            utc_instant = request.reference_instant.astimezone(timezone.utc)
            utc_start = start.astimezone(timezone.utc)
            utc_end = end.astimezone(timezone.utc)
            if trigger is PropertyStateTrigger.CHECKIN_WINDOW_OPENED and (reservation.status is not ReservationStatus.CONFIRMED or start.date() != instant.date()):
                raise IncompatibleTransitionContextError("Check-in window requires a CONFIRMED reservation entering today")
            if trigger is PropertyStateTrigger.CHECKIN_TIME_REACHED and (reservation.status not in (ReservationStatus.CONFIRMED, ReservationStatus.CHECKED_IN_ESTIMATED) or utc_instant < utc_start or utc_instant >= utc_end):
                raise IncompatibleTransitionContextError("Check-in time requires an active reservation at or after effective check-in")
            if trigger is PropertyStateTrigger.CHECKOUT_TIME_REACHED and (reservation.status not in (ReservationStatus.CONFIRMED, ReservationStatus.CHECKED_IN_ESTIMATED) or utc_instant < utc_end):
                raise IncompatibleTransitionContextError("Checkout time requires an eligible reservation at or after effective checkout")
            if trigger is PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN and (reservation.status is not ReservationStatus.CANCELLED or utc_instant >= utc_start):
                raise IncompatibleTransitionContextError("Cancellation must precede effective check-in")
        if trigger in (PropertyStateTrigger.CLEANER_ASSIGNED, PropertyStateTrigger.CLEANER_REJECTED, PropertyStateTrigger.CLEANING_STARTED, PropertyStateTrigger.CLEANING_COMPLETED, PropertyStateTrigger.CLEANING_CANCELLED):
            task = cls._source_cleaning(request)
            expected = {
                PropertyStateTrigger.CLEANER_ASSIGNED: {CleaningTaskStatus.ASSIGNED},
                PropertyStateTrigger.CLEANER_REJECTED: {CleaningTaskStatus.REJECTED},
                PropertyStateTrigger.CLEANING_STARTED: {CleaningTaskStatus.IN_PROGRESS},
                PropertyStateTrigger.CLEANING_COMPLETED: {CleaningTaskStatus.COMPLETED},
                PropertyStateTrigger.CLEANING_CANCELLED: {CleaningTaskStatus.CANCELLED},
            }[trigger]
            if task.status not in expected:
                raise IncompatibleTransitionContextError("Cleaning trigger status is incompatible")
        if trigger in (PropertyStateTrigger.INCIDENT_HIGH, PropertyStateTrigger.INCIDENT_CRITICAL, PropertyStateTrigger.INCIDENT_RESOLVED):
            incident = cls._source_incident(request)
            if trigger in (PropertyStateTrigger.INCIDENT_HIGH, PropertyStateTrigger.INCIDENT_CRITICAL) and incident.status in (IncidentStatus.RESOLVED, IncidentStatus.CANCELLED):
                raise IncompatibleTransitionContextError("Incident severity trigger requires an active incident")
            if trigger is PropertyStateTrigger.INCIDENT_HIGH and incident.severity is not IncidentSeverity.HIGH:
                raise IncompatibleTransitionContextError("HIGH incident trigger requires HIGH severity")
            if trigger is PropertyStateTrigger.INCIDENT_CRITICAL and incident.severity is not IncidentSeverity.CRITICAL:
                raise IncompatibleTransitionContextError("CRITICAL incident trigger requires CRITICAL severity")
            # `CANCELLED` counts as resolved here (`maintenance` design D9), and this is not
            # a licence that change took: `ContextualStateResolver.after_incident_resolution`
            # already filters active incidents with `status not in (RESOLVED, CANCELLED)`,
            # so the resolver treats the two alike and only this guard did not. Without it
            # R2.5 strands the property: an owner rejecting the budget cancels the incident,
            # and nothing else fires to bring the property back out of `CRITICAL_INCIDENT`.
            if trigger is PropertyStateTrigger.INCIDENT_RESOLVED and incident.status not in (IncidentStatus.RESOLVED, IncidentStatus.CANCELLED):
                raise IncompatibleTransitionContextError("Resolution trigger requires a RESOLVED or CANCELLED incident")

    @staticmethod
    def _source_reservation(request: PropertyStateChangeRequest):
        matches = [r for r in request.context.reservations if r.id == request.source_entity_id]
        if len(matches) != 1:
            raise IncompatibleTransitionContextError("Reservation source entity is missing or ambiguous")
        return matches[0]

    @staticmethod
    def _source_cleaning(request: PropertyStateChangeRequest):
        matches = [t for t in request.context.cleaning_tasks if t.id == request.source_entity_id]
        if len(matches) != 1:
            raise IncompatibleTransitionContextError("Cleaning source entity is missing or ambiguous")
        return matches[0]

    @staticmethod
    def _source_incident(request: PropertyStateChangeRequest):
        matches = [i for i in request.context.incidents if i.id == request.source_entity_id]
        if len(matches) != 1:
            raise IncompatibleTransitionContextError("Incident source entity is missing or ambiguous")
        return matches[0]
