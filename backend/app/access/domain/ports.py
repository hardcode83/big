"""The access provider port of PRD §15 (`access-notifications` design D12).

> AutoHostAI **NO** controla GrinPass directamente. El acceso es gestionado externamente por
> GrinPass a través del PMS. (PRD §15)

That sentence is the whole shape of this port. We do not create codes, we do not open doors,
and we do not read door events — `steering/architecture.md` lists "lógica dependiente de
eventos de apertura de puerta" among the outright anti-patterns. What an adapter does is
tell us the state of an access the provider owns, and give us a way to record one a human
arranged by hand.

**The provider is an open decision, and this port is what protects it.**
[ADR 0006](../../../../docs/adr/0006-pms-channel-manager-provider.md) decision 5 reopened
what PRD §5.5 had closed: GrinPass has no public API *yet* but is receptive, and Beds24
brings TTLock/Nuki plus an Arrivals API. Nothing above this interface may assume which way
it goes; the MVP runs on `ManualAccessAdapter`.

`async`, unlike PRD §15's signatures, for the same reason as `NotificationAdapter`: a real
provider means a network round trip and this backend is async throughout.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.access.domain.entities import AccessRecord
from app.access.domain.enums import AccessRecordStatus


@dataclass(frozen=True)
class AccessStatusResult:
    """What a provider says about an access it owns.

    `code_masked` and not `code`: PRD §15 has the provider deliver the code to the guest, so
    there is no path on which we need the value — and rule 4 of `sdd/steering/security.md`
    would mask it the moment it landed anywhere of ours anyway.
    """

    status: AccessRecordStatus
    external_id: str | None = None
    code_masked: str | None = None


class AccessProviderAdapter(Protocol):
    async def get_access_status(
        self, reservation_external_id: str
    ) -> AccessStatusResult | None:
        """The provider's view of the access for a reservation, or `None` if it has none.

        `None` rather than an exception: "the provider does not know this booking" is an
        ordinary answer during the window between a booking arriving and the provider
        importing it, not a failure.
        """
        ...

    async def create_manual_access(
        self, *, record: AccessRecord, code: str, notes: str | None, now: datetime
    ) -> AccessRecord:
        """Record a code an operator arranged out of band (PRD §15, `ManualAccessAdapter`).

        Takes the entity and returns it moved, so the state machine of design D14 stays the
        only place a transition happens. The `code` argument dies inside: the entity masks it
        and no implementation may keep it.
        """
        ...

    async def mark_external_managed(
        self, *, record: AccessRecord, notes: str | None, now: datetime
    ) -> AccessRecord:
        """Record that the provider created and owns this access."""
        ...


class LegalRegistrationInitialiser(Protocol):
    """PRD §17 step 1, as a port so the access reconciler does not import the guests module.

    A one-method port rather than the whole guests repository: `steering/backend-
    architecture.md`'s I — "puertos pequeños y por rol". The reconciler needs to say "this
    stay now needs guest data" and nothing else, and the implementation lives in `guests/`
    where the column does.

    Why the access sweep owns the call at all (design D2): PRD §17 step 1 and PRD §15's
    `AccessRecord` are triggered by the same event — a reservation being confirmed — and both
    have to cover the stays that were already confirmed before this change existed. One sweep
    answering "what has this confirmed stay not been given yet?" cannot get out of step with
    itself; two jobs over the same rows can.
    """

    async def initialise(
        self, *, tenant_id: uuid.UUID, reservation_id: uuid.UUID, now: datetime
    ) -> bool:
        """Move a reservation to `PENDING_GUEST_DATA`; `True` if it actually moved."""
        ...
