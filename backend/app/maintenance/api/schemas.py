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

from app.auth.domain.enums import UserRole
from app.core.storable_text import MultiLineText
from app.maintenance.application.use_cases import UploadedIncidentPhoto
from app.maintenance.domain.entities import (
    MAX_INCIDENT_MESSAGE_LENGTH,
    MAX_MATERIALS,
    Incident,
    IncidentMessage,
)
from app.maintenance.domain.read_models import IncidentContext
from app.maintenance.domain.repositories import IncidentMessagePage
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentPhotoStage,
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

    **`eta_at` and `materials` are here, and that includes the paginated listing** — this one
    schema serves both the detail and the `items` of the page (`tech-cycle-completion` D8).
    `properties.access_notes` paid the price of leaving the listing under **excepción 6**,
    which is a different concession: that value is a note about how to get into a flat, and
    `GET /api/v1/guest/info/{token}` hands it verbatim to an anonymous bearer. `materials` is
    **excepción 3**, and its audience is exactly the one already reading `title`,
    `description` and `ai_summary` in this same listing — `READ_INCIDENTS`, and if the caller
    is a technician, only their own rows. Splitting the schema would remove no reader and
    would take from the technician's own list the one column that explains the cost.
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
    eta_at: datetime | None
    owner_approval_required: bool
    estimated_cost: Decimal | None
    approved_cost: Decimal | None
    final_cost: Decimal | None
    materials: str | None
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
            eta_at=incident.eta_at,
            owner_approval_required=incident.owner_approval_required,
            estimated_cost=incident.estimated_cost,
            approved_cost=incident.approved_cost,
            final_cost=incident.final_cost,
            materials=incident.materials,
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


class IncidentEtaRequest(BaseModel):
    """The body of `accept` and of `en-route` — **one schema for both** (R3.2, design D6).

    One and not two because the field set is identical, and duplicating it would put R3.2's
    "en ninguna otra ruta" in two places that could drift apart. The router takes it as
    `payload: IncidentEtaRequest | None = None`, so a `POST` with no body at all keeps
    working exactly as it did before this change.

    **No validation of the instant lives here**, deliberately (D6): "una ETA no puede estar en
    el pasado" is a business rule, its reference instant is the router's `now_utc()`, and a
    rule written into a DTO would leave every non-HTTP caller — `seed_demo`, the tests —
    without it. `Incident._apply_eta` is where it lives, and it also refuses a naïve
    timestamp, which is what keeps the comparison from surfacing as an undeclared `500`.

    `extra="forbid"` is what makes "no other route accepts an ETA" a `422` rather than a
    convention: sending `eta_at` to `wait-parts` or `resume` is rejected because those routes
    take no body at all, and sending anything else here is rejected by this line.
    """

    model_config = ConfigDict(extra="forbid")

    eta_at: datetime | None = None


class ResolveIncidentRequest(BaseModel):
    """R4.2 — `final_cost` is required, which is where "SHALL exigir `final_cost`" lands for
    an HTTP caller. The entity requires it too, for callers that are not HTTP.

    `materials` is optional and, when it comes, is written; when it does not, whatever was
    there survives (R4.3, D7). That asymmetry with `assign`'s complete-operation semantics is
    load-bearing rather than an inconsistency: the close that trips the owner-approval gate
    writes `materials` and parks the incident, and when the owner answers the technician
    repeats the close — so a "complete operation" reading would silently erase the description
    of a spend R4.3 has just protected.

    **The bound is imported, never re-derived** (D7). `MAX_MATERIALS` lives in
    `app/maintenance/domain/entities.py`, the module that owns the column — its DDL is next
    door in that module's `infrastructure/models.py` — so a literal `2000` here would be a
    copy nobody keeps in step with either.

    `MultiLineText` is not decoration: without it a value carrying `U+0000` or an unpaired
    surrogate reaches asyncpg and surfaces as an undeclared `500`, which is the failure the
    section-7 panel of `guest-portal-api` measured twice. Multi-line rather than single, since
    a list of parts is prose a person types. `str_strip_whitespace=True` with `min_length=1` is
    what makes a whitespace-only value a `422`, and it means the maximum counts characters
    *after* stripping — so "no materials" is said by **omitting** the field, not by sending
    `""`.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    final_cost: Annotated[Decimal, Field(ge=0, le=MAX_COST, decimal_places=2)]
    materials: Annotated[
        MultiLineText, Field(min_length=1, max_length=MAX_MATERIALS)
    ] | None = None


class RespondOwnerApprovalRequest(BaseModel):
    """`POST /owner-approvals/{id}/respond` (R2.4, R2.5).

    `status` is the enum, and the entity refuses anything but `APPROVED`/`REJECTED` — the
    two an owner can give. `response_notes` is free text the owner types, bounded here and
    kept out of `audit_logs.changes` by the allowlist (D6).
    """

    model_config = ConfigDict(extra="forbid")

    status: OwnerApprovalStatus
    response_notes: Annotated[str | None, Field(max_length=MAX_RESPONSE_NOTES)] = None


class IncidentPhotoResponse(BaseModel):
    """One incident photo, and the signed URL that reads its bytes back (R3.3, design D10).

    **Every field is enumerated and the model is built by `from_upload` below — never by
    `model_validate` or `from_attributes` over the entity.** That is not style: `IncidentPhoto`
    carries `storage_key`, and a dump would publish it. R3.3 forbids the key in any response
    body or header, and the only reason this schema can be trusted is that there is no code path
    here that serialises a field nobody listed.

    `url` is what replaces it, and what it reveals depends on the tenant's backend:

    * `LOCAL` — a route of this API (`/api/v1/incident-photos/{photo_id}`) carrying the photo's
      id, its expiry and a signature. The internal path is not in it.
    * `S3` — a presigned URL minted by the object store itself, so it necessarily contains the
      bucket and the full object key. That is inherent to presigned URLs, is the single named
      exception to rule 5 of `steering/security.md`, and is accepted in writing in
      `sdd/specs/file-storage.md` and ADR 0008.

    In neither case is `storage_key` a **field** of this body, which is what R3.3 governs.
    """

    id: uuid.UUID
    incident_id: uuid.UUID
    stage: IncidentPhotoStage
    uploaded_by: uuid.UUID
    created_at: datetime
    url: str

    @classmethod
    def from_upload(cls, uploaded: "UploadedIncidentPhoto") -> "IncidentPhotoResponse":
        """Build from the use case's result, naming every field explicitly.

        Takes `UploadedIncidentPhoto` rather than an `IncidentPhoto` plus a string because the
        URL is minted per response and belongs with the photo it was minted for — passing them
        separately is how a listing ends up pairing one photo with another's URL.
        """
        photo = uploaded.photo
        return cls(
            id=photo.id,
            incident_id=photo.incident_id,
            stage=photo.stage,
            uploaded_by=photo.uploaded_by,
            created_at=photo.created_at,
            url=uploaded.url,
        )


class IncidentPhotoListResponse(BaseModel):
    """The photos of one incident, oldest first (R3.1).

    **Unpaginated, like `cleaning`'s.** A photo list is bounded by how many photos a technician
    took of one fault, which is single digits; `per_page` exists on the incident *listing*
    because that one grows with the tenant's whole history. An envelope with `items` rather than
    a bare array so the response can gain a field later without breaking every client.
    """

    items: Sequence[IncidentPhotoResponse]

    @classmethod
    def from_uploads(
        cls, uploaded: "Sequence[UploadedIncidentPhoto]"
    ) -> "IncidentPhotoListResponse":
        """Build the envelope, so the router does not map the elements itself.

        Mirrors `CleaningPhotoListResponse.build` — D10 points at that envelope as the shape to
        follow, and `steering/backend.md` wants routers thin ("La lógica nunca vive en el
        router"). Encapsulating the mapping here also means `from_upload` stays the **only** way
        an element is constructed, which is what keeps R3.3 true for the listing as well as for
        the `201`.
        """
        return cls(items=[IncidentPhotoResponse.from_upload(item) for item in uploaded])


# --- incident messages (`staff-messaging`) ----------------------------------------


class SendIncidentMessageRequest(BaseModel):
    """`POST /incidents/{incident_id}/messages` (R2, R5.1, R5.2).

    The exact shape of `app.cleaning.api.schemas.SendCleaningTaskMessageRequest`, itself the
    shape of `ResolveIncidentRequest.materials` (design D5): `storable_text` guards against a
    value asyncpg cannot store, `Field(min_length=1, max_length=...)` rejects an empty or
    oversized body as a `422` before anything reaches the use case, and
    `str_strip_whitespace=True` means the maximum counts characters *after* stripping — so a
    whitespace-only message is refused rather than persisted.

    **The bound is imported, never re-derived**: `MAX_INCIDENT_MESSAGE_LENGTH` lives in
    `app/maintenance/domain/entities.py`, the module that owns the column — its DDL is next
    door in that module's `infrastructure/models.py`.

    `MultiLineText` rather than `SingleLineText`: a staff message can span more than one line,
    the same choice `ResolveIncidentRequest.materials` makes.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: Annotated[
        MultiLineText, Field(min_length=1, max_length=MAX_INCIDENT_MESSAGE_LENGTH)
    ]


class IncidentMessageResponse(BaseModel):
    """One message of an incident's staff thread. **An allowlist, never a dump of the entity**
    (the rule this module opens with) — even though `IncidentMessage` has no field this change
    needs to exclude, `from_domain` is the only way in, the `IncidentPhotoResponse` discipline
    and not an accident.
    """

    id: uuid.UUID
    author_id: uuid.UUID
    author_role: UserRole
    content: str
    created_at: datetime

    @classmethod
    def from_domain(cls, message: IncidentMessage) -> "IncidentMessageResponse":
        return cls(
            id=message.id,
            author_id=message.author_id,
            author_role=message.author_role,
            content=message.content,
            created_at=message.created_at,
        )


class IncidentMessagePageResponse(BaseModel):
    """The envelope of PRD §23, the `CleaningTaskMessagePageResponse` pattern."""

    data: list[IncidentMessageResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(
        cls, page: IncidentMessagePage, *, page_number: int, per_page: int
    ) -> "IncidentMessagePageResponse":
        return cls(
            data=[IncidentMessageResponse.from_domain(item) for item in page.items],
            total=page.total,
            page=page_number,
            per_page=per_page,
            total_pages=(page.total + per_page - 1) // per_page if per_page else 0,
        )
