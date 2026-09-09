"""What `GET /incidents/{incident_id}/context` serves (`tech-incident-context` design D4).

The read side of a poor man's CQRS, the same construction as
`app/cleaning/domain/read_models.py` and `app/dashboard/domain/read_models.py`: no entity here,
no table, no writer. Pure Python — no pydantic, no sqlalchemy — `tests/test_layering.py`
enforces it, and `app/maintenance/api/schemas.py` maps it to the wire.

**Why the field list is closed, and which rules depend on it staying closed.** A `TECHNICIAN`
holds five permissions and neither `READ_PROPERTIES` nor `READ_RESERVATIONS` is among them
(`app/auth/domain/policy.py`). What that role already reaches is `IncidentResponse`
(`app/maintenance/api/schemas.py`), which carries `property_id` and `reservation_id` as bare
identifiers and no attribute of either row. This projection is the only route that carries
`Property` **attributes** to that role, which is what makes enumerating them here the mechanism
that turns three requirements **structural** instead of remembered:

* **R2.5 / R5.2** — `wifi_password_encrypted` is not a field of `Property` at all
  (`properties-crud` D2), and `has_wifi_password`, `cleaning_notes` and `emergency_notes` are
  not fields of this projection. Rule 3 of `steering/security.md` grants no form for a WiFi
  password, masked or otherwise, and the flag is excluded too: no requirement asks for it, and
  the narrowest projection ages best. `Property` is never serialised; a field that is not here
  has nowhere to land.
* **R5.3** — no attribute of any reservation: no `gross_amount`, `ota_commission`, `net_amount`,
  `payment_status`, `channel`, `guest_id`, `special_requests` or `internal_notes`. PRD §12 does
  not ask for the booking on this screen, and the use case reads no reservation repository, so
  there is not even a statement that could produce one.
* **R5.4** — no `reported_by_guest_token`, `reported_by_user_id` or `ai_classification`. The
  first never leaves the port (`IncidentRepository.get` drops it); the other two are excluded
  the same way as everything else, by not being here.

The rule for whoever adds a field, inherited verbatim from `cleaner-task-context` design D8: **a
projection may narrow, never union.** A field that a permission guards *as a whole* — a
reservation's amount, a guest's name — does not come in here; it goes through `dashboard-api`
D10. `tests/maintenance/test_incident_context_read_model.py` pins the set so that adding one is
a deliberate act.

This capability **diverges** from "aggregating cannot grant" with the same bounded scope
`cleaner-task-context` claimed: its subject is an incident the caller may already read in full,
and what it adds are ten attributes of one property over a row set **narrower** than
`READ_PROPERTIES` would give.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)

#: `owner_approvals` has no `currency` column (§7.19), so this listing cannot read the
#: currency off the row — it has to declare one. `EUR` is not a guess: the tenant threshold
#: this whole flow gates against is literally `owner_approval_threshold_eur`
#: (`app/tenants/domain/entities.py:151`), so the amount an owner is asked to approve is
#: already denominated in EUR before it ever reaches this projection (`approvals-web` D3).
OWNER_APPROVAL_CURRENCY = "EUR"


@dataclass(frozen=True)
class IncidentContext:
    """Where the technician has to go, how to get in, and what the manager said (R1, R2, R3).

    Ten of the eleven fields come from the property, which is why a property that does not
    resolve inside the tenant is a `404` and never a partial answer (R1.5, design D9). The
    eleventh, `assignment_note`, belongs to the **assignment in force** and is replaced on every
    reassignment (design D7).

    The fields are named after their columns rather than aliased by audience. The guest portal
    renames `access_notes` to `arrival_notes`, which is right there — its reader never sees a
    column name — but a third name for a column that has to be auditable across the tree makes
    it ungreppable, and a technician's screen is a surface of operation, not of hospitality.
    """

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


@dataclass(frozen=True)
class OwnerApprovalIncidentRef:
    """The incident behind an `INCIDENT`/`MAINTENANCE_COST` approval (R1.3).

    Four attributes, not the entity: enough for the owner to recognise which fault this
    money answers for, without carrying `description` or `ai_summary` — the same narrowing
    `IncidentSummary` already applies to the dashboard, for the same rule-11 reason.

    `None` on `OwnerApprovalListItem.incident` — never this type with blank fields — is how
    an `OTHER`-related approval (one that answers for something that is not an incident at
    all) is told apart from one whose incident failed to resolve; the latter cannot happen
    without also dropping the whole row (see `OwnerApprovalReader.list_for_tenant`).
    """

    id: UUID
    title: str
    category: IncidentCategory
    severity: IncidentSeverity


@dataclass(frozen=True)
class OwnerApprovalPropertyRef:
    """The vivienda in the form a person reads, never a bare UUID (R1.3)."""

    id: UUID
    name: str
    internal_code: str


@dataclass(frozen=True)
class OwnerApprovalListItem:
    """One row of `GET /owner-approvals` — everything needed to decide without navigating
    away (R1.3), and no free text: neither `reason` nor `response_notes` is a field here,
    the same closed-form rule `OwnerApprovalSummary` already applies to the dashboard card
    (design D2).

    `currency` is always `OWNER_APPROVAL_CURRENCY` — declared, not read off a column that
    does not exist (design D3).

    `incident` is `None` exactly when `related_type` is `OTHER` (an approval that does not
    answer for an incident at all); it is never `None` because a resolvable incident failed
    to resolve, since `OwnerApprovalReader.list_for_tenant`'s LEFT OUTER JOIN only omits
    `OTHER` rows on purpose (design D4).

    `property` is populated by composing this reader's output with
    `PropertyRepository.list_for_ids` in the use case, not by this module — see that
    reader's own docstring for why, and for what a reader-produced item's `property` field
    holds before that composition runs.
    """

    id: UUID
    related_type: OwnerApprovalRelatedType
    status: OwnerApprovalStatus
    amount: Decimal
    currency: str
    requested_at: datetime
    responded_at: datetime | None
    incident: OwnerApprovalIncidentRef | None
    property: OwnerApprovalPropertyRef


@dataclass(frozen=True)
class OwnerApprovalPage:
    """One page of `OwnerApprovalListItem`, plus the `total` a client needs for
    `total_pages` — the same shape `IncidentPage` already gives its own listing."""

    items: tuple[OwnerApprovalListItem, ...]
    total: int
