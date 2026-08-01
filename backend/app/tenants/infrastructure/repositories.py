"""SQLAlchemy adapters for the tenants ports (R5.1, R5.7, design D12, D13, D21).

No method commits: the transactional boundary is the use case, so the change and its audit row
live or die together (R6.4).
"""

import uuid
from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenants.domain.entities import Tenant, TenantConfig
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel

# `status` is absent on purpose (R5.3), and so are the identity columns.
TENANT_WRITABLE = frozenset(
    {"name", "billing_email", "country", "timezone", "default_language"}
)

# `storage_type` is absent on purpose (R5.4).
CONFIG_WRITABLE = frozenset(
    {
        "owner_approval_threshold_eur",
        "ai_confidence_threshold",
        "sla_critical_minutes",
        "sla_high_minutes",
        "sla_medium_minutes",
        "sla_low_minutes",
        "checkin_window_hours_before",
        "checkout_ready_hours_after",
        "auto_create_cleaning_task",
        "cleaning_photo_required",
        "notification_email_enabled",
        "notification_whatsapp_enabled",
    }
)


class SqlAlchemyTenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        model = (
            await self._session.execute(
                select(TenantModel).where(TenantModel.id == tenant_id)
            )
        ).scalar_one_or_none()
        return _to_tenant(model) if model is not None else None

    async def apply_changes(
        self, tenant_id: uuid.UUID, values: Mapping[str, object]
    ) -> None:
        if not values:
            return
        _reject_unwritable(values, TENANT_WRITABLE, "tenant")
        result = await self._session.execute(
            update(TenantModel).where(TenantModel.id == tenant_id).values(**values)
        )
        if result.rowcount != 1:
            raise ValueError("Cannot update a tenant that does not exist")


class SqlAlchemyTenantConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, tenant_id: uuid.UUID, now: datetime) -> TenantConfig:
        """Read the row, creating it with its defaults if it is missing (R5.7).

        Read-then-insert rather than an `ON CONFLICT` upsert: `tenant_configs.tenant_id` is
        unique, so two concurrent creations would make one of them fail — but the only callers
        are two administrative endpoints of one tenant, and the flush makes the failure loud
        rather than silent. If this ever becomes a hot path it wants a real upsert.
        """
        model = (
            await self._session.execute(
                select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if model is not None:
            return _to_config(model)

        created = TenantConfig.with_defaults(tenant_id=tenant_id, now=now)
        self._session.add(
            TenantConfigModel(
                id=created.id,
                tenant_id=created.tenant_id,
                owner_approval_threshold_eur=created.owner_approval_threshold_eur,
                ai_confidence_threshold=created.ai_confidence_threshold,
                sla_critical_minutes=created.sla_critical_minutes,
                sla_high_minutes=created.sla_high_minutes,
                sla_medium_minutes=created.sla_medium_minutes,
                sla_low_minutes=created.sla_low_minutes,
                checkin_window_hours_before=created.checkin_window_hours_before,
                checkout_ready_hours_after=created.checkout_ready_hours_after,
                auto_create_cleaning_task=created.auto_create_cleaning_task,
                cleaning_photo_required=created.cleaning_photo_required,
                storage_type=created.storage_type,
                notification_email_enabled=created.notification_email_enabled,
                notification_whatsapp_enabled=created.notification_whatsapp_enabled,
            )
        )
        await self._session.flush()
        return created

    async def apply_changes(
        self, tenant_id: uuid.UUID, values: Mapping[str, object]
    ) -> None:
        if not values:
            return
        _reject_unwritable(values, CONFIG_WRITABLE, "tenant config")
        result = await self._session.execute(
            update(TenantConfigModel)
            .where(TenantConfigModel.tenant_id == tenant_id)
            .values(**values)
        )
        if result.rowcount != 1:
            raise ValueError("Cannot update a tenant config that does not exist")


def _reject_unwritable(
    values: Mapping[str, object], writable: frozenset[str], what: str
) -> None:
    unknown = set(values) - writable
    if unknown:
        raise ValueError(f"Columns {sorted(unknown)} are not writable on a {what}")


def _to_tenant(model: TenantModel) -> Tenant:
    return Tenant(
        id=model.id,
        name=model.name,
        billing_email=model.billing_email,
        created_at=model.created_at,
        updated_at=model.updated_at,
        country=model.country,
        timezone=model.timezone,
        default_language=model.default_language,
        status=model.status,
    )


def _to_config(model: TenantConfigModel) -> TenantConfig:
    return TenantConfig(
        id=model.id,
        tenant_id=model.tenant_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        owner_approval_threshold_eur=model.owner_approval_threshold_eur,
        ai_confidence_threshold=model.ai_confidence_threshold,
        sla_critical_minutes=model.sla_critical_minutes,
        sla_high_minutes=model.sla_high_minutes,
        sla_medium_minutes=model.sla_medium_minutes,
        sla_low_minutes=model.sla_low_minutes,
        checkin_window_hours_before=model.checkin_window_hours_before,
        checkout_ready_hours_after=model.checkout_ready_hours_after,
        auto_create_cleaning_task=model.auto_create_cleaning_task,
        cleaning_photo_required=model.cleaning_photo_required,
        storage_type=model.storage_type,
        notification_email_enabled=model.notification_email_enabled,
        notification_whatsapp_enabled=model.notification_whatsapp_enabled,
    )
