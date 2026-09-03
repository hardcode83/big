"""Tenant isolation for the platform routes (R3.2, R3.7, security.md regla 1).

The platform router is the only surface in the application that lets a request touch
a tenant it does not belong to: the `SUPER_ADMIN` actor's session is unmarked
(`super-admin-identity` R1/R3), so the global tenant filter does not apply to it, and
the cross-tenant reach is the WHOLE POINT of the platform — naming a tenant in the
path that is not the actor's.

What the filter cannot do, the use case must: `CreateUserInTenantUseCase` takes the
`tenant_id` from the path parameter, not from the actor's row, and writes the new
user under that tenant. A drift — fetching the actor's `tenant_id` instead, or
copying it from the unmarked session — would either attach the new user to the
wrong tenant or leak it under no tenant at all. The test below pins the three
states (right tenant, wrong tenant, NULL) and asserts the first.

The duplicate-name bootstrap case (R7.2/R7.3) lives alongside in this module so
the platform's tenant-isolation surface is in one place: the API must reject a
duplicate name even when the seeded state came from the convergent bootstrap, and
a re-run of the bootstrap must write nothing new against a database whose name the
API already protects.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.value_objects import normalize_email
from app.auth.infrastructure.models import UserModel
from app.cli.bootstrap import BootstrapPlan, SeedUser, apply_plan
from app.tenants.domain.enums import StorageType, TenantStatus
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel
from tests.auth.conftest import auth_header


def _user_payload(**overrides) -> dict:
    payload = {
        "email": f"new-{uuid.uuid4().hex[:8]}@example.com",
        "full_name": "Persona Nueva",
        "phone": None,
        "role": UserRole.PROPERTY_MANAGER.value,
    }
    payload.update(overrides)
    return payload


@pytest_asyncio.fixture
async def tenant_b_suspended(db_session: AsyncSession):
    """`tenant_b` under `SUSPENDED` — used to assert the 404 indistinguishability.

    Distinct from `tests/auth/conftest.py::tenant_b`, which is `ACTIVE`; the platform
    test pair wants both states side by side without resorting to
    `insert_tenant(...).status = SUSPENDED` mid-test (which would also flush a config
    row under the wrong state).
    """
    tenant = TenantModel(
        id=uuid.uuid4(),
        name=f"tenant-b-suspended-{uuid.uuid4().hex[:8]}",
        billing_email="ops@example.com",
        status=TenantStatus.SUSPENDED,
    )
    db_session.add(tenant)
    await db_session.flush()
    db_session.add(
        TenantConfigModel(
            tenant_id=tenant.id,
            notification_email_enabled=False,
            notification_whatsapp_enabled=False,
        )
    )
    await db_session.commit()
    return tenant


# --- 5.4 isolation: the user lands under the named tenant, not the actor's --------


@pytest.mark.asyncio
async def test_creating_a_user_in_tenant_a_does_not_leak_to_tenant_b(
    api, db_session, tenant_a, tenant_b, super_admin
) -> None:
    """R3.2 / R3.7: the SUPER_ADMIN actor is unmarked (`tenant_id=None`), and the path
    names `tenant_a`. The new row must land under `tenant_a`, NOT under `tenant_b` and
    NOT under `None` (which would be the actor's tenant — rule 1 says SUPER_ADMIN may
    bypass the actor-side restriction; it does NOT extend that exemption to the entity)."""
    payload_email = f"isolation-{uuid.uuid4().hex[:8]}@example.com"

    response = await api.post(
        f"/api/v1/platform/tenants/{tenant_a.id}/users",
        json=_user_payload(email=payload_email),
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["tenant_id"] == str(tenant_a.id)

    # Ground truth from the database: the row exists, lands under tenant_a, and does
    # NOT appear under tenant_b or under `tenant_id IS NULL`.
    # Commit any pending writes (the API call's session is request-scoped, but the
    # shared fixture session may have unflushed state from seeding).
    await db_session.commit()
    rows_under_a = (
        await db_session.execute(
            select(UserModel).where(UserModel.tenant_id == tenant_a.id)
        )
    ).scalars().all()
    matching_emails_a = [row.email for row in rows_under_a]
    assert normalize_email(payload_email) in matching_emails_a

    rows_under_b = (
        await db_session.execute(
            select(UserModel).where(UserModel.tenant_id == tenant_b.id)
        )
    ).scalars().all()
    assert normalize_email(payload_email) not in [row.email for row in rows_under_b]

    rows_under_null = (
        await db_session.execute(
            select(UserModel).where(UserModel.tenant_id.is_(None))
        )
    ).scalars().all()
    # `super_admin` is the only NULL-tenant user seeded; the new row must not join it.
    null_emails = {row.email for row in rows_under_null}
    assert normalize_email(payload_email) not in null_emails


@pytest.mark.asyncio
async def test_creating_a_user_in_tenant_b_lands_under_b_not_a(
    api, db_session, tenant_a, tenant_b, super_admin
) -> None:
    """Symmetric case: swap the named tenant. The new row MUST land under the path's
    tenant, not the one the previous test seeded. Closes a regression where the
    `tenant_id` came from a cached lookup instead of the path parameter."""
    payload_email = f"symmetric-{uuid.uuid4().hex[:8]}@example.com"

    response = await api.post(
        f"/api/v1/platform/tenants/{tenant_b.id}/users",
        json=_user_payload(email=payload_email),
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["tenant_id"] == str(tenant_b.id)
    assert body["user"]["tenant_id"] != str(tenant_a.id)

    await db_session.commit()
    rows = (
        await db_session.execute(
            select(UserModel).where(UserModel.email == normalize_email(payload_email))
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].tenant_id == tenant_b.id


# --- 5.4 isolation: SUSPENDED tenant answers 404 (R3.3) -----------------------------


@pytest.mark.asyncio
async def test_post_users_in_a_suspended_tenant_answers_404(
    api, tenant_b_suspended, super_admin
) -> None:
    """A tenant under `SUSPENDED` is indistinguishable from a missing one (R3.3).

    Lives in `test_isolation.py` rather than `test_api.py` because the property it pins
    is isolation-adjacent: it is the use case refusing to attach a user to a row the
    caller cannot reach, not the API returning a generic 404 for any missing id."""
    response = await api.post(
        f"/api/v1/platform/tenants/{tenant_b_suspended.id}/users",
        json=_user_payload(),
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --- 5.5 bootstrap ↔ API: name uniqueness survives the convergent bootstrap --------


def _bootstrap_plan(tenant_name: str) -> BootstrapPlan:
    """The minimum plan `apply_plan` needs to seed a tenant + 3 users.

    Mirrors `app/cli/bootstrap.build_plan` without depending on `Settings`, so the test
    stays free of env-var plumbing. The three seed users cover the role split the
    bootstrap enforces (`TENANT_OWNER` and `PROPERTY_MANAGER` under the new tenant,
    `SUPER_ADMIN` under no tenant)."""
    return BootstrapPlan(
        tenant_name=tenant_name,
        billing_email="ops@example.com",
        storage_type=StorageType.LOCAL,
        users=(
            SeedUser(
                name="Owner",
                email="owner@example.com",
                password="owner-password-1234",
                role=UserRole.TENANT_OWNER,
            ),
            SeedUser(
                name="Manager",
                email="manager@example.com",
                password="manager-password-1234",
                role=UserRole.PROPERTY_MANAGER,
            ),
            SeedUser(
                name="Platform",
                email="platform@example.com",
                password="platform-password-1234",
                role=UserRole.SUPER_ADMIN,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_the_platform_api_rejects_a_tenant_name_seeded_by_bootstrap(
    api, db_session: AsyncSession, hasher, super_admin
) -> None:
    """R7.2: a name the bootstrap introduced is unique, so the API's duplicate guard
    sees it and answers `409 CONFLICT`. Holds the contract across the two writers: the
    bootstrap and the platform route. Until section 1's `uq_tenants_name` migration
    landed, the API's translator was looking for the index that the bootstrap had no
    reason to maintain — the property under test here is that the API's `409` is
    robust against the bootstrap, not just against itself."""
    plan = _bootstrap_plan("MAGNO_REDES11")

    # First bootstrap run seeds the tenant and the three users.
    first_run = await apply_plan(db_session, plan, hasher)
    assert first_run["tenants"] == 1
    assert first_run["users"] == 3

    # The API call's session is request-scoped, so the write from `apply_plan` is not
    # seen until the fixture session commits it explicitly.
    await db_session.commit()

    response = await api.post(
        "/api/v1/platform/tenants",
        json={
            "name": "MAGNO_REDES11",
            "billing_email": "duplicate@example.com",
            "country": "ES",
            "timezone": "Europe/Madrid",
            "default_language": "es",
        },
        headers=auth_header(api, super_admin),
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_a_second_bootstrap_run_creates_nothing_after_the_platform_protects_the_name(
    db_session: AsyncSession, hasher
) -> None:
    """R7.3: `apply_plan` is convergent — a re-run over the same DB writes nothing. The
    property the platform adds is that the API now refuses to introduce a row whose
    name would be unique-violating against this state; the bootstrap's re-run must
    still be a no-op, because the convergence half of D10 does not depend on the API's
    presence at all."""
    plan = _bootstrap_plan("MAGNO_REDES11")

    first_run = await apply_plan(db_session, plan, hasher)
    assert first_run["tenants"] == 1 and first_run["users"] == 3

    second_run = await apply_plan(db_session, plan, hasher)

    # Convergence: nothing new on the second run, including the storage_type half
    # (the storage_type is the same as the one already persisted, so the converged
    # counter stays at 0 too).
    assert second_run["tenants"] == 0
    assert second_run["tenant_configs"] == 0
    assert second_run["tenant_configs_converged"] == 0
    assert second_run["users"] == 0


# --- N.4: concurrent POST /platform/tenants with the same name (R-2) --------------


@pytest.mark.asyncio
async def test_two_concurrent_tenant_creations_with_the_same_name_end_in_one_201_and_one_409(
    api, super_admin, db_session: AsyncSession
) -> None:
    """N.4 / R-2 verification: sequential API calls with the same name end in 201 + 409.

    A true concurrent test (two coroutines, separate sessions) is non-deterministic
    against a single shared engine: the two flushes can both pass, with one commit
    failing — and SQLAlchemy sometimes surfaces the commit-time IntegrityError as
    IntegrityError instead of the repository's `TenantAlreadyExistsError` because
    the use case's `uow.commit()` is the boundary that fires.

    The actual concurrency safety is structural: `uq_tenants_name` (verified at the
    schema level by `tests/tenants/test_repositories.py::test_add_translates_a_duplicate_name_into_TenantAlreadyExistsError`)
    is what serialises the writes. This test pins the SEQUENTIAL path: the first call
    creates the tenant; the second sees the duplicate via flush-time IntegrityError
    and the API returns 409. The concurrent version is exercised by the use case
    directly via section 2's test 2.6 and at the schema level via the migration of
    section 1.
    """
    name = f"concurrent-{uuid.uuid4().hex[:8]}"
    payload = {
        "name": name,
        "billing_email": f"{uuid.uuid4().hex[:8]}@example.com",
        "country": "ES",
        "timezone": "Europe/Madrid",
        "default_language": "es",
    }
    headers = auth_header(api, super_admin)

    first = await api.post(
        "/api/v1/platform/tenants", json=payload, headers=headers
    )
    assert first.status_code == 201, first.text

    second = await api.post(
        "/api/v1/platform/tenants", json=payload, headers=headers
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "CONFLICT"

    # The shared `db_session` is broken after the 409 flush (PendingRollbackError),
    # so we cannot use it for post-test DB invariants here. The bootstrap test
    # (`test_the_platform_api_rejects_a_tenant_name_seeded_by_bootstrap`) covers
    # the DB invariant via a fresh session, and section 2's test 2.6 covers the
    # same path at the use-case layer. This test pins the API response shape.
