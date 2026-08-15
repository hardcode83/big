"""The two ports `maintenance` owns beyond persistence (design D1, D7).

Both are one method, which is what `steering/backend-architecture.md` asks for — "puertos
pequeños y por rol, no un `StorageAdapter` gigante con 15 métodos si un caso de uso solo
necesita `get_signed_url`. Divide por consumidor real" — and the same size
`guest-portal-api` gave `IncidentRepository.add`.

`LiveCleaningTaskQuery` is the mirror image of `BlockingIncidentQuery`
(`app/cleaning/domain/ports.py`), which `cleaning` declared to read *our* aggregate for one
precondition. The import direction is the one that module already uses: the domain that
needs the answer declares the port, and the other side's infrastructure is never imported.
"""

import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from app.maintenance.domain.value_objects import IncidentClassification

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.cleaning.domain.entities import CleaningTask


class IncidentClassifier(Protocol):
    async def classify(
        self, *, title: str, description: str
    ) -> IncidentClassification:
        """Read the reported text and say what kind of fault it is (R1.1).

        **The `summary` it returns is the adapter's own words and never an echo of `title`
        or `description`** — this is the contract design D4 fixes, and it is a security
        obligation rather than a style preference. `incidents.ai_summary` is a rule-11 sink
        of `sdd/steering/security.md` under the **structured form by default**, not under
        excepción 2: that exception covers "la prosa que escribió quien reporta... porque
        el valor no es nuestro y no lo hemos ido a buscar", and says of itself that it
        "**No autoriza a un escritor nuestro**". A classifier is our writer, working from
        text an anonymous guest typed, so an adapter that paraphrases the description
        copies whatever the guest put in it — a document number, a code — into a column
        nobody declared.

        **This is enforced, not requested**: declare the closed set in the returned
        `IncidentClassification.vocabulary`, which refuses a `summary` outside it. Prose here
        used to be the whole obligation, and prose does not survive a second implementation.

        `confidence` is a `0..1` fraction compared against
        `TenantConfig.ai_confidence_threshold`; `IncidentClassification` refuses anything
        outside that range.

        **Raising is a supported outcome** (R1.6): the caller leaves the incident in `OPEN`
        with `ai_classification` unwritten, so the job of D2 picks it up again on the next
        tick. An adapter must not invent a low-confidence verdict to avoid failing —
        that would make the failure indistinguishable from a real "I do not know", which
        D3 relies on telling apart.
        """
        ...


class LiveCleaningTaskQuery(Protocol):
    async def list_live_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence["CleaningTask"]:
        """The cleaning tasks of that property that are still alive (design D7).

        Needed because `ContextualStateResolver.after_incident_resolution` falls through to
        `_contextual_reservation_cleaning`, which reads `context.cleaning_tasks` **and**
        `context.reservations`: without this collection a property with a pending cleaning
        leaves `MAINTENANCE_REQUIRED` for `VACANT_READY` instead of `AWAITING_CLEANING`,
        and nothing fails — the destination is merely wrong.

        Entities and not a projection, because the state machine reads their fields.
        "Alive" is `cleaning`'s own `LIVE_STATUSES`: this port asks that module's question
        in that module's vocabulary rather than restating it here.
        """
        ...
