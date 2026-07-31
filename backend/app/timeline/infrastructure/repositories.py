"""SQLAlchemy adapter for `TimelineEventRepository` (design D2).

First writer of `timeline_events` in the system. Two details that are not cosmetic:

* `created_at` is written from the event, not left to `server_default`. The events of one
  business operation must share the instant the use case decided on, and a server-side
  default would stamp each INSERT with its own `now()`.
* `metadata` is stored under the model's `metadata_` attribute, because `metadata` is
  taken by SQLAlchemy's declarative API. The column in Postgres is `metadata`, as
  PRD §7.8 requires.

`tenant_id` is a parameter, not constructor state, so an instance cannot disagree with its
caller about the acting tenant. What this adapter can check is the event's own tenant; the
tenant of its *references* it cannot — see the port's precondition.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.timeline.domain.entities import TimelineEvent
from app.timeline.infrastructure.models import TimelineEventModel


class SqlAlchemyTimelineEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: uuid.UUID, event: TimelineEvent) -> None:
        if event.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="timeline event",
                entity_tenant_id=event.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            TimelineEventModel(
                id=event.id,
                tenant_id=event.tenant_id,
                property_id=event.property_id,
                reservation_id=event.reservation_id,
                actor_user_id=event.actor_user_id,
                actor_type=event.actor_type,
                event_type=event.event_type,
                severity=event.severity,
                title=event.title,
                description=event.description,
                metadata_=event.metadata or None,
                created_at=event.created_at,
            )
        )
        await self._session.flush()
