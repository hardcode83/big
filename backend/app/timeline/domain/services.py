import uuid
from copy import deepcopy

from app.properties.domain.entities import PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity

from .exceptions import TimelineEventValidationError
from .value_objects import TimelineEventData


class TimelineEventFactory:
    @staticmethod
    def create(data: TimelineEventData) -> TimelineEvent:
        if data.created_at.tzinfo is None or data.created_at.utcoffset() is None:
            raise TimelineEventValidationError("created_at must be timezone-aware")
        if not data.title.strip():
            raise TimelineEventValidationError("title must be non-empty")
        if data.actor_type is TimelineActorType.USER and data.actor_user_id is None:
            raise TimelineEventValidationError("USER timeline events require actor_user_id")
        if data.actor_type is not TimelineActorType.USER and data.actor_user_id is not None:
            raise TimelineEventValidationError("Only USER timeline events may provide actor_user_id")
        return TimelineEvent(
            id=data.id,
            tenant_id=data.tenant_id,
            property_id=data.property_id,
            actor_type=data.actor_type,
            event_type=data.event_type,
            title=data.title,
            created_at=data.created_at,
            reservation_id=data.reservation_id,
            actor_user_id=data.actor_user_id,
            severity=data.severity,
            description=data.description,
            metadata=deepcopy(data.metadata),
        )

    @staticmethod
    def property_state_changed(
        *,
        transition: PropertyStateTransition,
        trigger: object,
        timeline_event_id: uuid.UUID | None = None,
        source_entity_id: uuid.UUID | None = None,
        reservation_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
    ) -> TimelineEvent:
        actor_map = {
            StateTransitionTriggeredBy.SYSTEM: TimelineActorType.SYSTEM,
            StateTransitionTriggeredBy.USER: TimelineActorType.USER,
            StateTransitionTriggeredBy.SCHEDULER: TimelineActorType.SCHEDULER,
            StateTransitionTriggeredBy.WEBHOOK: TimelineActorType.WEBHOOK,
        }
        metadata = {
            "from_state": transition.from_state.value if transition.from_state else None,
            "to_state": transition.to_state.value,
            "trigger": getattr(trigger, "value", str(trigger)),
        }
        if source_entity_id is not None:
            metadata["source_entity_id"] = str(source_entity_id)
        if correlation_id is not None:
            metadata["correlation_id"] = correlation_id
        title = f"Property state changed to {transition.to_state.value}"
        event_id = timeline_event_id or transition.metadata.get("timeline_event_id")
        if not isinstance(event_id, uuid.UUID):
            raise TimelineEventValidationError("timeline_event_id is required")
        return TimelineEventFactory.create(
            TimelineEventData(
                id=event_id,
                tenant_id=transition.tenant_id,
                property_id=transition.property_id,
                actor_type=actor_map[transition.triggered_by],
                actor_user_id=transition.triggered_by_user_id,
                event_type=TimelineEventType.PROPERTY_STATE_CHANGED,
                title=title,
                created_at=transition.created_at,
                reservation_id=reservation_id,
                severity=TimelineSeverity.INFO,
                description=transition.reason,
                metadata=metadata,
            )
        )
