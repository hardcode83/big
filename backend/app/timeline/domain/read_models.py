"""What `GET /api/v1/timeline` serves (`dashboard-activity-feed` design D6, D7).

The read side of a poor man's CQRS, the same construction as `app/dashboard/domain/read_models.py`
and `app/maintenance/domain/read_models.py`: no entity here, no table, no writer. Pure Python —
no pydantic, no sqlalchemy — `tests/test_layering.py` enforces it.

**Why this lives here and not in `rendering.py`** (design D7): `rendering.py` is scoped to the
localization catalogue — turning one `TimelineEvent` into a `RenderedEntry` in a locale — and
that module is explicitly out of scope for this change. The tenant-wide feed composes a second,
unrelated domain's identity (`Property.name`/`Property.internal_code`) into the row, which is a
different concern with a different failure mode (design D6: a dangling or cross-tenant
`property_id` degrades to `None`, it never raises and never drops the entry). Keeping that
composition in its own module means `rendering.py` stays exactly what its docstring says it is.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.rendering import RenderedEntry


@dataclass(frozen=True)
class TenantActivityEntry:
    """One entry of the tenant-wide feed: the seven fields of `RenderedEntry`, plus the
    identity of the property it belongs to (R3.1, R3.2).

    `property_name`/`property_internal_code` are `None` when the event's `property_id` does
    not resolve within the tenant — design D6. That is a valid, expected shape of this type,
    not an error state: the entry still carries every other field.
    """

    id: uuid.UUID
    occurred_at: datetime
    actor_type: TimelineActorType
    event_type: TimelineEventType
    severity: TimelineSeverity
    title: str
    description: str | None
    property_id: uuid.UUID
    property_name: str | None
    property_internal_code: str | None


def from_rendered(
    entry: RenderedEntry,
    *,
    property_id: uuid.UUID,
    property_name: str | None,
    property_internal_code: str | None,
) -> TenantActivityEntry:
    """Compose a rendered entry with the identity of its property (module function, matching
    `rendering.render` — a free function, not a classmethod, since that is the style this
    domain already uses for entry construction)."""
    return TenantActivityEntry(
        id=entry.id,
        occurred_at=entry.occurred_at,
        actor_type=entry.actor_type,
        event_type=entry.event_type,
        severity=entry.severity,
        title=entry.title,
        description=entry.description,
        property_id=property_id,
        property_name=property_name,
        property_internal_code=property_internal_code,
    )
