from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.cleaning.domain.enums import CleaningTaskStatus
from app.maintenance.domain.enums import IncidentSeverity, IncidentStatus
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState
from app.reservations.domain.enums import ReservationStatus

from .exceptions import IncompatibleTransitionContextError, TransitionScopeMismatchError
from .value_objects import PropertyTransitionContext


class ContextualStateResolver:
    CONTEXTUAL_STATES = frozenset(
        {
            PropertyOperationalState.CRITICAL_INCIDENT,
            PropertyOperationalState.MAINTENANCE_REQUIRED,
            PropertyOperationalState.CLEANING_IN_PROGRESS,
            PropertyOperationalState.AWAITING_CLEANING,
            PropertyOperationalState.OCCUPIED_ESTIMATED,
            PropertyOperationalState.AWAITING_CHECKIN,
            PropertyOperationalState.READY_FOR_NEXT_GUEST,
            PropertyOperationalState.VACANT_READY,
        }
    )

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
        start = cls._localize_wall_time(reservation.check_in_date, check_in, zone)
        end = cls._localize_wall_time(reservation.check_out_date, check_out, zone)
        if end <= start:
            raise IncompatibleTransitionContextError("Reservation effective checkout must be after check-in")
        return start, end

    @staticmethod
    def _localize_wall_time(day: date, wall_time: time, zone: ZoneInfo) -> datetime:
        if not isinstance(wall_time, time):
            raise IncompatibleTransitionContextError("Reservation local time must be a datetime.time")
        naive = datetime.combine(day, wall_time.replace(tzinfo=None))
        candidates: list[datetime] = []
        seen_utc: set[datetime] = set()
        for fold in (0, 1):
            candidate = naive.replace(tzinfo=zone, fold=fold)
            round_trip = candidate.astimezone(timezone.utc).astimezone(zone)
            if round_trip.replace(tzinfo=None) != naive or round_trip.fold != fold:
                continue
            utc_candidate = candidate.astimezone(timezone.utc)
            if utc_candidate not in seen_utc:
                candidates.append(candidate)
                seen_utc.add(utc_candidate)
        if not candidates:
            raise IncompatibleTransitionContextError(
                "Reservation local time does not exist in the property timezone"
            )
        if len(candidates) == 2:
            if getattr(wall_time.tzinfo, "key", None) != zone.key:
                raise IncompatibleTransitionContextError(
                    "Reservation local time is ambiguous and requires explicit property timezone and fold"
                )
            return candidates[wall_time.fold]
        if wall_time.tzinfo is not None and getattr(wall_time.tzinfo, "key", None) != zone.key:
            raise IncompatibleTransitionContextError(
                "Reservation local time timezone must match the property timezone"
            )
        return candidates[0]

    @classmethod
    def _active_reservations(cls, property: Property, context: PropertyTransitionContext, instant: datetime) -> list[object]:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise IncompatibleTransitionContextError("Reference instant must be timezone-aware")
        candidates: list[object] = []
        for reservation in context.reservations:
            if reservation.status not in (ReservationStatus.CONFIRMED, ReservationStatus.CHECKED_IN_ESTIMATED):
                continue
            start, end = cls._effective_bounds(property, reservation)
            utc_instant = instant.astimezone(timezone.utc)
            if start.astimezone(timezone.utc) <= utc_instant < end.astimezone(timezone.utc):
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
                candidates.append((start.astimezone(timezone.utc), reservation))
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
        if cls._active_reservations(property, context, instant):
            raise IncompatibleTransitionContextError(
                "Cleaning completion is incompatible with an active reservation"
            )
        next_res = cls._next_reservations(property, context, instant)
        if next_res:
            local_date = instant.astimezone(cls._zone(property)).date()
            start, _ = cls._effective_bounds(property, next_res[0])
            if start.astimezone(cls._zone(property)).date() == local_date:
                return PropertyOperationalState.AWAITING_CHECKIN
            return PropertyOperationalState.READY_FOR_NEXT_GUEST
        return PropertyOperationalState.VACANT_READY

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
        if target in cls.CONTEXTUAL_STATES and target is not contextual:
            raise IncompatibleTransitionContextError("Explicit target is incompatible with context")
        if target is PropertyOperationalState.CLEANING_SCHEDULED:
            scheduled_tasks = [
                task
                for task in context.cleaning_tasks
                if task.status in (CleaningTaskStatus.ASSIGNED, CleaningTaskStatus.ACCEPTED)
            ]
            if (
                contextual is not PropertyOperationalState.AWAITING_CLEANING
                or len(scheduled_tasks) != 1
            ):
                raise IncompatibleTransitionContextError(
                    "CLEANING_SCHEDULED requires exactly one assigned or accepted cleaning task"
                )
