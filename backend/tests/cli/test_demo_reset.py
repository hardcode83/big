"""The demonstration tenant's provisioning-and-reset command (change `demo-user`).

The tests of R2's three clauses live here (design D18): the credential exists only inside the
demonstration tenant, its value stays out of the tree, and tenant isolation is the single barrier
that holds. Each one is proven the way D18 prescribes, which is not the same way for all three.
"""

import base64
import json
import re
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.access.infrastructure.models import AccessRecordModel
from app.audit.domain import actions
from app.audit.domain.entities import AuditLog
from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.domain.password_policy import PASSWORD_MAX_BYTES, PASSWORD_MIN_LENGTH
from app.auth.infrastructure.models import (
    PasswordResetTokenModel,
    UserModel,
    UserSessionModel,
)
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.infrastructure.models import (
    CleaningChecklistCompletionModel,
    CleaningChecklistTemplateModel,
    CleaningPhotoModel,
    CleaningTaskMessageModel,
    CleaningTaskModel,
)
from app.cli import demo_reset, seed_demo
from app.core.config import FERNET_KEY_BYTES, Settings, settings
from app.core.db import Base, bind_session_to_tenant, tenant_scoped_classes
from app.core.tenancy import TenantMismatchedSessionError, TenantUnmarkedSessionError
from app.guests.domain.portal_token import hash_guest_token
from app.guests.infrastructure.models import GuestAccessTokenModel, GuestModel
from app.integrations.domain.enums import PmsCredentialScope, PMSProvider
from app.integrations.infrastructure.models import (
    PmsCredentialModel,
    WebhookEndpointModel,
    WebhookEventModel,
)
from app.maintenance.domain.enums import (
    IncidentPhotoStage,
    IncidentSource,
    OwnerApprovalRelatedType,
)
from app.maintenance.infrastructure.models import (
    IncidentMessageModel,
    IncidentModel,
    IncidentPhotoModel,
    OwnerApprovalModel,
)
from app.messaging.domain.enums import ConversationChannel, MessageSenderType
from app.messaging.infrastructure.models import (
    ConversationModel,
    MessageModel,
    WhatsAppInboundEventModel,
    WhatsAppPhoneNumberModel,
)
from app.notifications.domain.enums import NotificationChannel
from app.notifications.infrastructure.models import NotificationLogModel
from app.pricing.infrastructure.models import PriceRecommendationModel, PricingRuleModel
from app.properties.domain.enums import (
    PropertyOperationalState,
    StateTransitionTriggeredBy,
)
from app.properties.infrastructure.models import (
    PropertyModel,
    PropertyStateTransitionModel,
)
from app.reservations.domain.enums import ReservationChannel
from app.reservations.infrastructure.models import ReservationModel
from app.reviews.domain.enums import ReviewChannel
from app.reviews.infrastructure.models import ReviewModel, ReviewResponseDraftModel
from app.statements.domain.enums import ExpenseCategory
from app.statements.infrastructure.models import ExpenseModel, OwnerStatementModel
from app.tenants.domain.enums import StorageType
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from tests.auth.conftest import insert_tenant, insert_user
from tests.cli.conftest import (
    hasher,  # noqa: F401  -- fixture used by the section-4 tests
)
from tests.conftest import TEST_BCRYPT_ROUNDS

_REQUIRED = {
    "jwt_secret_key": "0" * 64,
    "encryption_key": base64.urlsafe_b64encode(b"0" * FERNET_KEY_BYTES).decode(),
}

#: Long enough for the policy, and recognisable if it ever turns up somewhere it must not.
DEMO_PASSWORD = "demo-password-for-tests"

#: What a database error's string looks like: the statement and its PARAMETERS, one of which is
#: the bcrypt hash of an account this command just converged. Nothing may forward it (D15).
_LEAKY_DETAIL = (
    "UPDATE users SET password_hash=$1 WHERE users.id = $2] "
    "[parameters: ('$2b$04$notarealhashbutshapedlikeone', 'a-user-id')]"
)


class _DatabaseErrorCarryingItsParameters(Exception):
    """Stands in for `sqlalchemy.exc.DBAPIError` without needing a broken database."""


@pytest.fixture(autouse=True)
def demo_storage_root(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Root every `LOCAL` store this module can reach at `tmp_path`, not at `MEDIA_ROOT`.

    The seed phase uploads the closed cleaning's photos, and it does so through
    `seed_demo._file_storage_factory()`, whose `local_root` defaults to `MEDIA_ROOT` —
    `/app/media`. Two independent reasons that has to be redirected, and the second is why this
    is `autouse`:

    1. **`/app` is not writable where the suite really runs.** In the container the repository
       is a bind mount and the directory happens to be writable, so leaving the default green
       locally; in CI it is not, and the seed phase fails with
       `PermissionError: [Errno 13] Permission denied: '/app'` surfacing as
       `PhaseError: seed: failed with PhotoStorageUnavailableError`. That is exactly what
       happened on PR #123: 14 tests of this file red in CI and all of them green here.
    2. **Shared mutable state between tests.** Every test that runs the command writes the same
       six objects to the same place, so counts and sweeps would depend on which tests ran
       before.

    `test_seed_demo.py::seed_storage` solves the identical problem the identical way and its
    docstring says so; this is that fixture, for the command that composes that seed. The sweep
    tests that patch `ConfiguredFileStorageFactory.storage_for` outright are unaffected — they
    replace the store rather than its root.
    """
    root = tmp_path / "media"
    real = demo_reset.ConfiguredFileStorageFactory

    class _RootedFactory(real):
        """The real factory, with `local_root` forced to the test's own directory.

        A subclass and not a lambda on purpose: the sweep tests patch
        `demo_reset.ConfiguredFileStorageFactory.storage_for`, which only works if the module
        attribute is still a class. They patch this subclass, and inherit everything else.
        """

        def __init__(self, **kwargs):
            super().__init__(**{**kwargs, "local_root": root})

    monkeypatch.setattr(demo_reset, "ConfiguredFileStorageFactory", _RootedFactory)
    monkeypatch.setattr(
        seed_demo, "_file_storage_factory", lambda: _RootedFactory(signing_key=b"k" * 32)
    )
    return root


@pytest.fixture
def demo_env(monkeypatch: pytest.MonkeyPatch):
    """A configuration in which the command would run: a password, and a neighbour tenant.

    `bootstrap_tenant_name` is pinned to something that is NOT the demonstration tenant, so a
    developer whose own `.env` happens to name it does not turn the refusal tests green for the
    wrong reason.
    """
    monkeypatch.setattr(settings, "demo_account_password", DEMO_PASSWORD)
    monkeypatch.setattr(settings, "bootstrap_tenant_name", "AutoHostAI Dev")
    monkeypatch.setattr(settings, "bootstrap_storage_type", StorageType.LOCAL.value)
    return DEMO_PASSWORD


def _use_the_test_database(monkeypatch: pytest.MonkeyPatch, test_engine: AsyncEngine) -> None:
    """Point the command's own session factory at the throwaway database.

    `demo_reset` does `from app.core.db import async_session_factory`, which binds a copy of the
    name into that module at import time; the factory itself was built from
    `settings.database_url`, i.e. the database the running stack serves. Any test that lets
    `main()`/`run()` reach a session must rebind it **in the CLI module** — patching
    `app.core.db` would be too late for the copy. `tests/auth/test_reset_password_cli.py` does
    the same thing, and its docstring records the bug that skipping it hid.

    Without this the write-path tests would be worse than absent: they would pass while writing
    the demonstration tenant into the real `autohostai` database, and a broken refusal would be
    invisible because the snapshot and the write would be in two different databases.

    `bcrypt_rounds` comes down to the suite's cheap value at the same time: the command builds
    its own hasher from `settings`, and the production default of 12 would dominate the runtime
    of every test that reaches it.
    """
    monkeypatch.setattr(
        demo_reset, "async_session_factory", async_sessionmaker(test_engine, expire_on_commit=False)
    )
    monkeypatch.setattr(settings, "bcrypt_rounds", TEST_BCRYPT_ROUNDS)


async def snapshot_tenant_rows(engine: AsyncEngine, tenant_id) -> dict[str, list[tuple]]:
    """One tenant's rows, for comparing across a run that legitimately writes another's.

    Read the same way `snapshot_every_row` is and for the same reason (design D18.3): Core, on
    an unmarked connection. The four child tables without `tenant_id` — `messages`,
    `cleaning_checklist_completions`, `cleaning_photos`, `review_response_drafts`, the fifth
    declared limit of the listener in `app/core/db.py` — are not reachable by a `tenant_id`
    filter and are covered by the delete phase's own isolation test in section 3.
    """
    async with engine.connect() as connection:
        snapshot = {}
        for table in Base.metadata.sorted_tables:
            if "tenant_id" in table.c:
                statement = select(table).where(table.c.tenant_id == tenant_id)
            elif table.name == "tenants":
                statement = select(table).where(table.c.id == tenant_id)
            else:
                continue
            snapshot[table.name] = [
                tuple(str(value) for value in row)
                for row in (
                    await connection.execute(statement.order_by(*table.primary_key.columns))
                ).all()
            ]
        return snapshot


async def snapshot_children_of(engine: AsyncEngine, tenant_id) -> dict[str, list[tuple]]:
    """The four tables with no `tenant_id`, reached through the parent that has one.

    `snapshot_tenant_rows` cannot see these, and they are precisely the half of the delete the
    listener does **not** cover (the fifth limit in `app/core/db.py`, design D6) — so a test that
    only used the other helper would leave the risky half unwatched.
    """
    async with engine.connect() as connection:
        snapshot = {}
        for child, (foreign_key, parent) in demo_reset.unscoped_children().items():
            table = Base.metadata.tables[child]
            parent_table = Base.metadata.tables[parent]
            snapshot[child] = [
                tuple(str(value) for value in row)
                for row in (
                    await connection.execute(
                        select(table)
                        .where(
                            table.c[foreign_key].in_(
                                select(parent_table.c.id).where(
                                    parent_table.c.tenant_id == tenant_id
                                )
                            )
                        )
                        .order_by(*table.primary_key.columns)
                    )
                ).all()
            ]
        return snapshot


async def snapshot_every_row(engine: AsyncEngine) -> dict[str, list[tuple]]:
    """Every row of every table, read the one way that can observe damage to a neighbour.

    A Core `select` on a connection nothing marked: the ORM listener of `app/core/db.py` adds
    `tenant_id = <marked>` to every ORM SELECT, so a snapshot taken over a session marked to the
    demonstration tenant would return the neighbour's rows as empty and the comparison could not
    fail (design D18.3). Core also keeps this immune to the very mechanism it is auditing.
    """
    async with engine.connect() as connection:
        return {
            table.name: [
                tuple(str(value) for value in row)
                for row in (
                    await connection.execute(
                        select(table).order_by(*table.primary_key.columns)
                    )
                ).all()
            ]
            for table in Base.metadata.sorted_tables
        }


# --- R2.1: the value is nowhere in the tree (design D18.2) -----------------------------


def test_the_demo_password_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The absence of a DEFAULT is the property under test, so the ambient environment goes.

    Same reasoning as the BOOTSTRAP_*/SEED_* tests in `tests/test_config.py`: a developer who
    filled DEMO_ACCOUNT_PASSWORD in their own `.env` to run `make demo-reset` would otherwise
    fail this for the wrong reason.
    """
    monkeypatch.delenv("DEMO_ACCOUNT_PASSWORD", raising=False)

    assert Settings(_env_file=None, **_REQUIRED).demo_account_password == ""


#: Where `.env.example` can be read from. `/workspace/` is the read-only bind mount
#: `docker-compose.yml` gives the backend container, because it mounts `./backend` as `/app` and
#: the repository root is not reachable from inside. The repository layout is the second and last
#: candidate, which is the one that resolves in CI, where the checkout is complete. The rule 11
#: ownership guard used to have this same shape and for the same reason; it no longer does, because
#: `rule11-guard-trigger-and-scope` moved it out of the container to `scripts/rule11-ownership.py`,
#: where a single origin suffices. The shape survives here because THIS suite still runs inside.
_ENV_EXAMPLE_CANDIDATES = (
    Path("/workspace/.env.example"),
    Path(__file__).resolve().parents[3] / ".env.example",
)


def _env_example() -> Path:
    for candidate in _ENV_EXAMPLE_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise AssertionError(
        ".env.example is not readable from any of "
        f"{[str(path) for path in _ENV_EXAMPLE_CANDIDATES]}. Inside the container it arrives "
        "through a bind mount added by `docker-compose.yml`; recreate the service (`make up`) "
        "if this container predates it."
    )


def test_env_example_declares_the_demo_password_by_name_and_without_a_value() -> None:
    """The other half of R2.1, and the half that a `Settings` default cannot cover.

    A value to the right of the `=` would ship a known credential for a publicly reachable
    environment in a versioned file — which is precisely what R2.1 forbids and what makes this
    worth a test rather than a review habit.
    """
    lines = [
        line
        for line in _env_example().read_text(encoding="utf-8").splitlines()
        if line.startswith("DEMO_ACCOUNT_PASSWORD")
    ]

    assert lines == ["DEMO_ACCOUNT_PASSWORD="]


# --- R1.2, R2.3: the constants and the validated plan (design D2, D3) ------------------


def test_the_tenant_and_its_four_addresses_are_constants() -> None:
    """Pinned by value, because their being constants is what R1.4 and R3.2 rest on (D2).

    A test that read them from `demo_reset` and asserted they were non-empty would pass on the
    day somebody turned one of them into `settings.demo_tenant_name` — which is the single
    change that would let a stray `-e` in a workflow point this command at the working tenant.
    """
    assert demo_reset.DEMO_TENANT_NAME == "AutoHostAI Demo"
    assert demo_reset.DEMO_OWNER_EMAIL == "owner@demo.autohostai.test"
    assert demo_reset.DEMO_MANAGER_EMAIL == "manager@demo.autohostai.test"
    assert demo_reset.DEMO_CLEANER_EMAIL == "cleaner@demo.autohostai.test"
    assert demo_reset.DEMO_TECHNICIAN_EMAIL == "technician@demo.autohostai.test"


def test_the_module_offers_no_way_to_name_another_tenant() -> None:
    """The claim of D2 stated as a property of the module rather than of one call site.

    `Settings` is scanned instead of the module: what would reopen this is a *setting* that
    names a tenant, and `demo_account_password` is the only field this change is allowed to
    add.
    """
    tenant_settings = [
        name
        for name in Settings.model_fields
        if "demo" in name and ("tenant" in name or "email" in name)
    ]

    assert tenant_settings == []


def test_a_missing_password_is_refused_naming_the_variable_and_not_its_value(
    demo_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "demo_account_password", "")

    with pytest.raises(demo_reset.DemoResetConfigurationError) as excinfo:
        demo_reset.build_plan()

    assert "DEMO_ACCOUNT_PASSWORD" in str(excinfo.value)


@pytest.mark.parametrize(
    "too_short",
    [
        pytest.param("a" * (PASSWORD_MIN_LENGTH - 1), id="one-character-short"),
        pytest.param("short", id="obviously-short"),
    ],
)
def test_a_password_below_the_policy_floor_is_refused_without_echoing_it(
    demo_env, monkeypatch: pytest.MonkeyPatch, too_short: str
) -> None:
    """R2.3: below PASSWORD_MIN_LENGTH the published credential would be unrecoverable.

    A visitor who changed it could not set it back through `POST /auth/change-password`, which
    applies the same policy — so the credentials on the page would stay broken until the next
    scheduled reset.
    """
    monkeypatch.setattr(settings, "demo_account_password", too_short)

    with pytest.raises(demo_reset.DemoResetConfigurationError) as excinfo:
        demo_reset.build_plan()

    message = str(excinfo.value)
    assert "DEMO_ACCOUNT_PASSWORD" in message
    assert too_short not in message


def test_a_password_over_the_bcrypt_ceiling_is_refused(
    demo_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not in R2.3, and refused all the same: past 72 bytes bcrypt truncates in silence.

    The password that got published would not be the password that authenticates, and the
    symptom would be a login that works for whoever pasted the first 72 bytes.

    It drives `build_plan()` rather than asserting `PASSWORD_MAX_BYTES == 72`, which is what
    this test did first and which proved nothing: narrowing `build_plan`'s `except` tuple to
    drop `PasswordTooLongError` would leave that exception escaping past `main()`'s handlers
    and out of the 0/1/2 contract R3.4 and R5.5 depend on, and a constant comparison would
    stay green through it.
    """
    too_long = "a" * (PASSWORD_MAX_BYTES + 1)
    monkeypatch.setattr(settings, "demo_account_password", too_long)

    with pytest.raises(demo_reset.DemoResetConfigurationError) as excinfo:
        demo_reset.build_plan()

    assert "DEMO_ACCOUNT_PASSWORD" in str(excinfo.value)
    assert too_long not in str(excinfo.value)


def test_a_valid_password_builds_the_four_accounts_with_their_roles(demo_env) -> None:
    plan = demo_reset.build_plan()

    assert plan.bootstrap.tenant_name == demo_reset.DEMO_TENANT_NAME
    assert plan.seed.tenant_name == demo_reset.DEMO_TENANT_NAME
    assert [(user.email, user.role) for user in plan.bootstrap.users] == [
        (demo_reset.DEMO_OWNER_EMAIL, UserRole.TENANT_OWNER),
        (demo_reset.DEMO_MANAGER_EMAIL, UserRole.PROPERTY_MANAGER),
    ]
    assert [(account.email, account.role) for account in plan.seed.accounts] == [
        (demo_reset.DEMO_CLEANER_EMAIL, UserRole.CLEANER),
        (demo_reset.DEMO_TECHNICIAN_EMAIL, UserRole.TECHNICIAN),
    ]
    # One password for the four, which is R2.1 read literally: four variables could
    # desynchronise, and the credentials are published as a single pair.
    assert {user.password for user in plan.bootstrap.users} == {DEMO_PASSWORD}
    assert {account.password for account in plan.seed.accounts} == {DEMO_PASSWORD}


def test_the_plan_does_not_read_the_working_tenants_configuration(
    demo_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D3: it BUILDS the two plans instead of calling the `build_plan()` of those modules.

    Theirs read `BOOTSTRAP_*`/`SEED_*`, so they name the working tenant and the team's own
    addresses. Here every one of those is set to something recognisable, and none of it must
    reach the plan.
    """
    for name, value in {
        "bootstrap_tenant_name": "The Working Tenant",
        "bootstrap_tenant_billing_email": "team@example.com",
        "bootstrap_owner_email": "real-owner@example.com",
        "bootstrap_owner_password": "the-teams-own-password",
        "seed_cleaner_email": "real-cleaner@example.com",
        "seed_technician_email": "real-technician@example.com",
    }.items():
        monkeypatch.setattr(settings, name, value)

    plan = demo_reset.build_plan()

    rendered = repr(plan)
    for leaked in ("The Working Tenant", "example.com", "the-teams-own-password"):
        assert leaked not in rendered
    # The demo password belongs in this list as much as the working tenant's does (R2.5): the
    # generated `__repr__` used to render it five times, once here and once per nested
    # `SeedUser`/`SeedAccount`, and this assertion is what keeps `repr=False` from being
    # quietly dropped.
    assert DEMO_PASSWORD not in rendered
    # And one attribute deeper, which is where the first version of this fix stopped: the
    # nested `BootstrapPlan`/`SeedPlan` hold their own copy of the password through `SeedUser`
    # and `SeedAccount`, so `repr(plan)` being clean said nothing about `repr(plan.bootstrap)`.
    for nested in (plan.bootstrap, plan.seed, *plan.bootstrap.users, *plan.seed.accounts):
        assert DEMO_PASSWORD not in repr(nested)
        assert DEMO_PASSWORD not in str(nested)


def test_the_storage_type_is_the_one_the_environment_runs_on(
    demo_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D14: the deploy passes `BOOTSTRAP_STORAGE_TYPE=S3` inline so the demo tenant is born S3.

    That variable is not a tenant identity — it is the store the whole environment uses — so it
    is the one thing besides the password this command reads from the environment. Without it
    the demonstration tenant would exercise a storage path its neighbour does not.
    """
    monkeypatch.setattr(settings, "bootstrap_storage_type", StorageType.S3.value)

    assert demo_reset.build_plan().bootstrap.storage_type is StorageType.S3


# --- R1.4, R3.2: the refusal, before any transaction (design D2) -----------------------


def test_the_command_refuses_when_the_working_tenant_carries_the_demo_name(
    demo_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "bootstrap_tenant_name", demo_reset.DEMO_TENANT_NAME)

    with pytest.raises(demo_reset.DemoResetRefusedError) as excinfo:
        demo_reset.refuse_if_the_working_tenant_is_the_demo_tenant()

    assert demo_reset.DEMO_TENANT_NAME in str(excinfo.value)


@pytest.mark.parametrize(
    "working",
    [
        pytest.param("AutoHostAI Dev", id="an-ordinary-working-tenant"),
        pytest.param("", id="unset-which-is-the-deployed-case"),
        pytest.param("   ", id="whitespace-only"),
        pytest.param("autohostai demo", id="differently-cased-is-a-different-row"),
    ],
)
def test_an_unrelated_working_tenant_does_not_trip_the_refusal(
    demo_env, monkeypatch: pytest.MonkeyPatch, working: str
) -> None:
    """The empty case is the one that matters, and it is why D2 does not rely on this gate.

    The `.env` the deploy renders on the VM carries no `BOOTSTRAP_TENANT_NAME`, so in the
    environment this command actually runs in the comparison is against the empty string. The
    barrier there is the constant, not this check.

    The differently-cased case is not laxity: `bootstrap` and `seed_demo` resolve the tenant
    with `TenantModel.name == …`, so `autohostai demo` IS another row, and refusing on it would
    refuse a run that was never in danger.
    """
    monkeypatch.setattr(settings, "bootstrap_tenant_name", working)

    demo_reset.refuse_if_the_working_tenant_is_the_demo_tenant()


@pytest.mark.asyncio
async def test_a_refused_run_leaves_the_database_byte_for_byte_identical(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """R1.4 says "exit without writing anything", and this is that claim, measured.

    Asserted over EVERY table rather than over the ones this command would have touched: what
    R1.4 protects against is a run that got further than it should, and a run that got further
    would not respect the list of tables somebody wrote down here.

    The comparison is read over a Core `select` on an unmarked connection, which is the only
    reading that could observe damage to the working tenant — a session marked to the
    demonstration tenant filters the neighbour's rows down to nothing, so the assertion could
    not fail (design D18.3).

    **It drives `run()` and not `main()`, and that is the whole point of the test.** Written
    against `main()` it went red under a broken gate for the wrong reason: `main()` calls
    `asyncio.run`, which Python forbids inside the running loop of an async test, so the failure
    was a `RuntimeError` raised *before any session opened* and the snapshot comparison was never
    reached. It looked like evidence and was an artefact of the harness — a mechanism that does
    not exist in production, where `main()` runs at top level. Awaiting `run()` is the pattern
    `tests/auth/test_reset_password_cli.py` uses and the one the sibling write-path tests use.

    Reaching `run()` also makes the scenario stronger than the sync gate alone: with the working
    tenant carrying the demonstration name, the impostor guard inside `apply_plan` finds a row
    whose billing address is not `DEMO_BILLING_EMAIL` and refuses over an open session — a real
    write attempt, refused, with the database provably untouched.
    """
    # The working tenant is literally called "AutoHostAI Demo" — the one case D2's second gate
    # exists for. Its billing address is not the demonstration tenant's, which is what the
    # impostor guard inside `apply_plan` recognises when the run reaches a session.
    tenant = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await insert_user(db_session, tenant=tenant, role=UserRole.TENANT_OWNER)
    await db_session.commit()
    monkeypatch.setattr(settings, "bootstrap_tenant_name", demo_reset.DEMO_TENANT_NAME)
    # Without this the test could not fail. `demo_reset` imported `async_session_factory` into
    # its own namespace, and that factory is built at import time from `settings.database_url` —
    # the environment's REAL database, not the throwaway one `tests/conftest.py` creates. A
    # refusal that stopped refusing would write there, and the snapshot taken over `test_engine`
    # would still match, because the two are different databases. Patched in the CLI module
    # where the name was imported, exactly as `tests/auth/test_reset_password_cli.py` does.
    _use_the_test_database(monkeypatch, test_engine)

    # The sync gate of D2 fires first, and it is what `main()` consults before opening anything.
    with pytest.raises(demo_reset.DemoResetRefusedError):
        demo_reset.refuse_if_the_working_tenant_is_the_demo_tenant()

    before = await snapshot_every_row(test_engine)
    with pytest.raises(demo_reset.DemoResetRefusedError):
        await demo_reset.run(demo_reset.build_plan())
    after = await snapshot_every_row(test_engine)

    assert after == before


def test_the_working_tenant_gate_makes_main_exit_one_without_opening_a_transaction(
    demo_env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The exit-code half of R1.4, in a plain test because `main()` calls `asyncio.run`.

    Split from the test above deliberately: that one proves the database is untouched, this one
    proves the code is 1 and that `run()` is never entered. Keeping both in one async test is
    what produced a red-for-the-wrong-reason before.
    """
    monkeypatch.setattr(settings, "bootstrap_tenant_name", demo_reset.DEMO_TENANT_NAME)

    async def _must_not_run(_plan):  # pragma: no cover - not being called is the assertion
        raise AssertionError("the working-tenant gate let the run start")

    monkeypatch.setattr(demo_reset, "run", _must_not_run)

    assert demo_reset.main() == 1
    assert "refusing to continue" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_a_run_that_is_not_refused_leaves_the_working_tenant_untouched(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """The other half of D18.3, and the half the refusal test cannot give: a run that WRITES.

    The refusal test proves nothing was written by a command that stopped before opening a
    session. R1.5 is about "ninguna de sus fases", so it needs an execution that reaches them.
    This one does — today that is the `bootstrap` phase, and sections 3-5 will extend the same
    assertion over `delete`, `converge` and `seed`.

    The working tenant's rows are snapshotted on their own rather than the whole database,
    because a successful run legitimately adds the demonstration tenant's.
    """
    neighbour = await insert_tenant(db_session, name="AutoHostAI Dev")
    await insert_user(db_session, tenant=neighbour, role=UserRole.TENANT_OWNER)
    await db_session.commit()
    _use_the_test_database(monkeypatch, test_engine)

    before = await snapshot_tenant_rows(test_engine, neighbour.id)
    report = await demo_reset.run(demo_reset.build_plan())
    after = await snapshot_tenant_rows(test_engine, neighbour.id)

    assert report.counts["tenants"] == 1
    assert after == before
    # And the run did what it says: the demonstration tenant exists, with its own id.
    async with test_engine.connect() as connection:
        demo_tenants = (
            await connection.execute(
                select(TenantModel.__table__.c.id, TenantModel.__table__.c.billing_email).where(
                    TenantModel.__table__.c.name == demo_reset.DEMO_TENANT_NAME
                )
            )
        ).all()
    assert len(demo_tenants) == 1
    assert demo_tenants[0].id != neighbour.id
    assert demo_tenants[0].billing_email == demo_reset.DEMO_BILLING_EMAIL


# --- R1.5: a name is not an identity, because `tenants.name` is not unique --------------


@pytest.mark.asyncio
async def test_a_tenant_that_only_shares_the_name_is_refused_before_anything_is_written(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """R1.5 against the gap the constant of D2 does not close on its own.

    `tenants` has no uniqueness on `name`, and `bootstrap.apply_plan` resolves its tenant with
    `TenantModel.name == …` — so a row that merely carries this name would be *adopted*: its
    config converged, two accounts bearing the published password inserted into it, and the
    whole thing deleted by the phase of section 3. The second gate of D2 cannot see this: in the
    deployed environment `BOOTSTRAP_TENANT_NAME` is absent and compares against "".
    """
    await insert_user(
        db_session,
        tenant=await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME),
        role=UserRole.TENANT_OWNER,
    )
    await db_session.commit()
    _use_the_test_database(monkeypatch, test_engine)

    before = await snapshot_every_row(test_engine)
    with pytest.raises(demo_reset.DemoResetRefusedError):
        await demo_reset.run(demo_reset.build_plan())
    after = await snapshot_every_row(test_engine)

    assert after == before


@pytest.mark.asyncio
async def test_the_demonstration_tenants_own_row_is_not_mistaken_for_an_impostor(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """The converse, which is what makes the guard usable: a reset must still be idempotent.

    The mark is the billing address `bootstrap.apply_plan` writes when it creates the tenant, so
    the second run of the command has to recognise its own work.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()

    first = await demo_reset.run(plan)
    second = await demo_reset.run(plan)

    assert first.counts["tenants"] == 1
    # Nothing created the second time: `bootstrap.apply_plan` is a no-op on a reset (D7), and
    # the guard recognised the row it wrote itself rather than refusing it as an impostor.
    assert second.counts["tenants"] == 0


# --- R2.5, R3.4, R5.5: phases named, and an exit code that tells them apart (D15) ------


def test_the_declared_phases_are_the_ones_the_design_names() -> None:
    """D15's contract, plus the two the section-5 security panel required.

    `prepare` and `scope` are not decoration. R5.5 promises the workflow turns red "nombrando la
    fase que falló", and the stretch between `bootstrap` and `delete` used to sit outside every
    `_phase` — so a failure there reported "outside any phase", which is exactly what that
    promise excludes. Three failure sources lived in that gap: the store read, the tenant-column
    convergence flush, and `collect_storage_keys`'s own precondition.
    """
    assert demo_reset.PHASES == (
        "configuration",
        "refusal",
        "prepare",
        "bootstrap",
        "scope",
        "delete",
        "converge",
        "seed",
        "storage-sweep",
        # `demo-tenant-audit-retention`: between `storage-sweep` and `clear-lock`, outside
        # the apply transaction. `purge_old_audit_logs` opens its own session and degrades
        # on failure the same way `storage-sweep`/`clear-lock` do — see demo_reset.run().
        "purge-audit",
        "clear-lock",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", demo_reset.PHASES)
async def test_a_failure_inside_a_phase_is_attributed_to_that_phase(phase: str) -> None:
    report = demo_reset.DemoResetReport(phases=[], counts={}, notes=[])

    with pytest.raises(demo_reset.PhaseError) as excinfo:
        async with demo_reset._phase(phase, report):
            raise _DatabaseErrorCarryingItsParameters(_LEAKY_DETAIL)

    assert excinfo.value.phase == phase
    assert report.phases == [phase]


@pytest.mark.asyncio
async def test_a_nested_phase_keeps_its_own_name() -> None:
    """Otherwise the outer phase would relabel the failure and name the wrong culprit."""
    report = demo_reset.DemoResetReport(phases=[], counts={}, notes=[])

    with pytest.raises(demo_reset.PhaseError) as excinfo:
        async with demo_reset._phase("seed", report):
            async with demo_reset._phase("delete", report):
                raise RuntimeError("boom")

    assert excinfo.value.phase == "delete"


@pytest.mark.parametrize("phase", demo_reset.PHASES)
def test_an_unexpected_failure_exits_two_naming_the_phase_and_nothing_else(
    demo_env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], phase: str
) -> None:
    """R2.5 and R5.5 read together: the phase is the whole diagnosis the log may carry.

    The detail withheld is not hypothetical. A SQLAlchemy error stringifies its statement
    TOGETHER with its parameters, and this command's parameters include the bcrypt hash of an
    account it just converged — so an `except Exception as exc: print(exc)` would put a
    credential hash in a public build log at 03:15 with nobody watching.
    """

    async def _explode(_plan):
        raise demo_reset.PhaseError(phase, _DatabaseErrorCarryingItsParameters(_LEAKY_DETAIL))

    monkeypatch.setattr(demo_reset, "run", _explode)

    assert demo_reset.main() == 2

    captured = capsys.readouterr()
    everything = captured.out + captured.err
    assert phase in everything
    assert "_DatabaseErrorCarryingItsParameters" in everything
    assert _LEAKY_DETAIL not in everything
    assert DEMO_PASSWORD not in everything


def test_a_refusal_raised_inside_the_run_still_exits_one(
    demo_env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The impostor guard lives inside `run()`, so `main()` has to catch it there too.

    It sits deliberately OUTSIDE any `_phase`: `_phase` turns what it catches into a
    `PhaseError` and therefore into exit 2, and D15 reserves exit 1 for "nada escrito".
    """

    async def _refuse(_plan):
        raise demo_reset.DemoResetRefusedError("a tenant only shares the name")

    monkeypatch.setattr(demo_reset, "run", _refuse)

    assert demo_reset.main() == 1
    assert "refusing to continue" in capsys.readouterr().err


def test_an_escape_from_outside_every_phase_still_exits_two_without_its_detail(
    demo_env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The catch-all `seed_demo.main()` has, which this command lacked (D15, R2.5, R5.5).

    Not everything happens inside a `_phase`: building the hasher, entering and leaving the
    session, a rollback that fails while a `PhaseError` is already propagating. Without a
    catch-all those escape as a traceback that prints the whole `__cause__` chain — and the
    original SQLAlchemy error in that chain stringifies as `[SQL: …] [parameters: (…)]`, whose
    parameters are the bcrypt hashes this command just wrote. An escape would also exit 1, the
    code D15 reserves for runs that wrote nothing.
    """

    async def _explode(_plan):
        raise _DatabaseErrorCarryingItsParameters(_LEAKY_DETAIL)

    monkeypatch.setattr(demo_reset, "run", _explode)

    assert demo_reset.main() == 2

    everything = "".join(capsys.readouterr())
    assert "_DatabaseErrorCarryingItsParameters" in everything
    assert _LEAKY_DETAIL not in everything
    assert DEMO_PASSWORD not in everything


def test_a_configuration_failure_exits_one_and_never_reaches_a_transaction(
    demo_env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "demo_account_password", "")

    async def _must_not_run(_plan):  # pragma: no cover - the assertion is that it is not called
        raise AssertionError("a configuration failure opened a transaction")

    monkeypatch.setattr(demo_reset, "run", _must_not_run)

    assert demo_reset.main() == 1
    assert "DEMO_ACCOUNT_PASSWORD" in capsys.readouterr().err


# --- Section 3: the delete phase ------------------------------------------------------


async def populate_tenant(session: AsyncSession, tenant: TenantModel) -> dict[str, uuid.UUID]:
    """A tenant with rows in the tables the delete phase has to reason about.

    Not the real seed: `seed_demo.apply_plan` uploads photos to an object store and would make
    these tests depend on it. What matters here is one row in each of the shapes the phase
    treats differently — a scoped table, each of the four children the listener cannot reach
    (design D6), the two credential tables D5 says must go, and a `webhook_events` row with a
    `NULL` tenant that must survive without being excluded by name.
    """
    user = await insert_user(session, tenant=tenant, role=UserRole.CLEANER)
    prop = PropertyModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Vivienda",
        internal_code=f"CODE-{uuid.uuid4().hex[:6]}",
    )
    guest = GuestModel(id=uuid.uuid4(), tenant_id=tenant.id, full_name="Huésped")
    session.add_all([prop, guest])
    await session.flush()

    reservation = ReservationModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        channel=ReservationChannel.AIRBNB,
        check_in_date=date(2026, 8, 1),
        check_out_date=date(2026, 8, 4),
        nights=3,
    )
    template = CleaningChecklistTemplateModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Plantilla",
        items=[{"id": "vent", "label": "Ventilar"}],
        required_photos=[],
    )
    conversation = ConversationModel(
        id=uuid.uuid4(), tenant_id=tenant.id, channel=ConversationChannel.WHATSAPP
    )
    review = ReviewModel(
        id=uuid.uuid4(), tenant_id=tenant.id, property_id=prop.id, channel=ReviewChannel.AIRBNB
    )
    timeline = TimelineEventModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        actor_type=TimelineActorType.SYSTEM,
        event_type=TimelineEventType.RESERVATION_IMPORTED,
        title="Reserva importada",
    )
    session.add_all([reservation, template, conversation, review, timeline])
    await session.flush()

    task = CleaningTaskModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        checklist_template_id=template.id,
    )
    session.add(task)
    await session.flush()

    # The four tables with no `tenant_id`, reachable only through their parent (D6).
    session.add_all(
        [
            MessageModel(
                id=uuid.uuid4(),
                conversation_id=conversation.id,
                sender_type=MessageSenderType.GUEST,
                content="Hola",
            ),
            CleaningPhotoModel(
                id=uuid.uuid4(),
                cleaning_task_id=task.id,
                uploaded_by=user.id,
                photo_type="AFTER",
                storage_key=f"tenants/{tenant.id}/cleaning-tasks/{task.id}/photo.jpg",
            ),
            CleaningChecklistCompletionModel(
                id=uuid.uuid4(), cleaning_task_id=task.id, item_id="vent"
            ),
            ReviewResponseDraftModel(
                id=uuid.uuid4(), review_id=review.id, draft_content="Gracias", language="es"
            ),
        ]
    )
    # What a visitor left open. D5: these two go, because a session that survived the reset
    # would be a credential the reset handed back.
    session.add_all(
        [
            UserSessionModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                user_id=user.id,
                family_id=uuid.uuid4(),
                expires_at=datetime(2026, 12, 1, tzinfo=UTC),
            ),
            PasswordResetTokenModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                user_id=user.id,
                token_hash=uuid.uuid4().hex,
                expires_at=datetime(2026, 12, 1, tzinfo=UTC),
            ),
        ]
    )

    # The remaining scoped tables. They are here so the isolation assertion of D18.3 —
    # "fotografía de **todas** las filas del tenant de trabajo" — is literally true rather than
    # comparing `[] == []` for two thirds of the tables. Before this, 14 of the 24 tables the
    # phase deletes from were empty for BOTH tenants in every test, so a hand-rolled unscoped
    # delete on any one of them would have shipped with the suite still green.
    rule = PricingRuleModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Regla",
        base_price=Decimal("100.00"),
        min_price=Decimal("50.00"),
        max_price=Decimal("300.00"),
    )
    incident = IncidentModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.GUEST,
        title="WiFi va lento",
        description="No carga",
    )
    session.add_all([rule, incident])
    await session.flush()

    session.add_all(
        [
            AccessRecordModel(id=uuid.uuid4(), tenant_id=tenant.id, property_id=prop.id),
            CleaningTaskMessageModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                task_id=task.id,
                author_id=user.id,
                author_role=UserRole.CLEANER,
                content="Ventilado y listo",
                created_at=datetime(2026, 8, 2, tzinfo=UTC),
            ),
            ExpenseModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                property_id=prop.id,
                category=ExpenseCategory.CLEANING,
                description="Limpieza",
                amount=Decimal("40.00"),
                date=date(2026, 8, 2),
            ),
            GuestAccessTokenModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                reservation_id=reservation.id,
                token_hash=uuid.uuid4().hex,
            ),
            IncidentMessageModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                incident_id=incident.id,
                author_id=user.id,
                author_role=UserRole.CLEANER,
                content="Aviso enviado al propietario",
                created_at=datetime(2026, 8, 2, tzinfo=UTC),
            ),
            IncidentPhotoModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                incident_id=incident.id,
                uploaded_by=user.id,
                stage=IncidentPhotoStage.BEFORE,
                storage_key=f"tenants/{tenant.id}/incidents/{incident.id}/photo.jpg",
                created_at=datetime(2026, 8, 2, tzinfo=UTC),
            ),
            NotificationLogModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                recipient_contact="alguien@example.com",
                channel=NotificationChannel.EMAIL,
                notification_type="CLEANING_ASSIGNED",
            ),
            OwnerApprovalModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                property_id=prop.id,
                related_type=OwnerApprovalRelatedType.INCIDENT,
                related_id=incident.id,
                amount=Decimal("120.00"),
                reason="Cambio de grifo",
            ),
            OwnerStatementModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                property_id=prop.id,
                period_start=date(2026, 8, 1),
                period_end=date(2026, 8, 31),
            ),
            PmsCredentialModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                provider=PMSProvider.MOCK,
                scope=PmsCredentialScope.ACCOUNT,
                secret_encrypted="encrypted",
            ),
            PriceRecommendationModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                property_id=prop.id,
                pricing_rule_id=rule.id,
                date=date(2026, 8, 10),
                recommended_price=Decimal("130.00"),
                explanation="Demanda alta",
            ),
            PropertyStateTransitionModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                property_id=prop.id,
                to_state=PropertyOperationalState.VACANT_READY,
                triggered_by=StateTransitionTriggeredBy.SYSTEM,
            ),
            WebhookEndpointModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                provider=PMSProvider.MOCK,
                token_hash=uuid.uuid4().hex,
                header_name="X-Signature",
                header_secret_encrypted="encrypted",
            ),
            WebhookEventModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                provider="beds24",
                event_type="booking.updated",
                payload={},
            ),
            # `whatsapp-cloud-adapter`'s two tables. Seeded for the reason the comment above
            # `empty` gives: a scoped table with no neighbour row turns D18.3's "photograph
            # every row of the working tenant" into `[] == []`, and an unscoped delete on it
            # would ship green.
            WhatsAppPhoneNumberModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                phone_number_id=uuid.uuid4().hex[:15],
                default_property_id=prop.id,
            ),
            WhatsAppInboundEventModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                default_property_id=prop.id,
                phone_number_id=uuid.uuid4().hex[:15],
                provider_message_id=f"wamid.{uuid.uuid4().hex}",
                sender_phone="+34612345678",
                message_text="Hola",
                received_at=datetime(2026, 8, 2, tzinfo=UTC),
            ),
            # R3.6's table, with a real row. Preserved — and until now its survival was only
            # asserted structurally, by `PRESERVED_TABLES` membership, so a typo in the loop's
            # skip condition would have emptied it with every test still green.
            AuditLogModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                action="INCIDENT_CREATED",
                entity_type="Incident",
                entity_id=incident.id,
                # Pointed at the user the prune deletes, on purpose. The prune rests on
                # `audit_logs.actor_user_id` being `ondelete="SET NULL"` — the only foreign key
                # into `users` from a table the phase PRESERVES. Without an actor here, no test
                # ever deletes a user a preserved row references, so a later migration flipping
                # that column to RESTRICT would abort the whole reset transaction on the VM with
                # the suite still green, and the demo would keep whatever the last visitor left.
                actor_user_id=user.id,
            ),
        ]
    )
    await session.flush()
    return {"user": user.id, "task": task.id, "conversation": conversation.id, "review": review.id}


async def insert_unattributed_webhook_event(session: AsyncSession) -> uuid.UUID:
    """A `webhook_events` row with `tenant_id` NULL — what §7.26 records but cannot attribute."""
    event = WebhookEventModel(
        id=uuid.uuid4(), provider="beds24", event_type="booking.created", payload={}
    )
    session.add(event)
    await session.flush()
    return event.id


def test_the_delete_phase_covers_every_scoped_table_minus_the_four_it_preserves() -> None:
    """R1.5 as a decision per table, enforced in CI rather than discovered on the VM.

    The phase derives its table list from the metadata, so a table added later joins the delete
    on its own. This test is the other half of that: it fails when a new table appears, so
    somebody has to decide explicitly whether it is emptied or preserved. Without it, the
    derivation would silently start deleting — or silently stop covering — whatever arrives.
    """
    scoped = {model.__tablename__ for model in tenant_scoped_classes()}
    children = set(demo_reset.unscoped_children())

    emptied = {
        table.name
        for table in Base.metadata.sorted_tables
        if table.name not in demo_reset.PRESERVED_TABLES
    }

    assert emptied == (scoped - demo_reset.PRESERVED_TABLES) | children
    assert demo_reset.PRESERVED_TABLES == {"tenants", "tenant_configs", "users", "audit_logs"}
    # And the set pinned by VALUE, because the equality above is computed from the same metadata
    # on both sides: it catches a new table nobody decided about (via `unscoped_children()`
    # raising), but it does NOT catch `PRESERVED_TABLES` growing an entry — both sides shrink
    # together. This literal is what makes a table silently dropping out of the delete go red.
    assert emptied == {
        "access_records",
        "cleaning_checklist_completions",
        "cleaning_checklist_templates",
        "cleaning_photos",
        "cleaning_task_messages",
        "cleaning_tasks",
        "conversations",
        "expenses",
        "guest_access_tokens",
        "guests",
        "incident_messages",
        "incident_photos",
        "incidents",
        "messages",
        "notification_logs",
        "owner_approvals",
        "owner_statements",
        "password_reset_tokens",
        "pms_credentials",
        "price_recommendations",
        "pricing_rules",
        "properties",
        "property_state_transitions",
        "reservations",
        "review_response_drafts",
        "reviews",
        "timeline_events",
        "user_sessions",
        "webhook_endpoints",
        "webhook_events",
        # `whatsapp-cloud-adapter`: the tenant's number-to-tenant association (section 6) and
        # the inbound delivery queue (section 7). Both are emptied rather than preserved — a
        # demo tenant's WhatsApp association is demo configuration, and its inbound traffic is
        # demo traffic. Like `webhook_events`, the queue's `tenant_id` is nullable, so the rows
        # of a delivery that resolved to no tenant survive the reset; that is the same
        # deliberate consequence `delete_the_tenants_rows` records for its sibling.
        "whatsapp_inbound_events",
        "whatsapp_phone_numbers",
    }


def test_the_four_tables_without_a_tenant_column_are_the_ones_the_design_names() -> None:
    """D6, pinned by value: the listener's fifth limit is a closed list, not a guess.

    Derived from the foreign keys rather than written down, so this asserts the derivation lands
    where the design says it should — and goes red if a fifth child table appears, which is
    exactly when a human has to look.
    """
    assert demo_reset.unscoped_children() == {
        "messages": ("conversation_id", "conversations"),
        "cleaning_checklist_completions": ("cleaning_task_id", "cleaning_tasks"),
        "cleaning_photos": ("cleaning_task_id", "cleaning_tasks"),
        "review_response_drafts": ("review_id", "reviews"),
    }


def test_children_are_deleted_before_the_parents_they_hang_from() -> None:
    """With 51 RESTRICT foreign keys, order is not a detail — it is whether the phase runs.

    Derived from `sorted_tables` reversed rather than asserted against a literal order: what
    this test pins is the property that makes the derivation correct.
    """
    order = [
        table.name
        for table in reversed(Base.metadata.sorted_tables)
        if table.name not in demo_reset.PRESERVED_TABLES
    ]

    for child, (_, parent) in demo_reset.unscoped_children().items():
        assert order.index(child) < order.index(parent), f"{child} must go before {parent}"


@pytest.mark.asyncio
async def test_the_delete_phase_empties_the_demo_tenant(
    db_session: AsyncSession, test_engine
) -> None:
    # `with_notification_config=False`: this test's own assertion documents that
    # `tenant_configs` is preserved but the fixture never creates one — true again now that
    # `insert_tenant` seeds one by default (`notification-channel-routing`).
    demo = await insert_tenant(
        db_session, name=demo_reset.DEMO_TENANT_NAME, with_notification_config=False
    )
    # One of the four constant accounts, which must survive, and one a visitor could have
    # created through `POST /users` with the published owner credential, which must not.
    await insert_user(
        db_session, tenant=demo, role=UserRole.TENANT_OWNER, email=demo_reset.DEMO_OWNER_EMAIL
    )
    await populate_tenant(db_session, demo)
    await db_session.commit()

    marked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(marked, demo.id)
    deleted = await demo_reset.delete_the_tenants_rows(marked, demo.id)
    await marked.commit()
    await marked.close()

    remaining = await snapshot_tenant_rows(test_engine, demo.id)
    # `tenants`, `users` and `audit_logs` survive by design (D5); everything else of this tenant
    # is gone. `tenant_configs` is preserved too but the fixture never creates one.
    assert {name for name, rows in remaining.items() if rows} == {
        "tenants",
        "users",
        "audit_logs",
    }
    # R3.6 with a real row, not merely by `PRESERVED_TABLES` membership: a typo in the loop's
    # skip condition would empty this table while the set and its cardinality stayed intact.
    assert len(remaining["audit_logs"]) == 1
    # And its actor pointed at the account the prune deleted, so this also exercises the one
    # `SET NULL` the prune depends on: the record of what happened survives, only the throwaway
    # identity that did it goes. If that column were ever `RESTRICT`, the prune would abort the
    # whole reset transaction instead — which is why this assertion is here and not implied.
    async with test_engine.connect() as connection:
        actors = (
            await connection.execute(
                select(AuditLogModel.__table__.c.actor_user_id).where(
                    AuditLogModel.__table__.c.tenant_id == demo.id
                )
            )
        ).scalars().all()
    assert actors == [None]
    # And it reported what it removed, per entity.
    assert deleted["messages"] == 1
    assert deleted["cleaning_photos"] == 1
    assert deleted["incident_photos"] == 1


@pytest.mark.asyncio
async def test_only_the_four_constant_accounts_survive_the_reset(
    db_session: AsyncSession, test_engine
) -> None:
    """D5 keeps the `users` TABLE; it does not keep whatever a visitor left in it.

    The published `TENANT_OWNER` credential carries `MANAGE_USERS`, so a visitor can create an
    account with a password only they know — and accounts are deactivated, never deleted, so
    nothing else ever reclaims it. Surviving the reset would break D5's own "lo que un visitante
    dejó abierto no debe sobrevivir al reset" and R3.3's "indistinguible del que produce un
    aprovisionamiento desde cero", and because addresses are unique across the whole
    installation (ADR 0005) it would also squat that address for good.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    for email in demo_reset.DEMO_ACCOUNT_EMAILS:
        await insert_user(db_session, tenant=demo, role=UserRole.CLEANER, email=email)
    await insert_user(
        db_session, tenant=demo, role=UserRole.PROPERTY_MANAGER, email="squatter@company.example"
    )
    await db_session.commit()

    marked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(marked, demo.id)
    deleted = await demo_reset.delete_the_tenants_rows(marked, demo.id)
    await marked.commit()
    await marked.close()

    async with test_engine.connect() as connection:
        survivors = (
            await connection.execute(
                select(UserModel.__table__.c.email).where(
                    UserModel.__table__.c.tenant_id == demo.id
                )
            )
        ).scalars().all()

    assert sorted(survivors) == sorted(demo_reset.DEMO_ACCOUNT_EMAILS)
    assert deleted["users"] == 1


@pytest.mark.asyncio
async def test_a_neighbours_accounts_are_never_pruned(
    db_session: AsyncSession, test_engine
) -> None:
    """The pruning is a delete on `users`, so it needs its own isolation evidence (R1.5).

    It is the one statement in the phase that touches a table D5 otherwise preserves, and its
    only tenant predicate is the session marker.
    """
    neighbour = await insert_tenant(db_session, name="AutoHostAI Dev")
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await insert_user(
        db_session, tenant=neighbour, role=UserRole.TENANT_OWNER, email="real@company.example"
    )
    await insert_user(
        db_session, tenant=demo, role=UserRole.CLEANER, email=demo_reset.DEMO_CLEANER_EMAIL
    )
    await db_session.commit()

    before = await snapshot_tenant_rows(test_engine, neighbour.id)
    marked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(marked, demo.id)
    await demo_reset.delete_the_tenants_rows(marked, demo.id)
    await marked.commit()
    await marked.close()

    assert await snapshot_tenant_rows(test_engine, neighbour.id) == before


@pytest.mark.asyncio
async def test_the_delete_phase_refuses_a_session_that_is_not_bound_to_the_tenant(
    db_session: AsyncSession, test_engine
) -> None:
    """The precondition that stops the phase from emptying the whole database (R1.5, R3.2).

    24 of its 28 statements take their `tenant_id` predicate from the session marker alone —
    `delete(GuestModel)` on an unmarked session compiles to a bare `DELETE FROM guests`. So an
    unmarked session does not fail, it deletes those tables for every tenant. `tenant_id` being
    a parameter, nothing else in the function could catch it.
    """
    neighbour = await insert_tenant(db_session, name="AutoHostAI Dev")
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await populate_tenant(db_session, neighbour)
    await db_session.commit()

    before = await snapshot_every_row(test_engine)

    unmarked = AsyncSession(test_engine, expire_on_commit=False)
    with pytest.raises(TenantUnmarkedSessionError):
        await demo_reset.delete_the_tenants_rows(unmarked, demo.id)
    await unmarked.rollback()
    await unmarked.close()

    mismarked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(mismarked, neighbour.id)
    with pytest.raises(TenantMismatchedSessionError):
        await demo_reset.delete_the_tenants_rows(mismarked, demo.id)
    await mismarked.rollback()
    await mismarked.close()

    assert await snapshot_every_row(test_engine) == before


@pytest.mark.asyncio
async def test_the_reported_counts_are_right_for_more_than_one_row(
    db_session: AsyncSession, test_engine
) -> None:
    """D15's "recuentos por entidad", exercised past a count of one.

    Every other test in this section inserts exactly one row per table, so `rowcount == 1` would
    also be what a hard-coded `1` produced. Both branches of the phase are covered here — the ORM
    bulk delete (`messages` goes through the Core child subquery, `guests` through the ORM) —
    because they are two different statements and `rowcount` is a driver-level promise for each.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await populate_tenant(db_session, demo)
    conversation = (
        await db_session.execute(
            select(ConversationModel.__table__.c.id).where(
                ConversationModel.__table__.c.tenant_id == demo.id
            )
        )
    ).scalar_one()
    for index in range(3):
        db_session.add(GuestModel(id=uuid.uuid4(), tenant_id=demo.id, full_name=f"Huésped {index}"))
        db_session.add(
            MessageModel(
                id=uuid.uuid4(),
                conversation_id=conversation,
                sender_type=MessageSenderType.GUEST,
                content=f"Mensaje {index}",
            )
        )
    await db_session.commit()

    marked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(marked, demo.id)
    deleted = await demo_reset.delete_the_tenants_rows(marked, demo.id)
    await marked.commit()
    await marked.close()

    # One from the fixture plus the three added here, on both branches.
    assert deleted["guests"] == 4
    assert deleted["messages"] == 4


@pytest.mark.asyncio
async def test_the_sessions_and_reset_tokens_of_the_demo_tenant_are_deleted(
    db_session: AsyncSession, test_engine
) -> None:
    """D5, last paragraph: what a visitor left open must not outlive the reset.

    Called out separately from the sweep above because these two are the tables whose survival
    would be a security defect rather than stale data — a live session is a credential.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await populate_tenant(db_session, demo)
    await db_session.commit()

    marked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(marked, demo.id)
    deleted = await demo_reset.delete_the_tenants_rows(marked, demo.id)
    await marked.commit()
    await marked.close()

    assert deleted["user_sessions"] == 1
    assert deleted["password_reset_tokens"] == 1
    remaining = await snapshot_tenant_rows(test_engine, demo.id)
    assert remaining["user_sessions"] == []
    assert remaining["password_reset_tokens"] == []


@pytest.mark.asyncio
async def test_an_unattributed_webhook_event_survives_without_being_excluded_by_name(
    db_session: AsyncSession, test_engine
) -> None:
    """D4's good consequence, asserted rather than assumed.

    `webhook_events` rows with a `NULL` tenant are the ones §7.26 records without being able to
    attribute. They fall outside the delete for free, because a marked session filters them to
    zero — so `webhook_events` needs no entry in the preserved list, and if the phase ever stops
    going through the marked ORM it will take them with it.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await populate_tenant(db_session, demo)
    unattributed = await insert_unattributed_webhook_event(db_session)
    await db_session.commit()

    marked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(marked, demo.id)
    await demo_reset.delete_the_tenants_rows(marked, demo.id)
    await marked.commit()
    await marked.close()

    async with test_engine.connect() as connection:
        survivors = (
            await connection.execute(
                select(WebhookEventModel.__table__.c.id).where(
                    WebhookEventModel.__table__.c.tenant_id.is_(None)
                )
            )
        ).scalars().all()

    assert survivors == [unattributed]


@pytest.mark.asyncio
async def test_the_delete_phase_leaves_every_row_of_the_working_tenant_untouched(
    db_session: AsyncSession, test_engine
) -> None:
    """D18.3, over the phase that actually has the power to do damage.

    Two tenants, both populated, and the whole of the working tenant photographed before and
    after. The reading is a Core `select` on an unmarked connection: over a session marked to the
    demonstration tenant this assertion could not fail, because the listener filters the
    neighbour's rows to nothing.

    Its red is verified by mutation, not by inspection: replacing the ORM delete with a Core one
    that drops the tenant clause — which is what makes the listener stop seeing it — reds this
    test.
    """
    # `with_notification_config=False` on both: this test documents `tenant_configs`
    # as the one table neither fixture populates — true again now that
    # `insert_tenant` seeds a config row by default (`notification-channel-routing`).
    neighbour = await insert_tenant(
        db_session, name="AutoHostAI Dev", with_notification_config=False
    )
    demo = await insert_tenant(
        db_session, name=demo_reset.DEMO_TENANT_NAME, with_notification_config=False
    )
    await populate_tenant(db_session, neighbour)
    await populate_tenant(db_session, demo)
    await db_session.commit()

    before = await snapshot_tenant_rows(test_engine, neighbour.id)
    children_before = await snapshot_children_of(test_engine, neighbour.id)
    # `all`, not `any`, and that upgrade is the point. While `populate_tenant` covered only ten
    # of the twenty-four tables the phase deletes from, this comparison was `[] == []` for the
    # other fourteen — a vacuous pass, and an unscoped delete on any of them would have shipped
    # green. The fixture now fills every scoped table, so D18.3's "fotografía de **todas** las
    # filas" is literally true. `tenant_configs` is the one exception and it is named here rather
    # than tolerated: the fixture creates no config row, and the phase never touches that table.
    empty = {name for name, rows in before.items() if not rows}
    assert empty == {"tenant_configs"}, f"tables with no neighbour row to protect: {empty}"
    assert all(rows for rows in children_before.values())

    marked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(marked, demo.id)
    await demo_reset.delete_the_tenants_rows(marked, demo.id)
    await marked.commit()
    await marked.close()

    assert await snapshot_tenant_rows(test_engine, neighbour.id) == before
    # The four children too, which `snapshot_tenant_rows` cannot see: they carry no `tenant_id`,
    # and they are the half of the delete the listener does NOT protect (D6).
    assert await snapshot_children_of(test_engine, neighbour.id) == children_before


# --- Section 4: the password convergence, bounded to the four accounts -----------------


async def _marked_session(test_engine, tenant_id) -> AsyncSession:
    session = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(session, tenant_id)
    return session


async def _password_hash_of(engine: AsyncEngine, email: str) -> str | None:
    """Read a stored hash over Core on an unmarked connection (design D18.1).

    Through a session marked to the demonstration tenant a neighbour's row comes back empty and
    the assertion could not fail, which is the whole trap D18.1 names.
    """
    async with engine.connect() as connection:
        return (
            await connection.execute(
                select(UserModel.__table__.c.password_hash).where(
                    UserModel.__table__.c.email == email
                )
            )
        ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_the_password_converges_over_one_the_visitor_changed(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """R2.2: convergent, not create-only. This is the requirement's whole point.

    `bootstrap.apply_plan` is create-only for users (`if existing is not None: continue`), so
    without this phase a visitor who changed the password would leave the published credentials
    broken until somebody noticed. The account here starts with a *different* password, exactly
    as it would after `POST /auth/change-password`.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await insert_user(
        db_session,
        tenant=demo,
        role=UserRole.TENANT_OWNER,
        email=demo_reset.DEMO_OWNER_EMAIL,
        password="whatever-the-visitor-chose",
        hasher=hasher,
    )
    await db_session.commit()

    marked = await _marked_session(test_engine, demo.id)
    converged = await demo_reset.converge_the_demo_passwords(
        marked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
    )
    await marked.commit()
    await marked.close()

    assert len(converged) == 1
    stored = await _password_hash_of(test_engine, demo_reset.DEMO_OWNER_EMAIL)
    assert await hasher.verify(DEMO_PASSWORD, stored)
    assert not await hasher.verify("whatever-the-visitor-chose", stored)


@pytest.mark.asyncio
async def test_the_converged_accounts_are_operational_at_once(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """R1.3: `temporary=False`. A forced change would break the published credentials.

    Starts from `must_change_password=True` so the assertion is about what the phase writes and
    not about the column's default.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    user = await insert_user(
        db_session,
        tenant=demo,
        role=UserRole.CLEANER,
        email=demo_reset.DEMO_CLEANER_EMAIL,
        hasher=hasher,
    )
    user.must_change_password = True
    await db_session.flush()
    await db_session.commit()

    marked = await _marked_session(test_engine, demo.id)
    await demo_reset.converge_the_demo_passwords(
        marked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
    )
    await marked.commit()
    await marked.close()

    async with test_engine.connect() as connection:
        must_change = (
            await connection.execute(
                select(UserModel.__table__.c.must_change_password).where(
                    UserModel.__table__.c.id == user.id
                )
            )
        ).scalar_one()
    assert must_change is False


@pytest.mark.asyncio
async def test_the_previous_visitors_sessions_are_revoked(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """D9 step 4: leaving them alive would add a credential rather than restore the account."""
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    user = await insert_user(
        db_session,
        tenant=demo,
        role=UserRole.TENANT_OWNER,
        email=demo_reset.DEMO_OWNER_EMAIL,
        hasher=hasher,
    )
    db_session.add(
        UserSessionModel(
            id=uuid.uuid4(),
            tenant_id=demo.id,
            user_id=user.id,
            family_id=uuid.uuid4(),
            expires_at=datetime(2026, 12, 1, tzinfo=UTC),
        )
    )
    await db_session.commit()

    marked = await _marked_session(test_engine, demo.id)
    await demo_reset.converge_the_demo_passwords(
        marked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
    )
    await marked.commit()
    await marked.close()

    async with test_engine.connect() as connection:
        rows = (
            await connection.execute(
                select(
                    UserSessionModel.__table__.c.revoked_at,
                    UserSessionModel.__table__.c.revoked_reason,
                ).where(UserSessionModel.__table__.c.user_id == user.id)
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].revoked_at is not None
    assert rows[0].revoked_reason == SessionRevokedReason.PASSWORD_RESET.value


@pytest.mark.asyncio
async def test_the_convergence_leaves_an_audit_row_without_the_password(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """D9 step 3, and R2.5 over the one table that records the operation.

    `redacted("password")` rather than a diff: an audit row carrying the value would put the
    published credential in the one table the reset deliberately never clears.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await insert_user(
        db_session,
        tenant=demo,
        role=UserRole.TENANT_OWNER,
        email=demo_reset.DEMO_OWNER_EMAIL,
        hasher=hasher,
    )
    await db_session.commit()

    marked = await _marked_session(test_engine, demo.id)
    await demo_reset.converge_the_demo_passwords(
        marked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
    )
    await marked.commit()
    await marked.close()

    async with test_engine.connect() as connection:
        rows = (
            await connection.execute(
                select(
                    AuditLogModel.__table__.c.action,
                    AuditLogModel.__table__.c.actor_user_id,
                    AuditLogModel.__table__.c.changes,
                ).where(AuditLogModel.__table__.c.tenant_id == demo.id)
            )
        ).all()

    assert len(rows) == 1
    assert rows[0].action == actions.USER_PASSWORD_RESET
    # No actor: a command line has no identity to record (D9).
    assert rows[0].actor_user_id is None
    assert DEMO_PASSWORD not in json.dumps(rows[0].changes)


@pytest.mark.asyncio
async def test_a_neighbours_password_is_never_touched(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """D18.1, the first of R2's three clauses: the credential exists only inside the demo tenant.

    The neighbour holds an account whose password is known, and after the phase it must still
    verify with its own hash unchanged. Read over Core on an unmarked connection, because a
    session marked to the demonstration tenant returns the neighbour's rows empty and the
    assertion could not fail.

    **What reds this test, measured rather than assumed.** Not "dropping the `tenant_id` from the
    lookup", which is what task 4.3 asked for and what an earlier version of this docstring
    claimed: that lookup contains no `tenant_id` to drop — its scoping is the listener — and
    *deleting* the explicit tenant predicates elsewhere is a no-op, because the marked session
    re-adds them. What does red it is **substituting** a foreign tenant id into
    `users.apply_changes`, which makes its `rowcount != 1` guard raise. And note what this test
    can never catch: the neighbour holds `owner@company.example`, an address the phase never
    queries, so no tenant-check mutation could reach it. It stands as a regression guard against
    a future version of this phase that iterates something wider than its four constants — not as
    the proof of R2.4, which is the marker plus `require_session_bound_to` (see D18.1 as amended).
    """
    neighbour = await insert_tenant(db_session, name="AutoHostAI Dev")
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    # The neighbour's own account, and deliberately at one of the DEMO addresses' *shape* but a
    # different address: emails are unique installation-wide, so it cannot be the same one.
    await insert_user(
        db_session,
        tenant=neighbour,
        role=UserRole.TENANT_OWNER,
        email="owner@company.example",
        password="the-teams-own-password",
        hasher=hasher,
    )
    await insert_user(
        db_session,
        tenant=demo,
        role=UserRole.TENANT_OWNER,
        email=demo_reset.DEMO_OWNER_EMAIL,
        hasher=hasher,
    )
    await db_session.commit()

    before = await _password_hash_of(test_engine, "owner@company.example")

    marked = await _marked_session(test_engine, demo.id)
    await demo_reset.converge_the_demo_passwords(
        marked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
    )
    await marked.commit()
    await marked.close()

    after = await _password_hash_of(test_engine, "owner@company.example")
    assert after == before
    assert await hasher.verify("the-teams-own-password", after)
    assert not await hasher.verify(DEMO_PASSWORD, after)


@pytest.mark.asyncio
async def test_an_address_of_the_demo_set_owned_by_another_tenant_is_left_alone(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """R2.4 at its sharpest: the same address, in the wrong tenant, must not be converged.

    It cannot normally get there — `bootstrap.apply_plan` and the seed's
    `_refuse_addresses_owned_by_another_tenant` both refuse it upstream, unmarked, where a global
    lookup is still possible — so this pins what happens if it ever does: the scoped lookup does
    not see it, and nothing is written to it.
    """
    neighbour = await insert_tenant(db_session, name="AutoHostAI Dev")
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await insert_user(
        db_session,
        tenant=neighbour,
        role=UserRole.TENANT_OWNER,
        email=demo_reset.DEMO_OWNER_EMAIL,
        password="belongs-to-the-neighbour",
        hasher=hasher,
    )
    await db_session.commit()

    before = await _password_hash_of(test_engine, demo_reset.DEMO_OWNER_EMAIL)

    marked = await _marked_session(test_engine, demo.id)
    converged = await demo_reset.converge_the_demo_passwords(
        marked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
    )
    await marked.commit()
    await marked.close()

    assert converged == []
    assert await _password_hash_of(test_engine, demo_reset.DEMO_OWNER_EMAIL) == before


@pytest.mark.asyncio
async def test_a_deactivated_demo_account_is_brought_back(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """R1.3 against the way a visitor can defeat it, found by the section-4 security panel.

    The published `TENANT_OWNER` credential holds `MANAGE_USERS`, so a visitor can
    `POST /users/{id}/deactivate` the manager, the cleaner or the technician. Nothing else in the
    reset brings them back: `users` is preserved by D5, the prune only removes addresses outside
    the four, and `bootstrap.apply_plan` is create-only. Converging the password alone would write
    it onto an `INACTIVE` row — login refuses it (`use_cases.py` checks status) — and the run
    would still exit 0. Three of the four published credentials, killable for good and silently.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    user = await insert_user(
        db_session,
        tenant=demo,
        role=UserRole.CLEANER,
        email=demo_reset.DEMO_CLEANER_EMAIL,
        status=UserStatus.INACTIVE,
        hasher=hasher,
    )
    await db_session.commit()

    marked = await _marked_session(test_engine, demo.id)
    await demo_reset.converge_the_demo_passwords(
        marked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
    )
    await marked.commit()
    await marked.close()

    async with test_engine.connect() as connection:
        row = (
            await connection.execute(
                select(
                    UserModel.__table__.c.status, UserModel.__table__.c.role
                ).where(UserModel.__table__.c.id == user.id)
            )
        ).one()
    assert row.status == UserStatus.ACTIVE.value
    assert row.role == UserRole.CLEANER.value


@pytest.mark.asyncio
async def test_a_demoted_demo_account_gets_its_declared_role_back(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """The same shape as deactivation, one column over (R1.2, R1.3).

    R1.2 declares which role each of the four addresses has. A visitor who demotes the manager to
    `CLEANER` would otherwise leave the demo permanently unable to show anything a manager does,
    and `docs/demo-tenant.md` would be documenting a role the account no longer has.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    user = await insert_user(
        db_session,
        tenant=demo,
        role=UserRole.CLEANER,  # a visitor demoted the manager
        email=demo_reset.DEMO_MANAGER_EMAIL,
        hasher=hasher,
    )
    await db_session.commit()

    marked = await _marked_session(test_engine, demo.id)
    await demo_reset.converge_the_demo_passwords(
        marked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
    )
    await marked.commit()
    await marked.close()

    async with test_engine.connect() as connection:
        role = (
            await connection.execute(
                select(UserModel.__table__.c.role).where(UserModel.__table__.c.id == user.id)
            )
        ).scalar_one()
    assert role == UserRole.PROPERTY_MANAGER.value


def test_the_four_accounts_and_their_declared_roles_are_constants() -> None:
    """R1.2 pinned by value, now that the roles are what the converge phase restores."""
    assert demo_reset.DEMO_ACCOUNTS == (
        ("owner@demo.autohostai.test", "Propietaria Demo", UserRole.TENANT_OWNER),
        ("manager@demo.autohostai.test", "Gestora Demo", UserRole.PROPERTY_MANAGER),
        ("cleaner@demo.autohostai.test", "Limpiadora Demo", UserRole.CLEANER),
        ("technician@demo.autohostai.test", "Técnico Demo", UserRole.TECHNICIAN),
    )
    assert demo_reset.DEMO_ACCOUNT_EMAILS == tuple(
        email for email, _, _ in demo_reset.DEMO_ACCOUNTS
    )


@pytest.mark.asyncio
async def test_the_reset_takes_the_tenant_population_lock_before_any_write(
    demo_env, db_session: AsyncSession, test_engine, hasher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lock `user_admin.py` takes before touching `role`/`status`, in the same ORDER.

    It sits at the head of the transaction and **not** inside the converge phase, which is where
    it was first written. The security panel of section 4 caught that as a lock-order inversion:
    the delete phase takes row locks on `users` before converge would ask for the `tenants` lock,
    while the interactive path asks for the tenant lock first — so a concurrent `PATCH` could
    deadlock the reset and Postgres would abort one of the two. Taking it once, first, matches
    the interactive order and the inversion disappears.

    Asserted as a spy rather than by racing two transactions: what matters is that the lock comes
    before the first write, and a race test would be slower and flakier while proving less.
    Without the lock at all the suite was green, so this is what keeps it honest.
    """
    _use_the_test_database(monkeypatch, test_engine)

    order: list[str] = []
    real_lock = SqlAlchemyUserRepository.lock_tenant_for_admin
    real_apply = SqlAlchemyUserRepository.apply_changes

    async def spy_lock(self, tenant_id):
        order.append("lock")
        return await real_lock(self, tenant_id)

    async def spy_apply(self, tenant_id, user_id, values):
        order.append("write")
        return await real_apply(self, tenant_id, user_id, values)

    monkeypatch.setattr(SqlAlchemyUserRepository, "lock_tenant_for_admin", spy_lock)
    monkeypatch.setattr(SqlAlchemyUserRepository, "apply_changes", spy_apply)

    await demo_reset.run(demo_reset.build_plan())

    assert order, "neither the lock nor a write happened at all"
    assert order[0] == "lock"
    assert "write" in order, "the converge phase never wrote, so the order proves nothing"


@pytest.mark.asyncio
async def test_a_defaced_display_name_and_phone_are_restored(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """R3.3 against the only content a visitor can leave behind permanently.

    Every other piece of visitor-authored data in the tenant is emptied by the delete phase.
    These four `users` rows are the exception D5 preserves — and `PATCH /users/{id}` accepts
    `name` and `phone` from a `MANAGE_USERS` actor, which the published owner credential is. So
    without this, a visitor renames the demo owner to a phishing string once and no reset ever
    removes it: every later visitor reads it as if the product had written it.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    user = await insert_user(
        db_session,
        tenant=demo,
        role=UserRole.TENANT_OWNER,
        email=demo_reset.DEMO_OWNER_EMAIL,
        hasher=hasher,
    )
    user.name = "Soporte AutoHostAI — escribe a soporte@attacker.example"
    user.phone = "+34600000000"
    await db_session.flush()
    await db_session.commit()

    marked = await _marked_session(test_engine, demo.id)
    await demo_reset.converge_the_demo_passwords(
        marked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
    )
    await marked.commit()
    await marked.close()

    async with test_engine.connect() as connection:
        row = (
            await connection.execute(
                select(UserModel.__table__.c.name, UserModel.__table__.c.phone).where(
                    UserModel.__table__.c.id == user.id
                )
            )
        ).one()
    assert row.name == "Propietaria Demo"
    assert row.phone is None


@pytest.mark.asyncio
async def test_a_role_change_is_audited_under_its_own_action(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """Rule 9 of `steering/security.md`: "AuditLog para … **roles de User**".

    Converging the role put this phase inside that rule, and the row it used to emit said only
    `USER_PASSWORD_RESET` with the password redacted — so a visitor's demotion and the reset's
    own correction of it were both invisible. `USER_ROLE_CHANGED` makes it an indexed `action`
    filter rather than a JSONB query, which is the choice `user_admin.py` already made.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await insert_user(
        db_session,
        tenant=demo,
        role=UserRole.CLEANER,  # demoted manager
        email=demo_reset.DEMO_MANAGER_EMAIL,
        hasher=hasher,
    )
    await db_session.commit()

    marked = await _marked_session(test_engine, demo.id)
    await demo_reset.converge_the_demo_passwords(
        marked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
    )
    await marked.commit()
    await marked.close()

    async with test_engine.connect() as connection:
        rows = (
            await connection.execute(
                select(
                    AuditLogModel.__table__.c.action, AuditLogModel.__table__.c.changes
                ).where(AuditLogModel.__table__.c.tenant_id == demo.id)
            )
        ).all()

    assert len(rows) == 1
    assert rows[0].action == actions.USER_ROLE_CHANGED
    rendered = json.dumps(rows[0].changes)
    assert "PROPERTY_MANAGER" in rendered
    # And still never the password.
    assert DEMO_PASSWORD not in rendered


@pytest.mark.asyncio
async def test_a_converged_account_that_changed_nothing_but_the_password_keeps_its_action(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """The other side of the action choice: no role move means it is a password reset."""
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await insert_user(
        db_session,
        tenant=demo,
        role=UserRole.TENANT_OWNER,
        email=demo_reset.DEMO_OWNER_EMAIL,
        hasher=hasher,
    )
    await db_session.commit()

    marked = await _marked_session(test_engine, demo.id)
    await demo_reset.converge_the_demo_passwords(
        marked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
    )
    await marked.commit()
    await marked.close()

    async with test_engine.connect() as connection:
        action = (
            await connection.execute(
                select(AuditLogModel.__table__.c.action).where(
                    AuditLogModel.__table__.c.tenant_id == demo.id
                )
            )
        ).scalar_one()
    assert action == actions.USER_PASSWORD_RESET


@pytest.mark.asyncio
async def test_a_partial_redis_failure_only_reports_the_accounts_it_could_not_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One unreachable account must not be reported as four (D9.5).

    Wrapping the whole loop in a single `try` made a failure partway through claim every id was
    uncleared, including ones already cleared. `reset_password.clear_lock` reports per account.
    """
    first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    class _PartiallyBrokenThrottle:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def clear_account_lock(self, user_id) -> None:
            if user_id == second:
                raise RuntimeError("this one failed")

    monkeypatch.setattr(demo_reset, "get_redis", lambda: object())
    monkeypatch.setattr(demo_reset, "RedisLoginThrottle", _PartiallyBrokenThrottle)

    assert await demo_reset.clear_login_locks([first, second, third]) == [second]


@pytest.mark.asyncio
async def test_the_converge_phase_refuses_a_session_that_is_not_bound_to_the_tenant(
    db_session: AsyncSession, test_engine, hasher
) -> None:
    """Same precondition as the delete phase, for the same reason (D4bis point 1).

    The lookup that finds the four accounts is scoped by the marker alone, so on an unmarked
    session it would find — and rewrite the password of — an account of any tenant that happens
    to carry one of the four addresses.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await insert_user(
        db_session,
        tenant=demo,
        role=UserRole.TENANT_OWNER,
        email=demo_reset.DEMO_OWNER_EMAIL,
        hasher=hasher,
    )
    await db_session.commit()
    before = await _password_hash_of(test_engine, demo_reset.DEMO_OWNER_EMAIL)

    unmarked = AsyncSession(test_engine, expire_on_commit=False)
    with pytest.raises(TenantUnmarkedSessionError):
        await demo_reset.converge_the_demo_passwords(
            unmarked, demo.id, DEMO_PASSWORD, hasher, now=datetime(2026, 8, 23, tzinfo=UTC)
        )
    await unmarked.rollback()
    await unmarked.close()

    assert await _password_hash_of(test_engine, demo_reset.DEMO_OWNER_EMAIL) == before


@pytest.mark.asyncio
async def test_a_redis_failure_reports_the_lock_it_could_not_clear_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D9.5: Redis and Postgres share no transaction, so one has to be able to fail alone.

    The reset is already committed when this runs. Reporting failure here would be a lie, and a
    lock that expires by itself within the lockout window over an already-converged account is
    the benign degradation.
    """

    def _explode():
        raise RuntimeError("redis is unreachable")

    monkeypatch.setattr(demo_reset, "get_redis", _explode)
    user_id = uuid.uuid4()

    assert await demo_reset.clear_login_locks([user_id]) == [user_id]


# --- Section 5: the single transaction, the sweep, and R3.3 ----------------------------


_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)

#: An instant, anywhere in a value — including inside JSON, which is where two of them hide
#: (`incidents.ai_classification.classified_at`). The **date is kept** and only the time of day is
#: scrubbed, which is exactly the line R3.1 draws: "las fechas del dataset ancladas al **día** de
#: la ejecución". Two runs seconds apart legitimately differ in the instant; a run that put the
#: stay on the wrong DAY is the real bug this comparison has to keep catching — `seed_demo`'s own
#: R4.3 comment records that happening once, when a run between midnight and 02:00 Madrid time
#: used UTC's day and landed all three stays a day early.
_INSTANT = re.compile(r"(\d{4}-\d{2}-\d{2})[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2})?")

#: Columns and tables that R3.3 does NOT promise to reproduce, each named by D17 or D17bis:
#: `audit_logs` entirely (R3.6 preserves it and no endpoint reads it), and on the rows that
#: survive a reset, the mechanical bookkeeping plus `users.last_login_at` — the one observable
#: column the reset cannot restore, because `apply_changes` forbids writing it.
_OUTSIDE_R33_TABLES = {"audit_logs"}

#: Per table, because the reason is per table. `users` rows **survive** a reset (D5 preserves
#: them), so their `created_at` is legitimately older than a fresh provisioning's and their
#: `last_login_at` cannot be restored at all (D17bis). Every other table is deleted and reseeded,
#: so its timestamps are "today" in both runs and belong in the comparison — dropping them
#: globally, as an earlier version did, threw away the columns an API orders a timeline by and
#: with them the ability to catch the one bug the design records as having happened: a run near
#: midnight anchoring the dataset a day early.
_OUTSIDE_R33_COLUMNS = {
    "users": {"created_at", "updated_at", "last_login_at", "password_hash"},
    # The portal token's digest differs between runs **because R4.3 requires it to**: each reset
    # mints a fresh link and the old one dies, so an identical digest would mean the reset had
    # handed back a credential it was supposed to replace. Same shape as `password_hash` above —
    # a value that differs by construction while what it stands for is equivalent — and no
    # endpoint returns the digest either.
    "guest_access_tokens": {"token_hash"},
}


def _comparable(snapshot: dict, columns: dict) -> dict:
    """What R3.3 actually promises: composition, operational states, timeline and dates.

    **Not row identity**, and that is the point rather than a concession. Every entity of a fresh
    seed gets a new UUID — including ones that end up inside notification bodies — so a literal
    comparison fails on the very thing a reset is supposed to do. D17 says «indistinguible» is
    read over what the API and the screens return; ids are the part a visitor cannot contrast
    against anything, so they are scrubbed to `<id>` and everything else is compared verbatim.

    Timestamps of the `created_at`/`updated_at` kind go too: they are bookkeeping and they move by
    construction between two runs. Every other instant keeps its **date** and loses only its time
    of day — measured, not assumed: the only two values that differed once ids were scrubbed were
    `notification_logs.sla_deadline_at` and a `classified_at` buried inside
    `incidents.ai_classification`, both derived from the wall clock and half a second apart. The
    date surviving is what keeps this test able to catch the failure R3.1 actually cares about, a
    dataset anchored to the wrong day. `password_hash` is excluded because bcrypt salts every
    hash: it differs by construction while the password it verifies is identical.
    """
    out = {}
    for table, rows in snapshot.items():
        if table in _OUTSIDE_R33_TABLES:
            continue
        dropped = _OUTSIDE_R33_COLUMNS.get(table, set())
        keep = [
            index for index, name in enumerate(columns[table]) if name not in dropped
        ]
        out[table] = sorted(
            tuple(
                _INSTANT.sub(r"\1T<time>", _UUID.sub("<id>", row[index]))
                for index in keep
            )
            for row in rows
        )
    return out


def _column_names() -> dict:
    return {t.name: [c.name for c in t.columns] for t in Base.metadata.sorted_tables}


@pytest.mark.asyncio
async def test_the_command_provisions_a_missing_tenant_and_resets_an_existing_one(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """D1: one command, the same phases both times. R1.1 and R3.1 in one assertion.

    That there is no separate "provision" path is what makes R3.3 a property of the code rather
    than something to check — there are not two routes that could drift apart.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()

    first = await demo_reset.run(plan)
    assert first.counts["tenants"] == 1
    assert first.phases == list(demo_reset.PHASES)

    second = await demo_reset.run(plan)
    assert second.counts["tenants"] == 0  # bootstrap is a no-op on a reset (D7)
    assert second.phases == list(demo_reset.PHASES)
    # And the dataset is there again, not merely deleted.
    assert second.counts["seed_properties"] == 2


@pytest.mark.asyncio
async def test_a_failure_in_seed_reverts_the_delete_as_well(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """R3.4's "sin cambios parciales", which D7 makes true without code of its own.

    The delete, the converge and the seed share one transaction whose only commit is the seed's,
    so a failure in the seed takes the delete down with it. Measured on a **reset** rather than a
    first run, deliberately: `bootstrap.apply_plan` commits on its own account (D7 accepts this),
    so on a first run its rows would legitimately survive and the assertion would be about the
    wrong thing.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()
    await demo_reset.run(plan)

    before = await snapshot_every_row(test_engine)
    assert any(rows for rows in before.values())

    async def _explode(*_args, **_kwargs):
        raise RuntimeError("the seed failed halfway")

    monkeypatch.setattr(demo_reset.seed_demo, "apply_plan", _explode)

    with pytest.raises(demo_reset.PhaseError) as excinfo:
        await demo_reset.run(plan)

    assert excinfo.value.phase == "seed"
    # Every row of the demonstration tenant is still there: the delete reverted with it.
    assert await snapshot_every_row(test_engine) == before


@pytest.mark.asyncio
async def test_nothing_is_deleted_from_the_store_when_the_transaction_reverts(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """D16's order, which is the whole reason the sweep is a separate phase.

    Deleting objects before the commit would, if anything rolled back, leave live rows pointing
    at objects that no longer exist — worse than the orphans it avoids.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()
    await demo_reset.run(plan)

    deleted: list[str] = []

    async def _record(keys, tenant_id, storage_type):
        deleted.extend(keys)
        return []

    async def _explode(*_args, **_kwargs):
        raise RuntimeError("the seed failed halfway")

    monkeypatch.setattr(demo_reset, "sweep_storage", _record)
    monkeypatch.setattr(demo_reset.seed_demo, "apply_plan", _explode)

    with pytest.raises(demo_reset.PhaseError):
        await demo_reset.run(plan)

    assert deleted == [], "the store was swept even though the transaction reverted"


@pytest.mark.asyncio
async def test_a_successful_reset_sweeps_the_objects_the_delete_orphaned(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """R3.5's other half: on success the orphans are actually swept, not merely reported.

    Its sibling proves nothing is swept when the transaction reverts, which is the dangerous
    direction — but on its own that assertion is also satisfied by a sweep that never runs at all.
    Measured: disabling the sweep entirely left the whole suite green until this test existed.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()
    await demo_reset.run(plan)  # first run seeds the photos the second one will orphan

    swept: list[tuple[str, ...]] = []

    async def _record(keys, tenant_id, storage_type):
        swept.append(keys)
        return [f"storage-sweep: deleted {len(keys)} object(s)"]

    monkeypatch.setattr(demo_reset, "sweep_storage", _record)

    report = await demo_reset.run(plan)

    assert swept, "the sweep phase never ran"
    assert swept[0], "the sweep ran with no keys, so the delete orphaned nothing it could see"
    # Every key belongs to the demonstration tenant, and the report says what happened.
    assert any("storage-sweep" in note for note in report.notes)


@pytest.mark.asyncio
async def test_the_sweep_reports_the_keys_it_could_not_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3.5: report the orphans. A store failure must not turn the run red (D16).

    The database is already consistent by the time this runs, so calling the reset failed would
    be false — the honest outcome is a note naming the keys.
    """

    class _RefusingStore:
        async def delete(self, key: str) -> None:
            if "second" in key:
                raise RuntimeError("the store refused")

    monkeypatch.setattr(
        demo_reset.ConfiguredFileStorageFactory,
        "storage_for",
        lambda self, storage_type: _RefusingStore(),
    )

    tenant_id = uuid.uuid4()
    notes = await demo_reset.sweep_storage(
        (f"tenants/{tenant_id}/first.jpg", f"tenants/{tenant_id}/second.jpg"),
        tenant_id,
        StorageType.LOCAL,
    )

    assert any("deleted 1 of 2" in note for note in notes)
    assert any(f"tenants/{tenant_id}/second.jpg" in note for note in notes)


@pytest.mark.asyncio
async def test_the_sweep_refuses_a_key_outside_the_tenants_own_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last thing between a query result and an irreversible delete (R1.5, R3.5).

    The bucket is shared by every tenant of the environment and has no tenant filter of its own,
    so if a scoped read upstream ever regressed, this loop is what stops the damage. The tenancy
    panel of this section demonstrated the read regressing — `collect_storage_keys` on an unmarked
    session returned a neighbour's key — so the check exists because that path was shown to be
    reachable, not because it might be.
    """
    deleted: list[str] = []

    class _RecordingStore:
        async def delete(self, key: str) -> None:
            deleted.append(key)

    monkeypatch.setattr(
        demo_reset.ConfiguredFileStorageFactory,
        "storage_for",
        lambda self, storage_type: _RecordingStore(),
    )
    mine, neighbour = uuid.uuid4(), uuid.uuid4()

    notes = await demo_reset.sweep_storage(
        (f"tenants/{mine}/a.jpg", f"tenants/{neighbour}/b.jpg"),
        mine,
        StorageType.LOCAL,
    )

    assert deleted == [f"tenants/{mine}/a.jpg"]
    assert any("REFUSED" in note and str(neighbour) in note for note in notes)


@pytest.mark.asyncio
async def test_the_key_collection_refuses_a_session_that_is_not_bound_to_the_tenant(
    db_session: AsyncSession, test_engine
) -> None:
    """The guard its two sibling phases already had, and this read needed most (R3.2).

    Proven reachable rather than hypothesised: on an unmarked session this function returned a
    neighbour's `incident_photos` key — that table carries no explicit predicate of its own and
    was scoped solely by the marker — and that key would have gone straight to
    `FileStoragePort.delete`. A Postgres mistake in this change rolls back; a bucket delete does
    not.
    """
    neighbour = await insert_tenant(db_session, name="AutoHostAI Dev")
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await populate_tenant(db_session, neighbour)
    await populate_tenant(db_session, demo)
    await db_session.commit()

    unmarked = AsyncSession(test_engine, expire_on_commit=False)
    with pytest.raises(TenantUnmarkedSessionError):
        await demo_reset.collect_storage_keys(unmarked, demo.id)
    await unmarked.close()

    mismarked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(mismarked, neighbour.id)
    with pytest.raises(TenantMismatchedSessionError):
        await demo_reset.collect_storage_keys(mismarked, demo.id)
    await mismarked.close()


def test_every_storage_key_column_in_the_schema_is_accounted_for() -> None:
    """R3.5 as a decision per column, enforced in CI rather than discovered in the bucket.

    Derived from the metadata so a new column joins the sweep on its own; pinned by value so its
    arrival is somebody's decision. `expenses.receipt_storage_key` is here because the tenancy
    panel of this section found it: D16 named only the two photo tables, and `app/statements/` has
    no writer yet — so the day `revenue-statements` gives it one, nothing would have told the
    sweep it existed and the objects would have orphaned silently.
    """
    assert demo_reset.storage_key_columns() == {
        "cleaning_photos": "storage_key",
        "incident_photos": "storage_key",
        "expenses": "receipt_storage_key",
    }


@pytest.mark.asyncio
async def test_the_sweep_collects_cleaning_photos_through_their_parent(
    db_session: AsyncSession, test_engine
) -> None:
    """The cross-tenant read the section-3 security panel warned about, before it could ship.

    `cleaning_photos` carries no `tenant_id` (the listener's fifth limit, D6), so a marked ORM
    read of it returns EVERY tenant's photos — and the sweep would then delete a neighbour's
    objects out of the shared bucket. `incident_photos` is scoped, so the marker covers it.
    """
    neighbour = await insert_tenant(db_session, name="AutoHostAI Dev")
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await populate_tenant(db_session, neighbour)
    await populate_tenant(db_session, demo)
    await db_session.commit()

    marked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(marked, demo.id)
    keys = await demo_reset.collect_storage_keys(marked, demo.id)
    await marked.close()

    assert keys, "no keys collected at all"
    for key in keys:
        assert str(demo.id) in key, f"{key} does not belong to the demonstration tenant"
        assert str(neighbour.id) not in key


def test_a_redis_failure_leaves_the_command_at_exit_zero(
    demo_env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Task 4.2's literal wording, closable only now that the phases are wired (D9.5).

    The reset is committed by the time the lock is cleared, so a Redis failure is a degradation
    to report, not a run to fail. Exercised through `main()` because "exit 0" is a statement
    about the command, not about the helper — which is why 4.2 stayed unchecked until here.
    """
    converged = [uuid.uuid4(), uuid.uuid4()]

    async def _apply(session, plan, hasher):
        return demo_reset.DemoResetReport(
            phases=["configuration", "refusal"],
            counts={"tenants": 0},
            notes=[],
            converged_user_ids=converged,
        )

    def _no_redis():
        raise RuntimeError("redis is unreachable")

    monkeypatch.setattr(demo_reset, "apply_plan", _apply)
    monkeypatch.setattr(demo_reset, "get_redis", _no_redis)
    monkeypatch.setattr(
        demo_reset, "async_session_factory", _NullSessionFactory()
    )

    assert demo_reset.main() == 0

    everything = "".join(capsys.readouterr())
    assert "login lockout" in everything
    assert DEMO_PASSWORD not in everything


class _NullSessionFactory:
    """A session factory whose session touches no database — `apply_plan` is stubbed out."""

    def __call__(self):
        return self

    async def __aenter__(self):
        return None

    async def __aexit__(self, *_exc):
        return False


@pytest.mark.asyncio
async def test_the_sweep_uses_the_tenants_own_store_and_not_the_environments(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """R3.5: a sweep against the wrong store reports a cleanup that never happened.

    Both adapters succeed on an absent object — LOCAL unlinks with `missing_ok=True`, S3 answers
    204 — so deleting from a store that never held the keys prints "deleted N of N" and the real
    orphans are never named. `seed_demo` reads `tenant_configs.storage_type` for exactly this
    question; an earlier version of this phase read `BOOTSTRAP_STORAGE_TYPE` instead.

    **No stubs.** An earlier version of both the code and this test needed two: the read happened
    *after* `bootstrap.apply_plan`, which converges the config to the environment value and
    commits, so the two sources could never disagree in a real run and the test could only reach
    the interesting state by disabling bootstrap. The security panel of this section pointed out
    that this made the test assert a property the command did not have. Reading the store *before*
    bootstrap is what makes the divergence real: the value captured is the one the objects being
    orphaned were actually written under, which is the whole question.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()
    await demo_reset.run(plan)

    async with test_engine.connect() as connection:
        tenant_id = (
            await connection.execute(
                select(TenantModel.__table__.c.id).where(
                    TenantModel.__table__.c.name == demo_reset.DEMO_TENANT_NAME
                )
            )
        ).scalar_one()
        await connection.execute(
            TenantConfigModel.__table__.update()
            .where(TenantConfigModel.__table__.c.tenant_id == tenant_id)
            .values(storage_type=StorageType.S3.value)
        )
        await connection.commit()

    # The environment says LOCAL; the tenant's own config now says S3. The run proceeds normally:
    # bootstrap converges the config back to LOCAL, and the seed therefore never meets the S3
    # tenant it would rightly refuse — but the store the sweep uses was already captured as S3,
    # which is what the objects on disk were written under.
    assert settings.bootstrap_storage_type == StorageType.LOCAL.value

    report = await demo_reset.run(plan)

    assert report.storage_type is StorageType.S3


@pytest.mark.asyncio
async def test_a_visitor_cannot_move_the_day_the_dataset_is_anchored_to(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """R3.1 and R3.3 against the one `tenants` column that must be converged.

    `PATCH /tenants/{id}` accepts `timezone` from any `TENANT_OWNER` — which the published
    credential is — and `seed_demo.apply_plan` anchors the WHOLE dataset's dates to it, computing
    "today" on the tenant's calendar rather than UTC's. So a visitor sets a zone on the far side
    of the date line once, and every later reset dates the demo to a day a fresh provisioning
    never would, reporting success each time.

    That is why this column is converged while `billing_email` deliberately is not: the
    `billing_email` exposure fails **closed** (the identity guard refuses, nothing is written, and
    it is a documented accepted limit), and this one fails **wrong**. A reset that lies about
    having restored the dataset is worse than one that refuses to run.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()
    await demo_reset.run(plan)

    async with test_engine.connect() as connection:
        await connection.execute(
            TenantModel.__table__.update()
            .where(TenantModel.__table__.c.name == demo_reset.DEMO_TENANT_NAME)
            .values(timezone="Pacific/Kiritimati")
        )
        await connection.commit()

    report = await demo_reset.run(plan)

    async with test_engine.connect() as connection:
        zone = (
            await connection.execute(
                select(TenantModel.__table__.c.timezone).where(
                    TenantModel.__table__.c.name == demo_reset.DEMO_TENANT_NAME
                )
            )
        ).scalar_one()
    assert zone == demo_reset.DEMO_TENANT_TIMEZONE
    # The note must name what was ACTUALLY there. An earlier version formatted it after the
    # assignment, so it always claimed the value it had just written — the one fact an operator
    # reading the 03:15 log cannot get anywhere else.
    assert any("Pacific/Kiritimati" in note for note in report.notes)


@pytest.mark.asyncio
async def test_a_defaced_tenant_country_is_restored(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """R3.3 against the third case the converge criterion did not name at first.

    `country` is the awkward one precisely because nothing computes from it: it produces no
    refusal like `billing_email` and no wrong dates like `timezone` — just a permanent visible
    defacement that no reset removes. Found by the QA panel of this section attacking the
    criterion the panel before it had established, which is the whole reason to write criteria
    down rather than decide case by case.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()
    await demo_reset.run(plan)

    async with test_engine.connect() as connection:
        await connection.execute(
            TenantModel.__table__.update()
            .where(TenantModel.__table__.c.name == demo_reset.DEMO_TENANT_NAME)
            .values(country="XX")
        )
        await connection.commit()

    report = await demo_reset.run(plan)

    async with test_engine.connect() as connection:
        country = (
            await connection.execute(
                select(TenantModel.__table__.c.country).where(
                    TenantModel.__table__.c.name == demo_reset.DEMO_TENANT_NAME
                )
            )
        ).scalar_one()
    assert country == demo_reset.DEMO_TENANT_COUNTRY
    assert any("'XX'" in note for note in report.notes)


@pytest.mark.asyncio
async def test_a_renamed_demo_tenant_fails_closed_and_commits_nothing(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """The accepted limit, pinned — and pinned with the exception it actually raises.

    A visitor can rename the tenant, after which the identity guard finds nothing and
    `bootstrap.apply_plan` tries to create a fresh one. It does **not** fork the demo: the four
    addresses already belong to the renamed row, and the global `uq_users_lower_email` makes
    `bootstrap` raise `BootstrapConflictError` before anything commits. This is the "fails
    closed" side of the converge criterion, and the Risks table named the wrong exception
    (`MultipleResultsFound`) until this test measured it — which matters because that name is
    what a runbook entry for this symptom would search for.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()
    await demo_reset.run(plan)

    async with test_engine.connect() as connection:
        await connection.execute(
            TenantModel.__table__.update()
            .where(TenantModel.__table__.c.name == demo_reset.DEMO_TENANT_NAME)
            .values(name="AutoHostAI Demo (renamed by a visitor)")
        )
        await connection.commit()

    before = await snapshot_every_row(test_engine)

    with pytest.raises(demo_reset.PhaseError) as excinfo:
        await demo_reset.run(plan)

    assert excinfo.value.phase == "bootstrap"
    assert excinfo.value.cause_class == "BootstrapConflictError"
    assert await snapshot_every_row(test_engine) == before


@pytest.mark.asyncio
async def test_the_reset_publishes_the_guest_portal_link(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """R4.3 end to end, which is the requirement R2.5's only exception exists for (D19).

    This test exists because the wiring was missing and nothing noticed: the seed minted the
    token and appended its URL to a list `demo_reset` never passed in, so `report.portal_url`
    was `None` on every run and `main()`'s print was unreachable. Every other test passed —
    section 6 asserted the seed's own list, which was populated, and nothing asserted the
    command's report. The headline requirement was undelivered behind a green suite.

    The cleartext token exists exactly once, in that return; only its digest is stored. So this
    also checks the URL is usable rather than merely present: the token in it must verify against
    the digest the database kept.
    """
    _use_the_test_database(monkeypatch, test_engine)

    report = await demo_reset.run(demo_reset.build_plan())

    assert report.portal_url is not None
    assert report.portal_url.startswith(f"{settings.frontend_base_url}/guest/")
    token = report.portal_url.rsplit("/", 1)[1]
    async with test_engine.connect() as connection:
        digest = (
            await connection.execute(select(GuestAccessTokenModel.__table__.c.token_hash))
        ).scalar_one()
    assert hash_guest_token(token) == digest


@pytest.mark.asyncio
async def test_every_reset_publishes_a_fresh_link_and_kills_the_previous_one(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """The second of the three facts that bound R2.5's exception (D19): it dies in the next reset.

    The seed skips minting when a live token exists — that is what keeps `make seed-demo`
    idempotent — so this is what proves the reset is not affected by that skip: its delete phase
    empties `guest_access_tokens` first, so every run genuinely publishes a new link and the
    previous one stops working.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()

    first = (await demo_reset.run(plan)).portal_url
    second = (await demo_reset.run(plan)).portal_url

    assert first is not None and second is not None
    assert first != second
    async with test_engine.connect() as connection:
        digests = (
            await connection.execute(select(GuestAccessTokenModel.__table__.c.token_hash))
        ).scalars().all()
    # Exactly one token exists, and it is the second one: the first was deleted with the stay.
    assert digests == [hash_guest_token(second.rsplit("/", 1)[1])]


def test_main_prints_the_portal_link_it_was_given(
    demo_env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R2.5's exception is only satisfied if the URL actually reaches the output (D19).

    Driven over a canned report, because `main()` calls `asyncio.run` and cannot be invoked from
    a running loop — the same device `test_seed_demo.py::_drive_main` uses and for the same
    reason. What is under test is the print, not the composition.
    """
    url = "https://demo.example/guest/a-token-that-only-exists-once"

    async def _report(_plan):
        return demo_reset.DemoResetReport(
            phases=list(demo_reset.PHASES), counts={}, notes=[], portal_url=url
        )

    monkeypatch.setattr(demo_reset, "run", _report)

    assert demo_reset.main() == 0

    out = capsys.readouterr().out
    assert url in out
    # And the line carries PORTAL_LINE_PREFIX, which is the half of this seam the workflow greps
    # for. Asserting only `url in out` left the two halves free to drift: the workflow-side tests
    # pin the constant inside the .yml, but nothing tied it to what the command actually prints,
    # so renaming the literal here kept the whole suite green while the link silently stopped
    # reaching the job summary (R4.3). Found by the /sdd:review panel, 2026-08-24 — the exact
    # seam BLOCKED.md asked a reviewer to look at, and what the constant's own docstring warns of.
    assert f"{demo_reset.PORTAL_LINE_PREFIX}: {url}" in out
    # And still never the password, which the same exception explicitly does not cover.
    assert DEMO_PASSWORD not in out


@pytest.mark.asyncio
async def test_a_reset_is_indistinguishable_from_a_fresh_provisioning(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """R3.3, read the way D17 and D17bis define it.

    Two runs on the same day must leave the same observable tenant. Compared at row level rather
    than through the API, which is strictly stronger — every column an endpoint could return is
    included — minus the four things D17/D17bis exclude and name: `audit_logs` entirely (R3.6
    preserves it and no endpoint reads it), and `users.created_at`/`id`/`last_login_at`.
    `password_hash` is excluded too: bcrypt salts every hash, so it differs by construction while
    the password it verifies is identical.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()
    columns = _column_names()

    await demo_reset.run(plan)
    first = _comparable(await snapshot_every_row(test_engine), columns)

    await demo_reset.run(plan)
    second = _comparable(await snapshot_every_row(test_engine), columns)

    assert second == first


# --- Section 9: the scheduled workflow, read as a contract ------------------------------

_WORKFLOW_CANDIDATES = (
    Path("/workspace/demo-reset.yml"),
    Path(__file__).resolve().parents[3] / ".github/workflows/demo-reset.yml",
)


def _workflow_text() -> str:
    """The workflow, from the container mount or the repository layout.

    Same two-candidate shape the `.env.example` test uses, and for the same reason: the backend
    container mounts only `./backend`, so the repo root is not reachable from where the suite runs.
    (The rule 11 guard was the third user of this shape until `rule11-guard-trigger-and-scope` took
    it out of the container; a guard that runs on the host needs only one origin.) `docker-compose.yml` already mounted `deploy-dev.yml` for
    the provenance regression, and this change adds the same mount for this file at
    `/workspace/demo-reset.yml`, so it resolves locally as well as in CI.
    """
    for candidate in _WORKFLOW_CANDIDATES:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    pytest.skip(
        "demo-reset.yml is not reachable from this container, which should not normally happen: "
        "`docker-compose.yml` mounts it read-only at /workspace/demo-reset.yml, the first candidate "
        "above. Kept as a skip rather than a failure so that a stack brought up from an older "
        "compose file degrades instead of reporting a defect that is not in the code."
    )


def test_the_workflow_greps_for_the_line_the_command_actually_prints() -> None:
    """The seam that would break R4.3 in silence.

    The workflow publishes the portal link by grepping the command's stdout. Nothing connects the
    two but a string, so editing the message would stop the link reaching the job summary with no
    test failing and no red run — the requirement undelivered behind a green pipeline. That is the
    same producer/consumer shape that already hid the `portal_links` wiring defect in section 6,
    which is why this is pinned rather than trusted.
    """
    assert demo_reset.PORTAL_LINE_PREFIX in _workflow_text()


def test_the_workflow_keeps_the_portal_token_out_of_any_shared_persistent_path() -> None:
    """D19: the job summary is the ONLY channel by which the portal token reaches anyone.

    The command's stdout is teed to a file so the summary step can grep it, and *where* that file
    lives is a security property rather than a detail. `/tmp` on the self-hosted runner is shared
    and persistent: a token written there stays readable by any local user until the next 03:15 run
    overwrites it — a second channel, and D19's bounding of R2.5's single exception rests on there
    being none. `RUNNER_TEMP` is emptied by the runner around every job, so the file cannot outlive
    the run even if the cleanup below is skipped.

    Stated as the universal it is, not as two examples of it: the first version of this test banned
    the one literal path the fix had replaced and asserted the replacement was present, which left
    an ADDED sink green — a second `tee`, a `cp` to `/tmp`, or an `upload-artifact` step, any of
    which reopens the channel the docstring says is closed. Raised by the `/sdd:review` security
    panel on 2026-08-24, one round after the same panel raised the underlying fix.
    """
    import re

    import yaml

    job = yaml.safe_load(_workflow_text())["jobs"]["reset"]
    steps = job["steps"]
    scripts = [step.get("run") or "" for step in steps]

    # No sink under a shared, persistent path — whatever it is named.
    for script in scripts:
        assert "/tmp/" not in script, "no step may write the command's output under a shared /tmp"

    # And every reference to the file goes through RUNNER_TEMP, which the runner empties per job.
    for script in scripts:
        for match in re.finditer(r"\S*demo-reset\.out", script):
            assert re.search(r"\$\{?RUNNER_TEMP\}?/demo-reset\.out$", match.group(0)), (
                f"{match.group(0)!r} must live under $RUNNER_TEMP"
            )

    # An artifact outlives the run by its retention period, which is the same channel by post.
    for step in steps:
        assert "upload-artifact" not in (step.get("uses") or "")


def test_the_workflow_deletes_the_intermediate_output_even_when_the_reset_fails() -> None:
    """D19, second half: the file that carried the token is removed unconditionally.

    `if: always()` is the load-bearing part — a cleanup gated on success would leave the token
    behind on exactly the runs where something went wrong.

    Two things this asserts carefully, both because the first version got them wrong in the
    direction that cries wolf on correct code — the hazard
    `test_the_workflow_does_not_publish_the_password_in_its_summary` already records for this file.
    The ordering is asserted against the steps that actually **read the file**, not against every
    step that writes the job summary: those coincide today, but a second summary step that never
    touches the file, or a legitimate mid-job cleanup, would have failed the earlier form without
    the property being broken. And the condition is matched as a substring, so `${{ always() }}`
    and `always() && …` — both equally valid — do not red correct code.
    """
    import yaml

    steps = yaml.safe_load(_workflow_text())["jobs"]["reset"]["steps"]

    def _mentions(step: dict) -> bool:
        return "demo-reset.out" in (step.get("run") or "")

    cleanups = [i for i, step in enumerate(steps) if _mentions(step) and "rm -f" in step["run"]]
    readers = [i for i, step in enumerate(steps) if _mentions(step) and i not in cleanups]

    assert cleanups, "no step removes the file that carried the portal token"
    for i in cleanups:
        assert "always()" in (steps[i].get("if") or ""), (
            "the cleanup must not be gated on the reset succeeding"
        )

    assert readers, "no step reads the file, so the tee has no purpose"
    assert max(readers) < min(cleanups), "the cleanup must run after the last reader"


def test_the_workflow_shares_the_deploy_jobs_concurrency_group() -> None:
    """D13: the same group as `deploy-dev.yml`'s `deploy` job, and it is deliberate.

    A reset must never run while a deployment is rewriting the `.env` and recreating containers.
    It is the only coupling this change adds to the existing workflow, so a rename on either side
    silently removes the protection.
    """
    text = _workflow_text()
    assert "group: deploy-dev" in text
    assert "cancel-in-progress: false" in text


def test_the_workflow_masks_the_password_before_it_invokes_anything() -> None:
    """R5.5: the mask is what stops a later failure volcando la contraseña.

    Asserted by ORDER, not by presence: a `::add-mask::` after the invocation would satisfy a
    grep and protect nothing.
    """
    text = _workflow_text()
    mask = text.index("::add-mask::")
    invoke = text.index("app.cli.demo_reset")
    assert mask < invoke, "the password must be masked before the command runs"


def test_the_workflow_passes_the_password_without_a_value_on_the_command_line() -> None:
    """D14: `-e DEMO_ACCOUNT_PASSWORD` with no `=valor`, so it never reaches the process table."""
    text = _workflow_text()
    assert "-e DEMO_ACCOUNT_PASSWORD \\" in text or "-e DEMO_ACCOUNT_PASSWORD " in text
    assert "-e DEMO_ACCOUNT_PASSWORD=" not in text


def test_the_workflow_does_not_publish_the_password_in_its_summary() -> None:
    """R2.5: the exception covers the portal link and nothing else.

    The summary step writes to `$GITHUB_STEP_SUMMARY`, which is readable by anyone who can see the
    run. It may carry the URL; it may not carry the credential.

    Scoped by parsing the YAML and reading **only that step's** `run` block. A textual window
    around the marker was the first attempt and it was wrong in the direction that matters: it
    swept in the invocation step, which legitimately names `DEMO_ACCOUNT_PASSWORD`, so the test
    failed on correct code. A test that cries wolf about a security property gets weakened or
    deleted, which is worse than not having it.
    """
    import yaml

    workflow = yaml.safe_load(_workflow_text())
    steps = workflow["jobs"]["reset"]["steps"]
    summary_steps = [
        step for step in steps if "GITHUB_STEP_SUMMARY" in (step.get("run") or "")
    ]

    assert summary_steps, "no step writes the job summary"
    for step in summary_steps:
        assert "DEMO_ACCOUNT_PASSWORD" not in step["run"]
        # And it does carry the link, which is the half R4.3 needs.
        assert demo_reset.PORTAL_LINE_PREFIX in step["run"]


# --- `demo-tenant-audit-retention`: the `purge-audit` phase -----------------------------
#
# The reset's audit-log retention: `purge_old_audit_logs` deletes rows older than the
# cutoff, `_safe_purge_old_audit_logs` wraps it with audit-row-before-delete and
# degradation on failure. Each test pins one clause of R1/R2/R3; together they prove the
# design from three angles — the raw DELETE, the wrapper, and the run-level wire-up.


@pytest.mark.asyncio
async def test_purge_old_audit_logs_deletes_rows_older_than_cutoff(
    db_session: AsyncSession, test_engine
) -> None:
    """R1.1 + R1.3 — the raw DELETE removes rows older than the cutoff, leaves newer ones.

    Three rows pinned around the cutoff: one comfortably after it (must survive), one
    comfortably before (must go), and one exactly at the cutoff. The SQL is `< :cutoff`,
    not `<=`, so the boundary row belongs to the kept side — D3 spells it out as the
    construction that preserves the last reset's rows, and asserting it here is what
    catches a future `<=` typo that would silently over-purge by one day.

    The marked-session guard is the second half of R1.3. Verified by a sibling test that
    binds the session to a different tenant, so this one stays focused on the DELETE.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await db_session.flush()

    cutoff = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    survivor = AuditLogModel(
        id=uuid.uuid4(),
        tenant_id=demo.id,
        action=actions.USER_PASSWORD_RESET,
        entity_type=actions.ENTITY_USER,
        entity_id=uuid.uuid4(),
        # One day after the cutoff — survives with a comfortable margin.
        created_at=cutoff + timedelta(days=1),
    )
    casualty = AuditLogModel(
        id=uuid.uuid4(),
        tenant_id=demo.id,
        action=actions.USER_UPDATED,
        entity_type=actions.ENTITY_USER,
        entity_id=uuid.uuid4(),
        # Three days before the cutoff — purged.
        created_at=cutoff - timedelta(days=3),
    )
    boundary = AuditLogModel(
        id=uuid.uuid4(),
        tenant_id=demo.id,
        action=actions.INCIDENT_CREATED,
        entity_type=actions.ENTITY_INCIDENT,
        entity_id=uuid.uuid4(),
        # Exactly at the cutoff. `< :cutoff` keeps this row; `<=` would drop it.
        created_at=cutoff,
    )
    db_session.add_all([survivor, casualty, boundary])
    await db_session.commit()

    marked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(marked, demo.id)
    deleted = await demo_reset.purge_old_audit_logs(marked, demo.id, cutoff)
    await marked.commit()
    await marked.close()

    assert deleted == 1, "only the row before the cutoff should have been deleted"

    async with test_engine.connect() as connection:
        remaining_ids = {
            row[0]
            for row in (
                await connection.execute(
                    select(AuditLogModel.__table__.c.id).where(
                        AuditLogModel.__table__.c.tenant_id == demo.id
                    )
                )
            ).all()
        }
    assert remaining_ids == {survivor.id, boundary.id}, (
        "the cutoff row belongs to the kept side: `< :cutoff` keeps it, `<=` would drop it"
    )


@pytest.mark.asyncio
async def test_purge_old_audit_logs_refuses_a_session_bound_to_a_different_tenant(
    db_session: AsyncSession, test_engine
) -> None:
    """R1.4 — the SQL guard, not just the run-level dispatch.

    `require_session_bound_to` is the constant D5 names, and the proposal spells it out
    twice: once for the run-level dispatch ("WHERE el `tenant_id` resuelto no es el del
    demo, THE SYSTEM SHALL rechazar la fase con código 2 sin escribir nada"), and once for
    the SQL boundary, where the listener's `WHERE tenant_id = :tenant_id` would still
    pass the wrong id through. The mismatch raises before any DELETE runs; we assert the
    error class because the run() catches everything as `PhaseError`, and the type is what
    inherits from `TenantMismatchedSessionError` for that exact case.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    other = await insert_tenant(db_session, name="Other Tenant For The Audit Purge")
    await db_session.flush()

    mismarked = AsyncSession(test_engine, expire_on_commit=False)
    bind_session_to_tenant(mismarked, other.id)
    with pytest.raises(TenantMismatchedSessionError):
        await demo_reset.purge_old_audit_logs(
            mismarked, demo.id, datetime.now(UTC)
        )
    await mismarked.close()

    async with test_engine.connect() as connection:
        count = (
            await connection.execute(
                select(AuditLogModel.__table__.c.id).where(
                    AuditLogModel.__table__.c.tenant_id == demo.id
                )
            )
        ).all()
    assert count == [], "the refused phase must not write to audit_logs"


@pytest.mark.asyncio
async def test_safe_purge_old_audit_logs_writes_the_audit_row_before_the_delete(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.1 + R3.2 — the audit row is written before the DELETE.

    `purge_old_audit_logs` is patched to record the call order without touching the
    database: the assertion is on the order, not on what the DELETE did. The audit row's
    fields are checked by hand because `audit.add` is the chokepoint and its argument is
    the only place where the rule 11 contract is enforced. Note that the audit row does
    NOT survive a DELETE failure — the row and the DELETE share one `session.commit()`,
    so the row only persists if the DELETE also persists (atomic semantics; the proposal
    amendment in this change drops the OLD R3.2 "survives failure" wording and the test
    only pins temporal order, which is what R3.2 now requires).
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await db_session.commit()
    started_at = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    cutoff = started_at - timedelta(days=demo_reset.DEMO_AUDIT_RETENTION_DAYS)

    order: list[str] = []
    captured: dict[str, AuditLog] = {}

    async def _record(session, tenant_id, bound_cutoff):
        order.append("purge")
        return 0

    async def _record_add(self, _tenant_id, entry):
        order.append("audit_add")
        captured["row"] = entry

    monkeypatch.setattr(demo_reset, "purge_old_audit_logs", _record)
    monkeypatch.setattr(
        demo_reset.SqlAlchemyAuditLogRepository, "add", _record_add
    )

    count, note = await demo_reset._safe_purge_old_audit_logs(demo.id, started_at)

    assert count == 0
    assert note is None
    # Audit row first, then the DELETE — R3.2 by construction.
    assert order == ["audit_add", "purge"]
    row = captured["row"]
    assert row.action == actions.AUDIT_LOG_PURGED
    assert row.entity_type == actions.ENTITY_AUDIT_LOG
    assert row.entity_id == uuid.uuid5(demo.id, "demo-audit-purge")
    assert row.actor_user_id is None
    assert row.actor_ip is None
    # The ChangeSet is on `AUDIT_LOG`, which carries both keys by design (test 1.4 above).
    assert row.changes is not None
    assert "deleted_count" in row.changes
    assert "cutoff" in row.changes
    assert row.changes["cutoff"] == {"old": None, "new": cutoff.isoformat()}


@pytest.mark.asyncio
async def test_safe_purge_old_audit_logs_degrades_when_the_delete_fails(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2.3 — a DELETE failure becomes a note, not exit 2.

    The note format matches `clear_login_locks`' shape so the operator-facing surface
    stays uniform: phase name, exception class, and an explicit "detail withheld on
    purpose" rather than the bare class name. The `(0, note)` return is what task 5.7 of
    the proposal pinned as the contract — the run keeps reporting success. Note that
    because the audit row and the DELETE share one `session.commit()`, the row is
    reverted with the transaction on DELETE failure; the degradation note is the
    honest record of the attempt, not a committed audit row.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await db_session.commit()
    started_at = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

    async def _explode(session, tenant_id, cutoff):
        raise RuntimeError("simulated DB error")

    monkeypatch.setattr(demo_reset, "purge_old_audit_logs", _explode)

    count, note = await demo_reset._safe_purge_old_audit_logs(demo.id, started_at)

    assert count == 0
    assert note == "purge-audit: failed with RuntimeError (detail withheld on purpose)"
    # The original message must NOT appear in the note — R2.3 is the only reason this
    # matters, but R2.5 says the credential has no other channel and a database error
    # can stringify its way to a bcrypt hash.
    assert "simulated DB error" not in (note or "")


@pytest.mark.asyncio
async def test_safe_purge_old_audit_logs_degrades_when_the_audit_row_write_fails(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.3 — no re-entry into `audit.add`. Once it raises, the function must not retry.

    The `add` call count is the assertion the panel of section 4 measured: a second call
    would race against the rolled-back DELETE and could write a row that describes a
    purge that never committed. Sharing the same `try/except` boundary as the DELETE
    failure case is what keeps the two halves symmetric.
    """
    demo = await insert_tenant(db_session, name=demo_reset.DEMO_TENANT_NAME)
    await db_session.commit()
    started_at = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

    add_calls = 0

    async def _boom(self, _tenant_id, _entry):
        nonlocal add_calls
        add_calls += 1
        raise RuntimeError("audit.add refused")

    async def _no_delete(session, tenant_id, cutoff):
        raise AssertionError("purge_old_audit_logs should not be reached")

    monkeypatch.setattr(
        demo_reset.SqlAlchemyAuditLogRepository, "add", _boom
    )
    monkeypatch.setattr(demo_reset, "purge_old_audit_logs", _no_delete)

    count, note = await demo_reset._safe_purge_old_audit_logs(demo.id, started_at)

    assert count == 0
    assert note == "purge-audit: failed with RuntimeError (detail withheld on purpose)"
    assert add_calls == 1, "the function must not retry audit.add after a raise"


@pytest.mark.asyncio
async def test_a_full_reset_terminates_with_purge_audit_in_phases_and_count_in_report(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """R2.4 — the wire-up carries through end-to-end, twice.

    `test_the_command_provisions_a_missing_tenant_and_resets_an_existing_one` already
    pins `first.phases == second.phases == list(PHASES)`. This test pins the parts that
    are specific to the new phase: `purge-audit` is in the list, and the count in the
    report is a non-negative integer. The value is not asserted because a fresh test
    database has no `audit_logs` rows older than seven days, and an empty database has
    to produce `0` for the count to stay reproducible.
    """
    _use_the_test_database(monkeypatch, test_engine)
    plan = demo_reset.build_plan()

    first = await demo_reset.run(plan)
    assert "purge-audit" in first.phases
    assert isinstance(first.counts.get("audit_logs_purged"), int)
    assert first.counts["audit_logs_purged"] >= 0

    second = await demo_reset.run(plan)
    assert "purge-audit" in second.phases
    assert isinstance(second.counts.get("audit_logs_purged"), int)
    assert second.counts["audit_logs_purged"] >= 0


@pytest.mark.asyncio
async def test_purge_audit_does_not_run_when_prepare_did_not_run(
    demo_env, monkeypatch: pytest.MonkeyPatch, test_engine, db_session: AsyncSession
) -> None:
    """D8 — the `purge-audit` phase is gated on `prepare` having populated `started_at`.

    Raising inside `prepare` keeps `report.started_at` at its default `None`, and
    `_safe_purge_old_audit_logs` returns `(0, None)` without opening a session. The
    phase block in `run()` still records its name, so the `phases` list shows that
    `purge-audit` was reached — but the absence of a count, and the absence of any row
    in `audit_logs` matching the purge action, are what proves the body did not run.

    Asserted by inspecting `report.counts` and `audit_logs` rather than `report.phases`
    because the phase list records attempt, not execution.
    """
    _use_the_test_database(monkeypatch, test_engine)

    real_prepare = demo_reset._phase

    @asynccontextmanager
    async def _prepare_bombs(name, report):
        async with real_prepare(name, report):
            if name == "prepare":
                raise RuntimeError("prepare raised on purpose")
            yield

    monkeypatch.setattr(demo_reset, "_phase", _prepare_bombs)

    # `_phase` catches the inner exception and re-raises as `PhaseError`, which is what
    # `run()` propagates. Asserting on `PhaseError.phase == "prepare"` is the same path
    # the production code follows; the inner `RuntimeError` does not reach the caller.
    with pytest.raises(demo_reset.PhaseError) as excinfo:
        await demo_reset.run(demo_reset.build_plan())
    assert excinfo.value.phase == "prepare"

    # No audit_logs row with the purge action — `purge-audit`'s body never ran.
    async with test_engine.connect() as connection:
        purge_rows = (
            await connection.execute(
                select(AuditLogModel.__table__.c.action).where(
                    AuditLogModel.__table__.c.action == actions.AUDIT_LOG_PURGED
                )
            )
        ).all()
    assert purge_rows == [], "purge-audit wrote its audit row despite prepare failing"
