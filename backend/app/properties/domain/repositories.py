"""Ports owned by the properties domain (design D16).

Read-only on purpose. This change needs to *resolve* a property — by id from the API,
by `internal_code` from a CSV, by `pms_external_id` from the PMS — and nothing more;
writing properties belongs to the change that introduces `/api/v1/properties`.
Interface Segregation (`steering/backend-architecture.md`): the port is shaped by its
consumers, not by everything a property repository could eventually do.

Every method takes `tenant_id` explicitly and returns `None` outside it. That is what
makes R1.4 answer `404` (design D6) instead of leaking the existence of a neighbour's
property, and what lets the ingest paths of R3.4/R4.2 report a row as an error rather
than aborting the batch.
"""

import uuid
from typing import Protocol

from app.properties.domain.entities import Property


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
