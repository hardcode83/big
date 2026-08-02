"""Invariants of the tenant configuration (R5.2-R5.5, design D13).

Written before the methods existed. Two of these are refusals with a reason worth spelling out:
`status` would lock every user of the tenant out with no way back through the API, and
`storage_type` would point already-uploaded photos at a backend that does not have them.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.tenants.domain.entities import Tenant, TenantConfig
from app.tenants.domain.enums import StorageType, TenantStatus
from app.tenants.domain.exceptions import TenantValidationError


def _tenant(**overrides) -> Tenant:
    now = datetime.now(UTC)
    values = {
        "id": uuid.uuid4(),
        "name": "MAGNO",
        "billing_email": "billing@example.com",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return Tenant(**values)


def _config(**overrides) -> TenantConfig:
    now = datetime.now(UTC)
    values = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return TenantConfig(**values)


# --- tenant ------------------------------------------------------------------------


def test_updating_a_tenant_reports_what_changed() -> None:
    tenant = _tenant(name="MAGNO", country="ES")

    changed = tenant.update(name="MAGNO SL", country="pt")

    assert changed == {"name": "MAGNO SL", "country": "PT"}
    assert tenant.country == "PT"  # normalised on the way in


def test_updating_a_tenant_with_identical_values_reports_nothing() -> None:
    """Design D15: a PATCH that changes nothing writes neither row nor audit entry."""
    tenant = _tenant(name="MAGNO", timezone="Europe/Madrid")

    assert tenant.update(name="MAGNO", timezone="Europe/Madrid") == {}


def test_a_tenant_validates_its_timezone() -> None:
    tenant = _tenant()

    with pytest.raises(TenantValidationError):
        tenant.update(timezone="Europe/Madridd")

    assert tenant.timezone == "Europe/Madrid"


def test_a_tenant_validates_its_language_and_country() -> None:
    tenant = _tenant()

    with pytest.raises(TenantValidationError):
        tenant.update(default_language="fr")
    with pytest.raises(TenantValidationError):
        tenant.update(country="ESP")


def test_a_tenant_validates_its_billing_email() -> None:
    tenant = _tenant()

    with pytest.raises(TenantValidationError):
        tenant.update(billing_email="not-an-address")


def test_a_tenant_name_cannot_be_blanked() -> None:
    tenant = _tenant(name="MAGNO")

    with pytest.raises(TenantValidationError):
        tenant.update(name="   ")


def test_the_status_of_a_tenant_is_not_reachable_through_update() -> None:
    """R5.3: suspending yourself locks every user out with no way back through the API.

    `auth-tenancy` revalidates on every request that the tenant is ACTIVE, so this is not a
    reversible mistake — changing a tenant's status is a platform operation.
    """
    tenant = _tenant()

    with pytest.raises(TypeError):
        tenant.update(status=TenantStatus.SUSPENDED)  # type: ignore[call-arg]

    assert tenant.status is TenantStatus.ACTIVE


# --- config ------------------------------------------------------------------------


def test_updating_the_config_reports_what_changed() -> None:
    config = _config(sla_high_minutes=15)

    changed = config.update(sla_high_minutes=30)

    assert changed == {"sla_high_minutes": 30}
    assert config.sla_high_minutes == 30


def test_updating_the_config_with_identical_values_reports_nothing() -> None:
    config = _config(auto_create_cleaning_task=True)

    assert config.update(auto_create_cleaning_task=True) == {}


def test_the_approval_threshold_cannot_be_negative() -> None:
    """It is the control behind principle 4 of steering/product.md."""
    config = _config()

    with pytest.raises(TenantValidationError):
        config.update(owner_approval_threshold_eur=Decimal("-1"))


def test_the_approval_threshold_can_be_zero() -> None:
    """Zero means "every expense needs approval", which is a legitimate posture."""
    config = _config()

    assert config.update(owner_approval_threshold_eur=Decimal("0")) == {
        "owner_approval_threshold_eur": Decimal("0")
    }


def test_the_approval_threshold_must_fit_its_column() -> None:
    """`Numeric(10, 2)`: more digits fail at the driver, mid-transaction."""
    config = _config()

    with pytest.raises(TenantValidationError):
        config.update(owner_approval_threshold_eur=Decimal("12345678901"))


@pytest.mark.parametrize("value", [Decimal("-0.01"), Decimal("1.01"), Decimal("2")])
def test_the_ai_confidence_threshold_stays_within_zero_and_one(value: Decimal) -> None:
    config = _config()

    with pytest.raises(TenantValidationError):
        config.update(ai_confidence_threshold=value)


def test_the_ai_confidence_threshold_must_be_representable() -> None:
    """`Numeric(3, 2)` holds two decimals; a third would be silently rounded by Postgres."""
    config = _config()

    with pytest.raises(TenantValidationError):
        config.update(ai_confidence_threshold=Decimal("0.755"))


@pytest.mark.parametrize(
    "field",
    [
        "sla_critical_minutes",
        "sla_high_minutes",
        "sla_medium_minutes",
        "sla_low_minutes",
    ],
)
def test_every_sla_must_be_positive(field: str) -> None:
    """A zero-minute SLA is breached the instant it is created."""
    config = _config()

    for value in (0, -5):
        with pytest.raises(TenantValidationError):
            config.update(**{field: value})


@pytest.mark.parametrize(
    "field", ["checkin_window_hours_before", "checkout_ready_hours_after"]
)
def test_the_windows_cannot_be_negative_but_can_be_zero(field: str) -> None:
    config = _config()

    with pytest.raises(TenantValidationError):
        config.update(**{field: -1})

    assert config.update(**{field: 0}) == {field: 0}


def test_the_storage_type_is_not_reachable_through_update() -> None:
    """R5.4: flipping it points already-uploaded photos at a backend without them."""
    config = _config()

    with pytest.raises(TypeError):
        config.update(storage_type=StorageType.S3)  # type: ignore[call-arg]

    assert config.storage_type is StorageType.LOCAL


def test_the_notification_switches_are_updatable() -> None:
    config = _config(notification_whatsapp_enabled=False)

    assert config.update(notification_whatsapp_enabled=True) == {
        "notification_whatsapp_enabled": True
    }


def test_defaults_can_be_created_for_a_tenant() -> None:
    """R5.7: the API must not depend on the bootstrap having created the row."""
    tenant_id = uuid.uuid4()
    now = datetime.now(UTC)

    config = TenantConfig.with_defaults(tenant_id=tenant_id, now=now)

    assert config.tenant_id == tenant_id
    assert config.owner_approval_threshold_eur == Decimal("100.00")
    assert config.storage_type is StorageType.LOCAL
    assert isinstance(config.id, uuid.UUID)


# --- integer bounds (security panel of sections 7-8) -------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "sla_critical_minutes",
        "sla_high_minutes",
        "sla_medium_minutes",
        "sla_low_minutes",
        "checkin_window_hours_before",
        "checkout_ready_hours_after",
    ],
)
def test_an_integer_too_large_for_its_column_is_refused(field: str) -> None:
    """Regression for what the security panel of sections 7-8 reproduced live.

    `{"sla_high_minutes": 99999999999}` used to reach asyncpg as
    `DataError: value out of int32 range` — not a `TenantDomainError`, so it surfaced as an
    unmapped `500` instead of the `422` R5.5 requires. Every `Decimal` field had its bound
    from the start; the plain integers did not.
    """
    config = _config()

    with pytest.raises(TenantValidationError) as caught:
        config.update(**{field: 99999999999})

    assert field in str(caught.value)


def test_the_largest_value_the_column_holds_is_accepted() -> None:
    """The positive half: the bound is the column's, not an invented business ceiling."""
    from app.tenants.domain.entities import INT32_MAX

    config = _config()

    assert config.update(sla_low_minutes=INT32_MAX) == {"sla_low_minutes": INT32_MAX}


def test_one_past_the_column_limit_is_refused() -> None:
    """The boundary itself, so the check cannot be off by one in the permissive direction."""
    from app.tenants.domain.entities import INT32_MAX

    config = _config()

    with pytest.raises(TenantValidationError):
        config.update(sla_low_minutes=INT32_MAX + 1)


# --- valid boundaries (QA panel of sections 7-8) -----------------------------------
#
# The rejections were covered; the ACCEPTANCES at the exact edges were not. A swapped `<`/`<=`
# would start refusing a legitimate configuration and nothing would have caught it.


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("1"), Decimal("0.75")])
def test_the_ai_confidence_threshold_accepts_its_whole_range(value: Decimal) -> None:
    """`0` means "always escalate to a person" and `1` "never" — both are real postures."""
    config = _config(ai_confidence_threshold=Decimal("0.5"))

    assert config.update(ai_confidence_threshold=value) == {"ai_confidence_threshold": value}


def test_the_approval_threshold_accepts_the_largest_value_its_column_holds() -> None:
    """`Numeric(10, 2)`: eight integer digits plus two decimals."""
    config = _config()

    assert config.update(owner_approval_threshold_eur=Decimal("99999999.99")) == {
        "owner_approval_threshold_eur": Decimal("99999999.99")
    }


def test_one_past_the_threshold_column_limit_is_refused() -> None:
    config = _config()

    with pytest.raises(TenantValidationError):
        config.update(owner_approval_threshold_eur=Decimal("100000000.00"))


def test_a_valid_billing_email_is_applied() -> None:
    """The success path was never exercised: only the rejection of a malformed address was.

    A bug that dropped `billing_email` from the writable set would have gone unnoticed.
    """
    tenant = _tenant(billing_email="old@example.com")

    changed = tenant.update(billing_email="  NEW@Example.COM  ")

    assert changed == {"billing_email": "new@example.com"}
    assert tenant.billing_email == "new@example.com"


# --- domain guards the schema shadows (feature-scale QA review) --------------------
#
# These five branches are unreachable through the API: the Pydantic layer rejects the input
# first. That makes them defence in depth — and it also means an API test can never cover them,
# which is why they get direct domain tests. The QA review found line 270 (`_require_int`'s
# boolean guard) at 0% precisely because the only test for it went through the API.


@pytest.mark.parametrize(
    "field",
    [
        "sla_critical_minutes",
        "sla_high_minutes",
        "sla_medium_minutes",
        "sla_low_minutes",
        "checkin_window_hours_before",
        "checkout_ready_hours_after",
    ],
)
def test_a_boolean_is_not_an_integer_at_the_domain_layer(field: str) -> None:
    """`isinstance(True, int)` is True in Python, so this needs its own clause.

    The API cannot reach it — `_reject_bool` in the schema fires first — so without this test
    the guard sits at 0% coverage and a refactor that "simplified" it away would go unnoticed.
    """
    config = _config()

    with pytest.raises(TenantValidationError) as caught:
        config.update(**{field: True})

    assert field in str(caught.value)


@pytest.mark.parametrize("value", ["30", 30.5, None, [30]])
def test_a_non_integer_is_refused_at_the_domain_layer(value: object) -> None:
    config = _config()

    with pytest.raises(TenantValidationError):
        config.update(sla_high_minutes=value)  # type: ignore[arg-type]


def test_a_name_longer_than_its_column_is_refused_at_the_domain_layer() -> None:
    """`tenants.name` is VARCHAR(200); the schema bounds it too, so this is the domain half."""
    tenant = _tenant(name="MAGNO")

    with pytest.raises(TenantValidationError) as caught:
        tenant.update(name="x" * 201)

    assert "name" in str(caught.value)


def test_a_threshold_with_too_many_decimals_is_refused() -> None:
    """`Numeric(10, 2)` would round a third decimal silently."""
    config = _config()

    with pytest.raises(TenantValidationError) as caught:
        config.update(owner_approval_threshold_eur=Decimal("100.005"))

    assert "decimals" in str(caught.value)


@pytest.mark.parametrize("value", ["not-a-number", object(), [1]])
def test_a_value_that_is_not_a_number_is_refused(value: object) -> None:
    """The `_as_decimal` fallback: any parse failure is the same answer."""
    config = _config()

    with pytest.raises(TenantValidationError) as caught:
        config.update(owner_approval_threshold_eur=value)  # type: ignore[arg-type]

    assert "owner_approval_threshold_eur" in str(caught.value)
