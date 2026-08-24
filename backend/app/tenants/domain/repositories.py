"""Ports of the tenants aggregate (R5.1, R5.7, design D12, D13).

Every method takes `tenant_id` explicitly and speaks in domain entities, never ORM models —
the same contract every other port in this codebase follows.

There is no `list` and no `add`: creating and listing tenants is out of scope (the MVP has one
tenant, created by the bootstrap) and PRD §23 defines neither. A speculative method here would
be surface nobody has reasoned about.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from app.tenants.domain.entities import Tenant, TenantConfig


class TenantRepository(Protocol):
    async def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        """The tenant, or `None`.

        Unscoped by nature — `tenants` has no `tenant_id` column, it IS the tenant — which is
        exactly why the use case must compare the requested id against the token's BEFORE
        calling this (design D12): `tenant_scoped_classes()` in `app/core/db.py` selects
        mappers by that column, so the global session filter does not cover this table. That
        comparison is the only protection there is.
        """
        ...

    async def apply_changes(
        self, tenant_id: uuid.UUID, values: Mapping[str, object]
    ) -> None:
        """Write only the named columns of the tenant.

        Partial by the same reasoning as `UserRepository.apply_changes` (design D21): a write
        that names only what changed cannot revert a concurrent change to a column it does not
        name. `status` and `id` are never writable through here.
        """
        ...


class TenantConfigRepository(Protocol):
    async def get_or_create(self, tenant_id: uuid.UUID, now: datetime) -> TenantConfig:
        """The tenant's configuration, created with its defaults if the row is missing (R5.7).

        Upsert rather than a plain `get` so the API does not depend on the bootstrap having
        created it: a tenant that arrived any other way still has a configuration to read and
        patch.
        """
        ...

    async def checkin_window_hours(self, tenant_id: uuid.UUID) -> int:
        """How many hours before check-in the operator's window opens, defaulted when unset.

        Added by `cleaning-stall-blocks-next-stay` for `GET /api/v1/blocked-transitions`, whose
        design D5 promises the collection "no guarda nada". `get_or_create` breaks that promise for
        a tenant whose row does not exist yet: it stages an `INSERT` on a plain `GET`, reachable by
        a role that does not hold `MANAGE_TENANT_SETTINGS`. Harmless today only because nothing on
        that path commits — the kind of safety that stops being true quietly.

        **Returns the one value its consumer needs, not a `TenantConfig`.** The first attempt
        returned a transient entity built by `TenantConfig.with_defaults(...)`, and the section-4
        panel pointed out that such an object carries a freshly minted `id` and real-looking
        timestamps, so nothing but a docstring distinguished it from a persisted row. An `int`
        cannot be mistaken for one, cannot be handed to a writer, and needs no warning.

        Falls back to `TenantConfig.checkin_window_hours_before`'s own default, referenced rather
        than repeated, so the API and a fresh tenant cannot disagree about what "unset" means.
        """
        ...

    async def apply_changes(
        self, tenant_id: uuid.UUID, values: Mapping[str, object]
    ) -> None:
        """Write only the named columns of the configuration. `storage_type` is not writable."""
        ...
