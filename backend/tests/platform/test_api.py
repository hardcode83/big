"""The platform endpoints over ASGI (`platform-admin-api` R1.1-R1.4, R3.1-R3.6, R5).

Two routes, eight contracts (R1.1 happy path, R1.2 duplicate, R1.3 invalid body, R1.4 RBAC,
R3.1 user happy path, R3.3 SUSPENDED/missing tenants, R3.4 cross-tenant email, R3.5
SUPER_ADMIN rejection). The patterns reuse the `users_by_role_a` and `auth_header` fixtures
of `tests/auth/conftest.py` and the inline `super_admin` seeded in
`tests/platform/conftest.py`.
"""

import uuid

import pytest
from sqlalchemy import select

from app.auth.domain.enums import UserRole
from app.auth.infrastructure.models import UserModel
from app.tenants.infrastructure.models import TenantModel
from app.tenants.domain.enums import TenantStatus
from tests.auth.conftest import auth_header, insert_tenant, insert_user


def _tenant_payload(**overrides) -> dict:
    """The minimum body `POST /api/v1/platform/tenants` accepts (R1.1)."""
    payload = {
        "name": f"Magno-{uuid.uuid4().hex[:8]}",
        "billing_email": f"billing-{uuid.uuid4().hex[:8]}@example.com",
        "country": "ES",
        "timezone": "Europe/Madrid",
        "default_language": "es",
    }
    payload.update(overrides)
    return payload


def _user_payload(**overrides) -> dict:
    """The minimum body `POST /api/v1/platform/tenants/{id}/users` accepts (R3.1)."""
    payload = {
        "email": f"new-{uuid.uuid4().hex[:8]}@example.com",
        "full_name": "Persona Nueva",
        "phone": None,
        "role": UserRole.PROPERTY_MANAGER.value,
    }
    payload.update(overrides)
    return payload


# --- 4.7 happy path: POST /platform/tenants (R1.1, R5) -----------------------------


@pytest.mark.asyncio
async def test_post_tenants_creates_an_active_tenant_with_default_config(
    api, super_admin
) -> None:
    response = await api.post(
        "/api/v1/platform/tenants",
        json=_tenant_payload(),
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert uuid.UUID(body["id"])  # minted
    assert body["status"] == "ACTIVE"
    # `TenantConfig.with_defaults` defines the default thresholds; the response is the
    # canonical place this contract is published (R1.1 / R5).
    config = body["config"]
    assert config["owner_approval_threshold_eur"] == "100.00"
    assert config["sla_critical_minutes"] == 5
    assert config["ai_confidence_threshold"] == "0.75"


@pytest.mark.asyncio
async def test_post_tenants_does_not_set_cache_control_no_store(api, super_admin) -> None:
    """R1.1 / 4.7: the tenant-creation response carries no one-time secret, so it is
    cacheable. The `no-store` header is reserved for the user-creation response (4.10)."""
    response = await api.post(
        "/api/v1/platform/tenants",
        json=_tenant_payload(),
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 201
    assert response.headers.get("cache-control") != "no-store"


# --- 4.8 duplicate name (R1.2, R1.4) ------------------------------------------------


@pytest.mark.asyncio
async def test_post_tenants_with_a_duplicate_name_answers_409_without_a_second_row(
    api, db_session, super_admin
) -> None:
    name = f"Magno-{uuid.uuid4().hex[:8]}"
    seed = await insert_tenant(db_session, name=name, status=TenantStatus.ACTIVE)

    # `insert_tenant` only flushes; the API call's session would otherwise try to add the
    # seed itself and hit its own duplicate. Commit first so the seed is the row the
    # application sees, then let the API surface its `409`.
    await db_session.commit()

    response = await api.post(
        "/api/v1/platform/tenants",
        json=_tenant_payload(name=name),
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    # The API call rolled the session back on the duplicate; the fixture-shared
    # `db_session` needs an explicit rollback before the next statement can read from it.
    await db_session.rollback()
    # No second row written: the duplicate path aborted before `commit()`.
    rows = (
        await db_session.execute(select(TenantModel).where(TenantModel.name == name))
    ).scalars().all()
    assert len(rows) == 1 and rows[0].id == seed.id


# --- 4.9 invalid body (R1.3) -------------------------------------------------------


@pytest.mark.asyncio
async def test_post_tenants_with_an_invalid_body_answers_422_with_the_prd_envelope(
    api, super_admin
) -> None:
    response = await api.post(
        "/api/v1/platform/tenants",
        json={
            "name": "",  # too short (max_length still passes; length is a `Field(...)` rule)
            "billing_email": "not-an-email",
            "country": "ESPA",  # max_length=2
            "timezone": "Europe/Madrid",
            "default_language": "es",
        },
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    failed_fields = {item["loc"][-1] for item in body["error"]["details"]["errors"]}
    # All three fields the body broke are named in the envelope.
    assert {"name", "billing_email", "country"} <= failed_fields

    # R1.3's other half, which was unpinned: the envelope leaks NOTHING else. The
    # serialiser in `app/core/errors.py` is an allowlist of exactly three keys, and this
    # is what holds it to that: handing Pydantic's raw error through would add `input`
    # — the value the caller submitted, echoed back — plus `url` and sometimes `ctx`.
    for item in body["error"]["details"]["errors"]:
        assert set(item) == {"loc", "type", "msg"}, item
    serialised = response.text.lower()
    for leak in ("sqlalchemy", "asyncpg", "psycopg", "traceback", "uq_"):
        assert leak not in serialised, leak


# --- 4.10 happy path: POST /platform/tenants/{id}/users (R3.1, R3.4) ----------------


@pytest.mark.asyncio
async def test_post_users_in_a_named_tenant_returns_201_with_no_store_and_a_password(
    api, tenant_a, super_admin
) -> None:
    response = await api.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/users",
        json=_user_payload(),
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["user"]["tenant_id"] == str(tenant_a.id)
    assert body["temporary_password"]


# --- 4.11 SUPER_ADMIN rejection at the schema (R3.5) --------------------------------


@pytest.mark.asyncio
async def test_post_users_with_role_super_admin_answers_422(
    api, tenant_a, super_admin
) -> None:
    response = await api.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/users",
        json=_user_payload(role=UserRole.SUPER_ADMIN.value),
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- R3.6 invalid body on the user endpoint ----------------------------------------


@pytest.mark.asyncio
async def test_post_users_with_an_invalid_body_answers_422_with_the_failing_fields(
    api, tenant_a, super_admin
) -> None:
    """R3.6: the user route's OWN body validation.

    The tenant route had this test and this one did not, so a criterion the change states
    was resting on its sibling: nothing here would have failed if
    `CreatePlatformUserRequest` had lost its field rules.
    """
    response = await api.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/users",
        json={
            "email": "not-an-email",
            "full_name": "",
            "phone": None,
            "role": UserRole.PROPERTY_MANAGER.value,
        },
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    failed_fields = {item["loc"][-1] for item in body["error"]["details"]["errors"]}
    assert {"email", "full_name"} <= failed_fields, failed_fields


# --- 4.12 SUSPENDED and missing tenant are indistinguishable (R3.3) -----------------


@pytest.mark.asyncio
async def test_post_users_with_a_missing_tenant_answers_404(
    api, super_admin
) -> None:
    response = await api.post(
        f"/api/v1/platform/tenants/{uuid.uuid4()}/users",
        json=_user_payload(),
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_post_users_with_a_suspended_tenant_answers_404_indistinguishably(
    api, db_session, super_admin
) -> None:
    suspended = await insert_tenant(
        db_session, status=TenantStatus.SUSPENDED
    )

    response = await api.post(
        f"/api/v1/platform/tenants/{suspended.id}/users",
        json=_user_payload(),
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    # Same envelope as the missing-tenant case (R3.3's "indistinguishable").
    assert body["error"]["message"] == "Tenant does not exist"


# --- 4.13 cross-tenant email collision (R3.4) --------------------------------------


@pytest.mark.asyncio
async def test_post_users_with_an_email_used_by_another_tenant_answers_409(
    api, db_session, tenant_a, tenant_b, super_admin
) -> None:
    """ADR 0005: the address is unique across the whole installation."""
    await insert_user(db_session, tenant=tenant_b, email="taken@example.com")

    response = await api.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/users",
        json=_user_payload(email="taken@example.com"),
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONFLICT"
    # No mention of the tenant that owns the address.
    assert "tenant_b" not in body["error"]["message"]
    assert "tenant" not in body["error"]["message"].lower()


# --- 4.14 RBAC: 403 cuts before body validation (R1.4) -----------------------------


@pytest.mark.asyncio
async def test_post_tenants_with_a_non_super_admin_token_and_an_invalid_body_answers_403(
    api, users_by_role_a
) -> None:
    """`MANAGE_PLATFORM` is `SUPER_ADMIN`'s alone; a `TENANT_OWNER` token gets `403` before
    `body: CreateTenantRequest` is even parsed (R1.4 / 4.14). The invalid body fields are
    irrelevant: had the body been parsed first, the answer would have been `422`."""
    owner = users_by_role_a[UserRole.TENANT_OWNER]

    response = await api.post(
        "/api/v1/platform/tenants",
        json={
            "name": "",
            "billing_email": "not-an-email",
            "country": "ESPA",
            "timezone": "Europe/Madrid",
            "default_language": "es",
        },
        headers=auth_header(api, owner),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "FORBIDDEN"
    # No 422 body would have listed fields here; the 403 carries a single reason.
    assert "details" in body["error"]
    assert body["error"]["details"] == {}


# --- bonus: the response does not leak password material anywhere -------------------


@pytest.mark.asyncio
async def test_no_platform_response_carries_password_material(
    api, tenant_a, super_admin
) -> None:
    for endpoint, json_body in (
        ("/api/v1/platform/tenants", _tenant_payload()),
        (
            f"/api/v1/platform/tenants/{tenant_a.id}/users",
            _user_payload(),
        ),
    ):
        response = await api.post(
            endpoint, json=json_body, headers=auth_header(api, super_admin)
        )
        assert response.status_code == 201
        serialised = response.text
        assert "password_hash" not in serialised
        # The user-creation response IS allowed to carry `temporary_password`; the tenant
        # one is not.
        if "tenants/" in endpoint and endpoint.endswith("/users"):
            continue
        assert "temporary_password" not in serialised
