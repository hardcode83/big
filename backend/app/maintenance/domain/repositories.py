"""Ports owned by the maintenance domain (`dashboard-api` R2 design D2; `guest-portal-api` R5.5 design D15).

**Two changes met here, and the split between them is the interesting part.** `maintenance` was
"solo estructura de datos" — `domain/entities.py` plus `infrastructure/models.py`, no
`application/`, no ports — which is the shape `steering/backend-architecture.md` prescribes for a
domain without a use case yet: "Un módulo cuyas entidades existen pero que aún no tiene ningún
caso de uso nace con `domain/` + `infrastructure/` a secas".

* `dashboard-api` gave it a reason to be **read** (PRD §9.1 wants an open-incident count on every
  card, §9.2 the list on the detail) and no reason to be written, so it added `IncidentReader` and
  `OwnerApprovalReader` with **no `add`, no `save`, no `update`, no `delete`** — the same device
  `TimelineEventRepository` uses, where the signature is the boundary. Its docstring said the
  writers "arrive with the `maintenance` change".
* `guest-portal-api` needed exactly **one** of those writers first, because a guest reporting a
  fault is the first thing in the system that persists an `Incident`, and
  `sdd/specs/domain-foundation-ops.md:12` assigns the `application/` of an entity to "el change que
  primero persiste/expone la entidad". So `IncidentRepository` below is that one method and nothing
  more; the classification, assignment and resolution flows still belong to `maintenance`.

The two arrived on parallel branches and the reader half landed first, which is why the sentence
"the first port this module has ever had" is gone: it was true of each in isolation and false of
the file.

`OwnerApproval` gets its own port for the same reason `steering/backend-architecture.md`
gives — "No repositorio 'Dios' con métodos de varios agregados; un repositorio por agregado
raíz" — even though both are read by the same use case today. `IncidentRepository` is separate
from `IncidentReader` for a sharper version of it: reading and writing this aggregate are owned by
different changes, and one Protocol carrying both would have made that invisible.

Every method takes `tenant_id` explicitly and returns nothing outside it, the contract the
rest of the project uses: the parameter is the authoritative mechanism and the global loader
criteria of `app/core/db.py` are only the net.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.maintenance.domain.entities import Incident, IncidentPhoto, OwnerApproval
from app.maintenance.domain.enums import IncidentSeverity, IncidentStatus
from app.maintenance.domain.value_objects import IncidentSummary, OwnerApprovalSummary


@dataclass(frozen=True)
class IncidentFilters:
    """The filters of `GET /incidents`, combined with AND (R5.1, D14).

    `assigned_technician_id` is **not** a client-supplied filter dressed up as one: the use
    case sets it from the authenticated role when that role is `TECHNICIAN`
    (`IncidentActor.restrict_to_technician_id`, D13), so the row-level restriction of R5.3
    cannot be dropped by omitting a query parameter. Same construction `cleaning` uses for
    `CleaningTaskFilters.assigned_cleaner_id`, and for the same reason.
    """

    property_id: uuid.UUID | None = None
    status: IncidentStatus | None = None
    severity: IncidentSeverity | None = None
    assigned_technician_id: uuid.UUID | None = None


@dataclass(frozen=True)
class IncidentPage:
    """One page of results plus the total the client needs for `total_pages` (PRD §23)."""

    items: tuple[Incident, ...]
    total: int


class IncidentReader(Protocol):
    """Read-only. Named `Reader` rather than `Repository` so the absence of writers is
    visible at the call site and not only in this file."""

    async def count_open_for_properties(
        self, tenant_id: uuid.UUID, property_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """How many open incidents each property has, in ONE query (R1.7).

        Keyed by `property_id`. **A property with none is absent from the mapping** rather
        than mapped to `0` — the caller already has to default for a property it did not
        ask about, and returning a dense mapping would make the two cases indistinguishable
        from a bug that dropped rows.

        "Open" is `OPEN_INCIDENT_STATUSES` (`app/maintenance/domain/entities.py`), which is
        an `ASSUMPTION`: the PRD asks for the count without defining where the line falls.
        It is not a parameter, because a caller choosing its own statuses would be a second
        copy of that decision.

        An empty `property_ids` returns an empty mapping without querying.

        Answers `{}` today for every tenant, because nothing writes `incidents` yet. That is
        the correct answer and not a stub (design D9): the contract does not change when
        `maintenance` lands, only the data.
        """
        ...

    async def list_open_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[IncidentSummary]:
        """The open incidents of one property, newest first (R2.1, PRD §9.2).

        **Returns `IncidentSummary`, not `Incident`** — see that class for why the free-text
        and identifier fields are structurally out of reach here rather than filtered out
        downstream. It is the `GuestSummary` construction, applied to the same problem.

        Unpaginated on purpose: it feeds a detail panel, and a property with enough open
        incidents to need paging is an operational emergency rather than a UI problem.
        """

    async def list_open_for_properties(
        self, tenant_id: uuid.UUID, property_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, uuid.UUID]:
        """The **newest** open incident id per property, in ONE query (`blocked-transition-response-ids` R3.4).

        Returns `dict[property_id, incident_id]` — **only the id, not a summary** —
        because the only consumer today is `ActionIdResolver`, which needs the id to
        populate the `BlockedTransitionResponse.cleaning_task_id` / `incident_id` fields
        (R1.3: the wire format is a UUID string or `null`, never `category`/`severity`/
        `opened_at`). This is the "puertos pequeños y por rol" rule of
        `steering/backend-architecture.md` in action: the sibling `count_open_for_properties`
        returns `dict[property_id, int]` for the same reason.

        Sibling of `count_open_for_properties` — same sparse-mapping convention: a property
        with no open incident is **absent** from the dict, not mapped to `None`. The caller
        already defaults to "no incident" for a property it did not ask about, and a dense
        mapping would make the two cases indistinguishable from a bug that dropped rows.

        Newest first per property (`created_at DESC, id DESC` tiebreak); the caller picks
        the one that surfaces in the dashboard's action button. Subsequent open incidents on
        the same property are not exposed: the dashboard only has one button per stall, and
        "the first one" is a deterministic choice that matches how the collection orders.

        Empty `property_ids` returns an empty mapping without querying.
        """
        ...


class IncidentQuery(Protocol):
    """The reads that return **entities**, for the consumers inside `maintenance`.

    Separate from `IncidentReader` above, and the separation is the point:
    `steering/backend-architecture.md` asks for "puertos pequeños y por rol… divide por
    consumidor real", and these two have different real consumers. `IncidentReader` serves
    the dashboard, which by `dashboard-api`'s own security decision may only ever see
    projections; this one serves this module's `api/` and the state machine, which need the
    aggregate. One Protocol carrying both would have made the dashboard's structural
    guarantee an accident of which method a caller happened to pick.

    The adapter implements both, because one class over one table is not two adapters —
    what is split is the contract, which is where the rule bites. Raised by the architecture
    panel of section 5.
    """

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: IncidentFilters,
        *,
        page: int,
        per_page: int,
    ) -> IncidentPage:
        """The paginated listing of `GET /incidents` (`maintenance` R5.1).

        **Returns whole `Incident` entities and not `IncidentSummary`**, which is the
        difference `value_objects.py` predicted: the dashboard may know only what is wrong
        and how badly, while this module owns the surface a technician works from, and a
        technician has to read the description of the fault. The redaction that goes with
        owning that surface lives in `api/schemas.py`, where the audience is known.

        **`reported_by_guest_token` is never hydrated by any reader of this module** — see
        `IncidentRepository.get`.
        """
        ...

    async def list_pending_classification(
        self, tenant_id: uuid.UUID, *, limit: int
    ) -> Sequence[Incident]:
        """The candidates of the classification job (design D2, D3).

        **`status = OPEN AND ai_classification IS NULL`, and that pair is the whole rule.**
        It gives the two properties D3 needs at once: an incident whose adapter failed comes
        back on the next tick, because nothing was written; and one the adapter did look at
        and was unsure about does **not**, because `ai_classification` is set even below the
        threshold. Without the second half a deterministic adapter would be asked the same
        question for ever and answer the same way.

        Oldest first, and `limit`ed: a tenant whose classifier was down all night must not
        turn one tick into an unbounded run.
        """
        ...

    async def list_active_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[Incident]:
        """Every non-terminal incident of the property (design D7).

        Entities, because `PropertyStateMachine` reads `severity`, `status`, `tenant_id` and
        `property_id` off them — a projection would have to guess which fields the machine
        will need next.

        **All of them, not just the one being changed**: `after_incident_resolution`
        decides between `CRITICAL_INCIDENT`, `MAINTENANCE_REQUIRED` and the contextual
        states by looking at what is *still* open, so a caller that passed only the incident
        it just resolved would release a property that still has a critical fault.
        """
        ...


class OwnerApprovalReader(Protocol):
    async def list_pending_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[OwnerApprovalSummary]:
        """The approvals still awaiting an answer, oldest request first (PRD §9.2).

        **Returns `OwnerApprovalSummary`, not `OwnerApproval`**, for the reason its sibling
        records: `reason` and `response_notes` are free text and have no business in a
        dashboard payload.

        Oldest first and not newest: this is a to-do list, so the one that has been waiting
        longest is the one that matters. The timeline is the surface that reads newest-first.
        """
        ...


class IncidentRepository(Protocol):
    """The write side (`guest-portal-api` R5.5 design D15, widened by `maintenance` D5).

    It was one method — `add` — for as long as reporting a fault was the only thing that
    wrote `incidents`. `guest-portal-api` named the cost in its own design Risks ("whoever
    brings AI classification may find a port that does not serve it") and chose it
    deliberately: "a one-method port is cheaper to widen than a speculative ten-method one
    is to narrow". This is that widening, and it is still small — `get` and `save`, because
    the flow reads one incident, mutates it through its own methods and writes it back.

    Reading *collections* stays on `IncidentReader`: the split is by role, not by table.
    """

    async def add(self, tenant_id: uuid.UUID, incident: Incident) -> None:
        """Append an incident for the acting tenant. Never commits — the use case owns the
        transaction, which is what makes the incident and its audit row atomic (R6.2).

        **Precondition the caller must honour**: `property_id`, `reservation_id` and
        `cleaning_task_id` must already have been resolved *within* `tenant_id`. The foreign
        keys of `incidents` are global rather than composite with `tenant_id`, so the database
        would accept an incident of tenant A anchored to a property — or a cleaning task — of
        tenant B, and this port cannot detect it without a query of its own; the same
        precondition `TimelineEventRepository` states, for the same schema reason.

        `cleaning_task_id` joined the list in `cleaner-incident-report` and carries the
        identical characteristic, which is why it is named here rather than left to be
        inferred from the two beside it (raised by that change's tenancy panel of section 1).
        Its caller discharges the precondition by composition: the id is that of a task the
        cleaning use case already loaded with an explicit `tenant_id` before this port ever
        sees it. The guest portal satisfies its own two structurally — both ids come from the
        `GuestSession` the portal's authoriser resolved from the token, never from the
        request (R2.1).
        """
        ...

    async def get(self, tenant_id: uuid.UUID, incident_id: uuid.UUID) -> Incident | None:
        """The incident, or `None` when it does not exist **within this tenant**.

        Returning `None` rather than raising keeps the 404 decision in the use case, which
        is also where the row-level restriction of R5.3 applies — and R5.3 needs the two to
        be indistinguishable, so the port must not answer differently for "unknown" and
        "not yours".

        **`reported_by_guest_token` is never hydrated**, by this method or by any read of
        `IncidentQuery`: nothing in this flow reads it, and it is a stable unsalted digest
        that correlates one guest's stay across properties — the field
        `IncidentSummary`'s docstring names when it explains why the dashboard was given a
        projection. It comes back `None` however the row is stored, and that is not lossy:
        no writer of this port touches the column, so what the guest portal wrote survives.
        Stated here rather than only in the adapter, because a contract a caller cannot read
        is not a contract. Raised by the architecture panel of section 5.
        """
        ...

    async def save(self, tenant_id: uuid.UUID, incident: Incident) -> None:
        """Persist the mutations the entity's own methods made. Never commits.

        The whole flow of R1-R4 goes through here, so this is the one write path that has
        to stay atomic with the `AuditLog` and the `TimelineEvent` of R6.1 — which is
        exactly why it does not commit.
        """
        ...


class OwnerApprovalRepository(Protocol):
    """Its own port, not a method on the incident's (design D6, D11).

    "No repositorio 'Dios' con métodos de varios agregados; un repositorio por agregado
    raíz" (`steering/backend-architecture.md`) — and here the separation is load-bearing
    rather than tidy: one incident can raise two approvals, D11's budget gate and its
    real-cost gate, so the approval has an identity the incident cannot stand in for.
    """

    async def get(
        self, tenant_id: uuid.UUID, approval_id: uuid.UUID
    ) -> OwnerApproval | None:
        """The approval, or `None` outside this tenant (R2.6, "ni responder una de otro
        tenant")."""
        ...

    async def add(self, tenant_id: uuid.UUID, approval: OwnerApproval) -> None:
        """Open a gate. Never commits — the approval, the incident's new status, the audit
        row and the owner's notification are one transaction (R6.1)."""
        ...

    async def save(self, tenant_id: uuid.UUID, approval: OwnerApproval) -> None:
        """Record the answer. Never commits, for the reason `add` gives."""
        ...

    async def find_approved_for_incident(
        self, tenant_id: uuid.UUID, incident_id: uuid.UUID
    ) -> Sequence[OwnerApproval]:
        """Every `APPROVED` approval raised against that incident, newest answer first.

        What D11's "cubierto por una aprobación aprobada" is checked against when the
        technician closes with a `final_cost`. A sequence and not one row: the budget gate
        and the real-cost gate can both have been approved, and which one covers the bill
        is the caller's arithmetic, not this port's.
        """
        ...


class IncidentPhotoRepository(Protocol):
    """The photos of one incident: append one, list that incident's (`incident-photos` R1, R3).

    **Two methods, and each has a caller in this change** — `add` from
    `UploadIncidentPhotoUseCase`, `list_for_incident` from `ListIncidentPhotosUseCase`. No
    `get`, no `delete`: the proposal keeps every deletion surface out of scope, and the only
    caller of `FileStoragePort.delete` remains the compensating delete of a failed transaction,
    which works from a key it already holds and never needs to read a row back. A port sized
    for what the table could eventually support is the Interface Segregation failure
    `steering/backend-architecture.md` names by hand.

    **Every method takes `tenant_id` first**, like every other port here. That is the mechanism;
    the global filter of `app/core/db.py` — which `incident_photos` is inside, because the row
    carries its own `tenant_id` (design D2) — is the net behind it.

    The one read that does *not* take a tenant is deliberately not on this port: it is
    `UnscopedObjectLocationQuery` in `app/integrations/domain/storage.py`, implemented by a
    class of its own so that no authenticated use case holding this repository can reach it by
    accident (design D13). Putting it here would be the fifth-method mistake `cleaning`'s
    equivalent port documents.
    """

    async def add(self, tenant_id: uuid.UUID, photo: IncidentPhoto) -> None:
        """Append one photo. **Never commits** — the row, the object and the audit entry are
        one transaction, and the use case owns its boundary (design D7).

        Several photos of the same incident and the same `stage` are legal and expected (R1.4):
        a technician photographs two angles of the same fault, so there is no uniqueness to
        violate and this never raises for a duplicate.

        **Precondition the caller owns, stated because nothing here can check it**:
        `photo.uploaded_by` must be a user of `tenant_id`. It is a plain `uuid.UUID` and the
        column is a plain foreign key to `users.id` with no tenant qualification — the same
        shape, and the same deliberate omission, as `cleaning_photos.uploaded_by` — so a value
        from another tenant would be persisted verbatim. What makes it safe is that the only
        caller derives it from the **verified token** (`IncidentActor.user_id`) and never from
        the request body, exactly as `IncidentRepository.add` documents its own preconditions
        on `property_id` and `cleaning_task_id`. Raised by the tenancy panel of section 3, so
        that the guarantee is written where an implementer of this port will read it rather
        than inferred from the one call site that happens to be correct today.
        """
        ...

    async def list_for_incident(
        self, tenant_id: uuid.UUID, incident_id: uuid.UUID
    ) -> Sequence[IncidentPhoto]:
        """That incident's photos, **oldest first** (R3.1).

        The order is part of the contract and not a convenience: the two stages are `BEFORE`
        and `AFTER`, so upload order is what tells the story, and a reader comparing the first
        photo with the last is doing the thing the listing exists for. Ordered in the database
        by `created_at` then `id`, because `created_at` is written by the use case and two
        photos of one upload burst can share a timestamp.

        An empty sequence for an incident with no photos — and also for one that is not this
        tenant's, though the caller never gets that far: it resolves the incident through
        `_load_incident_in_scope` first, which is what makes the `404` of R3.4
        indistinguishable across its three cases.
        """
        ...
