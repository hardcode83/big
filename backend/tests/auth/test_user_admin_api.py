"""The user-administration endpoints over ASGI (R1, R2, R3, R4, R6).

Reuses the `api` fixture of `tests/reservations/conftest.py`-style wiring, defined for this
package in `tests/auth/conftest_api.py`: the real app, the real router, the real use cases,
over the test session.
"""

import uuid

import pytest
from sqlalchemy import select

from app.audit.domain import actions
from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel, UserSessionModel
from tests.auth.conftest import PASSWORD, auth_header, insert_user

OWNER = UserRole.TENANT_OWNER


def _payload(**overrides) -> dict:
    payload = {
        "name": "Ana Limpieza",
        "email": f"ana-{uuid.uuid4().hex[:8]}@example.com",
        "role": UserRole.CLEANER.value,
    }
    payload.update(overrides)
    return payload


# --- create (R1) -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creating_a_user_answers_201_with_a_working_password(
    api, db_session, users_by_role_a
) -> None:
    body = _payload()

    response = await api.post(
        "/api/v1/users", json=body, headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert response.status_code == 201
    created = response.json()
    assert created["user"]["email"] == body["email"]
    assert created["user"]["status"] == UserStatus.ACTIVE.value
    assert created["temporary_password"]

    # The password works: this is what makes the endpoint useful rather than merely correct.
    login = await api.post(
        "/api/v1/auth/login",
        json={"email": body["email"], "password": created["temporary_password"]},
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_the_created_password_response_is_not_cacheable(api, users_by_role_a) -> None:
    """Design D10: the two responses that carry the secret say `no-store`."""
    response = await api.post(
        "/api/v1/users", json=_payload(), headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_creating_a_user_normalises_the_address(api, users_by_role_a) -> None:
    response = await api.post(
        "/api/v1/users",
        json=_payload(email="MiXeD@Example.COM"),
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "mixed@example.com"


@pytest.mark.asyncio
async def test_a_duplicate_address_answers_409_without_naming_the_tenant(
    api, db_session, tenant_b, users_by_role_a
) -> None:
    """R1.4: global uniqueness (ADR 0005) makes this a conflict even across tenants."""
    await insert_user(db_session, tenant=tenant_b, email="taken@example.com")

    response = await api.post(
        "/api/v1/users",
        json=_payload(email="taken@example.com"),
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONFLICT"
    assert "tenant" not in body["error"]["message"].lower()


@pytest.mark.asyncio
async def test_creating_a_super_admin_answers_422(api, users_by_role_a) -> None:
    response = await api.post(
        "/api/v1/users",
        json=_payload(role=UserRole.SUPER_ADMIN.value),
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_a_tenant_id_in_the_body_is_rejected(api, users_by_role_a, tenant_b) -> None:
    """`extra="forbid"`: the effective tenant comes only from the token (R1.3)."""
    response = await api.post(
        "/api/v1/users",
        json=_payload(tenant_id=str(tenant_b.id)),
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "email", ["no-at-sign", "spaces in@example.com", "trailing@dot.", "@example.com"]
)
async def test_a_malformed_address_answers_422(api, users_by_role_a, email) -> None:
    response = await api.post(
        "/api/v1/users",
        json=_payload(email=email),
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_creating_a_user_writes_one_audit_row_without_the_password(
    api, db_session, users_by_role_a
) -> None:
    response = await api.post(
        "/api/v1/users", json=_payload(), headers=auth_header(api, users_by_role_a[OWNER])
    )
    created = response.json()

    rows = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == actions.USER_CREATED)
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].actor_user_id == users_by_role_a[OWNER].id
    assert rows[0].changes["password"] == {"changed": True}
    assert created["temporary_password"] not in str(rows[0].changes)


# --- read (R2) ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_listing_uses_the_prd_envelope(api, users_by_role_a) -> None:
    response = await api.get("/api/v1/users", headers=auth_header(api, users_by_role_a[OWNER]))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "total", "page", "per_page", "total_pages"}
    # The five seeded users of tenant A.
    assert body["total"] == len(UserRole)
    assert body["total_pages"] == 1


@pytest.mark.asyncio
async def test_no_response_carries_password_material(api, users_by_role_a) -> None:
    """R2.5, checked on the wire and not only on the schema."""
    listing = await api.get("/api/v1/users", headers=auth_header(api, users_by_role_a[OWNER]))
    detail = await api.get(
        f"/api/v1/users/{users_by_role_a[UserRole.CLEANER].id}",
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    for response in (listing, detail):
        serialised = response.text
        assert "password_hash" not in serialised
        assert "temporary_password" not in serialised
        assert PASSWORD not in serialised


@pytest.mark.asyncio
async def test_the_listing_filters_by_role(api, users_by_role_a) -> None:
    response = await api.get(
        "/api/v1/users?role=CLEANER", headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert response.status_code == 200
    assert [user["role"] for user in response.json()["data"]] == ["CLEANER"]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["page=0", "per_page=0", "per_page=101", "page=100001"])
async def test_pagination_outside_its_bounds_answers_422(api, users_by_role_a, query) -> None:
    """R2.2: `page` becomes a SQL OFFSET, so it needs a ceiling as much as `per_page`."""
    response = await api.get(
        f"/api/v1/users?{query}", headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reading_an_unknown_user_answers_404(api, users_by_role_a) -> None:
    response = await api.get(
        f"/api/v1/users/{uuid.uuid4()}", headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert response.status_code == 404


# --- update (R3) -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patching_the_profile_answers_200(api, users_by_role_a) -> None:
    target = users_by_role_a[UserRole.CLEANER]

    response = await api.patch(
        f"/api/v1/users/{target.id}",
        json={"name": "Ana Ruiz", "phone": "+34600000000"},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Ana Ruiz"
    assert response.json()["phone"] == "+34600000000"


@pytest.mark.asyncio
async def test_a_patch_that_changes_nothing_writes_no_audit_row(
    api, db_session, users_by_role_a
) -> None:
    target = users_by_role_a[UserRole.CLEANER]

    response = await api.patch(
        f"/api/v1/users/{target.id}",
        json={"name": target.name},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 200
    rows = (await db_session.execute(select(AuditLogModel))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_changing_a_role_answers_200_and_audits_it_as_such(
    api, db_session, users_by_role_a
) -> None:
    target = users_by_role_a[UserRole.CLEANER]

    response = await api.patch(
        f"/api/v1/users/{target.id}",
        json={"role": UserRole.TECHNICIAN.value},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 200
    assert response.json()["role"] == "TECHNICIAN"
    row = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == actions.USER_ROLE_CHANGED)
        )
    ).scalar_one()
    assert row.changes["role"] == {"old": "CLEANER", "new": "TECHNICIAN"}


@pytest.mark.asyncio
async def test_changing_your_own_role_answers_422(api, db_session, tenant_a) -> None:
    """R3.5. A second owner is seeded so the refusal is about self-service, not the last owner."""
    owner = await insert_user(db_session, tenant=tenant_a, role=OWNER)
    await insert_user(db_session, tenant=tenant_a, role=OWNER)

    response = await api.patch(
        f"/api/v1/users/{owner.id}",
        json={"role": UserRole.CLEANER.value},
        headers=auth_header(api, owner),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_tenant_cannot_be_left_without_an_owner_through_this_api(
    api, db_session, tenant_a
) -> None:
    """R3.6 is currently UNREACHABLE over HTTP, and this test pins why.

    Only `TENANT_OWNER` holds `MANAGE_USERS` (design D8), and R3.5 refuses a self-change. So
    the only actor who could demote the last owner is that owner, and it is stopped one step
    earlier — the `422` below is `SelfRoleChangeError`, not `LastOwnerError`.

    R3.6 is therefore defence in depth at this layer, not dead code: it is reachable and
    tested at the use-case level (`test_user_admin_use_cases.py`) and against real Postgres
    under concurrency (`test_last_owner_concurrency.py`), and it is what would save the tenant
    the day `MANAGE_USERS` is granted to another role or self-service is allowed. What this
    test guarantees is the property that matters operationally: **no sequence of HTTP calls
    leaves the tenant without an active owner.**
    """
    first = await insert_user(db_session, tenant=tenant_a, role=OWNER)
    second = await insert_user(db_session, tenant=tenant_a, role=OWNER)

    # One owner demotes the other: allowed, one remains.
    demoted = await api.patch(
        f"/api/v1/users/{second.id}",
        json={"role": UserRole.CLEANER.value},
        headers=auth_header(api, first),
    )
    assert demoted.status_code == 200

    # The survivor cannot demote itself (R3.5)…
    self_demotion = await api.patch(
        f"/api/v1/users/{first.id}",
        json={"role": UserRole.CLEANER.value},
        headers=auth_header(api, first),
    )
    assert self_demotion.status_code == 422

    # …nor deactivate itself, which is the same rule (design D19).
    self_deletion = await api.delete(
        f"/api/v1/users/{first.id}", headers=auth_header(api, first)
    )
    assert self_deletion.status_code == 422

    # …and the demoted one no longer has the permission to do it either.
    by_the_demoted = await api.patch(
        f"/api/v1/users/{first.id}",
        json={"role": UserRole.CLEANER.value},
        headers=auth_header(api, second),
    )
    assert by_the_demoted.status_code == 403

    row = (
        await db_session.execute(select(UserModel).where(UserModel.id == first.id))
    ).scalar_one()
    assert row.role is UserRole.TENANT_OWNER and row.status is UserStatus.ACTIVE


@pytest.mark.asyncio
async def test_promoting_to_super_admin_answers_422(api, users_by_role_a) -> None:
    response = await api.patch(
        f"/api/v1/users/{users_by_role_a[UserRole.CLEANER].id}",
        json={"role": UserRole.SUPER_ADMIN.value},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_field_in_the_patch_answers_422(api, users_by_role_a) -> None:
    response = await api.patch(
        f"/api/v1/users/{users_by_role_a[UserRole.CLEANER].id}",
        json={"password_hash": "injected"},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422


# --- deactivate (R3.8, R3.9) -------------------------------------------------------


@pytest.mark.asyncio
async def test_deleting_a_user_deactivates_it_and_keeps_the_row(
    api, db_session, users_by_role_a
) -> None:
    target = users_by_role_a[UserRole.CLEANER]

    response = await api.delete(
        f"/api/v1/users/{target.id}", headers=auth_header(api, users_by_role_a[OWNER])
    )

    assert response.status_code == 204
    row = (
        await db_session.execute(select(UserModel).where(UserModel.id == target.id))
    ).scalar_one()
    assert row.status is UserStatus.INACTIVE


@pytest.mark.asyncio
async def test_deleting_twice_answers_204_and_audits_once(
    api, db_session, users_by_role_a
) -> None:
    target = users_by_role_a[UserRole.CLEANER]
    header = auth_header(api, users_by_role_a[OWNER])

    first = await api.delete(f"/api/v1/users/{target.id}", headers=header)
    second = await api.delete(f"/api/v1/users/{target.id}", headers=header)

    assert (first.status_code, second.status_code) == (204, 204)
    rows = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == actions.USER_DEACTIVATED)
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_deactivating_a_user_stops_it_from_refreshing(
    api, db_session, users_by_role_a
) -> None:
    """R3.7. `POST /auth/refresh` does not revalidate status, so the revocation is the guard.

    Without it, a deactivated account keeps minting fresh pairs for the whole 7-day refresh
    lifetime while its access tokens are being rejected.
    """
    target = users_by_role_a[UserRole.CLEANER]
    login = await api.post(
        "/api/v1/auth/login", json={"email": target.email, "password": PASSWORD}
    )
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]

    await api.delete(
        f"/api/v1/users/{target.id}", headers=auth_header(api, users_by_role_a[OWNER])
    )

    refreshed = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refreshed.status_code == 401
    revoked = (
        await db_session.execute(
            select(UserSessionModel).where(UserSessionModel.user_id == target.id)
        )
    ).scalars().all()
    assert revoked and all(session.revoked_at is not None for session in revoked)


# --- reset password (R4) -----------------------------------------------------------


@pytest.mark.asyncio
async def test_resetting_a_password_issues_a_working_one_and_kills_the_old(
    api, users_by_role_a
) -> None:
    target = users_by_role_a[UserRole.CLEANER]

    response = await api.post(
        f"/api/v1/users/{target.id}/reset-password",
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    new_password = response.json()["temporary_password"]

    with_new = await api.post(
        "/api/v1/auth/login", json={"email": target.email, "password": new_password}
    )
    with_old = await api.post(
        "/api/v1/auth/login", json={"email": target.email, "password": PASSWORD}
    )
    assert with_new.status_code == 200
    assert with_old.status_code == 401


@pytest.mark.asyncio
async def test_resetting_audits_without_the_password(api, db_session, users_by_role_a) -> None:
    target = users_by_role_a[UserRole.CLEANER]

    response = await api.post(
        f"/api/v1/users/{target.id}/reset-password",
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    row = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == actions.USER_PASSWORD_RESET)
        )
    ).scalar_one()
    assert row.changes == {"password": {"changed": True}}
    assert response.json()["temporary_password"] not in str(row.changes)


@pytest.mark.asyncio
async def test_resetting_an_unknown_user_answers_404(api, users_by_role_a) -> None:
    response = await api.post(
        f"/api/v1/users/{uuid.uuid4()}/reset-password",
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 404


# --- explicit nulls (security panel of sections 2-6) -------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["name", "email", "preferred_language", "role", "status"])
async def test_an_explicit_null_for_a_non_nullable_field_answers_422(
    api, db_session, users_by_role_a, field
) -> None:
    """Regression for the two findings the security panel of sections 2-6 reproduced live.

    `{"email": null}` used to answer `200` and write the literal string `"none"` into the login
    identity — locking the account out of a product whose identity IS its email (ADR 0005).
    `{"status": null}` used to reach the database and come back as an unmapped `500`.

    The cause was one conflation: every field of the PATCH schema is `X | None` because that is
    how "not sent" is spelled, and `model_fields_set` could not tell that apart from a `null`
    the caller actually sent.
    """
    target = users_by_role_a[UserRole.CLEANER]
    before = (
        await db_session.execute(select(UserModel).where(UserModel.id == target.id))
    ).scalar_one()
    previous = getattr(before, field)

    response = await api.patch(
        f"/api/v1/users/{target.id}",
        json={field: None},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    after = (
        await db_session.execute(select(UserModel).where(UserModel.id == target.id))
    ).scalar_one()
    assert getattr(after, field) == previous


@pytest.mark.asyncio
async def test_phone_is_the_one_field_a_null_may_clear(api, users_by_role_a) -> None:
    """`phone` is the only nullable column of `users`, so clearing it is legitimate."""
    target = users_by_role_a[UserRole.CLEANER]
    await api.patch(
        f"/api/v1/users/{target.id}",
        json={"phone": "+34600000000"},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    response = await api.patch(
        f"/api/v1/users/{target.id}",
        json={"phone": None},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 200
    assert response.json()["phone"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["fr", "de", "esp", "EN-GB", ""])
async def test_an_unsupported_language_answers_422_on_create(
    api, users_by_role_a, language
) -> None:
    """R1.7: `es` and `en` are the two locales that exist in `frontend/locales/`."""
    response = await api.post(
        "/api/v1/users",
        json=_payload(preferred_language=language),
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_an_unsupported_language_answers_422_on_patch(api, users_by_role_a) -> None:
    response = await api.patch(
        f"/api/v1/users/{users_by_role_a[UserRole.CLEANER].id}",
        json={"preferred_language": "fr"},
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_supported_language_is_accepted(api, users_by_role_a) -> None:
    """The positive half, so the test above cannot pass by rejecting everything."""
    response = await api.post(
        "/api/v1/users",
        json=_payload(preferred_language="en"),
        headers=auth_header(api, users_by_role_a[OWNER]),
    )

    assert response.status_code == 201
    assert response.json()["user"]["preferred_language"] == "en"


@pytest.mark.asyncio
async def test_the_temporary_password_never_reaches_the_application_log(
    api, caplog, users_by_role_a
) -> None:
    """R1.2 has three channels; this is the one that had no test (feature-scale QA review).

    The response body and the audit row were already asserted. The log was only true
    vacuously — `user_admin.py` has no logger at all — and "true because nobody writes there
    yet" is exactly the kind of guarantee that stops being true silently.
    """
    import logging

    with caplog.at_level(logging.DEBUG):
        created = await api.post(
            "/api/v1/users", json=_payload(), headers=auth_header(api, users_by_role_a[OWNER])
        )
        secret = created.json()["temporary_password"]
        reset = await api.post(
            f"/api/v1/users/{created.json()['user']['id']}/reset-password",
            headers=auth_header(api, users_by_role_a[OWNER]),
        )
        reset_secret = reset.json()["temporary_password"]

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in logged
    assert reset_secret not in logged
