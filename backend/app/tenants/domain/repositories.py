"""Ports of the tenants aggregate (R5.1, R5.7, design D12, D13).

Every method takes `tenant_id` explicitly and speaks in domain entities, never ORM models —
the same contract every other port in this codebase follows.

`list_page` (`super-admin-console` R2) is the first method with no `tenant_id` at all: it is
reached only through `SUPER_ADMIN`/`MANAGE_PLATFORM` (`app.platform.api.dependencies`), the
one caller for whom "every tenant" is the correct scope rather than a leak. `add` was the
prior deliberate exception, added by `platform-admin-api` (R1.2) for the API that introduced
it.
"""

import uuid
from collections.abc import Mapping, Sequence
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

    async def add(self, tenant: Tenant, config: TenantConfig) -> None:
        """Persist a brand-new tenant and its default configuration in one call (R1.2).

        The repository is the one place that knows the two rows are inseparable: a `tenants`
        row without a `tenant_configs` row is the broken half-state `bootstrap.py` documents
        and that the cross-checks of `auth-tenancy` reject (R5.7). One call, one flush, one
        place to translate the unique-constraint violation that the migration
        `936fef5a01b1_tenants_name_unique.py` introduces (R-2).

        `tenant.id` and `config.id` are taken as-is — the entity is the source of truth for
        the pair, and the use case that builds them is the one that also writes the audit
        row pointing at the same ids. No method commits: the use case is the transactional
        boundary, exactly as `apply_changes` above.
        """
        ...

    async def list_page(
        self, page: int, per_page: int
    ) -> tuple[Sequence[tuple[Tenant, TenantConfig]], int]:
        """Every tenant, one page, each paired with its configuration (R2.1, R2.2, R2.3).

        Ordered `created_at DESC`, no filter and no `tenant_id` argument: `SUPER_ADMIN` has
        no tenant of its own, so there is nothing to scope by — every tenant is
        platform-visible to the one caller allowed to reach this method.

        Paired with its `TenantConfig` in the same query rather than returning a bare
        `Tenant`: a `tenants` row without a `tenant_configs` row cannot exist (`add` always
        writes both in the same transaction), so the join costs nothing and the caller does
        not need a `get_or_create` per row just to build the response the platform API
        returns (`TenantResponse` nests the configuration). The pair is a plain `tuple` and
        not the application layer's `TenantSettings` — a domain port must not import
        `app.tenants.application.use_cases` (`tests/test_layering.py`); the use case that
        calls this method is what wraps each pair into one.

        Returns `(rows, total)`, the same shape `ConversationRepository.list` returns.

        The adapter guards this query with `require_unmarked_session` (`app/core/db.py`):
        `TenantConfig`'s table carries a `tenant_id` column, so a marked session would
        silently narrow the join to one tenant instead of raising — the same silent-wrong-
        answer shape the guard exists to convert into a loud failure.
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
