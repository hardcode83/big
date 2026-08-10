"""Projections of the maintenance aggregates (`dashboard-api` R2, security panel of §4).

**Why these exist rather than the entities themselves.** The first version of
`IncidentReader`/`OwnerApprovalReader` returned whole `Incident` and `OwnerApproval`
objects, and the security panel of section 4 was right to call that a shape decision a
downstream serialiser would inherit verbatim. Between them the two entities carry
`description`, `ai_summary`, `ai_classification`, `reason` and `response_notes` — free text
and free JSON, which rule 11 of `steering/security.md` treats as sinks that "pueden acabar
transportando un valor sensible sin declararlo en su nombre" — plus `reported_by_guest_token`
and three user ids.

The remedy is the one this codebase already uses, and the design cites it approvingly:
`GuestSummary` (`app/guests/domain/value_objects.py:24-39`) is "a frozen projection rather
than the `Guest` entity so the guarantee is structural: no future serialiser can reach a
field that is not here". Same construction, same reason.

**And it turns out to be the right shape for a second, independent reason.** PRD §9.2 and
`frontend/features/dashboard/data/dto.ts:138-143` declare the incident's `title` as
`LocalizedText` — text the backend has already translated. `incidents.title` is free text
typed by whoever reported the fault, in whatever language they typed it, so it could never
have satisfied that contract. `category` can: it is a closed enum, and
`app/dashboard/domain/labels.py` renders it in `es`/`en` (design D4, R5.2). So the field that
had to go for privacy is the same field that could not have been used anyway.

**What `maintenance` inherits from this.** These are the projections the *dashboard* needs.
When the `maintenance` change arrives with its own screens it will need richer readers —
the description is exactly what a technician must see — and it adds them, with the
field-level redaction rules that go with owning that surface. Nothing here forecloses it.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    OwnerApprovalRelatedType,
)


@dataclass(frozen=True)
class IncidentSummary:
    """What the property dashboard is allowed to know about an open incident.

    No `description`, no `ai_summary`, no `ai_classification`, no
    `reported_by_guest_token`, no `reported_by_user_id`, no `assigned_technician_id`, and
    none of the three cost fields — the detail page shows what is wrong and how badly, not
    who said so or what it will cost.
    """

    id: uuid.UUID
    category: IncidentCategory
    severity: IncidentSeverity
    opened_at: datetime


@dataclass(frozen=True)
class OwnerApprovalSummary:
    """What the property dashboard is allowed to know about a pending approval.

    No `reason`, no `response_notes`, no `responded_by`. `amount` stays: it is the whole
    point of an approval request, and PRD §9.2 puts it on the card.
    """

    id: uuid.UUID
    related_type: OwnerApprovalRelatedType
    amount: Decimal
    requested_at: datetime
