"""The port that makes an incident persistent (R5.5, design D15).

**`maintenance` gets its `application/` here, and only what this surface needs.**
`sdd/specs/domain-foundation-ops.md:12` establishes that the `application/` and the `api/` of
an entity are added by "el change que primero persiste/expone la entidad", and for `Incident`
that change is `guest-portal-api`. So this is the convention rather than an incursion into
another module's scope — but the convention says *who adds it*, not *how much*.

**One method, `add`, and the narrowness is the decision** (D15). Listing, assigning,
classifying and resolving are `maintenance`'s own flow, and a port that declared them would
be an open door for the next caller: interface segregation means dividing by the real
consumer, and the real consumer here reports one incident and never reads one back.
`steering/backend-architecture.md` puts it as "puertos pequeños y por rol".

The cost is named in the change's design Risks: the change that brings AI classification may
find a port that does not serve it. A one-method port is cheaper to widen than a speculative
ten-method one is to narrow.
"""

import uuid
from typing import Protocol

from app.maintenance.domain.entities import Incident


class IncidentRepository(Protocol):
    async def add(self, tenant_id: uuid.UUID, incident: Incident) -> None:
        """Append an incident for the acting tenant. Never commits — the use case owns the
        transaction, which is what makes the incident and its audit row atomic (R6.2).

        **Precondition the caller must honour**: `property_id` and `reservation_id` must
        already have been resolved *within* `tenant_id`. The foreign keys of `incidents` are
        global rather than composite with `tenant_id`, so the database would accept an
        incident of tenant A anchored to a property of tenant B, and this port cannot detect
        it without a query of its own — the same precondition `TimelineEventRepository`
        states, for the same schema reason. The one caller in this change satisfies it
        structurally: both ids come from the `GuestSession` the authoriser resolved from the
        token, never from the request (R2.1).
        """
        ...
