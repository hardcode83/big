"""Ports owned by the maintenance domain (`dashboard-api` R2, design D2).

**The first port this module has ever had, and it is read-only on purpose.** `maintenance`
has been "solo estructura de datos" — `domain/entities.py` plus `infrastructure/models.py`,
no `application/`, no ports — which is the shape `steering/backend-architecture.md`
prescribes for a domain without a use case yet: "Un módulo cuyas entidades existen pero que
aún no tiene ningún caso de uso nace con `domain/` + `infrastructure/` a secas".

`dashboard-api` gives it a reason to be read (PRD §9.1 wants an open-incident count on every
card, §9.2 the list on the detail) and no reason to be written. So this port has **no `add`,
no `save`, no `update`, no `delete`**, and that is the same device `TimelineEventRepository`
uses: the signature is where the boundary lives. Incident creation, classification,
assignment and resolution arrive with the `maintenance` change, which owns the writers and
the invariants that go with them — this file must not pre-empt any of it.

`OwnerApproval` gets its own port for the same reason `steering/backend-architecture.md`
gives — "No repositorio 'Dios' con métodos de varios agregados; un repositorio por agregado
raíz" — even though both are read by the same use case today.

Every method takes `tenant_id` explicitly and returns nothing outside it, the contract the
rest of the project uses: the parameter is the authoritative mechanism and the global loader
criteria of `app/core/db.py` are only the net.
"""

import uuid
from collections.abc import Sequence
from typing import Protocol

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
