import uuid
from datetime import datetime, timezone

import pytest

from app.tenants.domain.entities import Tenant, TenantConfig
from app.tenants.domain.enums import StorageType, TenantStatus
from app.tenants.domain.exceptions import TenantValidationError


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


def test_create_classmethod() -> None:
    """`platform-admin-api` R1.1 / design D2.

    Happy path plus the four input guards `update` also enforces — a name this accepted and
    `update` would reject (or the reverse) would be a tenant that could only be born in a state
    it could never be edited back into, which is why these re-use the same functions rather
    than re-implementing them.
    """
    now = datetime.now(timezone.utc)

    tenant = Tenant.create(
        name="  MAGNO  ",
        billing_email="  Owner@Example.COM  ",
        now=now,
        country="es",
        timezone="Europe/Madrid",
        default_language="EN",
    )

    # The three setters that do work: `name` trimmed, `email` trimmed and lower-cased, and
    # `country`/`language` upper-/lower-cased to their canonical form.
    assert tenant.name == "MAGNO"
    assert tenant.billing_email == "owner@example.com"
    assert tenant.country == "ES"
    assert tenant.default_language == "en"
    assert tenant.timezone == "Europe/Madrid"
    # `Tenant` is born with a fresh id and the same `now` for both timestamps; the caller
    # cannot influence either, which is what makes the audit diff in section 4 honest.
    assert tenant.id != uuid.UUID(int=0)
    assert tenant.created_at == now
    assert tenant.updated_at == now
    # ACTIVE is the only allowed birth state: a tenant created SUSPENDED would lock its own
    # users out with no endpoint to undo it (R5.3).
    assert tenant.status is TenantStatus.ACTIVE

    with pytest.raises(TenantValidationError, match="name cannot be empty"):
        Tenant.create(name="   ", billing_email="ok@example.com", now=now)
    with pytest.raises(TenantValidationError, match="billing_email is not a valid address"):
        Tenant.create(name="MAGNO", billing_email="not-an-email", now=now)
    with pytest.raises(TenantValidationError, match="two-letter country code"):
        Tenant.create(name="MAGNO", billing_email="ok@example.com", now=now, country="ESP")
    with pytest.raises(TenantValidationError, match="not a supported language"):
        Tenant.create(
            name="MAGNO", billing_email="ok@example.com", now=now, default_language="fr"
        )
