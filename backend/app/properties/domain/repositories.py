"""Ports owned by the properties domain (`reservations` design D16).

Shaped by its consumers, not by everything a property repository could eventually do
(Interface Segregation, `steering/backend-architecture.md`). It was read-only until
`celery-jobs`, whose scheduled jobs are the first writers of operational state: `save`
persists that column and nothing else, and `/api/v1/properties` still does not exist.

Every method takes `tenant_id` explicitly and returns `None` outside it. That is what
makes R1.4 answer `404` (design D6) instead of leaking the existence of a neighbour's
property, and what lets the ingest paths of R3.4/R4.2 report a row as an error rather
than aborting the batch.
"""

import uuid
from collections.abc import Collection
from typing import Protocol

from app.properties.domain.entities import Property, PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState


class PropertyRepository(Protocol):
    async def get(self, tenant_id: uuid.UUID, property_id: uuid.UUID) -> Property | None:
        """The property, only within `tenant_id` (R1.4)."""
        ...

    async def find_by_internal_code(
        self, tenant_id: uuid.UUID, internal_code: str
    ) -> Property | None:
        """Resolution for the CSV import, which names properties the way people do (D11).

        `internal_code` is unique per tenant (`uq_properties_tenant_id_internal_code`),
        so at most one row can match.
        """
        ...

    async def find_by_pms_external_id(
        self, tenant_id: uuid.UUID, pms_external_id: str
    ) -> Property | None:
        """Resolution for the PMS sync (R3.4).

        Unlike `internal_code` this column carries no uniqueness guarantee in the schema
        (`ix_properties_tenant_id_pms_external_id` is an index), so two properties of one
        tenant can share an external id. In that case this raises
        `AmbiguousPropertyExternalIdError` — a **domain** error, so the caller can report
        the row and carry on with the batch (R3.4) without importing SQLAlchemy to catch
        `MultipleResultsFound`, which the dependency rule forbids in `application/`.
        """
        ...

    async def list_by_state(
        self, tenant_id: uuid.UUID, states: Collection[PropertyOperationalState]
    ) -> list[Property]:
        """The tenant's properties currently in any of `states` (`celery-jobs` R3).

        The coarse half of design D3: it narrows the candidates a scheduled job has to
        consider, and nothing more. Whether a candidate may actually transition is
        `PropertyStateMachine`'s decision, never this query's.

        An empty `states` returns an empty list without querying — a job whose trigger
        has no source states has no candidates, and an `IN ()` is not the way to say so.
        """
        ...

    async def save(self, tenant_id: uuid.UUID, property: Property) -> None:
        """Persist `current_operational_state`, and only that (`celery-jobs` R3.6).

        Narrow on purpose. The only writer today is the state-transition use case, which
        has already had its destination approved by `PropertyStateMachine`; widening this
        to a full update would offer every future caller a way to change a property
        without passing through the machine, which `steering/backend.md` forbids
        outright ("no saltarse `PropertyStateMachine`").

        Raises `CrossTenantWriteError` when the entity belongs to another tenant.
        """
        ...


class PropertyStateTransitionRepository(Protocol):
    async def add(self, tenant_id: uuid.UUID, transition: PropertyStateTransition) -> None:
        """Append one transition to the history (`celery-jobs` R3.6).

        `add` and nothing else, for the same reason `TimelineEventRepository` has only
        `add`: a transition is a record of something that happened, and history is not
        edited. The signature is where that rule lives.

        **Precondition the caller owns**, identical to the one `TimelineEventRepository`
        already documents: `property_id` and `triggered_by_user_id` must have been
        resolved inside `tenant_id` before getting here. The adapter can check the row's
        own tenant and no more — `property_state_transitions`' foreign keys are not
        composite with `tenant_id`, so the database would happily accept a transition
        anchored to a neighbour's flat. This table is the audit record of property state
        (rule 9 of `sdd/steering/security.md`), so a misanchored row is a corrupted audit
        trail, not just a bad read.
        """
        ...
