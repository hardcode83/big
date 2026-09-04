"""Use cases of the platform module (`platform-admin-api` R1.1, R2.1, R2.3, R3.1, R3.3, design D2, D5).

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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.audit.domain import actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.value_objects import ChangeSet
from app.auth.application.user_admin import CreateUserCommand, CreateUserUseCase, _AuditWriter
from app.core.unit_of_work import UnitOfWork
from app.platform.domain.exceptions import TenantNotActiveError
from app.tenants.domain.entities import Tenant, TenantConfig
from app.tenants.domain.enums import TenantStatus
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


class CreateUserInTenantUseCase:
    """Validate a tenant and delegate user creation to `CreateUserUseCase` (R3.1, R3.3, design D3).

    The wrapper exists so `POST /api/v1/platform/tenants/{tenant_id}/users` does NOT duplicate
    the password generation, hashing, `must_change_password=True` flag, or the audit row that
    `CreateUserUseCase` already produces for the same operation in
    `POST /api/v1/users`. `user-management` (R4.3) explicitly invites this reuse: the wrapper
    validates the tenant and delegates.

    `tenant_id` is the path parameter — for `SUPER_ADMIN` (the only caller), the actor's
    session is unmarked, so the audit row's `tenant_id` comes from the wrapper's argument,
    not from the session (D5). `CreateUserUseCase.execute` takes `tenant_id` as a parameter
    for exactly that reason, and that parameter is what threads the path's id through to
    `audit_logs.tenant_id`.

    The wrapper DOES NOT commit and DOES NOT take a `UnitOfWork`. The wrapped use case owns
    its own `uow.commit()`; sharing a single `UnitOfWork` between them would create a nested
    transaction (`SAVEPOINT`) the design explicitly avoids — D3 promises "composition, not
    duplication". Section 4's `get_create_user_in_tenant_use_case` wires the inner use case
    with the same `UnitOfWork` the dependency providers pass in, so per-request commits
    collapse into the single `commit()` the `db_session` fixture / FastAPI dependency promises.
    """

    def __init__(
        self,
        *,
        tenants: TenantRepository,
        create_user: CreateUserUseCase,
    ) -> None:
        self._tenants = tenants
        self._create_user = create_user

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        command: CreateUserCommand,
        now: datetime,
    ):
        """Validate the tenant is ACTIVE and delegate to `CreateUserUseCase.execute` (R3.1, R3.3).

        A missing tenant and a non-ACTIVE tenant are the same error — `TenantNotActiveError` —
        so the response cannot leak the existence of a `SUSPENDED` row in the path's id space
        (R3.3). Both branches raise before `create_user.execute` is reached, so neither a
        `users` row nor an `audit_logs` row is written.

        On the happy path the wrapper returns whatever the wrapped use case returns, untouched.
        `CreatedUser` carries `user` and `temporary_password`; section 4's response mapper
        reads both.
        """
        tenant = await self._tenants.get(tenant_id)
        if tenant is None or tenant.status is not TenantStatus.ACTIVE:
            # Same error either way — a probe must not learn whether the tenant exists but
            # is suspended. R3.3's "indistinguishable from non-existent" is the only contract
            # the section-4 handler honours; do not introduce a second branch here.
            raise TenantNotActiveError(tenant_id=tenant_id)

        # D5: `tenant_id` here is the path parameter, not anything derived from the actor.
        # `CreateUserUseCase` uses it both for the new user's `tenant_id` column AND for the
        # audit row's `tenant_id`, so threading the path's id is what makes the audit row
        # correctly attributed to the tenant whose tenant_id the new account lives under.
        return await self._create_user.execute(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            command=command,
            now=now,
        )


@dataclass(frozen=True)
class TenantPage:
    """One page of tenants plus the total the response needs for `total_pages` (R2.1)."""

    items: Sequence[TenantSettings]
    total: int


class ListTenantsUseCase:
    """Thin pass-through over `TenantRepository.list_page` (R2.1, R2.2, R2.3, design D2).

    Same shape as `ListConversationsUseCase` (`app/messaging/application/use_cases.py:836`):
    no business rule to enforce, so there is nothing here beyond wiring the port to the
    response shape. The one thing it does add is the pairing `list_page` cannot do itself:
    the port returns `(Tenant, TenantConfig)` tuples, never `TenantSettings`, because a
    domain port must not import the application layer (`tests/test_layering.py`) — this use
    case already imports `TenantSettings` for `CreateTenantUseCase` above, so it is where the
    pair becomes the one type `TenantResponse.from_settings` maps from.
    """

    def __init__(self, *, tenants: TenantRepository) -> None:
        self._tenants = tenants

    async def execute(self, *, page: int, per_page: int) -> TenantPage:
        pairs, total = await self._tenants.list_page(page, per_page)
        return TenantPage(
            items=[TenantSettings(tenant=tenant, config=config) for tenant, config in pairs],
            total=total,
        )
