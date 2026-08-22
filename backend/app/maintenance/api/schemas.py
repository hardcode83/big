"""Request/response DTOs for the maintenance endpoints (PRD §23, R5).

Three rules this module exists to enforce:

* **No request schema has a `tenant_id`**, and none has an `assigned_technician_id` filter
  either. The effective tenant comes only from the verified token, and the row-level
  restriction of R5.3 is derived from the role inside the use case
  (`IncidentActor.restrict_to_technician_id`), never accepted from the client — a filter in
  a query string could otherwise be omitted, and the restriction with it.
* **Response fields are enumerated, never dumped from the entity.** `Incident` carries
  `reported_by_guest_token`, `reported_by_user_id` and `ai_classification`; a
  `from_attributes` dump would publish all three. The first is already dropped at the port
  (`IncidentRepository.get`), and this is the second wall — the one the security panel of
  section 5 asked section 8 to prove with a test on the serialised payload rather than on
  the entity.
* **`per_page` has a ceiling.** The port refuses a non-positive page; the ceiling belongs
  here, or one request pulls a tenant's whole incident table — descriptions included — in a
  single response.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.maintenance.domain.entities import Incident
from app.maintenance.domain.read_models import IncidentContext
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    OwnerApprovalStatus,
)

MAX_PER_PAGE = 100
# `page` needs a ceiling too, not just `per_page`: the value becomes a SQL OFFSET and a
# 20-digit page number overflows int8, producing an unhandled driver error instead of a 422
# in the PRD §23 envelope. Same bound and same reason as `cleaning` and `reservations`.
MAX_PAGE = 100_000
MAX_RESPONSE_NOTES = 2000
# Mirrors the `VARCHAR(2000)` of `incidents.assignment_note`: the bound lives in the DDL
# and in the schema, not only in the second (`tech-incident-context` D6).
MAX_ASSIGNMENT_NOTE = 2000
# Two decimals, because `Numeric(10, 2)` is what the three cost columns are: a third decimal
# would be silently rounded by the driver, and the owner would approve a number the system
# then stored as a different one.
MAX_COST = Decimal("99999999.99")


class IncidentResponse(BaseModel):
    """What an authenticated operator may see about one incident.

    `description` **is** here, unlike in the dashboard's `IncidentSummary`: this is the
    surface a technician works from and the fault is what they have to read. What is not
    here is everything that identifies who reported it (`reported_by_guest_token`,
    `reported_by_user_id`) and the raw classifier verdict (`ai_classification`) — the first
    is a stable digest that correlates a guest's stay, and the last is a rule-11 JSON sink
    whose audience is the flow, not a client. `ai_summary` stays: it is our own closed
    vocabulary, and it is what tells an operator the incident was looked at.
    """

    id: uuid.UUID
    property_id: uuid.UUID
    reservation_id: uuid.UUID | None
    source: IncidentSource
    category: IncidentCategory
    severity: IncidentSeverity
    status: IncidentStatus
    title: str
    description: str
    ai_summary: str | None
    assigned_technician_id: uuid.UUID | None
    owner_approval_required: bool
    estimated_cost: Decimal | None
    approved_cost: Decimal | None
    final_cost: Decimal | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, incident: Incident) -> "IncidentResponse":
        return cls(
            id=incident.id,
            property_id=incident.property_id,
            reservation_id=incident.reservation_id,
            source=incident.source,
            category=incident.category,
            severity=incident.severity,
            status=incident.status,
            title=incident.title,
            description=incident.description,
            ai_summary=incident.ai_summary,
            assigned_technician_id=incident.assigned_technician_id,
            owner_approval_required=incident.owner_approval_required,
            estimated_cost=incident.estimated_cost,
            approved_cost=incident.approved_cost,
            final_cost=incident.final_cost,
            resolved_at=incident.resolved_at,
            created_at=incident.created_at,
            updated_at=incident.updated_at,
        )


class IncidentContextResponse(BaseModel):
    """What `GET /incidents/{incident_id}/context` returns — exactly `IncidentContext` (D4).

    A field-for-field mirror on purpose, the `CleaningTaskContextResponse` construction. The
    projection is where R2.5, R5.2, R5.3 and R5.4 are enforced structurally, so this model
    earning its own opinion about which fields to include would reintroduce the very decision
    the read model exists to remove — and would make the router the owner of the denylist,
    which design D4 rejects by name.

    **`from_attributes` here reads a frozen dataclass of eleven fields, never an entity.** That
    is what makes it safe where a dump of `Property` would not be: `cleaning_notes`,
    `emergency_notes` and `has_wifi_password` are fields of that entity and are not fields of
    the projection. No `Property` and no `Reservation` is ever serialised on this route.

    No `exclude_none`, here or anywhere in `backend/app` — which is what satisfies R1.3: a
    `NULL` address travels as `null` **with its key**, rather than the key vanishing. That is
    inherited pydantic behaviour rather than something this model states, so it carries its own
    test against the serialised body (`tests/maintenance/test_incident_context_api.py`) instead
    of being assumed.
    """

    model_config = ConfigDict(from_attributes=True)

    property_name: str
    property_internal_code: str
    address_line1: str | None
    address_line2: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    country: str
    timezone: str
    access_notes: str | None
    assignment_note: str | None

    @classmethod
    def from_domain(cls, context: IncidentContext) -> "IncidentContextResponse":
        return cls.model_validate(context)


class IncidentPageResponse(BaseModel):
    items: list[IncidentResponse]
    total: int
    page: int
    per_page: int

    @classmethod
    def from_domain(
        cls, incidents: Sequence[Incident], *, total: int, page: int, per_page: int
    ) -> "IncidentPageResponse":
        return cls(
            items=[IncidentResponse.from_domain(incident) for incident in incidents],
            total=total,
            page=page,
            per_page=per_page,
        )


class TriageIncidentRequest(BaseModel):
    """`PATCH /incidents/{id}` (R1.4, R2.1).

    Every field is optional because a triage may correct only one of them; sending none is
    a no-op the entity accepts, and refusing it here would be a rule this schema invented.
    """

    model_config = ConfigDict(extra="forbid")

    category: IncidentCategory | None = None
    severity: IncidentSeverity | None = None
    estimated_cost: Annotated[Decimal | None, Field(ge=0, le=MAX_COST, decimal_places=2)] = None


class AssignIncidentRequest(BaseModel):
    """`POST /incidents/{id}/assign` (R3.2 of `tech-incident-context`).

    `assignment_note` is optional and **replaces** whatever the previous assignment carried:
    omitting it clears the note rather than preserving it (D7). That is why there is no
    "absent vs. explicit null" distinction to make here — this is a complete operation, not
    a patch, and `extra="forbid"` still refuses anything else.
    """

    model_config = ConfigDict(extra="forbid")

    technician_id: uuid.UUID
    assignment_note: Annotated[str | None, Field(max_length=MAX_ASSIGNMENT_NOTE)] = None


class ResolveIncidentRequest(BaseModel):
    """R4.2 — `final_cost` is required, which is where "SHALL exigir `final_cost`" lands for
    an HTTP caller. The entity requires it too, for callers that are not HTTP."""

    model_config = ConfigDict(extra="forbid")

    final_cost: Annotated[Decimal, Field(ge=0, le=MAX_COST, decimal_places=2)]


class RespondOwnerApprovalRequest(BaseModel):
    """`POST /owner-approvals/{id}/respond` (R2.4, R2.5).

    `status` is the enum, and the entity refuses anything but `APPROVED`/`REJECTED` — the
    two an owner can give. `response_notes` is free text the owner types, bounded here and
    kept out of `audit_logs.changes` by the allowlist (D6).
    """

    model_config = ConfigDict(extra="forbid")

    status: OwnerApprovalStatus
    response_notes: Annotated[str | None, Field(max_length=MAX_RESPONSE_NOTES)] = None
