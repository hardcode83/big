"""SQLAlchemy adapter for `TimelineEventRepository` (design D2).

First writer of `timeline_events` in the system. Two details that are not cosmetic:

* `created_at` is written from the event, not left to `server_default`. The events of
  one business operation must share the instant the use case decided on, and a
  server-side default would stamp each INSERT with its own `now()`.
* `metadata` is stored under the model's `metadata_` attribute, because `metadata` is
  taken by SQLAlchemy's declarative API. The column in Postgres is `metadata`, as
  PRD §7.8 requires.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.timeline.domain.entities import TimelineEvent
from app.timeline.infrastructure.models import TimelineEventModel


class CrossTenantWriteError(RuntimeError):
    """An event was about to be written for a tenant other than the acting one."""


class SqlAlchemyTimelineEventRepository:
    def __init__(self, session: AsyncSession, *, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def add(self, event: TimelineEvent) -> None:
        if event.tenant_id != self._tenant_id:
            raise CrossTenantWriteError(
                f"Refusing to record a timeline event for tenant {event.tenant_id} "
                f"while acting for {self._tenant_id}"
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
