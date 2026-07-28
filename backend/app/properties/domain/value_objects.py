import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.cleaning.domain.entities import CleaningTask
from app.maintenance.domain.entities import Incident
from app.properties.domain.entities import Property, PropertyStateTransition
from app.properties.domain.enums import StateTransitionTriggeredBy
from app.reservations.domain.entities import Reservation
from app.timeline.domain.entities import TimelineEvent

from .exceptions import InvalidTransitionInputError


@dataclass(frozen=True)
class PropertyTransitionContext:
    reservations: tuple[Reservation, ...] = ()
    cleaning_tasks: tuple[CleaningTask, ...] = ()
    incidents: tuple[Incident, ...] = ()


@dataclass(frozen=True)
class TransitionActor:
    triggered_by: StateTransitionTriggeredBy
    user_id: Optional[uuid.UUID] = None

    def __post_init__(self) -> None:
        if not isinstance(self.triggered_by, StateTransitionTriggeredBy):
            raise InvalidTransitionInputError("triggered_by must be StateTransitionTriggeredBy")
        if self.triggered_by is StateTransitionTriggeredBy.USER and self.user_id is None:
            raise InvalidTransitionInputError("USER actor requires user_id")
        if self.triggered_by is not StateTransitionTriggeredBy.USER and self.user_id is not None:
            raise InvalidTransitionInputError("Only USER actors may provide user_id")


@dataclass(frozen=True)
class TransitionEvidenceIds:
    transition_id: uuid.UUID
    timeline_event_id: uuid.UUID

    def __post_init__(self) -> None:
        if not isinstance(self.transition_id, uuid.UUID) or not isinstance(self.timeline_event_id, uuid.UUID):
            raise InvalidTransitionInputError("Evidence IDs must be UUIDs")
        if self.transition_id == self.timeline_event_id:
            raise InvalidTransitionInputError("Transition and timeline evidence IDs must differ")


@dataclass(frozen=True)
class PropertyStateChangeRequest:
    property: Property
    trigger: object
    context: PropertyTransitionContext
    actor: TransitionActor
    reference_instant: datetime
    evidence_ids: TransitionEvidenceIds
    requested_state: object = None
    reason: Optional[str] = None
    source_entity_id: Optional[uuid.UUID] = None
    reservation_id: Optional[uuid.UUID] = None
    correlation_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.reference_instant.tzinfo is None or self.reference_instant.utcoffset() is None:
            raise InvalidTransitionInputError("reference_instant must be timezone-aware")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise InvalidTransitionInputError("correlation_id must be non-empty")


@dataclass(frozen=True)
class PropertyStateChangeResult:
    transition: PropertyStateTransition
    timeline_event: TimelineEvent
