import uuid
from datetime import datetime, timezone

from app.tenants.domain.entities import Tenant, TenantConfig
from app.tenants.domain.enums import StorageType, TenantStatus


def test_tenant_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Owner A",
        billing_email="owner@example.com",
        created_at=now,
        updated_at=now,
    )

    assert tenant.country == "ES"
    assert tenant.timezone == "Europe/Madrid"
    assert tenant.default_language == "es"
    assert tenant.status == TenantStatus.ACTIVE


def test_tenant_config_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    config = TenantConfig(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )

    assert config.sla_critical_minutes == 5
    assert config.storage_type == StorageType.LOCAL
    assert config.notification_whatsapp_enabled is False
