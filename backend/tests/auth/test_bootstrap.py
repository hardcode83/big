"""Bootstrap of the initial tenant and users (R7.1-R7.4, design D14/D19)."""

import base64

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.auth.domain.enums import UserRole
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.cli.bootstrap import (
    BootstrapConfigurationError,
    BootstrapConflictError,
    apply_plan,
    build_plan,
)
from app.core.config import FERNET_KEY_BYTES, Settings, settings
from app.tenants.domain.enums import StorageType
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel
from tests.auth.conftest import TEST_BCRYPT_ROUNDS

_VALID_FERNET_KEY = base64.urlsafe_b64encode(b"0" * FERNET_KEY_BYTES).decode()

COMPLETE_ENV = {
    "BOOTSTRAP_TENANT_NAME": "AutoHostAI Madrid",
    "BOOTSTRAP_TENANT_BILLING_EMAIL": "billing@example.com",
    "BOOTSTRAP_OWNER_NAME": "Owner Person",
    "BOOTSTRAP_OWNER_EMAIL": "owner@example.com",
    "BOOTSTRAP_OWNER_PASSWORD": "owner-password-for-tests",
    "BOOTSTRAP_MANAGER_NAME": "Manager Person",
    "BOOTSTRAP_MANAGER_EMAIL": "manager@example.com",
    "BOOTSTRAP_MANAGER_PASSWORD": "manager-password-for-tests",
}


@pytest.fixture
def complete_env(monkeypatch: pytest.MonkeyPatch):
    for name, value in COMPLETE_ENV.items():
        monkeypatch.setattr(settings, name.lower(), value)
    # Pinned rather than inherited from the container's environment, and deliberately NOT a
    # member of COMPLETE_ENV: unlike the eight above it ships a working default, so it is not
    # one of the variables `build_plan` requires — see
    # `test_the_required_variables_are_exactly_the_ones_documented`.
    monkeypatch.setattr(settings, "bootstrap_storage_type", StorageType.LOCAL.value)
    return COMPLETE_ENV


@pytest.fixture
def hasher() -> BcryptPasswordHasher:
    return BcryptPasswordHasher(rounds=TEST_BCRYPT_ROUNDS)


@pytest.mark.parametrize("missing", sorted(COMPLETE_ENV))
def test_a_missing_variable_is_refused_before_anything_is_written(
    monkeypatch: pytest.MonkeyPatch, complete_env, missing: str
) -> None:
    monkeypatch.setattr(settings, missing.lower(), "")

    with pytest.raises(BootstrapConfigurationError) as excinfo:
        build_plan()

    assert missing in str(excinfo.value)


def test_a_whitespace_only_variable_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch, complete_env
) -> None:
    monkeypatch.setattr(settings, "bootstrap_owner_password", "   ")

    with pytest.raises(BootstrapConfigurationError):
        build_plan()


def test_every_missing_variable_is_reported_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in COMPLETE_ENV:
        monkeypatch.setattr(settings, name.lower(), "")

    with pytest.raises(BootstrapConfigurationError) as excinfo:
        build_plan()

    for name in COMPLETE_ENV:
        assert name in str(excinfo.value)


def test_the_error_never_echoes_a_password(monkeypatch: pytest.MonkeyPatch, complete_env) -> None:
    monkeypatch.setattr(settings, "bootstrap_manager_email", "")

    with pytest.raises(BootstrapConfigurationError) as excinfo:
        build_plan()

    assert COMPLETE_ENV["BOOTSTRAP_OWNER_PASSWORD"] not in str(excinfo.value)
    assert COMPLETE_ENV["BOOTSTRAP_MANAGER_PASSWORD"] not in str(excinfo.value)


def test_the_plan_carries_the_two_expected_roles(complete_env) -> None:
    plan = build_plan()

    assert [user.role for user in plan.users] == [
        UserRole.TENANT_OWNER,
        UserRole.PROPERTY_MANAGER,
    ]


def test_the_plan_normalises_the_addresses(monkeypatch: pytest.MonkeyPatch, complete_env) -> None:
    monkeypatch.setattr(settings, "bootstrap_owner_email", "  Jose@Example.COM ")

    plan = build_plan()

    assert plan.users[0].email == "jose@example.com"


@pytest.mark.asyncio
async def test_it_creates_the_tenant_its_config_and_both_users(
    db_session, complete_env, hasher
) -> None:
    created = await apply_plan(db_session, build_plan(), hasher)

    assert created == {
        "tenants": 1,
        "tenant_configs": 1,
        "tenant_configs_converged": 0,
        "users": 2,
    }
    tenant = (
        await db_session.execute(
            select(TenantModel).where(TenantModel.name == COMPLETE_ENV["BOOTSTRAP_TENANT_NAME"])
        )
    ).scalar_one()
    config = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant.id)
        )
    ).scalar_one_or_none()
    assert config is not None, "other modules assume a tenant always has its config"
    users = (
        (await db_session.execute(select(UserModel).where(UserModel.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert {user.role for user in users} == {UserRole.TENANT_OWNER, UserRole.PROPERTY_MANAGER}


@pytest.mark.asyncio
async def test_running_it_twice_changes_nothing(db_session, complete_env, hasher) -> None:
    """Convergence (D10) did not cost idempotency: with the configuration unchanged, a second
    run is still a no-op — including the `storage_type` it now converges."""
    await apply_plan(db_session, build_plan(), hasher)

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created == {
        "tenants": 0,
        "tenant_configs": 0,
        "tenant_configs_converged": 0,
        "users": 0,
    }
    assert await db_session.scalar(select(func.count()).select_from(TenantModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(UserModel)) == 2


@pytest.mark.asyncio
async def test_a_second_run_with_different_casing_stays_idempotent(
    db_session, monkeypatch: pytest.MonkeyPatch, complete_env, hasher
) -> None:
    """Without write-side normalisation this would hit the functional unique index.

    That is the failure the security panel described: the idempotency lookup and the
    insert must agree on what "the same email" is (design D19).
    """
    await apply_plan(db_session, build_plan(), hasher)
    monkeypatch.setattr(settings, "bootstrap_owner_email", "OWNER@Example.com")

    created = await apply_plan(db_session, build_plan(), hasher)

    assert created["users"] == 0


@pytest.mark.asyncio
async def test_the_stored_password_is_a_verifiable_bcrypt_hash(
    db_session, complete_env, hasher
) -> None:
    await apply_plan(db_session, build_plan(), hasher)

    owner = (
        await db_session.execute(
            select(UserModel).where(UserModel.email == COMPLETE_ENV["BOOTSTRAP_OWNER_EMAIL"])
        )
    ).scalar_one()

    assert owner.password_hash != COMPLETE_ENV["BOOTSTRAP_OWNER_PASSWORD"]
    assert owner.password_hash.startswith("$2")
    assert (
        await hasher.verify(COMPLETE_ENV["BOOTSTRAP_OWNER_PASSWORD"], owner.password_hash) is True
    )


@pytest.mark.asyncio
async def test_the_bootstrapped_owner_can_actually_log_in(
    db_session, monkeypatch: pytest.MonkeyPatch, complete_env, hasher
) -> None:
    """The point of the whole command: a fresh deployment has a way in (R7.1).

    The env var is set MIXED-CASE on purpose. An earlier version of this test used the
    already-lowercase fixture value, so it passed even with write-side normalisation
    removed — it proved only the read side and its docstring overclaimed. This way it
    fails if either half of design D19 goes missing.
    """
    from app.auth.infrastructure.repositories import SqlAlchemyUserRepository

    monkeypatch.setattr(settings, "bootstrap_owner_email", "OWNER@Example.COM")
    await apply_plan(db_session, build_plan(), hasher)

    found = await SqlAlchemyUserRepository(db_session).find_by_email_globally(
        "  owner@example.com "
    )

    assert found is not None
    assert (
        await hasher.verify(COMPLETE_ENV["BOOTSTRAP_OWNER_PASSWORD"], found.password_hash) is True
    )


@pytest.mark.asyncio
async def test_it_refuses_when_the_address_already_exists_under_another_tenant(
    db_session, monkeypatch: pytest.MonkeyPatch, complete_env, hasher
) -> None:
    """A typo in BOOTSTRAP_TENANT_NAME must fail with an explanation (security panel F3).

    Idempotency keys on the tenant name and `tenants` has no uniqueness on it, so a
    re-run with a changed name creates a second tenant and then tries to insert the
    same addresses under it. `uq_users_lower_email` refuses that write either way
    (ADR 0005) — what this check adds is an error naming the variable to look at
    instead of an IntegrityError about an index, so the assertion is on the type of
    error, not merely on the write failing.
    """
    await apply_plan(db_session, build_plan(), hasher)
    monkeypatch.setattr(settings, "bootstrap_tenant_name", "AutoHostAI Madird")  # typo

    with pytest.raises(BootstrapConflictError):
        await apply_plan(db_session, build_plan(), hasher)

    await db_session.rollback()
    from app.auth.infrastructure.repositories import SqlAlchemyUserRepository

    still_there = await SqlAlchemyUserRepository(db_session).find_by_email_globally(
        COMPLETE_ENV["BOOTSTRAP_OWNER_EMAIL"]
    )
    assert still_there is not None, "the owner must still be able to log in"


# --- `storage_type` by the seed route (`object-storage-provisioning` R6.1/R6.5, D10) ---


@pytest.mark.asyncio
async def test_the_configured_storage_type_is_applied_when_the_config_is_created(
    db_session, monkeypatch: pytest.MonkeyPatch, complete_env, hasher
) -> None:
    """R6.1 — the seed is the route into `S3`, and the only one.

    `storage_type` stays out of the `PATCH` of `TenantConfig` (R5.4 of `user-management`), so a
    deployment moves a tenant by configuring the bootstrap CLI and re-running it.
    """
    monkeypatch.setattr(settings, "bootstrap_storage_type", StorageType.S3.value)

    await apply_plan(db_session, build_plan(), hasher)

    assert await _stored_storage_type(db_session) is StorageType.S3


@pytest.mark.asyncio
async def test_a_re_run_converges_a_config_that_already_exists(
    db_session, monkeypatch: pytest.MonkeyPatch, complete_env, hasher
) -> None:
    """D10, and the whole reason `apply_plan` stopped being create-only.

    In `dev` the tenant and its config were seeded long before this setting existed. Create-only
    would leave `BOOTSTRAP_STORAGE_TYPE` unable to ever reach that environment without a
    hand-written `UPDATE` — which is what the IaC-first norm and R1.5 refuse.
    """
    await apply_plan(db_session, build_plan(), hasher)
    assert await _stored_storage_type(db_session) is StorageType.LOCAL
    monkeypatch.setattr(settings, "bootstrap_storage_type", StorageType.S3.value)

    created = await apply_plan(db_session, build_plan(), hasher)

    assert await _stored_storage_type(db_session) is StorageType.S3
    assert created["tenant_configs"] == 0, "nothing was created — it converged"
    assert created["tenant_configs_converged"] == 1


@pytest.mark.asyncio
async def test_convergence_goes_back_the_other_way_too(
    db_session, monkeypatch: pytest.MonkeyPatch, complete_env, hasher
) -> None:
    """Convergence means "the state the configuration declares", not "a one-way upgrade": an
    environment that has to be rolled back to `LOCAL` must be able to say so the same way."""
    monkeypatch.setattr(settings, "bootstrap_storage_type", StorageType.S3.value)
    await apply_plan(db_session, build_plan(), hasher)
    monkeypatch.setattr(settings, "bootstrap_storage_type", StorageType.LOCAL.value)

    created = await apply_plan(db_session, build_plan(), hasher)

    assert await _stored_storage_type(db_session) is StorageType.LOCAL
    assert created["tenant_configs_converged"] == 1


@pytest.mark.asyncio
async def test_a_new_tenant_is_born_local_when_nothing_is_configured(
    db_session, complete_env, hasher
) -> None:
    """R6.5 — held by construction: the column default and the setting default agree.

    The fixture pins the setting to its shipped default rather than clearing it, because the
    property under test is what an unconfigured deployment gets, and the deployed `.env` of a
    real environment may well say otherwise.
    """
    await apply_plan(db_session, build_plan(), hasher)

    assert await _stored_storage_type(db_session) is StorageType.LOCAL


def test_an_unknown_storage_type_is_refused_at_configuration_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R6.1 — refused while building `Settings`, not at the `INSERT`.

    Reaching the driver would mean failing after a tenant had been created and two passwords
    hashed, inside a transaction the operator then has to reason about.
    """
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            jwt_secret_key="0" * 64,
            encryption_key=_VALID_FERNET_KEY,
            bootstrap_storage_type="GLACIER",
        )


async def _stored_storage_type(db_session) -> StorageType:
    tenant = (
        await db_session.execute(
            select(TenantModel).where(TenantModel.name == COMPLETE_ENV["BOOTSTRAP_TENANT_NAME"])
        )
    ).scalar_one()
    config = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant.id)
        )
    ).scalar_one()
    return config.storage_type


def test_the_required_variables_are_exactly_the_ones_documented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keeps `build_plan`'s requirements and this module's fixture from drifting apart.

    Half of R7.4 is proven above: with every variable blank, `build_plan` refuses, so
    no default is baked into the code. The other half — that `.env.example` declares
    those same names with no value — is not asserted here, and the reason has changed.

    It used to be that it *could* not be: the container mounts only `backend/`, so the
    repo-root `.env.example` was unreachable from the project's own test command, and a
    test that cannot run where the suite runs is worse than none. The change `demo-user`
    settled that differently for its own variable (2026-08-23): `docker-compose.yml` now
    bind-mounts `.env.example` read-only at `/workspace/.env.example`, following the two
    precedents beside it, and `tests/cli/test_demo_reset.py` reads the file and goes red
    if anything appears to the right of the `=`.

    So the obstacle is gone and only the scope is left: extending that assertion to these
    eight names is a change to `auth-tenancy`'s contract and not to `demo-user`'s, so it
    belongs to whoever touches R7.4 next. Until then this half stays covered by the SDD
    documentation reviewer and the manual check of task 11.3.
    """
    # Blanked explicitly instead of relying on the container's ambient environment: a
    # developer who fills BOOTSTRAP_* in their own .env — which is exactly what
    # `make bootstrap` invites — would otherwise turn this test red for no reason.
    for name in COMPLETE_ENV:
        monkeypatch.setattr(settings, name.lower(), "")

    with pytest.raises(BootstrapConfigurationError) as excinfo:
        build_plan()

    reported = {
        word.strip(" ,")
        for word in str(excinfo.value).split()
        if word.strip(" ,").startswith("BOOTSTRAP_")
    }
    assert reported == set(COMPLETE_ENV)
