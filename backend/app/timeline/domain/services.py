import uuid
from copy import deepcopy
from datetime import datetime

from app.properties.domain.entities import PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity

from .exceptions import TimelineEventValidationError
from .value_objects import TimelineEventData


class TimelineEventFactory:
    @staticmethod
    def create(data: TimelineEventData) -> TimelineEvent:
        if not isinstance(data, TimelineEventData):
            raise TimelineEventValidationError("data must be TimelineEventData")
        for field_name in ("id", "tenant_id", "property_id"):
            if not isinstance(getattr(data, field_name), uuid.UUID):
                raise TimelineEventValidationError(f"{field_name} must be a UUID")
        for field_name in ("reservation_id", "actor_user_id"):
            value = getattr(data, field_name)
            if value is not None and not isinstance(value, uuid.UUID):
                raise TimelineEventValidationError(f"{field_name} must be a UUID when provided")
        if not isinstance(data.actor_type, TimelineActorType):
            raise TimelineEventValidationError("actor_type must be TimelineActorType")
        if not isinstance(data.event_type, TimelineEventType):
            raise TimelineEventValidationError("event_type must be TimelineEventType")
        if not isinstance(data.severity, TimelineSeverity):
            raise TimelineEventValidationError("severity must be TimelineSeverity")
        if not isinstance(data.created_at, datetime):
            raise TimelineEventValidationError("created_at must be a datetime")
        if data.created_at.tzinfo is None or data.created_at.utcoffset() is None:
            raise TimelineEventValidationError("created_at must be timezone-aware")
        if not isinstance(data.title, str) or not data.title.strip():
            raise TimelineEventValidationError("title must be non-empty")
        if data.description is not None and not isinstance(data.description, str):
            raise TimelineEventValidationError("description must be a string when provided")
        if not isinstance(data.metadata, dict):
            raise TimelineEventValidationError("metadata must be a dictionary")
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
        if not isinstance(transition, PropertyStateTransition):
            raise TimelineEventValidationError("transition must be PropertyStateTransition")
        if not isinstance(trigger, PropertyStateTrigger):
            raise TimelineEventValidationError("trigger must be PropertyStateTrigger")
        if not isinstance(transition.from_state, PropertyOperationalState):
            raise TimelineEventValidationError("transition.from_state must be PropertyOperationalState")
        if not isinstance(transition.to_state, PropertyOperationalState):
            raise TimelineEventValidationError("transition.to_state must be PropertyOperationalState")
        if not isinstance(transition.metadata, dict):
            raise TimelineEventValidationError("transition.metadata must be a dictionary")
        for field_name, value in (
            ("source_entity_id", source_entity_id),
            ("reservation_id", reservation_id),
        ):
            if value is not None and not isinstance(value, uuid.UUID):
                raise TimelineEventValidationError(f"{field_name} must be a UUID when provided")
        if correlation_id is not None and (
            not isinstance(correlation_id, str) or not correlation_id.strip()
        ):
            raise TimelineEventValidationError("correlation_id must be non-empty when provided")
        actor_map = {
            StateTransitionTriggeredBy.SYSTEM: TimelineActorType.SYSTEM,
            StateTransitionTriggeredBy.USER: TimelineActorType.USER,
            StateTransitionTriggeredBy.SCHEDULER: TimelineActorType.SCHEDULER,
            StateTransitionTriggeredBy.WEBHOOK: TimelineActorType.WEBHOOK,
        }
        actor_type = actor_map.get(transition.triggered_by)
        if actor_type is None:
            raise TimelineEventValidationError(
                "transition.triggered_by must be StateTransitionTriggeredBy"
            )
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
                actor_type=actor_type,
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
