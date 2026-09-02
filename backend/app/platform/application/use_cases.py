"""Use cases of the platform module (`platform-admin-api` R1.1, R2.1, R2.3, design D2, D5).

One use case is one business operation and one transaction: it orchestrates the aggregate and
its ports and calls `commit()` exactly once. No business rule lives here — the invariants are
in `Tenant` and in `TenantConfig.with_defaults` — and no `sqlalchemy` import either, which
`tests/test_layering.py` enforces for this layer.

The seam `_AuditWriter` from `app.auth.application.user_admin` is the chokepoint that builds
every `AuditLog` in this codebase, so use cases of this module go through it the same way
`CreateUserUseCase` does: an `AuditLog` constructed by hand would bypass rule 9 of
`steering/security.md` (the closed `action`/`entity_type` vocabulary) and rule 11 (the
`ChangeSet` allowlist + denylist) by definition.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.audit.domain import actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.value_objects import ChangeSet
from app.auth.application.user_admin import _AuditWriter
from app.core.unit_of_work import UnitOfWork
from app.tenants.domain.entities import Tenant, TenantConfig
from app.tenants.domain.repositories import TenantConfigRepository, TenantRepository


@dataclass(frozen=True)
class CreateTenantCommand:
    """What `POST /api/v1/platform/tenants` will accept (R1.1).

    No `status`: a tenant is born `ACTIVE` (`Tenant.create` decides that, design D2).
    No `tenant_id`: the system mints one. The five fields are the same ones `Tenant.update`
    accepts, on purpose — they are the same columns `tests/tenants/test_entities.py` already
    vetted through `Tenant.create`'s normalisers, and re-using them keeps the boundary
    `Tenant` enforces ("every guard is the same function `update` uses").
    """

    name: str
    billing_email: str
    country: str = "ES"
    timezone: str = "Europe/Madrid"
    default_language: str = "es"


# Re-export so the API and tests have one canonical import for the result type.
from app.tenants.application.use_cases import TenantSettings  # noqa: E402


class CreateTenantUseCase:
    def __init__(
        self,
        *,
        tenants: TenantRepository,
        configs: TenantConfigRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._tenants = tenants
        # `configs` is reserved for future use by `GetTenantSettingsUseCase`-style reads over
        # the just-created tenant; section 4 will wire that into the API. Holding it here keeps
        # the constructor signature the task specifies, and lets the next section reuse the
        # same dependency wiring without revisiting this file.
        self._configs = configs
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        command: CreateTenantCommand,
        now: datetime,
    ) -> TenantSettings:
        """Create an ACTIVE tenant and its default configuration, audit both as one row (R1.1, R2.1).

        The order matters and is part of the contract:

        1. `Tenant.create` mints the entity, running every normaliser `Tenant.update` would
           run on a PATCH. A bad value raises `TenantValidationError` here, **before** any
           row reaches the database — which is what keeps the 422 envelope of R1.3 honest.
        2. `TenantConfig.with_defaults` builds the configuration row the bootstrap would have
           built. The pair (`tenant`, `config`) is the unit of work `TenantRepository.add`
           is designed to persist.
        3. `tenants.add` does the two `session.add` calls and the single `flush` that
           surfaces `uq_tenants_name` as a `TenantAlreadyExistsError` (R-2). On that error,
           the use case does **not** commit and the exception propagates unwrapped so the
           section-4 handler maps it to `409`.
        4. The audit row is written **before** `commit()` so the failure of step 5 leaves no
           orphan tenant (R2.3, R4.2). `tenant_id` and `entity_id` here come from the NEW
           tenant's id — design D5's whole point: a `SUPER_ADMIN`'s session is unmarked, so
           the audit row's `tenant_id` cannot come from the session; it must come from the
           use case, and the use case sets it from the entity being audited.
        5. `uow.commit()` lands all three writes in one transaction. If any prior step
           raised, this line is never reached and the transaction aborts.

        Returns the same `TenantSettings` the tenants module's get/update use cases return,
        so the section-4 response mapper can be shared.
        """
        tenant = Tenant.create(
            name=command.name,
            billing_email=command.billing_email,
            now=now,
            country=command.country,
            timezone=command.timezone,
            default_language=command.default_language,
        )
        config = TenantConfig.with_defaults(tenant_id=tenant.id, now=now)

        await self._tenants.add(tenant, config)

        # D5: `audit_logs.tenant_id` is the entity's, not the actor's. For this use case the
        # actor is `SUPER_ADMIN` (no tenant) and the entity IS a tenant, so the two are
        # unrelated. Reading the new tenant's id rather than the actor's id is what makes
        # `AuditLogFactory.build` accept the row (`tenant_id` is `uuid.UUID`, not
        # `Optional`).
        await self._audit.record(
            tenant_id=tenant.id,
            action=actions.TENANT_CREATED,
            entity_type=actions.ENTITY_TENANT,
            entity_id=tenant.id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            changes=(
                ChangeSet(actions.ENTITY_TENANT)
                .diff("name", None, tenant.name)
                .diff("billing_email", None, tenant.billing_email)
                .diff("country", None, tenant.country)
                .diff("timezone", None, tenant.timezone)
                .diff("default_language", None, tenant.default_language)
            ),
            now=now,
        )

        await self._uow.commit()
        return TenantSettings(tenant=tenant, config=config)
