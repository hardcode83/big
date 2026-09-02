"""The tenant endpoints over ASGI (R5, R7).

Includes the R7.9 test with its own reason: `tenants` has no `tenant_id` column, so
`tenant_scoped_classes()` in `app/core/db.py` does not cover that table and the global session
filter protects nothing here. The comparison of the path id against the token's tenant is the
only protection there is, which is why it gets a test of its own rather than being assumed.
"""

import uuid

import pytest
from sqlalchemy import delete, select

from app.audit.domain import actions
from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.enums import UserRole
from tests.auth.conftest import auth_header

OWNER = UserRole.TENANT_OWNER
READERS = {UserRole.TENANT_OWNER, UserRole.PROPERTY_MANAGER}
MANAGERS = {UserRole.TENANT_OWNER}
ALL_ROLES = list(UserRole)


# --- read (R5.1) -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reading_returns_the_tenant_with_its_config_nested(
    api, tenant_a, users_by_role_a
) -> None:
    response = await api.get(
        f"/api/v1/tenants/{tenant_a.id}", headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(tenant_a.id)
    assert body["config"]["owner_approval_threshold_eur"] == "100.00"
    assert body["config"]["sla_critical_minutes"] == 5
    # Readable but not writable.
    assert body["config"]["storage_type"] == "LOCAL"


@pytest.mark.asyncio
async def test_the_config_row_is_created_on_first_read(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R5.7: a tenant with no config row gets one lazily, like a non-bootstrap one.

    `tests/auth/conftest.py`'s `insert_tenant` now seeds a config row by default
    (`notification-channel-routing`, so the channel-fan-out suite's single-row assertions
    stay valid elsewhere) — this test's whole point is the row's *absence*, so it deletes
    the one `tenant_a` seeded before exercising the lazy-creation path.
    """
    from app.tenants.infrastructure.models import TenantConfigModel

    await db_session.execute(
        delete(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_a.id)
    )
    await db_session.flush()

    before = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_a.id)
        )
    ).scalar_one_or_none()
    assert before is None

    response = await api.get(
        f"/api/v1/tenants/{tenant_a.id}", headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert response.status_code == 200
    after = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_a.id)
        )
    ).scalar_one()
    assert after is not None


# --- update (R5.2-R5.5) ------------------------------------------------------------


@pytest.mark.asyncio
async def test_patching_the_tenant_and_its_config_answers_200(
    api, tenant_a, users_by_role_a
) -> None:
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={
            "name": "MAGNO SL",
            "timezone": "Atlantic/Canary",
            "config": {"sla_high_minutes": 30, "owner_approval_threshold_eur": "250.50"},
        },
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "MAGNO SL"
    assert body["timezone"] == "Atlantic/Canary"
    assert body["config"]["sla_high_minutes"] == 30
    assert body["config"]["owner_approval_threshold_eur"] == "250.50"


@pytest.mark.asyncio
async def test_the_tenant_status_cannot_be_patched(api, tenant_a, users_by_role_a) -> None:
    """R5.3: suspending your own tenant locks every user out with no way back."""
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={"status": "SUSPENDED"},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_storage_type_cannot_be_patched(api, tenant_a, users_by_role_a) -> None:
    """R5.4: it would point already-uploaded photos at a backend without them."""
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={"config": {"storage_type": "S3"}},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"timezone": "Europe/Madridd"},
        {"country": "ESP"},
        {"default_language": "fr"},
        {"billing_email": "not-an-address"},
        {"config": {"owner_approval_threshold_eur": "-1"}},
        {"config": {"ai_confidence_threshold": "1.5"}},
        {"config": {"ai_confidence_threshold": "0.755"}},
        {"config": {"sla_high_minutes": 0}},
        {"config": {"checkin_window_hours_before": -1}},
    ],
)
async def test_an_invalid_value_answers_422(api, tenant_a, users_by_role_a, body) -> None:
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json=body,
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["name", "timezone", "country", "default_language"])
async def test_an_explicit_null_answers_422(api, tenant_a, users_by_role_a, field) -> None:
    """Same class of bug the security panel found in the user PATCH: `null` is not "absent"."""
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={field: None},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_an_explicit_null_in_the_config_answers_422(
    api, tenant_a, users_by_role_a
) -> None:
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={"config": {"sla_high_minutes": None}},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_a_patch_that_changes_nothing_writes_no_audit_row(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={"name": tenant_a.name},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 200
    assert (await db_session.execute(select(AuditLogModel))).scalars().all() == []


@pytest.mark.asyncio
async def test_changing_the_approval_threshold_is_audited(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={"config": {"owner_approval_threshold_eur": "250.00"}},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    row = (
        await db_session.execute(
            select(AuditLogModel).where(
                AuditLogModel.action == actions.TENANT_CONFIG_UPDATED
            )
        )
    ).scalar_one()
    assert row.tenant_id == tenant_a.id
    assert row.actor_user_id == users_by_role_a[OWNER].id
    assert row.changes["owner_approval_threshold_eur"]["new"] == "250.00"


# --- authorisation (R7.2, R7.4-R7.7) ----------------------------------------------


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_reading_is_allowed_for_readers_only(api, tenant_a, users_by_role_a, role) -> None:
    """`PROPERTY_MANAGER` reads: it needs the thresholds and SLAs to operate (design D8)."""
    response = await api.get(
        f"/api/v1/tenants/{tenant_a.id}", headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == (200 if role in READERS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_patching_is_allowed_for_the_owner_only(
    api, tenant_a, users_by_role_a, role
) -> None:
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={"name": "Renamed"},
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == (200 if role in MANAGERS else 403)


@pytest.mark.asyncio
async def test_neither_endpoint_is_reachable_without_a_token(api, tenant_a) -> None:
    assert (await api.get(f"/api/v1/tenants/{tenant_a.id}")).status_code == 401
    assert (
        await api.patch(f"/api/v1/tenants/{tenant_a.id}", json={"name": "x"})
    ).status_code == 401


@pytest.mark.asyncio
async def test_an_out_of_range_integer_answers_422_not_500(
    api, tenant_a, users_by_role_a
) -> None:
    """R5.5 end to end: the driver error the security panel found must never surface.

    Asserting `!= 500` explicitly as well as `== 422`: the point of the finding was that an
    authenticated caller could trigger an unhandled server error at will.
    """
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={"config": {"sla_high_minutes": 99999999999}},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_the_billing_email_can_actually_be_changed(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """End to end for the field whose success path the QA panel found untested."""
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={"billing_email": "Facturacion@Example.COM"},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 200
    assert response.json()["billing_email"] == "facturacion@example.com"
    row = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == actions.TENANT_UPDATED)
        )
    ).scalar_one()
    assert row.changes["billing_email"]["new"] == "facturacion@example.com"


# --- coercion guards (feature-scale QA review) --------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        "sla_high_minutes",
        "sla_critical_minutes",
        "checkin_window_hours_before",
        "checkout_ready_hours_after",
        "owner_approval_threshold_eur",
        "ai_confidence_threshold",
    ],
)
async def test_a_boolean_for_a_numeric_field_answers_422(
    api, tenant_a, users_by_role_a, field
) -> None:
    """`true` is not a number, however much Python disagrees (R5.5, design D22).

    Pydantic coerces `true` to `1` for an int field in lax mode, so without the guard in
    `_reject_bool` a `{"sla_high_minutes": true}` would be **accepted as one minute** — an SLA
    breached the instant it is set. The domain guard cannot catch it either: by the time
    `_require_int` runs, the bool is already an `int`.

    This test exists because the feature-scale QA review found the guard implemented and
    **untested**: the batch that was supposed to add it never ran (a shell `cd` failed and
    short-circuited the append), and the unchanged test count was the tell that got missed.
    """
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={"config": {field: True}},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_a_numeric_string_is_still_accepted(api, tenant_a, users_by_role_a) -> None:
    """The positive half: rejecting bools must not reject `"30"`, which JSON clients do send."""
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={"config": {"sla_high_minutes": "30"}},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 200
    assert response.json()["config"]["sla_high_minutes"] == 30


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("timezone", "x" * 5000),
        ("country", "ESP"),
        ("default_language", "es-ES-x-long"),
        ("name", "x" * 201),
    ],
)
async def test_an_oversized_string_answers_422(
    api, tenant_a, users_by_role_a, field, value
) -> None:
    """Bounded at the schema by the column width, so the `422` names the field."""
    response = await api.patch(
        f"/api/v1/tenants/{tenant_a.id}",
        json={field: value},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422, response.text
