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
from typing import Protocol

from app.maintenance.domain.entities import Incident
from app.maintenance.domain.value_objects import IncidentSummary, OwnerApprovalSummary


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
    """The write side, and deliberately one method (`guest-portal-api` R5.5, design D15).

    Listing, assigning, classifying and resolving are `maintenance`'s own flow — and reading is
    `IncidentReader` above — so this port declares `add` and nothing else. A port that declared
    the rest would be an open door for the next caller: interface segregation means dividing by
    the real consumer, and the real consumer here reports one incident and never reads one back.
    `steering/backend-architecture.md` puts it as "puertos pequeños y por rol".

    The cost is named in that change's design Risks: whoever brings AI classification may find a
    port that does not serve it. A one-method port is cheaper to widen than a speculative
    ten-method one is to narrow.
    """

    async def add(self, tenant_id: uuid.UUID, incident: Incident) -> None:
        """Append an incident for the acting tenant. Never commits — the use case owns the
        transaction, which is what makes the incident and its audit row atomic (R6.2).

        **Precondition the caller must honour**: `property_id` and `reservation_id` must
        already have been resolved *within* `tenant_id`. The foreign keys of `incidents` are
        global rather than composite with `tenant_id`, so the database would accept an
        incident of tenant A anchored to a property of tenant B, and this port cannot detect
        it without a query of its own — the same precondition `TimelineEventRepository`
        states, for the same schema reason. The one caller today satisfies it structurally:
        both ids come from the `GuestSession` the portal's authoriser resolved from the token,
        never from the request (R2.1).
        """
        ...
