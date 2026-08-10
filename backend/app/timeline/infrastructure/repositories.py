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
from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.exceptions import TimelineMetadataNotSerialisableError
from app.timeline.domain.repositories import Page, TimelineFilters
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


class SqlAlchemyTimelineEventReader:
    """Adapter for `TimelineEventReader` (`dashboard-api` design D2/D8).

    A class of its own, mirroring the port split: the writer's signature is the statement
    that the timeline is append-only, and giving it read methods would erase that.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_property(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        *,
        filters: TimelineFilters,
        page: int,
        per_page: int,
    ) -> Page:
        conditions = _conditions(tenant_id, property_id, filters)
        total = await self._session.scalar(
            select(func.count()).select_from(TimelineEventModel).where(*conditions)
        )
        rows = await self._session.execute(
            _ordered(select(TimelineEventModel).where(*conditions))
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return Page(
            items=tuple(_to_event(model) for model in rows.scalars()),
            total=int(total or 0),
        )

    async def last_for_properties(
        self, tenant_id: uuid.UUID, property_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, TimelineEvent]:
        """The newest event of each property in **one** statement (`dashboard-api` R1.7).

        `DISTINCT ON (property_id)` with a matching `ORDER BY` — Postgres keeps the first
        row of each group, so the ordering *is* the selection. The alternative shapes were
        both worse for this case: a correlated subquery per property is N queries wearing
        one statement's clothing, and a window function needs an outer filter over rows the
        database has already materialised. `DISTINCT ON` is Postgres-specific, which costs
        nothing here — the project is Postgres 16 by decision, and the schema already uses
        partial indexes and `JSONB`.

        `id DESC` after `created_at DESC` for the reason the paginated reader documents:
        the adapter writes `created_at` from the event, so the events of one business
        operation share it and "the newest" would otherwise be whichever the planner
        returned first.

        A property with no events is **absent** from the mapping rather than mapped to
        `None`, which is what the port promises.
        """
        if not property_ids:
            return {}
        rows = await self._session.execute(
            select(TimelineEventModel)
            .where(
                TimelineEventModel.tenant_id == tenant_id,
                TimelineEventModel.property_id.in_(list(property_ids)),
            )
            .distinct(TimelineEventModel.property_id)
            .order_by(
                TimelineEventModel.property_id,
                TimelineEventModel.created_at.desc(),
                TimelineEventModel.id.desc(),
            )
        )
        return {model.property_id: _to_event(model) for model in rows.scalars()}


def _conditions(
    tenant_id: uuid.UUID, property_id: uuid.UUID, filters: TimelineFilters
) -> list:
    conditions = [
        TimelineEventModel.tenant_id == tenant_id,
        TimelineEventModel.property_id == property_id,
    ]
    if filters.event_type is not None:
        conditions.append(TimelineEventModel.event_type == filters.event_type)
    if filters.severity is not None:
        conditions.append(TimelineEventModel.severity == filters.severity)
    if filters.actor_type is not None:
        conditions.append(TimelineEventModel.actor_type == filters.actor_type)
    # Inclusive on both ends: a caller asking for "this day" means the whole day, and an
    # exclusive bound would drop an event stamped exactly on it.
    if filters.occurred_from is not None:
        conditions.append(TimelineEventModel.created_at >= filters.occurred_from)
    if filters.occurred_to is not None:
        conditions.append(TimelineEventModel.created_at <= filters.occurred_to)
    return conditions


def _ordered(statement: Select) -> Select:
    """Newest first, `id` as the tiebreaker (design D8).

    `ix_timeline_events_property_id_created_at` covers the first key. The second is not in
    the index and therefore sorts in memory — but only **within one instant**, which is a
    handful of rows, and without it pagination repeats and omits entries: the adapter
    writes `created_at` from the event, so every event of one business operation shares it.
    """
    return statement.order_by(
        TimelineEventModel.created_at.desc(), TimelineEventModel.id.desc()
    )


def _to_event(model: TimelineEventModel) -> TimelineEvent:
    return TimelineEvent(
        id=model.id,
        tenant_id=model.tenant_id,
        property_id=model.property_id,
        actor_type=model.actor_type,
        event_type=model.event_type,
        title=model.title,
        created_at=model.created_at,
        reservation_id=model.reservation_id,
        actor_user_id=model.actor_user_id,
        severity=model.severity,
        description=model.description,
        metadata=model.metadata_ or {},
    )


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
