from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.cleaning.domain.enums import CleaningTaskStatus
from app.maintenance.domain.enums import IncidentSeverity, IncidentStatus
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState
from app.reservations.domain.enums import ReservationStatus

from .exceptions import IncompatibleTransitionContextError, TransitionScopeMismatchError
from .value_objects import PropertyTransitionContext


class ContextualStateResolver:
    @staticmethod
    def _zone(property: Property) -> ZoneInfo:
        try:
            return ZoneInfo(property.timezone)
        except ZoneInfoNotFoundError as exc:
            raise IncompatibleTransitionContextError("Property timezone is invalid") from exc

    @classmethod
    def _validate_scope(cls, property: Property, context: PropertyTransitionContext) -> None:
        for collection in (context.reservations, context.cleaning_tasks, context.incidents):
            for entity in collection:
                if entity.tenant_id != property.tenant_id or entity.property_id != property.id:
                    raise TransitionScopeMismatchError("Context entity does not match property scope")

    @classmethod
    def _effective_bounds(cls, property: Property, reservation: object) -> tuple[datetime, datetime]:
        zone = cls._zone(property)
        check_in = getattr(reservation, "check_in_time", None) or property.default_check_in_time
        check_out = getattr(reservation, "check_out_time", None) or property.default_check_out_time
        start = datetime.combine(reservation.check_in_date, check_in, zone)
        end = datetime.combine(reservation.check_out_date, check_out, zone)
        if end <= start:
            raise IncompatibleTransitionContextError("Reservation effective checkout must be after check-in")
        return start, end

    @classmethod
    def _active_reservations(cls, property: Property, context: PropertyTransitionContext, instant: datetime) -> list[object]:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise IncompatibleTransitionContextError("Reference instant must be timezone-aware")
        candidates: list[object] = []
        for reservation in context.reservations:
            if reservation.status not in (ReservationStatus.CONFIRMED, ReservationStatus.CHECKED_IN_ESTIMATED):
                continue
            start, end = cls._effective_bounds(property, reservation)
            local_instant = instant.astimezone(cls._zone(property))
            if start <= local_instant < end:
                candidates.append(reservation)
        if len(candidates) > 1:
            raise IncompatibleTransitionContextError("Active reservations overlap")
        return candidates

    @classmethod
    def _next_reservations(cls, property: Property, context: PropertyTransitionContext, instant: datetime) -> list[object]:
        zone = cls._zone(property)
        local_date = instant.astimezone(zone).date()
        candidates = []
        for reservation in context.reservations:
            if reservation.status is not ReservationStatus.CONFIRMED:
                continue
            start, _ = cls._effective_bounds(property, reservation)
            if start.astimezone(zone).date() >= local_date:
                candidates.append((start, reservation))
        candidates.sort(key=lambda pair: (pair[0], pair[1].id))
        return [reservation for _, reservation in candidates]

    @classmethod
    def after_incident_resolution(cls, property: Property, context: PropertyTransitionContext, instant: datetime) -> PropertyOperationalState:
        cls._validate_scope(property, context)
        active = [i for i in context.incidents if i.status not in (IncidentStatus.RESOLVED, IncidentStatus.CANCELLED)]
        if any(i.severity is IncidentSeverity.CRITICAL for i in active):
            return PropertyOperationalState.CRITICAL_INCIDENT
        if any(i.severity is IncidentSeverity.HIGH for i in active):
            return PropertyOperationalState.MAINTENANCE_REQUIRED
        return cls._contextual_reservation_cleaning(property, context, instant, include_incidents=False)

    @classmethod
    def after_cleaning_completion(cls, property: Property, context: PropertyTransitionContext, instant: datetime) -> PropertyOperationalState:
        cls._validate_scope(property, context)
        return cls._contextual_reservation_cleaning(property, context, instant, include_incidents=False, completed_only=True)

    @classmethod
    def _contextual_reservation_cleaning(cls, property: Property, context: PropertyTransitionContext, instant: datetime, *, include_incidents: bool, completed_only: bool = False) -> PropertyOperationalState:
        if not completed_only:
            if any(t.status is CleaningTaskStatus.IN_PROGRESS for t in context.cleaning_tasks):
                return PropertyOperationalState.CLEANING_IN_PROGRESS
            if any(t.status in (CleaningTaskStatus.CREATED, CleaningTaskStatus.ASSIGNED, CleaningTaskStatus.ACCEPTED) for t in context.cleaning_tasks):
                return PropertyOperationalState.AWAITING_CLEANING
        active = cls._active_reservations(property, context, instant)
        if active:
            return PropertyOperationalState.OCCUPIED_ESTIMATED
        next_res = cls._next_reservations(property, context, instant)
        if next_res:
            local_date = instant.astimezone(cls._zone(property)).date()
            start, _ = cls._effective_bounds(property, next_res[0])
            if start.astimezone(cls._zone(property)).date() == local_date:
                return PropertyOperationalState.AWAITING_CHECKIN
            return PropertyOperationalState.READY_FOR_NEXT_GUEST
        return PropertyOperationalState.VACANT_READY

    @classmethod
    def validate_explicit_target(cls, target: PropertyOperationalState, property: Property, context: PropertyTransitionContext, instant: datetime) -> None:
        cls._validate_scope(property, context)
        contextual = cls.after_incident_resolution(property, context, instant)
        if target in (PropertyOperationalState.OCCUPIED_ESTIMATED, PropertyOperationalState.AWAITING_CHECKIN, PropertyOperationalState.READY_FOR_NEXT_GUEST, PropertyOperationalState.VACANT_READY, PropertyOperationalState.AWAITING_CLEANING, PropertyOperationalState.CLEANING_IN_PROGRESS) and target is not contextual:
            raise IncompatibleTransitionContextError("Explicit target is incompatible with context")
