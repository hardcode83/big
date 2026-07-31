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

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.exceptions import TimelineMetadataNotSerialisableError
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
        _reject_unstorable_metadata(event)
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


def _reject_unstorable_metadata(event: TimelineEvent) -> None:
    """Fail with a typed error naming the offending keys, before the INSERT.

    `date`, `Decimal` and `UUID` are exactly the types a reservation's own fields have, so
    a caller putting one straight into `metadata` is the likely mistake, not the exotic
    one. Without this the failure is a `StatementError` wrapping "Object of type date is
    not JSON serializable" — a 500 that names no field.

    Deliberately NOT coerced with `json.dumps(..., default=str)`: silently turning a
    `date` into whatever `str()` produces would put an unspecified format in the audit
    trail, and the timeline is evidence. The caller decides how its values are rendered
    (see `Reservation.update_details`, which serialises its change map explicitly).
    """
    if not event.metadata:
        return
    offending = []
    for key, value in event.metadata.items():
        try:
            json.dumps({key: value})
        except TypeError:
            offending.append(f"{key}={type(value).__name__}")
    if offending:
        raise TimelineMetadataNotSerialisableError(
            "Timeline metadata must hold JSON-native values; offending entries: "
            + ", ".join(sorted(offending))
        )
