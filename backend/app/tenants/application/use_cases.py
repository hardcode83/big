"""Use cases of the tenant configuration (R5, design D12, D13).

One use case is one business operation and one transaction. No `sqlalchemy` import, which
`tests/test_layering.py` enforces for this layer.

The tenant of the path is compared against the tenant of the token **before** any query
(design D12): `tenants` has no `tenant_id` column, so `tenant_scoped_classes()` in
`app/core/db.py` does not cover that table and the global session filter offers nothing here.
This comparison is the only protection, which is why it has its own test (R7.9).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.audit.domain import actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.core.unit_of_work import UnitOfWork
from app.tenants.domain.entities import Tenant, TenantConfig
from app.tenants.domain.exceptions import TenantNotFoundError
from app.tenants.domain.repositories import TenantConfigRepository, TenantRepository

TENANT_FIELDS = ("name", "billing_email", "country", "timezone", "default_language")


@dataclass(frozen=True)
class TenantSettings:
    """What the endpoints return: one resource, the config nested (design D13)."""

    tenant: Tenant
    config: TenantConfig


def _require_own_tenant(*, requested: uuid.UUID, acting: uuid.UUID) -> None:
    """R7.9. Raised before touching the database, so the answer costs nothing to give.

    A `404` and not a `403`: a caller must not be able to confirm that another tenant exists by
    asking for it.
    """
    if requested != acting:
        raise TenantNotFoundError("Tenant does not exist")


class GetTenantSettingsUseCase:
    def __init__(
        self, *, tenants: TenantRepository, configs: TenantConfigRepository
    ) -> None:
        self._tenants = tenants
        self._configs = configs

    async def execute(
        self, *, tenant_id: uuid.UUID, requested_id: uuid.UUID, now: datetime
    ) -> TenantSettings:
        _require_own_tenant(requested=requested_id, acting=tenant_id)
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            # The token named a tenant that no longer exists. `auth-tenancy` revalidates the
            # tenant on every request, so reaching this means it was deleted mid-request.
            raise TenantNotFoundError("Tenant does not exist")
        config = await self._configs.get_or_create(tenant_id, now)
        return TenantSettings(tenant=tenant, config=config)


class UpdateTenantSettingsUseCase:
    def __init__(
        self,
        *,
        tenants: TenantRepository,
        configs: TenantConfigRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._tenants = tenants
        self._configs = configs
        self._audit = audit
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        requested_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        tenant_changes: dict[str, object],
        config_changes: dict[str, object],
        now: datetime,
    ) -> TenantSettings:
        """Patch the tenant and/or its configuration, auditing each separately (R5.2, R5.8).

        Two audit rows at most, one per entity, because `audit_logs.entity_id` points at one
        row: a single entry could not name both the tenant and its config. A patch that changes
        nothing writes neither (design D15).
        """
        _require_own_tenant(requested=requested_id, acting=tenant_id)

        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("Tenant does not exist")
        config = await self._configs.get_or_create(tenant_id, now)

        before_tenant = {field: getattr(tenant, field) for field in TENANT_FIELDS}
        applied_tenant = tenant.update(**tenant_changes)  # type: ignore[arg-type]
        before_config = {field: getattr(config, field) for field in config_changes}
        applied_config = config.update(**config_changes)  # type: ignore[arg-type]

        if applied_tenant:
            await self._tenants.apply_changes(tenant_id, applied_tenant)
            record = ChangeSet(actions.ENTITY_TENANT)
            for field, value in applied_tenant.items():
                record = record.diff(field, before_tenant[field], value)
            await self._record(
                tenant_id=tenant_id,
                action=actions.TENANT_UPDATED,
                entity_type=actions.ENTITY_TENANT,
                entity_id=tenant.id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=record,
                now=now,
            )

        if applied_config:
            await self._configs.apply_changes(tenant_id, applied_config)
            record = ChangeSet(actions.ENTITY_TENANT_CONFIG)
            for field, value in applied_config.items():
                record = record.diff(field, before_config[field], value)
            # Rule 9 of steering/security.md does not list TenantConfig, but
            # `owner_approval_threshold_eur` IS the control behind principle 4 of
            # steering/product.md: changing it without a trace changes in silence which
            # expenses need the owner's approval (R5.8).
            await self._record(
                tenant_id=tenant_id,
                action=actions.TENANT_CONFIG_UPDATED,
                entity_type=actions.ENTITY_TENANT_CONFIG,
                entity_id=config.id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=record,
                now=now,
            )

        if applied_tenant or applied_config:
            await self._uow.commit()
        return TenantSettings(tenant=tenant, config=config)

    async def _record(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        changes: ChangeSet,
        now: datetime,
    ) -> None:
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=changes,
                now=now,
            ),
        )
