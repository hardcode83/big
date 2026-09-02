"""The self-service password endpoints over the real HTTP boundary (R1).

Complements `test_recovery_use_cases.py`, which pins orchestration against fakes. What is
asserted here is what a client actually receives — status, envelope, and the fact that the
sessions really stop working — through the app with only the outermost adapters swapped.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.auth.domain.enums import UserRole
from app.auth.infrastructure.models import UserModel, UserSessionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.auth.conftest import PASSWORD, auth_header, insert_user

NEW_PASSWORD = "a-brand-new-passphrase"


async def _login(api, email: str, password: str):
    return await api.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


# --- the happy path (R1.1) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_changing_the_password_answers_204(api, db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a)

    response = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_header(api, user),
    )

    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_the_new_password_is_the_one_that_works_afterwards(
    api, db_session, tenant_a
) -> None:
    user = await insert_user(db_session, tenant=tenant_a)

    await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_header(api, user),
    )

    assert (await _login(api, user.email, NEW_PASSWORD)).status_code == 200
    assert (await _login(api, user.email, PASSWORD)).status_code == 401


# --- the wrong current password (R1.2) ---------------------------------------------


@pytest.mark.asyncio
async def test_a_wrong_current_password_answers_401_invalid_credentials(
    api, db_session, tenant_a
) -> None:
    user = await insert_user(db_session, tenant=tenant_a)

    response = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": "not-the-one", "new_password": NEW_PASSWORD},
        headers=auth_header(api, user),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_a_wrong_current_password_leaves_the_stored_hash_alone(
    api, db_session, tenant_a
) -> None:
    """R1.2 SHALL NOT modify the hash — asserted against the row, not the response."""
    user = await insert_user(db_session, tenant=tenant_a)
    before = user.password_hash

    await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": "not-the-one", "new_password": NEW_PASSWORD},
        headers=auth_header(api, user),
    )

    row = (
        await db_session.execute(select(UserModel).where(UserModel.id == user.id))
    ).scalar_one()
    assert row.password_hash == before
    assert (await _login(api, user.email, PASSWORD)).status_code == 200


# --- SUPER_ADMIN cannot change its password through this endpoint (`super-admin-identity` D7) --


@pytest.mark.asyncio
async def test_a_super_admin_gets_a_clean_403_not_an_unmapped_500(api, db_session) -> None:
    """Task 6.4: the refusal happens before any `AuditLog` row is written."""
    from app.audit.infrastructure.models import AuditLogModel

    admin = await insert_user(db_session, tenant=None, role=UserRole.SUPER_ADMIN)
    before = len((await db_session.execute(select(AuditLogModel))).scalars().all())

    response = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_header(api, admin),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    after = (await db_session.execute(select(AuditLogModel))).scalars().all()
    assert len(after) == before, "SuperAdminSelfServiceUnsupportedError must fire before any audit write"


@pytest.mark.asyncio
async def test_a_super_admins_password_is_unchanged_after_the_refusal(api, db_session) -> None:
    admin = await insert_user(db_session, tenant=None, role=UserRole.SUPER_ADMIN)

    await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_header(api, admin),
    )

    assert (await _login(api, admin.email, PASSWORD)).status_code == 200
    assert (await _login(api, admin.email, NEW_PASSWORD)).status_code == 401


# --- the policy and the request shape (R1.4, R1.5, R1.7) ---------------------------


@pytest.mark.asyncio
async def test_a_password_under_the_minimum_answers_422(api, db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a)

    response = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=auth_header(api, user),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_the_rejection_names_the_rule_without_echoing_the_password(
    api, db_session, tenant_a
) -> None:
    """R1.5: say which rule was broken, and never return the credential (R4.3)."""
    user = await insert_user(db_session, tenant=tenant_a)
    weak = "abc"

    response = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": weak},
        headers=auth_header(api, user),
    )

    body = response.text
    assert "12" in body
    assert weak not in body
    assert PASSWORD not in body


@pytest.mark.asyncio
async def test_a_password_identical_to_the_current_one_answers_422(
    api, db_session, tenant_a
) -> None:
    """R1.7 — it would revoke every session without rotating anything."""
    user = await insert_user(db_session, tenant=tenant_a)

    response = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": PASSWORD},
        headers=auth_header(api, user),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_a_body_that_names_another_user_is_refused(api, db_session, tenant_a) -> None:
    """R1.4: the subject comes from the token, so `extra="forbid"` must reject the attempt
    rather than silently ignore it — silent ignoring is how somebody believes it worked."""
    user = await insert_user(db_session, tenant=tenant_a)
    victim = await insert_user(db_session, tenant=tenant_a)

    response = await api.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "user_id": str(victim.id),
        },
        headers=auth_header(api, user),
    )

    assert response.status_code == 422
    row = (
        await db_session.execute(select(UserModel).where(UserModel.id == victim.id))
    ).scalar_one()
    assert row.password_hash == victim.password_hash


@pytest.mark.asyncio
async def test_a_tenant_id_in_the_body_is_refused(api, db_session, tenant_a) -> None:
    user = await insert_user(db_session, tenant=tenant_a)

    response = await api.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "tenant_id": str(uuid.uuid4()),
        },
        headers=auth_header(api, user),
    )

    assert response.status_code == 422


# --- authentication and permission (R1.4) ------------------------------------------


@pytest.mark.asyncio
async def test_it_requires_a_token(api) -> None:
    response = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "role", [role for role in UserRole if role is not UserRole.SUPER_ADMIN]
)
@pytest.mark.asyncio
async def test_every_role_that_can_authenticate_may_change_its_own_password(
    api, db_session, tenant_a, role
) -> None:
    """R1.4: `MANAGE_OWN_SESSION` is what PRD §6 grants to every authenticating role, so a
    CLEANER must be able to rotate their own credential exactly like a TENANT_OWNER.

    `SUPER_ADMIN` excluded on purpose: it holds `MANAGE_OWN_SESSION` too, but
    `super-admin-identity` D7 refuses it a clean `403` instead — pinned separately by
    `test_a_super_admin_gets_a_clean_403_not_an_unmapped_500` above, and it cannot be
    seeded here anyway (`ck_users_super_admin_tenant_id_null` refuses a `SUPER_ADMIN`
    row bound to a tenant)."""
    user = await insert_user(db_session, tenant=tenant_a, role=role)

    response = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_header(api, user),
    )

    assert response.status_code == 204


# --- session revocation (R1.3) -----------------------------------------------------


@pytest.mark.asyncio
async def test_the_previous_sessions_are_revoked(api, db_session, tenant_a) -> None:
    """R1.3 — including the family that made the call."""
    user = await insert_user(db_session, tenant=tenant_a)
    logged_in = await _login(api, user.email, PASSWORD)
    refresh_token = logged_in.json()["refresh_token"]

    await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_header(api, user),
    )

    refreshed = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refreshed.status_code == 401


@pytest.mark.asyncio
async def test_the_calling_session_itself_is_revoked(api, db_session, tenant_a) -> None:
    """R1.3's "**incluida la de la sesión que hizo la llamada**", demonstrated.

    The other revocation tests here use `auth_header()`, which mints a token with a fresh
    random `family_id` that was never persisted as a session row — so they prove "every
    OTHER session dies" and say nothing about the caller's own. This one authenticates with
    the access token that a real `login` issued, then shows the refresh token from that same
    login is dead afterwards.

    The guarantee holds by construction today (`revoke_all_for_user` has no family-exclusion
    parameter to exempt anyone with), but construction is not a test: somebody adding an
    `exclude_family_id` argument and wiring it wrong is exactly the regression this catches.
    Gap found by the QA panel of section 4.
    """
    user = await insert_user(db_session, tenant=tenant_a)
    logged_in = (await _login(api, user.email, PASSWORD)).json()

    # Establish that this refresh token WORKS first, or the assertion below would also pass
    # against a broken refresh endpoint. Rotation consumes it, so the token to kill later is
    # the one this hands back.
    rotated = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": logged_in["refresh_token"]}
    )
    assert rotated.status_code == 200
    live_refresh_token = rotated.json()["refresh_token"]

    response = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        # The caller's OWN token, from a session that really exists in the database.
        headers={"Authorization": f"Bearer {logged_in['access_token']}"},
    )
    assert response.status_code == 204

    refreshed = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": live_refresh_token}
    )
    assert refreshed.status_code == 401, (
        "the family that made the call survived, so the change added a credential "
        "instead of rotating one"
    )


@pytest.mark.asyncio
async def test_every_session_row_of_the_user_is_marked_revoked(
    api, db_session, tenant_a
) -> None:
    user = await insert_user(db_session, tenant=tenant_a)
    await _login(api, user.email, PASSWORD)
    await _login(api, user.email, PASSWORD)

    await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_header(api, user),
    )

    rows = (
        await db_session.execute(
            select(UserSessionModel).where(UserSessionModel.user_id == user.id)
        )
    ).scalars().all()
    assert rows
    assert all(row.revoked_at is not None for row in rows)


# --- R2: forgot-password, anonymous and indistinguishable --------------------------


async def _forgot(api, email: str):
    return await api.post("/api/v1/auth/forgot-password", json={"email": email})


@pytest.mark.asyncio
async def test_forgot_password_is_anonymous_and_answers_202(
    api, db_session, tenant_a
) -> None:
    user = await insert_user(db_session, tenant=tenant_a)

    response = await _forgot(api, user.email)

    assert response.status_code == 202
    assert "detail" in response.json()


@pytest.mark.asyncio
async def test_every_outcome_is_byte_identical(api, db_session, tenant_a, tenant_b) -> None:
    """R2.2 — the strongest form: code, body AND headers, for all five outcomes.

    An account, an unknown address, an inactive user, an inactive tenant, and an account at
    its live-token cap. If any of these differed, the endpoint would be an anonymous
    user-enumerator: the same reason `auth-tenancy` made its five login failures identical.
    """
    from app.auth.domain.enums import UserStatus
    from app.tenants.domain.enums import TenantStatus

    known = await insert_user(db_session, tenant=tenant_a)
    inactive_user = await insert_user(
        db_session, tenant=tenant_a, status=UserStatus.INACTIVE
    )
    in_suspended_tenant = await insert_user(db_session, tenant=tenant_b)
    tenant_b.status = TenantStatus.SUSPENDED
    await db_session.flush()

    capped = await insert_user(db_session, tenant=tenant_a)
    for _ in range(3):
        assert (await _forgot(api, capped.email)).status_code == 202

    responses = [
        await _forgot(api, known.email),
        await _forgot(api, "nobody-at-all@example.test"),
        await _forgot(api, inactive_user.email),
        await _forgot(api, in_suspended_tenant.email),
        await _forgot(api, capped.email),
    ]

    assert {r.status_code for r in responses} == {202}
    assert len({r.text for r in responses}) == 1, "the bodies differ between outcomes"
    # Headers that legitimately vary per response are excluded; the rest must match.
    volatile = {"date", "content-length", "server"}
    header_sets = {
        tuple(sorted((k.lower(), v) for k, v in r.headers.items() if k.lower() not in volatile))
        for r in responses
    }
    assert len(header_sets) == 1, "the headers differ between outcomes"


@pytest.mark.asyncio
async def test_only_the_resolvable_account_gets_a_row(api, db_session, tenant_a) -> None:
    """R2.2's other half: indistinguishable to the caller, but the refused paths really do
    write nothing — no token, no `notification_logs` row."""
    from app.auth.infrastructure.models import PasswordResetTokenModel
    from app.notifications.infrastructure.models import NotificationLogModel

    known = await insert_user(db_session, tenant=tenant_a)
    await _forgot(api, "nobody-at-all@example.test")

    assert (
        await db_session.execute(select(PasswordResetTokenModel))
    ).scalars().all() == []

    await _forgot(api, known.email)

    tokens = (await db_session.execute(select(PasswordResetTokenModel))).scalars().all()
    rows = (
        await db_session.execute(
            select(NotificationLogModel).where(
                NotificationLogModel.notification_type == "PASSWORD_RESET_REQUESTED"
            )
        )
    ).scalars().all()
    assert len(tokens) == 1
    assert tokens[0].user_id == known.id
    assert len(rows) == 1
    assert rows[0].recipient_user_id == known.id


@pytest.mark.asyncio
async def test_a_super_admin_email_answers_202_and_writes_no_token(api, db_session) -> None:
    """`super-admin-identity` D7 amendment: treated exactly like an unresolved address —
    `password_reset_tokens.tenant_id` stays `NOT NULL`, so a token row would fail at
    `commit()` as an unmapped `IntegrityError` if one were ever built."""
    from app.auth.infrastructure.models import PasswordResetTokenModel

    admin = await insert_user(db_session, tenant=None, role=UserRole.SUPER_ADMIN)

    response = await _forgot(api, admin.email)

    assert response.status_code == 202
    assert (
        await db_session.execute(select(PasswordResetTokenModel))
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_the_stored_row_carries_no_link(api, db_session, tenant_a) -> None:
    """R4.2 at the database, not only at the use case (design D2)."""
    from app.notifications.infrastructure.models import NotificationLogModel

    user = await insert_user(db_session, tenant=tenant_a)

    await _forgot(api, user.email)

    row = (
        await db_session.execute(
            select(NotificationLogModel).where(
                NotificationLogModel.notification_type == "PASSWORD_RESET_REQUESTED"
            )
        )
    ).scalar_one()
    assert "token=" not in (row.body or "")
    assert "reset-password" not in (row.body or "")
    assert row.status.value != "PENDING"
    assert row.sla_deadline_at is None


@pytest.mark.asyncio
async def test_forgot_password_writes_no_audit_row(api, db_session, tenant_a) -> None:
    """Design D9, asserted as an absence (security panel of section 6 asked for it).

    `audit_logs` is evidence of CHANGES, not of requests — the criterion `user-management`
    set — and this is anonymous surface, so auditing here would let the internet dictate the
    table's growth. The omission is structural (the use case takes no `AuditLogRepository`),
    but a future `_AuditWriter` added to this module would silently reverse the decision, and
    nothing would have failed.
    """
    from app.audit.infrastructure.models import AuditLogModel

    user = await insert_user(db_session, tenant=tenant_a)
    before = len((await db_session.execute(select(AuditLogModel))).scalars().all())

    await _forgot(api, user.email)
    await _forgot(api, "nobody-at-all@example.test")

    after = (await db_session.execute(select(AuditLogModel))).scalars().all()
    assert len(after) == before


@pytest.mark.asyncio
async def test_a_body_naming_a_tenant_is_refused(api, db_session, tenant_a) -> None:
    """R2.3: the tenant is derived from the resolved row, so the body cannot supply it."""
    user = await insert_user(db_session, tenant=tenant_a)

    response = await api.post(
        "/api/v1/auth/forgot-password",
        json={"email": user.email, "tenant_id": str(uuid.uuid4())},
    )

    assert response.status_code == 422


# --- R3: consuming the token over HTTP ----------------------------------------------


async def _link_token_for(api, db_session, tenant_a):
    """Drive the real R2 endpoint, then read the token out of the row.

    The cleartext only ever exists inside that request (design D2), so a test cannot see it —
    which is exactly the property R4.1 buys. What it CAN do is seed a token of its own with a
    known cleartext, which is what this returns.
    """
    from app.auth.domain.recovery_tokens import generate_recovery_token
    from app.auth.infrastructure.models import PasswordResetTokenModel

    user = await insert_user(db_session, tenant=tenant_a)
    cleartext, token_hash = generate_recovery_token()
    db_session.add(
        PasswordResetTokenModel(
            tenant_id=tenant_a.id,
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    await db_session.flush()
    return user, cleartext


@pytest.mark.asyncio
async def test_reset_password_answers_204_and_the_new_password_works(
    api, db_session, tenant_a
) -> None:
    """R3.1."""
    user, cleartext = await _link_token_for(api, db_session, tenant_a)

    response = await api.post(
        "/api/v1/auth/reset-password",
        json={"token": cleartext, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert (await _login(api, user.email, NEW_PASSWORD)).status_code == 200
    assert (await _login(api, user.email, PASSWORD)).status_code == 401


@pytest.mark.asyncio
async def test_reset_password_returns_no_session(api, db_session, tenant_a) -> None:
    """R3.6 — possession of a link must not become a session without a credential."""
    _user, cleartext = await _link_token_for(api, db_session, tenant_a)

    response = await api.post(
        "/api/v1/auth/reset-password",
        json={"token": cleartext, "new_password": NEW_PASSWORD},
    )

    assert "access_token" not in response.text
    assert "refresh_token" not in response.text


@pytest.mark.asyncio
async def test_a_token_cannot_be_spent_twice_over_http(api, db_session, tenant_a) -> None:
    """R3.2 at the boundary."""
    _user, cleartext = await _link_token_for(api, db_session, tenant_a)
    body = {"token": cleartext, "new_password": NEW_PASSWORD}

    assert (await api.post("/api/v1/auth/reset-password", json=body)).status_code == 204
    second = await api.post("/api/v1/auth/reset-password", json=body)

    assert second.status_code == 401
    assert second.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_every_failure_answers_the_same_401(api, db_session, tenant_a) -> None:
    """R3.3 — all **six** named causes are indistinguishable.

    Compared on code AND body, because the whole point is that a caller cannot tell which of
    them happened. R3.3 lists "su usuario **o su tenant** dejaron de estar `ACTIVE`" as two
    separate causes, and the sixth — active user, inactive tenant — was missing until the QA
    panel of sections 7-10 pointed it out: it is the only case that depends on the tenant join
    inside `get_active_by_id`, so dropping that join would have gone unnoticed.
    """
    from app.auth.domain.enums import UserStatus
    from app.auth.domain.recovery_tokens import generate_recovery_token
    from app.auth.infrastructure.models import PasswordResetTokenModel
    from app.tenants.domain.enums import TenantStatus
    from tests.auth.conftest import insert_tenant

    now = datetime.now(UTC)
    cases = []

    # unknown
    cases.append(generate_recovery_token()[0])
    # already used, expired, revoked — one seeded token each, all for a live user
    live_user = await insert_user(db_session, tenant=tenant_a)
    for kwargs in (
        {"used_at": now},
        {"expires_at": now - timedelta(minutes=1)},
        {"revoked_at": now},
    ):
        cleartext, token_hash = generate_recovery_token()
        db_session.add(
            PasswordResetTokenModel(
                tenant_id=tenant_a.id,
                user_id=live_user.id,
                token_hash=token_hash,
                expires_at=kwargs.pop("expires_at", now + timedelta(minutes=30)),
                **kwargs,
            )
        )
        cases.append(cleartext)
    # a usable token whose user is not ACTIVE
    dead_user = await insert_user(db_session, tenant=tenant_a, status=UserStatus.INACTIVE)
    cleartext, token_hash = generate_recovery_token()
    db_session.add(
        PasswordResetTokenModel(
            tenant_id=tenant_a.id,
            user_id=dead_user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(minutes=30),
        )
    )
    cases.append(cleartext)
    # a usable token, an ACTIVE user, and a tenant that is not — the sixth cause
    suspended = await insert_tenant(
        db_session, name="suspended-tenant", status=TenantStatus.SUSPENDED
    )
    stranded_user = await insert_user(db_session, tenant=suspended)
    cleartext, token_hash = generate_recovery_token()
    db_session.add(
        PasswordResetTokenModel(
            tenant_id=suspended.id,
            user_id=stranded_user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(minutes=30),
        )
    )
    cases.append(cleartext)
    await db_session.flush()
    stranded_hash = stranded_user.password_hash

    responses = [
        await api.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": NEW_PASSWORD},
        )
        for token in cases
    ]

    assert len(cases) == 6, "R3.3 names six causes; this test must present all of them"
    assert {r.status_code for r in responses} == {401}
    assert len({r.text for r in responses}) == 1, "the six failures are distinguishable"
    # And the stranded user's hash did not move: R3.3's "SHALL NOT modificar el hash" holds on
    # the branch this case exists to cover.
    row = (
        await db_session.execute(
            select(UserModel).where(UserModel.id == stranded_user.id)
        )
    ).scalar_one()
    assert row.password_hash == stranded_hash


@pytest.mark.asyncio
async def test_a_weak_password_answers_422_without_spending_the_token(
    api, db_session, tenant_a
) -> None:
    """Design D10: the policy is checked before the conditional UPDATE."""
    user, cleartext = await _link_token_for(api, db_session, tenant_a)

    weak = await api.post(
        "/api/v1/auth/reset-password", json={"token": cleartext, "new_password": "short"}
    )

    assert weak.status_code == 422
    # The token survived, so the holder can try again with a stronger password.
    good = await api.post(
        "/api/v1/auth/reset-password",
        json={"token": cleartext, "new_password": NEW_PASSWORD},
    )
    assert good.status_code == 204


@pytest.mark.asyncio
async def test_a_body_naming_an_account_is_refused(api, db_session, tenant_a) -> None:
    """R3.3 / design D3: the token IS the subject, so nothing else may name one."""
    _user, cleartext = await _link_token_for(api, db_session, tenant_a)

    response = await api.post(
        "/api/v1/auth/reset-password",
        json={
            "token": cleartext,
            "new_password": NEW_PASSWORD,
            "user_id": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_previous_sessions_die_and_the_login_after_a_lockout_works(
    api, db_session, tenant_a
) -> None:
    """R3.5 end to end: (a) sessions revoked and (c) the account lock lifted.

    The lockout half is the one that matters most — ten failed attempts are what usually
    precede "I've lost my password", so without lifting it the recovery would be followed by
    a login refused with the same generic `401`.
    """
    user, cleartext = await _link_token_for(api, db_session, tenant_a)
    logged_in = (await _login(api, user.email, PASSWORD)).json()

    reset = await api.post(
        "/api/v1/auth/reset-password",
        json={"token": cleartext, "new_password": NEW_PASSWORD},
    )
    assert reset.status_code == 204

    refreshed = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": logged_in["refresh_token"]}
    )
    assert refreshed.status_code == 401
    assert (await _login(api, user.email, NEW_PASSWORD)).status_code == 200


@pytest.mark.asyncio
async def test_the_other_live_links_stop_working(api, db_session, tenant_a) -> None:
    """R3.5(b) — a completed recovery leaves no spare credentials."""
    from app.auth.domain.recovery_tokens import generate_recovery_token
    from app.auth.infrastructure.models import PasswordResetTokenModel

    user, first = await _link_token_for(api, db_session, tenant_a)
    second_clear, second_hash = generate_recovery_token()
    db_session.add(
        PasswordResetTokenModel(
            tenant_id=tenant_a.id,
            user_id=user.id,
            token_hash=second_hash,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    await db_session.flush()

    assert (
        await api.post(
            "/api/v1/auth/reset-password",
            json={"token": first, "new_password": NEW_PASSWORD},
        )
    ).status_code == 204

    leftover = await api.post(
        "/api/v1/auth/reset-password",
        json={"token": second_clear, "new_password": "yet-another-passphrase"},
    )
    assert leftover.status_code == 401


# --- the temporary-password gate (R5.4, R5.5, R5.6, design D6) ---------------------


async def _create_user_with_temporary_password(api, db_session, tenant_a):
    """An account in the state R5 is about to fence: created by an administrator, holding a
    temporary password it has not changed."""
    owner = await insert_user(db_session, tenant=tenant_a, role=UserRole.TENANT_OWNER)
    created = await api.post(
        "/api/v1/users",
        json={"name": "Nueva", "email": f"n-{uuid.uuid4().hex[:8]}@example.com", "role": "CLEANER"},
        headers=auth_header(api, owner),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    # `CreatedUserResponse` is `{user: {...}, temporary_password: ...}` — the secret lives
    # beside the user, not inside it, because it is the only shape that carries it.
    return body["user"], body["temporary_password"]


@pytest.mark.asyncio
async def test_a_temporary_password_still_logs_in(api, db_session, tenant_a) -> None:
    """R5.5: blocking the login would leave the account dead rather than fenced — there
    would be no way to reach the endpoint that fixes it."""
    body, temporary = await _create_user_with_temporary_password(api, db_session, tenant_a)

    logged_in = await _login(api, body["email"], temporary)

    assert logged_in.status_code == 200
    assert logged_in.json()["access_token"]
    assert logged_in.json()["refresh_token"]


@pytest.mark.asyncio
async def test_the_whole_escape_route_works_end_to_end(api, db_session, tenant_a) -> None:
    """The net against the risk design D6 names: leaving an account encerrada.

    Login with the temporary → any ordinary endpoint answers `403 PASSWORD_CHANGE_REQUIRED`
    → `change-password` answers `204` → the same endpoint now answers. If any single link
    breaks, the account is trapped with no endpoint back, so this is asserted as one flow
    rather than as four separate facts.
    """
    body, temporary = await _create_user_with_temporary_password(api, db_session, tenant_a)
    tokens = (await _login(api, body["email"], temporary)).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    fenced = await api.get("/api/v1/notifications", headers=headers)
    assert fenced.status_code == 403
    assert fenced.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    changed = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": temporary, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert changed.status_code == 204

    # The change revoked every family, so a fresh login is required — which is R1.3, and is
    # why this step is not optional in the flow.
    fresh = (await _login(api, body["email"], NEW_PASSWORD)).json()
    released = await api.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {fresh['access_token']}"},
    )
    assert released.status_code == 200


@pytest.mark.asyncio
async def test_me_is_reachable_while_fenced_and_reports_the_flag(
    api, db_session, tenant_a
) -> None:
    """R5.6: the frontend has to be able to learn the state, or it can only discover it by
    provoking a `403` on something unrelated."""
    body, temporary = await _create_user_with_temporary_password(api, db_session, tenant_a)
    tokens = (await _login(api, body["email"], temporary)).json()

    me = await api.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert me.status_code == 200
    assert me.json()["must_change_password"] is True


@pytest.mark.asyncio
async def test_logout_is_reachable_while_fenced(api, db_session, tenant_a) -> None:
    """Somebody who cannot change it right now must be able to walk away cleanly instead of
    leaving a live session behind."""
    body, temporary = await _create_user_with_temporary_password(api, db_session, tenant_a)
    tokens = (await _login(api, body["email"], temporary)).json()

    logged_out = await api.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert logged_out.status_code == 204


@pytest.mark.asyncio
async def test_the_flag_is_false_after_the_change(api, db_session, tenant_a) -> None:
    """R5.3, observed through the API rather than the entity."""
    body, temporary = await _create_user_with_temporary_password(api, db_session, tenant_a)
    tokens = (await _login(api, body["email"], temporary)).json()
    await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": temporary, "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    fresh = (await _login(api, body["email"], NEW_PASSWORD)).json()
    me = await api.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {fresh['access_token']}"},
    )

    assert me.json()["must_change_password"] is False


@pytest.mark.asyncio
async def test_a_fenced_account_with_a_wrong_current_password_gets_401_not_403(
    api, db_session, tenant_a
) -> None:
    """The two refusals must not be confused (R5.4 vs R1.2).

    `change-password` is exempt unconditionally, so the gate never fires on it and the use
    case's own credential check decides. If the exempt check were ever made conditional on
    the flag — or moved after the verify — a fenced account with a typo would get `403`,
    telling it to do the very thing it was already doing. Gap named by the QA panel of
    section 5, which verified the behaviour by probe with nothing pinning it.
    """
    body, temporary = await _create_user_with_temporary_password(api, db_session, tenant_a)
    tokens = (await _login(api, body["email"], temporary)).json()

    response = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": "not-the-temporary-one", "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_a_trailing_slash_on_an_exempt_route_redirects_rather_than_fencing(
    api, db_session, tenant_a
) -> None:
    """The one untested boundary of "the gate matches the routed path" (R5.4).

    `GET /api/v1/auth/me/` is answered with Starlette's `307` to the canonical path before
    the gate is reached at all, so it is not a bypass — nothing is returned and no
    authorisation decision is skipped. Pinned because the reasoning is not obvious: a reader
    could otherwise conclude the trailing-slash form is exempt, or that it leaks. Named by
    the QA panel of section 5.
    """
    body, temporary = await _create_user_with_temporary_password(api, db_session, tenant_a)
    tokens = (await _login(api, body["email"], temporary)).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    redirected = await api.get("/api/v1/auth/me/", headers=headers)

    assert redirected.status_code == 307
    assert redirected.headers["location"].endswith("/api/v1/auth/me")
    # Following it lands on the exempt route and works, so the redirect costs nothing.
    followed = await api.get(redirected.headers["location"], headers=headers)
    assert followed.status_code == 200
    assert followed.json()["must_change_password"] is True


@pytest.mark.asyncio
async def test_an_account_that_owes_nothing_is_not_fenced(api, db_session, tenant_a) -> None:
    """The other half: the gate must not fire for everybody else."""
    user = await insert_user(db_session, tenant=tenant_a, role=UserRole.TENANT_OWNER)

    response = await api.get("/api/v1/notifications", headers=auth_header(api, user))

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_refresh_works_while_fenced(api, db_session, tenant_a) -> None:
    """R5.5 at the HTTP boundary: `refresh` does not pass through the gate, so a fenced
    account can still renew the session it needs to call `change-password`."""
    body, temporary = await _create_user_with_temporary_password(api, db_session, tenant_a)
    tokens = (await _login(api, body["email"], temporary)).json()

    refreshed = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert refreshed.status_code == 200


# --- the account lockout, over the real wiring (R1.8, design D14) ------------------


@pytest_asyncio.fixture
async def throttled_api(db_session):
    """The real app with a REAL-threshold throttle, unlike the shared `api` fixture.

    `tests/auth/conftest.py`'s `api` installs `UnlimitedLoginThrottle`, which is right for
    every other test here and useless for this one. The dependency override is what makes
    this test able to fail: if `get_change_own_password_use_case` stopped passing the
    throttle, every use-case test would stay green and only this one would notice.
    """
    from httpx import ASGITransport, AsyncClient

    from app.auth.api.dependencies import (
        get_login_throttle,
        get_password_hasher,
        get_token_codec,
    )
    from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
    from app.auth.infrastructure.token_codec import JwtTokenCodec
    from app.core.db import get_db_session
    from app.main import create_app
    from tests.auth.conftest import TEST_BCRYPT_ROUNDS
    from tests.auth.doubles import InMemoryLoginThrottle

    app = create_app()
    codec = JwtTokenCodec(secret="u" * 64, access_minutes=15, refresh_days=7)
    throttle = InMemoryLoginThrottle(attempts_per_minute=10**9, max_failures=3)

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_login_throttle] = lambda: throttle
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        client.throttle = throttle  # type: ignore[attr-defined]
        yield client


@pytest.mark.asyncio
async def test_forgot_password_spends_the_same_ip_budget_as_login(
    throttled_api, db_session, tenant_a
) -> None:
    """R2.4: ONE per-IP counter across `login`, `refresh` and `forgot-password`.

    Splitting it would let a caller spend two budgets from one address, which is exactly the
    reasoning that put `refresh` into login's counter. Asserted in both directions, because a
    shared counter is a claim about both endpoints.
    """
    user = await insert_user(db_session, tenant=tenant_a)
    throttled_api.throttle._attempts_per_minute = 3

    # Spend the whole budget on login, then forgot-password must be refused.
    for _ in range(3):
        await throttled_api.post(
            "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )

    refused = await throttled_api.post(
        "/api/v1/auth/forgot-password", json={"email": user.email}
    )

    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_login_is_refused_after_forgot_password_spends_the_budget(
    throttled_api, db_session, tenant_a
) -> None:
    """The other direction of R2.4's shared counter."""
    user = await insert_user(db_session, tenant=tenant_a)
    throttled_api.throttle._attempts_per_minute = 3

    for _ in range(3):
        await throttled_api.post(
            "/api/v1/auth/forgot-password", json={"email": user.email}
        )

    refused = await throttled_api.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )

    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_the_rate_limit_is_checked_before_the_address_is_resolved(
    throttled_api, db_session, tenant_a
) -> None:
    """R2.4 says "antes de resolver el email", and it is not cosmetic: it means an
    unresolvable address costs no database work, and that the `429` cannot be read as
    evidence about the address."""
    from app.auth.infrastructure.models import PasswordResetTokenModel

    user = await insert_user(db_session, tenant=tenant_a)
    throttled_api.throttle._attempts_per_minute = 0

    refused = await throttled_api.post(
        "/api/v1/auth/forgot-password", json={"email": user.email}
    )

    assert refused.status_code == 429
    # Nothing was emitted for an address that certainly exists, so the check really did
    # precede the resolution.
    assert (
        await db_session.execute(select(PasswordResetTokenModel))
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_wrong_current_passwords_lock_the_account_over_http(
    throttled_api, db_session, tenant_a
) -> None:
    """R1.8 end to end: the counter is reached through the real dependency wiring."""
    user = await insert_user(db_session, tenant=tenant_a)
    headers = auth_header(throttled_api, user)

    for _ in range(3):
        response = await throttled_api.post(
            "/api/v1/auth/change-password",
            json={"current_password": "wrong", "new_password": NEW_PASSWORD},
            headers=headers,
        )
        assert response.status_code == 401

    assert await throttled_api.throttle.is_account_locked(user.id) is True


@pytest.mark.asyncio
async def test_a_locked_account_cannot_change_its_password_even_correctly(
    throttled_api, db_session, tenant_a
) -> None:
    """The lockout has to bite on the CORRECT password too, or it bounds nothing."""
    user = await insert_user(db_session, tenant=tenant_a)
    headers = auth_header(throttled_api, user)
    for _ in range(3):
        await throttled_api.post(
            "/api/v1/auth/change-password",
            json={"current_password": "wrong", "new_password": NEW_PASSWORD},
            headers=headers,
        )

    response = await throttled_api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_a_reset_lets_a_LOCKED_account_log_in_again(
    throttled_api, db_session, tenant_a
) -> None:
    """R3.5(c) end to end, over a throttle that can actually lock.

    `test_the_previous_sessions_die_and_the_login_after_a_lockout_works` is named for this and
    does not do it: it runs on the shared `api` fixture, which installs
    `UnlimitedLoginThrottle` (`max_failures=10**9`), so no number of failures locks anything
    there and the "aunque la cuenta estuviera bloqueada" half was untested through the API.
    The QA panel of sections 7-10 found that. Here the account is locked for real, and the
    lock is asserted **before** the reset — otherwise a green run could mean "never locked".

    What this catches that the use-case test cannot: the wiring. If
    `get_consume_password_reset_use_case` stopped passing the throttle, or passed the wrong
    id, every test with a double would stay green and only this one would fail.
    """
    user, cleartext = await _link_token_for(throttled_api, db_session, tenant_a)

    for _ in range(3):
        refused = await throttled_api.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "wrong"}
        )
        assert refused.status_code == 401

    assert await throttled_api.throttle.is_account_locked(user.id) is True, (
        "the account never locked, so this test would prove nothing about lifting the lock"
    )
    # And while it is locked the right password is refused too — the state this reset has to
    # undo is a real one.
    assert (await _login(throttled_api, user.email, PASSWORD)).status_code == 401

    reset = await throttled_api.post(
        "/api/v1/auth/reset-password",
        json={"token": cleartext, "new_password": NEW_PASSWORD},
    )

    assert reset.status_code == 204
    assert await throttled_api.throttle.is_account_locked(user.id) is False
    assert (await _login(throttled_api, user.email, NEW_PASSWORD)).status_code == 200


# --- isolation (regla 1 of steering/security.md) -----------------------------------


@pytest.mark.asyncio
async def test_changing_a_password_does_not_touch_another_tenant(
    api, db_session, tenant_a, tenant_b, test_engine
) -> None:
    """Verified from a session that was NEVER marked with a tenant.

    Two wrong ways to write this, both tried first and both worth recording. Reading B's
    row from `db_session` afterwards returns nothing, because the authenticated request
    binds that very session to tenant A (`bind_session_to_tenant`) and the global filter
    then hides B — which reads as "the password vanished", not as isolation. Logging B in
    fails for the same reason: even `find_by_email_globally` runs through the marked
    session in this fixture, where production would use a fresh one per request.

    So the assertion uses a separate session, which `app/core/db.py:149` names as the
    supported way: "Read unmarked data from a session that was NEVER marked instead."
    """
    user_a = await insert_user(db_session, tenant=tenant_a)
    user_b = await insert_user(db_session, tenant=tenant_b)
    await db_session.commit()
    before = user_b.password_hash

    response = await api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_header(api, user_a),
    )
    assert response.status_code == 204

    async with AsyncSession(test_engine, expire_on_commit=False) as unmarked:
        rows = {
            row.id: row
            for row in (
                await unmarked.execute(
                    select(UserModel).where(
                        UserModel.id.in_([user_a.id, user_b.id])
                    )
                )
            ).scalars().all()
        }

    assert rows[user_b.id].password_hash == before, "tenant B's credential was touched"
    assert rows[user_a.id].password_hash != before, "tenant A's own change did not land"
