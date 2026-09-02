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
from app.maintenance.domain.exceptions import MaintenanceValidationError


@dataclass(frozen=True)
class IncidentClassification:
    """What an `IncidentClassifier` returns about one incident (R1.1, design D1).

    `summary` is the adapter's own words and **never an echo of `title`/`description`** —
    the contract rule 11 of `steering/security.md` gets for `incidents.ai_summary` (D4).
    `confidence` is compared against `TenantConfig.ai_confidence_threshold`, which is a
    `0..1` fraction, so a value outside that range is a broken adapter rather than a low
    score and is refused here instead of silently never classifying anything.

    **`vocabulary` is what makes D4 a property of the type rather than of one adapter.**
    An adapter declares, in the value it returns, the closed set its `summary` was drawn
    from, and this class refuses a `summary` outside it. That inversion is the whole point:
    the obligation used to live in prose on the port and in the construction of the single
    deterministic adapter, so it was satisfied by accident of who had written the code so
    far, and a second implementation inherited nothing. The review panel found the two ways
    that failed — a test sweep rooted at one directory cannot see an adapter in
    `app/integrations/`, which is exactly where `classifier.py` says a real provider goes,
    and a behavioural check that constructs adapters with no arguments silently skips the
    one shape a real provider has (an HTTP client, a model name, a key).

    Enforcing it here reaches all of them, because there is no way to produce the value the
    port is typed to return without going through this check. A paraphrase of the guest's
    description is not in any declared vocabulary, so it raises instead of reaching
    `incidents.ai_summary`.
    """

    category: IncidentCategory
    severity: IncidentSeverity
    summary: str
    confidence: Decimal
    vocabulary: frozenset[str]

    def __post_init__(self) -> None:
        if not Decimal(0) <= self.confidence <= Decimal(1):
            raise MaintenanceValidationError(
                f"Classification confidence must be within 0..1, got {self.confidence}"
            )
        if not self.vocabulary:
            raise MaintenanceValidationError(
                "A classifier must declare the closed vocabulary its summary comes from "
                "(rule 11 of steering/security.md, design D4)"
            )
        if self.summary not in self.vocabulary:
            raise MaintenanceValidationError(
                "Classification summary is not in the adapter's declared vocabulary, so it "
                "may carry reported text into incidents.ai_summary, a rule-11 free-text sink"
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
class OpenIncidentCounts:
    """The tenant-wide open-incident counts of `dashboard-operational-kpis` R3.

    `total` is every incident in `OPEN_INCIDENT_STATUSES`; `urgent` is the subset of those
    with `severity` in `{HIGH, CRITICAL}` — a breakdown, not a second independent count, so
    `urgent` is always `<= total`.
    """

    total: int
    urgent: int


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
