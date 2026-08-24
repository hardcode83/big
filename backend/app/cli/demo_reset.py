"""Provisions and resets the demonstration tenant (change `demo-user`, design D1).

Run with `make demo-reset`, or `python -m app.cli.demo_reset` inside the container. On a
demonstration tenant that does not exist yet it provisions it; on one that does it resets it,
and **both go through the same sequence of phases**. That is what makes R3.3 — "a state
indistinguishable from a provisioning from scratch on the same day" — a property of the code
rather than something to check: there are not two paths that could drift apart.

**The tenant it acts on is a constant of this module, not configuration** (D2). There is no
parameter, argument or environment variable by which this command can name another tenant, and
that is what satisfies R1.4 and R3.2 by construction. The obvious alternative — "refuse if the
name matches BOOTSTRAP_TENANT_NAME" — is useless in the environment that matters: the `.env`
the deploy renders on the VM carries no `BOOTSTRAP_TENANT_NAME`, so there the comparison would
be against the empty string and would refuse nothing. That comparison is kept anyway, as a
second gate, for the one case it does cover: somebody who named their working tenant after the
demonstration one.

Its single new setting is `DEMO_ACCOUNT_PASSWORD`, validated before any transaction opens and
never echoed. Nothing here ever prints the password, its hash or a session token; the one
exception is the guest-portal URL that the seed emits, which R2.5 names explicitly and D19
bounds.
"""

import asyncio
import dataclasses
import logging
import sys
import uuid
from datetime import UTC, datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import app.core.models_registry  # noqa: F401  -- see the comment below
from sqlalchemy import delete as sqlalchemy_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.domain import actions
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.domain.exceptions import PasswordPolicyError, PasswordTooLongError
from app.auth.domain.password_policy import PASSWORD_MIN_LENGTH, assert_password_acceptable
from app.auth.domain.value_objects import normalize_email
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.repositories import (
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
from app.auth.infrastructure.throttle import RedisLoginThrottle
from app.cleaning.infrastructure.models import CleaningPhotoModel, CleaningTaskModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.cli import bootstrap, seed_demo
from app.cli.bootstrap import BootstrapPlan, SeedUser
from app.cli.seed_demo import SeedAccount, SeedPlan
from app.core.config import settings
from app.core.redis import get_redis
from app.integrations.infrastructure.storage import ConfiguredFileStorageFactory
from app.maintenance.infrastructure.models import IncidentPhotoModel
from app.core.db import (
    Base,
    bind_session_to_tenant,
    async_session_factory,
    require_session_bound_to,
    tenant_scoped_classes,
)
from app.integrations.domain.storage import derive_signing_key
from app.tenants.domain.enums import StorageType
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel

# --- The demonstration tenant, by construction (D2) -------------------------------------
#
# Constants of the module, the same way `SEED_PROPERTIES`, `AIRBNB_PMS_ID` and
# `_CHECKLIST_ITEMS` are constants of `seed_demo.py`. Publishable by design: what has to stay
# out of the tree is the password, not who the accounts are.
#
# The domain is `.test`, which RFC 2606 reserves and no resolver answers. That is deliberate
# and it is not decoration: when SMTP arrives with `hardening-release`, mail to these four
# addresses will fail to resolve instead of reaching a stranger who happens to own the domain.

DEMO_TENANT_NAME = "AutoHostAI Demo"

#: The zone the dataset's dates are anchored on. PRD §27's environment is Madrid, and
#: `seed_demo.apply_plan` computes "today" on the tenant's calendar rather than UTC's — so this
#: is not decoration, it decides which day the demo shows.
DEMO_TENANT_TIMEZONE = "Europe/Madrid"

#: The tenant's country, converged for the reason `country` is easy to miss: nothing computes
#: from it, so it produces no refusal and no wrong dates — only a permanent defacement that no
#: reset would otherwise remove. PRD §27's environment is Spain.
DEMO_TENANT_COUNTRY = "ES"

DEMO_OWNER_EMAIL = "owner@demo.autohostai.test"
DEMO_MANAGER_EMAIL = "manager@demo.autohostai.test"
DEMO_CLEANER_EMAIL = "cleaner@demo.autohostai.test"
DEMO_TECHNICIAN_EMAIL = "technician@demo.autohostai.test"

DEMO_OWNER_NAME = "Propietaria Demo"
DEMO_MANAGER_NAME = "Gestora Demo"
DEMO_CLEANER_NAME = "Limpiadora Demo"
DEMO_TECHNICIAN_NAME = "Técnico Demo"

#: The four accounts this command owns, with the role each is declared to have. The converge
#: phase iterates THIS and restores every column of it, which is what R1.2 and R1.3 need: the
#: tuple says which accounts and what they are, the tenant check says which tenant (R2.4).
DEMO_ACCOUNTS = (
    (DEMO_OWNER_EMAIL, DEMO_OWNER_NAME, UserRole.TENANT_OWNER),
    (DEMO_MANAGER_EMAIL, DEMO_MANAGER_NAME, UserRole.PROPERTY_MANAGER),
    (DEMO_CLEANER_EMAIL, DEMO_CLEANER_NAME, UserRole.CLEANER),
    (DEMO_TECHNICIAN_EMAIL, DEMO_TECHNICIAN_NAME, UserRole.TECHNICIAN),
)

#: Just the addresses, derived so the two can never disagree.
DEMO_ACCOUNT_EMAILS = tuple(email for email, _, _ in DEMO_ACCOUNTS)

#: The tenant's billing address. Not one of the four accounts — `tenants.billing_email` is a
#: column of the tenant and not a login — so it gets its own name rather than borrowing the
#: owner's, which would make a row look like an account.
DEMO_BILLING_EMAIL = "billing@demo.autohostai.test"

#: The prefix of the line that carries the guest-portal URL, and a **contract with the workflow**
#: rather than a message. `.github/workflows/demo-reset.yml` greps stdout for it to publish the
#: link in the job summary, so an edit here silently stops the link being published — R4.3 would
#: fail with nothing turning red, which is exactly the producer/consumer seam that already hid a
#: defect once in this change. `tests/cli/test_demo_reset.py` pins the two together.
PORTAL_LINE_PREFIX = "guest portal for the active stay"

#: The phases this command declares, in order. They are the contract R3.4 and R5.5 name: every
#: failure reports the phase it happened in, and the scheduled workflow turns red saying which.
logger = logging.getLogger("app.auth")

PHASES = (
    "configuration",
    "refusal",
    "prepare",
    "bootstrap",
    "scope",
    "delete",
    "converge",
    "seed",
    "storage-sweep",
    "clear-lock",
)


class DemoResetConfigurationError(Exception):
    """`DEMO_ACCOUNT_PASSWORD` is missing or does not satisfy the password policy."""


class DemoResetRefusedError(Exception):
    """Proceeding would act on the environment's working tenant."""


class PhaseError(Exception):
    """An unexpected failure, attributed to the phase it happened in.

    Carries the phase and the failing exception's CLASS, never its detail. That parsimony is
    the whole point of the type: a SQLAlchemy error stringifies its statement together with its
    parameters, and among those parameters travels a bcrypt hash. R2.5 forbids emitting it, and
    an `except Exception as exc: print(exc)` would emit it in the one situation nobody is
    watching — a scheduled run at 03:15 writing to a public build log.
    """

    def __init__(self, phase: str, cause: BaseException) -> None:
        self.phase = phase
        self.cause_class = type(cause).__name__
        super().__init__(f"{phase}: failed with {self.cause_class}")


@dataclass(frozen=True, repr=False)
class DemoResetPlan:
    """Everything the run needs, resolved and validated before a transaction exists.

    Holds the two plans of the modules it composes rather than re-deriving their shape: what
    `bootstrap.apply_plan` and `seed_demo.apply_plan` accept is their business, and this
    command's job is to build those plans from ITS constants instead of from the environment.

    **`repr=False`, and it is not tidiness.** The generated `__repr__` would render the
    cleartext password five times — once here and once inside each nested `SeedUser` and
    `SeedAccount`, which carry their own copy. Nothing prints a plan today, but R2.5 forbids
    the password reaching "la salida del comando, sus logs", and the distance between here and
    a breach is one `logger.debug(f"{plan!r}")` somebody adds while chasing something else. A
    dataclass that cannot say it is a shorter distance than a rule that says it must not.
    """

    bootstrap: BootstrapPlan
    seed: SeedPlan
    password: str

    def __repr__(self) -> str:
        return (
            f"DemoResetPlan(tenant={DEMO_TENANT_NAME!r}, "
            f"accounts={len(DEMO_ACCOUNT_EMAILS)}, password=<withheld>)"
        )


def build_plan() -> DemoResetPlan:
    """Validates the configuration and composes the two plans (D3), before any transaction.

    It **builds** `BootstrapPlan` and `SeedPlan` directly instead of calling the `build_plan()`
    of those modules. That is not a shortcut: theirs read `BOOTSTRAP_*`/`SEED_*` from the
    environment, so they name the working tenant and the team's own addresses — exactly what
    this command must never touch.

    The one thing it does read from the environment besides the password is
    `BOOTSTRAP_STORAGE_TYPE`, which is not a tenant identity but the store the environment runs
    on: the deploy passes it inline (D14) so the demonstration tenant is born `S3` like its
    neighbour, and locally its `LOCAL` default is the right answer.
    """
    password = settings.demo_account_password
    if not password:
        raise DemoResetConfigurationError(
            "DEMO_ACCOUNT_PASSWORD is not set. Fill it in your .env — no default is shipped "
            "for it (see .env.example). In the deployed environment it comes from the OCI "
            "Vault secret autohostai-<env>-demo-account-password."
        )
    try:
        # The domain policy itself, not a length comparison of our own: below
        # PASSWORD_MIN_LENGTH the system would refuse to let a visitor set this same password
        # back through `POST /auth/change-password`, so the published credential would be
        # unrecoverable until the next scheduled reset (R2.3). The upper bound comes free and
        # matters too — past PASSWORD_MAX_BYTES bcrypt silently truncates, so the password that
        # gets published would not be the password that authenticates.
        assert_password_acceptable(password)
    except (PasswordPolicyError, PasswordTooLongError) as exc:
        # The domain messages state the rule and never the value, which is why they can be
        # forwarded verbatim. The variable name is prepended because the operator is looking
        # for something to edit, and the policy does not know what this one is called.
        raise DemoResetConfigurationError(
            f"DEMO_ACCOUNT_PASSWORD is not acceptable (value not echoed): {exc}. "
            f"It must be at least {PASSWORD_MIN_LENGTH} characters long."
        ) from exc

    return DemoResetPlan(
        bootstrap=BootstrapPlan(
            tenant_name=DEMO_TENANT_NAME,
            billing_email=normalize_email(DEMO_BILLING_EMAIL),
            storage_type=StorageType(settings.bootstrap_storage_type),
            users=(
                SeedUser(
                    name=DEMO_OWNER_NAME,
                    email=normalize_email(DEMO_OWNER_EMAIL),
                    password=password,
                    role=UserRole.TENANT_OWNER,
                ),
                SeedUser(
                    name=DEMO_MANAGER_NAME,
                    email=normalize_email(DEMO_MANAGER_EMAIL),
                    password=password,
                    role=UserRole.PROPERTY_MANAGER,
                ),
            ),
        ),
        seed=SeedPlan(
            tenant_name=DEMO_TENANT_NAME,
            accounts=(
                SeedAccount(
                    name=DEMO_CLEANER_NAME,
                    email=normalize_email(DEMO_CLEANER_EMAIL),
                    password=password,
                    role=UserRole.CLEANER,
                ),
                SeedAccount(
                    name=DEMO_TECHNICIAN_NAME,
                    email=normalize_email(DEMO_TECHNICIAN_EMAIL),
                    password=password,
                    role=UserRole.TECHNICIAN,
                ),
            ),
        ),
        password=password,
    )


def refuse_if_the_working_tenant_is_the_demo_tenant() -> None:
    """The second gate of D2, and the only one a constant cannot provide.

    Compared exactly rather than case-insensitively, because that is how the tenant is
    resolved: `bootstrap` and `seed_demo` look it up with `TenantModel.name == …`, so a
    differently-cased name IS a different row and refusing on it would refuse a run that was
    never in danger.
    """
    working = settings.bootstrap_tenant_name.strip()
    if working and working == DEMO_TENANT_NAME:
        raise DemoResetRefusedError(
            f"BOOTSTRAP_TENANT_NAME names {DEMO_TENANT_NAME!r}, which is the tenant this "
            "command deletes and re-seeds on every run. Nothing was written. Rename the "
            "working tenant, or run this against an environment where it is called something "
            "else."
        )


@dataclass(repr=False)
class DemoResetReport:
    """What the run did, in the only vocabulary the output is allowed to use.

    Counts per entity, the phases it went through, and any degradation it survived. **Never**
    the password, its hash or a session token (R2.5). `portal_url` is the single exception R2.5
    names and D19 bounds: the guest-portal link exists in cleartext exactly once, in the return
    of `IssueGuestAccessTokenUseCase`, so not emitting it is losing it — and with it R4.3.
    """

    phases: list[str]
    counts: dict[str, int]
    notes: list[str]
    portal_url: str | None = None

    #: Inputs to the two phases that run after the commit, not output. They live here because
    #: `apply_plan` is what can still see the rows they describe and `run` is what may act on
    #: them: the storage keys have to be read before the delete, and the converged ids exist
    #: only once the converge phase has run.
    storage_keys: tuple[str, ...] = ()
    converged_user_ids: list[uuid.UUID] = dataclasses.field(default_factory=list)
    tenant_id: uuid.UUID | None = None
    storage_type: StorageType = StorageType.LOCAL

    def __repr__(self) -> str:
        """Withholds `portal_url`, for the reason `DemoResetPlan` withholds the password.

        Demonstrated rather than feared: the security panel of section 6 triggered a test failure
        and captured this object's generated repr in the frame arguments, with a live cleartext
        token in it. `portal_url` is assigned outside any `_phase` and the report is then passed
        into the two post-commit phases, so any exception there renders it into whatever captures
        the traceback — a second channel, and R2.5's exception is bounded partly by there being
        "no hay otro canal".
        """
        return (
            f"DemoResetReport(phases={self.phases!r}, counts={self.counts!r}, "
            f"notes={len(self.notes)}, portal_url=<withheld>, "
            f"storage_keys={len(self.storage_keys)}, "
            f"converged_user_ids={len(self.converged_user_ids)}, "
            f"tenant_id={self.tenant_id!r}, storage_type={self.storage_type!r})"
        )


@asynccontextmanager
async def _phase(name: str, report: DemoResetReport) -> AsyncIterator[None]:
    """Record a phase, and attribute anything that escapes it to that phase.

    `PhaseError` passes through untouched so a nested phase keeps its own name rather than
    being relabelled by its caller.
    """
    report.phases.append(name)
    try:
        yield
    except PhaseError:
        raise
    except Exception as exc:
        raise PhaseError(name, exc) from exc


#: The four tables the reset does NOT empty, each for its own reason (D5) and not for comfort:
#:
#: - `tenants`: carries no `tenant_id`, is not a scoped class, and deleting it is provisioning
#:   again rather than resetting.
#: - `tenant_configs`: other modules assume a tenant always has its config, and
#:   `bootstrap.apply_plan` converges it (its D10).
#: - `users`: R2.2 requires the password to be **converged** on four accounts. If the reset
#:   deleted and recreated them, convergence would be a side effect of the delete rather than an
#:   operation, and R2.2 would stop being tested.
#: - `audit_logs`: R3.6. And keeping its rows is not enough on its own —
#:   `audit_logs.actor_user_id` is `ondelete="SET NULL"`, so deleting `users` would strip the
#:   record of its "who", which is half of why it exists. Keeping both is the same as keeping one.
PRESERVED_TABLES = frozenset({"tenants", "tenant_configs", "users", "audit_logs"})


def unscoped_children() -> dict[str, tuple[str, str]]:
    """The tables with no `tenant_id`, mapped to the parent that carries one (D6).

    The fifth declared limit of the listener in `app/core/db.py`: it cannot reach these, so they
    are deleted with `DELETE ... WHERE <fk> IN (SELECT id FROM <parent> WHERE tenant_id = :demo)`
    — the very pattern the rule already obliges their repositories to use.

    **Derived from the foreign keys rather than written down.** A literal table would be right
    today and wrong the next time somebody adds a child table, and it would be wrong at runtime
    against the public environment instead of in CI. The parent is the single foreign-key target
    that is tenant-scoped and not preserved: `users` is excluded because it is preserved, which
    is what disambiguates `messages.sender_user_id` from `messages.conversation_id` and
    `cleaning_photos.uploaded_by` from its `cleaning_task_id`.

    Raises if a table has no such parent or more than one, because either means a new table
    arrived and nobody decided how it gets cleaned. Failing here fails the coverage test in CI.
    """
    scoped = {model.__tablename__ for model in tenant_scoped_classes()}
    children: dict[str, tuple[str, str]] = {}
    for table in Base.metadata.sorted_tables:
        if table.name in scoped or table.name in PRESERVED_TABLES:
            continue
        candidates = [
            (key.parent.name, key.column.table.name)
            for key in table.foreign_keys
            if key.column.table.name in scoped and key.column.table.name not in PRESERVED_TABLES
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                f"table {table.name!r} has {len(candidates)} tenant-scoped parents "
                f"({sorted(name for _, name in candidates)}); the reset cannot decide how to "
                "scope its delete. Give it an explicit decision in `demo_reset.py`."
            )
        children[table.name] = candidates[0]
    return children


async def delete_the_tenants_rows(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
    """Empty the demonstration tenant, and nothing else (D4, D6).

    The scoped tables go through `sqlalchemy.delete(Model)` on the **ORM**, over a session
    already marked with `bind_session_to_tenant`, so the listener of `app/core/db.py` appends
    `tenant_id = <demo>` to each one. That is what turns R1.5 and R3.2 into a property of the
    isolation mechanism the project already has and already tests, instead of 27 hand-written
    `WHERE` clauses somebody has to review one at a time.

    The order is **derived** from `Base.metadata.sorted_tables` reversed — topological order of
    foreign keys, backwards — and not from a list. With 51 `RESTRICT` foreign keys a literal
    order breaks the next time a table is added, and it breaks at runtime against the public
    environment. Reversing also puts the unscoped children ahead of their parents for free,
    because that is exactly what "depends on" means in that ordering.

    Good consequence worth writing down: rows of `webhook_events` whose `tenant_id` is `NULL` —
    the ones §7.26 records without being able to attribute — fall **outside** this delete with no
    need to exclude them, because a marked session filters them to zero. Same fact
    `tests/test_tenant_filter.py::test_webhook_events_without_a_tenant_are_invisible_to_a_marked_session`
    already pins.
    """
    # The precondition, executable rather than documented (added after the security panel of
    # this section measured the emitted SQL). The 24 bulk deletes below take their `tenant_id`
    # predicate ENTIRELY from the session marker — `delete(GuestModel)` on an unmarked session
    # compiles to a bare `DELETE FROM guests`. So an unmarked session would not fail here, it
    # would empty those tables for **every tenant in the database**, while the four child
    # statements that carry their own `WHERE` stayed scoped, leaving the damage partial. And a
    # session marked to another tenant would split the delete across two. `tenant_id` is a
    # parameter, so nothing else in this function could notice either mistake.
    require_session_bound_to(session, tenant_id, write="the demo reset's delete phase")

    # The registry has to be COMPLETE before anything derived from it is trusted.
    # `tenant_scoped_classes()` reads `Base.registry.mappers`, which its own docstring says
    # "only grows as model modules get imported" — and the tenancy panel of this section
    # intermittently saw `unscoped_children()` raise because `reviews` was not mapped yet. That
    # direction is harmless (fail-closed, nothing deleted). The opposite one is not: a registry
    # missing a mapper makes this phase quietly skip that table, leaving a tenant with published
    # credentials holding rows nobody meant to keep — guest `document_number`, access codes,
    # WiFi passwords. So the two sources are cross-checked, because they are populated by the
    # same imports but are not the same object: `Base.metadata` knows the TABLE, the registry
    # knows the MAPPER, and only the second is what the loop iterates.
    declared = {
        table.name for table in Base.metadata.sorted_tables if "tenant_id" in table.c
    }
    mapped = {model.__tablename__ for model in tenant_scoped_classes()}
    if declared != mapped:
        raise RuntimeError(
            "the model registry is incomplete: "
            f"{sorted(declared - mapped)} have a tenant_id column but no mapper, and "
            f"{sorted(mapped - declared)} the reverse. Refusing to delete, because a missing "
            "mapper would silently leave that table's rows behind."
        )

    scoped = {model.__tablename__: model for model in tenant_scoped_classes()}
    children = unscoped_children()
    deleted: dict[str, int] = {}

    for table in reversed(Base.metadata.sorted_tables):
        if table.name in PRESERVED_TABLES:
            continue
        if table.name in children:
            foreign_key, parent = children[table.name]
            parent_table = Base.metadata.tables[parent]
            result = await session.execute(
                sqlalchemy_delete(table).where(
                    table.c[foreign_key].in_(
                        select(parent_table.c.id).where(parent_table.c.tenant_id == tenant_id)
                    )
                )
            )
        else:
            result = await session.execute(sqlalchemy_delete(scoped[table.name]))
        if result.rowcount:
            deleted[table.name] = result.rowcount

    # `users` is preserved as a TABLE (D5) but not as a free-for-all. The published
    # `TENANT_OWNER` credential carries `MANAGE_USERS`, so a visitor can `POST /users` and
    # leave behind an account with a password only they know — and accounts are deactivated,
    # never deleted, so nothing else ever reclaims it. That account would survive every reset,
    # against D5's own "lo que un visitante dejó abierto no debe sobrevivir al reset" and
    # against R3.3's "indistinguible del que produce un aprovisionamiento desde cero"; because
    # addresses are unique across the whole installation (ADR 0005), it would also permanently
    # squat whatever address it was given, including one a real colleague needs later.
    #
    # So the four constant addresses are preserved and everything else in this tenant goes.
    # It runs AFTER the loop on purpose: `cleaning_photos.uploaded_by` and
    # `incident_photos.uploaded_by` are `RESTRICT`, so the rows referencing these users have to
    # be gone first. Their `audit_logs` rows survive with `actor_user_id` set to NULL by the
    # column's own `ondelete`, which is the right trade: the record of what happened outlives
    # the throwaway identity that did it.
    visitors = await session.execute(
        sqlalchemy_delete(UserModel).where(
            UserModel.email.notin_([normalize_email(email) for email in DEMO_ACCOUNT_EMAILS])
        )
    )
    if visitors.rowcount:
        deleted["users"] = visitors.rowcount

    return deleted


async def converge_the_demo_passwords(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    password: str,
    hasher: BcryptPasswordHasher,
    *,
    now: datetime,
) -> list[uuid.UUID]:
    """R2.2: the password is **convergent**, not create-only — and R2.4 bounds where.

    Copies `app/cli/reset_password.py` step by step (D9), because what distinguishes this from
    an `UPDATE` by hand is exactly those steps: it goes through the entity, revokes the sessions,
    leaves an audit row, and (in `clear_login_locks`, after the commit) lifts the lockout.

    **What actually bounds this to the demonstration tenant, measured rather than assumed.**
    There are four layers, and the load-bearing one is not any of the three written below: the
    session is **marked**, so the listener of `app/core/db.py` appends `tenant_id = <demo>` to the
    ORM `UPDATE` that `apply_changes` emits, exactly as it does to the deletes. **Deleting** the
    scoped lookup, the explicit `users.get(tenant_id, …)` and the `tenant_id` handed to
    `apply_changes` — all three at once — leaves the suite green, because that fourth layer stops
    the write regardless.

    That is not the same as the checks being inert, and the distinction took a second measurement
    to find: **substituting** a foreign tenant id into either `users.get` or `apply_changes` reds
    four and five tests respectively. So the three are provably *active* — they execute and they
    decide — and merely not provably *protective*, because nothing can be made to produce a
    cross-tenant write: the marker, this phase's own `require_session_bound_to`, the global
    `uq_users_lower_email` index and `apply_changes`'s `rowcount != 1` guard each stop it
    independently. D18.1 was amended to record both halves.

    **Why it does not use `find_by_email_globally`.** That is what `reset_password` reaches for,
    but it requires an unmarked session and this one is marked — and being marked is better here,
    not a limitation to work around: the lookup below is scoped by the listener, so it
    **structurally cannot** return another tenant's row. `users.get(tenant_id, ...)` then carries
    the explicit tenant clause on top, which is R2.4's "comprobarlo en vez de confiarlo" — the
    check kept as a check even where the mechanism already makes it redundant. (This is the good
    consequence D10bis noted: resolving the seed's accounts before the mark is what freed this
    phase to read scoped.)

    **An address that is absent is not an error, and there are two ways it can be absent.**
    On a first run only the owner and the manager exist — `bootstrap.apply_plan` has just created
    them — and `seed_demo.apply_plan` creates the cleaner and the technician *after* this phase,
    with this same password, so they are born correct.

    The second way is a visitor: `email` is patchable by a `MANAGE_USERS` actor, which the
    published owner credential is, so all four addresses can be renamed. Then this phase finds
    nothing, converges nothing, and would report success — the same shape as the defect that put
    `status` and `role` in the write above. What heals it is the order of the phases rather than
    anything here: `bootstrap.apply_plan` re-creates a missing owner and manager, the delete
    phase's prune removes the renamed rows (their address is no longer one of the four), and the
    seed re-creates the cleaner and the technician. **That healing is a property of 5.1's
    composition, not of this function**, so this function reports what it did not find instead of
    asserting the four always exist — an earlier version of this docstring claimed they do,
    citing D5's preservation of `users`, and that was false.

    The one case this silence must never hide — an address of the four belonging to a
    **different** tenant — cannot arise: `uq_users_lower_email` is a **global** unique index, so
    "the neighbour owns this address" and "the demonstration tenant owns this account" are
    mutually exclusive states, and both `bootstrap.apply_plan` (`BootstrapConflictError`) and the
    seed's `_refuse_addresses_owned_by_another_tenant` refuse it upstream anyway, unmarked, where
    a global lookup is still possible.
    """
    require_session_bound_to(session, tenant_id, write="the demo reset's converge phase")

    users = SqlAlchemyUserRepository(session)
    audit = SqlAlchemyAuditLogRepository(session)
    sessions = SqlAlchemySessionRepository(session)

    converged: list[uuid.UUID] = []
    missing: list[str] = []
    for email, name, role in DEMO_ACCOUNTS:
        address = normalize_email(email)
        user_id = (
            await session.execute(select(UserModel.id).where(UserModel.email == address))
        ).scalar_one_or_none()
        if user_id is None:
            missing.append(address)
            continue
        user = await users.get(tenant_id, user_id)
        if user is None:  # pragma: no cover - the scoped lookup above already guarantees it
            missing.append(address)
            continue

        # `temporary=False` is R1.3: operational at once, no forced change. A visitor who has
        # to invent a new password on first login cannot use the credentials published to them.
        user.set_password_hash(await hasher.hash(password), temporary=False)
        written: dict[str, object] = {
            "password_hash": user.password_hash,
            "must_change_password": user.must_change_password,
        }
        record = ChangeSet(actions.ENTITY_USER).redacted("password")

        # Through the entity, which is what D9 asked for and what an earlier version of this
        # phase bypassed on a false premise: the reason recorded for the bypass was that
        # `GRANTABLE_ROLES` excludes `TENANT_OWNER`, and it does not — it is
        # `frozenset(UserRole) - {SUPER_ADMIN}`. With no actor the self-change guard never
        # fires either, so the entity methods work, and they hand back *whether* the value
        # moved — which is exactly what the audit diff below needs.
        previous_role, previous_status = user.role, user.status
        if user.change_role(role, actor_user_id=None):
            written["role"] = user.role
            record = record.diff("role", previous_role, user.role)
        if user.change_status(UserStatus.ACTIVE, actor_user_id=None):
            written["status"] = user.status
            record = record.diff("status", previous_status, user.status)

        # `name` and `phone` are not cosmetic here, they are the only durable defacement
        # channel in the tenant. `PATCH /users/{id}` accepts both from a `MANAGE_USERS` actor
        # — which the published owner credential is — and these four rows are the ONLY
        # visitor-writable content the reset preserves; everything else is emptied by the
        # delete phase. Without restoring them, a visitor renames the demo owner to a phishing
        # string once and no reset ever removes it (R3.3).
        before = {"name": user.name, "phone": user.phone}
        for field in user.update_profile(name=name, phone=None):
            written[field] = getattr(user, field)
            record = record.diff(field, before[field], getattr(user, field))

        await users.apply_changes(tenant_id, user.id, written)
        await audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                # A role change gets its own action, so rule 9 of `steering/security.md`
                # («AuditLog para … roles de User») is satisfied by an indexed `action` filter
                # rather than a JSONB query — the same choice `user_admin.py` makes. Otherwise
                # the row records what it primarily is: a password reset.
                action=(
                    actions.USER_ROLE_CHANGED
                    if "role" in written
                    else actions.USER_PASSWORD_RESET
                ),
                entity_type=actions.ENTITY_USER,
                entity_id=user.id,
                # No actor, like `reset_password` and the rows of `pms-provider-resolution`: a
                # command line has no identity to record, and `actor_ip` has no request.
                actor_user_id=None,
                actor_ip=None,
                changes=record,
                now=now,
            ),
        )
        # A convergence that left the previous visitor's sessions alive would not have restored
        # the account, it would have added a credential to it.
        await sessions.revoke_all_for_user(
            tenant_id, user.id, SessionRevokedReason.PASSWORD_RESET, now
        )
        converged.append(user.id)

    if missing:
        logger.info("demo_reset.accounts_not_yet_present", extra={"count": len(missing)})

    return converged


async def clear_login_locks(user_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Lift the login lockout for the converged accounts. Never raises (D9.5).

    Runs **after** the commit and outside the transaction, which is what `reset_password.clear_lock`
    documents and for the same reason: Redis and Postgres share no transaction, so one has to be
    able to fail alone. A lock that expires by itself within the lockout window, over an account
    whose password has already been converged, is the benign degradation; a reset that reported
    failure after committing is not.

    **The accepted limit here is not the one D9 clause 5 claimed.** That clause said the
    ten-failure block "stops being permanent", and it never was permanent: `RedisLoginThrottle`
    sets `login:lock:<uid>` with a TTL of `login_lockout_minutes` (15 by default), so it clears
    itself and this call only clears it sooner. The real limit, which no decision had named: the
    four addresses are publishable constants, so **anyone on the internet** can lock all four
    demonstration accounts for fifteen minutes with about forty failed logins, and repeat that
    indefinitely. The daily reset mitigates nothing there. It is availability only, bounded to the
    demonstration tenant, and accepted — but accepted explicitly rather than by omission.

    Each account is cleared independently, and that is what the loop's own `try` buys: wrapping
    the whole loop once made a single unreachable Redis report **every** id as uncleared,
    including the ones already cleared before the failure. `reset_password.clear_lock` reports per
    account, and a degradation note that overstates what it failed to do is a worse note.

    Returns the ids it could **not** clear, so the caller can report a degradation without
    turning the run red.
    """
    try:
        throttle = RedisLoginThrottle(
            get_redis(),
            attempts_per_minute=settings.login_rate_limit_per_minute,
            max_failures=settings.login_max_failed_attempts,
            lockout_minutes=settings.login_lockout_minutes,
        )
    except Exception:
        logger.warning("demo_reset.login_locks_not_cleared", extra={"count": len(user_ids)})
        return list(user_ids)

    uncleared: list[uuid.UUID] = []
    for user_id in user_ids:
        try:
            await throttle.clear_account_lock(user_id)
        except Exception:
            logger.warning("demo_reset.login_lock_not_cleared", extra={"user_id": str(user_id)})
            uncleared.append(user_id)
    return uncleared


def _now() -> datetime:
    """One clock for the whole run, read per phase like `reset_password._now` does.

    Not a single timestamp captured at the top: the seed anchors the dataset to the tenant's
    calendar day and takes its own `now`, so pinning one value here would only pretend the
    phases are simultaneous when they are not.
    """
    return datetime.now(UTC)


def storage_key_columns() -> dict[str, str]:
    """Every column in the schema that holds an object key, as `{table: column}`.

    **Derived, not written down**, for the same reason `unscoped_children()` is: the row-deletion
    phase already learned this lesson, and a hardcoded pair is right until it is not. The tenancy
    panel of this section found the third one — `expenses.receipt_storage_key`, which D16 never
    named — dead today because `app/statements/` has no application layer or router, and
    therefore exactly the kind of gap that would orphan objects in the shared bucket in silence
    the day `revenue-statements` gives it a writer. Deriving it means that day needs no change
    here, and the test that pins this set by value is what makes a new one somebody's decision
    instead of a silent omission (R3.5).
    """
    return {
        table.name: column.name
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if "storage_key" in column.name
    }


async def collect_storage_keys(session: AsyncSession, tenant_id: uuid.UUID) -> tuple[str, ...]:
    """The object keys the delete is about to orphan, read **before** it runs (D16).

    The rows hold the only copy of these keys, so after the delete they are unrecoverable —
    which is why this is a separate step in the caller rather than a return value of the delete.

    **The guard is not ceremony here, it is the difference between a leak and a demolition.**
    Its siblings `delete_the_tenants_rows` and `converge_the_demo_passwords` both refuse a session
    that is not bound to the tenant they were given; this one did not, and the tenancy panel of
    this section proved what that costs by calling it on an unmarked session: it returned a
    **neighbour's** `incident_photos` key, which would have gone straight into
    `FileStoragePort.delete`. A Postgres mistake in this change rolls back; an object store delete
    does not.

    Tables with no `tenant_id` are read through their scoped parent, and tables that have one are
    read directly and scoped by the marker. `cleaning_photos` is the first kind (the listener's
    fifth limit, D6) and `incident_photos` the second — getting that backwards is the cross-tenant
    read above, not a style question.
    """
    require_session_bound_to(
        session, tenant_id, write="the demo reset's storage-key collection"
    )

    children = unscoped_children()
    keys: list[str] = []
    for table_name, column_name in sorted(storage_key_columns().items()):
        table = Base.metadata.tables[table_name]
        column = table.c[column_name]
        if table_name in children:
            foreign_key, parent = children[table_name]
            parent_table = Base.metadata.tables[parent]
            statement = select(column).where(
                table.c[foreign_key].in_(
                    select(parent_table.c.id).where(parent_table.c.tenant_id == tenant_id)
                )
            )
        elif "tenant_id" in table.c:
            # Explicit, even though the marker would supply it: this is the read that feeds an
            # irreversible delete, so it does not rely on a listener staying wired.
            statement = select(column).where(table.c.tenant_id == tenant_id)
        else:  # pragma: no cover - `storage_key_columns` finds nothing else today
            raise RuntimeError(
                f"{table_name}.{column_name} holds an object key but the table is neither "
                "tenant-scoped nor a known child, so the sweep cannot scope it. Decide "
                "explicitly in `demo_reset.py`."
            )
        keys.extend(key for key in (await session.execute(statement)).scalars().all() if key)
    return tuple(keys)


async def sweep_storage(
    keys: tuple[str, ...], tenant_id: uuid.UUID, storage_type: StorageType
) -> list[str]:
    """Delete the orphaned objects, after the commit, and never fail the run (D16).

    The order is the point: deleting objects *before* the commit would, if anything rolled back,
    leave live rows pointing at objects that no longer exist — a worse state than the one being
    avoided. So this runs once the database is already consistent, and a failure of the store is
    reported rather than raised: saying the reset failed would be false.

    R3.5 only asks to *report* the orphans. They are deleted as well because this command runs
    daily: six photos per run that nobody collects is roughly 2,200 a year in `dev`'s bucket, and
    a scheduled job that leaks objects for ever is an operational defect rather than an accepted
    asymmetry.

    **It re-checks the prefix of every key, and that is not redundant with the scoped reads.**
    The bucket is shared by every tenant of the environment and has no tenant filter of its own,
    so this loop is the last thing between a query result and an irreversible delete. The prefix
    is a real invariant **for the two photo tables**, and not a naming habit: `_photo_storage_key`
    is the single private function both public key builders funnel through, and it is the only
    producer of those values. Checking it here means a future scoping regression upstream costs a
    skipped key and a line in the report instead of a neighbour's photos.

    It is **not** established for `expenses.receipt_storage_key`, which has no writer yet
    (`app/statements/` has no application layer), so nothing guarantees a future receipt key will
    use this prefix. If it does not, a legitimate object would be refused and this note would
    blame "a scoped read upstream" that never happened — wrong, but wrong in the safe direction:
    nothing is deleted and the key is still named, so R3.5's report survives. Whoever gives that
    column a writer owns making the prefix true or teaching this check about it.

    On naming the keys in the output: this does **not** invoke rule 5's named exception, which is
    about the value of an S3 presigned URL and, as `seed-data-demo-extension` put it when it
    declined to invoke it too, "es de otra cosa". Rule 5's prohibition is bounded to the response
    surface and does not reach logs; a CLI's stderr is not a response surface, and these keys are
    composed only of identifiers the system generated itself.
    """
    if not keys:
        return []

    prefix = f"tenants/{tenant_id}/"
    mine = [key for key in keys if key.startswith(prefix)]
    notes: list[str] = []
    if len(mine) != len(keys):
        foreign = sorted(set(keys) - set(mine))
        notes.append(
            f"storage-sweep: REFUSED {len(foreign)} key(s) outside {prefix} — "
            + ", ".join(foreign)
            + ". This means a scoped read upstream returned another tenant's rows; nothing was "
            "deleted for them."
        )

    factory = ConfiguredFileStorageFactory(
        signing_key=derive_signing_key(settings.jwt_secret_key),
        s3_bucket=settings.s3_bucket,
    )
    try:
        storage = factory.storage_for(storage_type)
    except Exception as exc:  # noqa: BLE001
        notes.append(
            f"storage-sweep: skipped {len(mine)} object(s) — no usable store "
            f"({type(exc).__name__}). They are orphaned in whatever store holds them."
        )
        return notes

    failed: list[str] = []
    for key in mine:
        try:
            await storage.delete(key)
        except Exception:  # noqa: BLE001
            failed.append(key)

    notes.append(f"storage-sweep: deleted {len(mine) - len(failed)} of {len(mine)} object(s)")
    if failed:
        notes.append("storage-sweep: could not delete " + ", ".join(sorted(failed)))
    return notes


async def refuse_a_tenant_that_only_shares_the_name(session: AsyncSession) -> None:
    """Prove the row is OUR tenant before writing to it. `tenants.name` is not unique.

    D2 rests the whole safety argument on a constant name, and a name is a weaker identity than
    it looks: `tenants` has no uniqueness on `name` — `bootstrap.py` says so itself about the
    typo case — and both `bootstrap.apply_plan` and `seed_demo.apply_plan` resolve their tenant
    with `TenantModel.name == …`. So a row that merely *happens* to be called "AutoHostAI Demo"
    would be **adopted**, not created: its `tenant_configs` row would be converged, two accounts
    carrying the internet-published password would be inserted into it, and the delete phase of
    section 3 would later wipe it. R1.5 says no row of anyone else's tenant may be modified in
    any phase, and the second gate of D2 cannot cover this — in the deployed environment
    `BOOTSTRAP_TENANT_NAME` is absent, so it compares against the empty string.

    On the first run there is no row and there is nothing to prove: `bootstrap.apply_plan`
    creates it with `DEMO_BILLING_EMAIL`, which is what makes the address usable as the mark on
    every run after that.

    Read on an UNMARKED session, and `tenants` carries no `tenant_id`, so the listener of
    `app/core/db.py` neither scopes this statement nor needs to.
    """
    tenant = (
        await session.execute(select(TenantModel).where(TenantModel.name == DEMO_TENANT_NAME))
    ).scalar_one_or_none()
    if tenant is None:
        return
    if tenant.billing_email != normalize_email(DEMO_BILLING_EMAIL):
        raise DemoResetRefusedError(
            f"a tenant named {DEMO_TENANT_NAME!r} already exists and is not the demonstration "
            f"tenant: its billing address is not {DEMO_BILLING_EMAIL}. `tenants.name` is not "
            "unique, so this command will not adopt a row it cannot identify — it would write "
            "published credentials into somebody else's tenant and delete it on the next run. "
            "Nothing was written."
        )


async def apply_plan(
    session: AsyncSession, plan: DemoResetPlan, hasher: BcryptPasswordHasher
) -> DemoResetReport:
    """The phases that write, in the order D7 fixes.

    Takes the session and the hasher rather than building them — the same split
    `app.cli.bootstrap` and `app.cli.reset_password` use, and for the same reason: it is what
    lets this run against the test database instead of a developer's dev stack.

    `bootstrap.apply_plan` goes FIRST and in a transaction of its own, because it commits on
    its own account (D7). On a reset it is a no-op that writes nothing; the first time, it is
    what creates the tenant, its config and the two administrative accounts.

    **Every step is inside a declared phase**, and that is not tidiness: R5.5 promises the
    scheduled workflow turns red "nombrando la fase que falló", and an earlier version left the
    whole stretch between `bootstrap` and `delete` un-phased — so a failure there reported only
    "outside any phase", which is the one thing that promise rules out. The security panel of
    this section counted three failure sources in that gap.
    """
    report = DemoResetReport(phases=["configuration", "refusal"], counts={}, notes=[])

    # Outside any `_phase`, deliberately: `_phase` turns everything it catches into a
    # `PhaseError` and therefore into exit 2, and this is a refusal — exit 1, nothing written.
    await refuse_a_tenant_that_only_shares_the_name(session)

    async with _phase("prepare", report):
        # The store is read HERE, before `bootstrap.apply_plan` runs, and that placement is the
        # whole point of the read. `bootstrap.apply_plan` converges `tenant_configs.storage_type`
        # to `BOOTSTRAP_STORAGE_TYPE` **and commits** — so reading it afterwards returns the
        # environment value by another route, which is exactly what an earlier version of this
        # code did while claiming otherwise. What the sweep needs is the store the objects it is
        # about to orphan were actually WRITTEN under, and that is the value as it stands now.
        #
        # A first run has no tenant and no objects, so `LOCAL` here is a value nothing uses.
        existing = (
            await session.execute(
                select(TenantModel).where(TenantModel.name == DEMO_TENANT_NAME)
            )
        ).scalar_one_or_none()
        storage_type = StorageType.LOCAL
        if existing is not None:
            storage_type = (
                await session.execute(
                    select(TenantConfigModel.storage_type).where(
                        TenantConfigModel.tenant_id == existing.id
                    )
                )
            ).scalar_one_or_none() or StorageType.LOCAL

    async with _phase("bootstrap", report):
        report.counts.update(await bootstrap.apply_plan(session, plan.bootstrap, hasher))

    async with _phase("scope", report):
        tenant = (
            await session.execute(
                select(TenantModel).where(TenantModel.name == DEMO_TENANT_NAME)
            )
        ).scalar_one()

        # The population lock, taken ONCE here and not inside `converge` — where it was first
        # put, and where the security panel of section 4 spotted it as a lock-order inversion:
        # the delete phase takes row locks on `users` before `converge` would ask for the
        # `tenants` lock, while `user_admin` takes the tenant lock first, so a concurrent `PATCH`
        # could deadlock the reset and Postgres would abort one of the two. Taken at the head of
        # the transaction, the order matches the interactive path's and the inversion disappears.
        await SqlAlchemyUserRepository(session).lock_tenant_for_admin(tenant.id)

        # The unscoped read hoisted out of the seed (D10bis), while the session is still
        # unmarked. This is the line that lets D4 (a marked delete), D7 (one transaction) and
        # D10 (reuse the seed as it is) all hold at once — without it, marking for the delete
        # makes the seed raise.
        known_accounts = await seed_demo.resolve_known_accounts(session, plan.seed)

        # From here the session is marked, and it is what scopes the bulk deletes of the delete
        # phase and the writes of the converge phase. `seed_demo.apply_plan` binds it again to
        # the same tenant further down, which is a no-op.
        bind_session_to_tenant(session, tenant.id)

        # Collected BEFORE the rows go, because the rows hold the only copy of the keys (D16).
        # The sweep itself runs after the commit; this is only the reading.
        storage_keys = await collect_storage_keys(session, tenant.id)

        # The two `tenants` columns that must be converged, and the criterion is which way they
        # fail. `timezone` decides the day `seed_demo` anchors the WHOLE dataset to, so a visitor
        # who moves it makes every later reset date the demo to a day a fresh provisioning never
        # would — it fails **wrong**, silently, reported as success. `country` computes nothing
        # at all, which is precisely why it needs converging too: no refusal, no wrong dates,
        # just a permanent visible defacement that no reset removes (R3.3) — the same class as
        # `users.name`/`phone`. Both found by the QA panel of this section, the second by
        # attacking the criterion the first one established.
        #
        # `billing_email` and `name` are deliberately NOT converged, and they are the other side
        # of that criterion: both fail **closed** and visibly. `billing_email` makes the identity
        # guard refuse (exit 1, nothing written); a renamed tenant makes `bootstrap.apply_plan`
        # raise `BootstrapConflictError` on the global email uniqueness (exit 2, nothing
        # committed) — measured, not assumed. Accepted limits, documented in Risks and task 10.1.
        for column, wanted in (
            ("timezone", DEMO_TENANT_TIMEZONE),
            ("country", DEMO_TENANT_COUNTRY),
        ):
            # Read BEFORE the write. An earlier version formatted this note after assigning, so
            # it reported the value it had just written as the value it "was" — always the
            # constant, never what a visitor had set, which is the one thing the note exists to
            # tell an operator.
            previous = getattr(tenant, column)
            if previous != wanted:
                setattr(tenant, column, wanted)
                report.notes.append(
                    f"tenant {column} was {previous!r}; restored to {wanted!r}"
                )
        await session.flush()

    async with _phase("delete", report):
        report.counts.update(await delete_the_tenants_rows(session, tenant.id))

    async with _phase("converge", report):
        report.converged_user_ids = await converge_the_demo_passwords(
            session, tenant.id, plan.password, hasher, now=_now()
        )

    # `seed_demo.apply_plan` ends with the single `commit` of this whole transaction (D7), so
    # nothing may write after it: a later statement would open a second transaction and R3.4's
    # "no partial changes" would stop being a property of the composition.
    async with _phase("seed", report):
        # `portal_links` is the whole delivery mechanism of R4.3, and an earlier version of this
        # call omitted it — so the seed minted the token, appended the URL to a list nobody
        # held, and `report.portal_url` stayed `None` for ever. The print in `main()` was
        # therefore dead code, and the requirement that motivated carving out R2.5's single
        # named exception (D19) was not delivered by the one command meant to run it. The
        # cleartext exists exactly once, in that list; there is no second chance to read it.
        portal_links: list[str] = []
        seeded = await seed_demo.apply_plan(
            session,
            plan.seed,
            hasher,
            now=_now(),
            known_accounts=known_accounts,
            portal_links=portal_links,
        )
    report.portal_url = portal_links[0] if portal_links else None
    report.counts.update({f"seed_{name}": count for name, count in seeded.items()})
    report.storage_keys = storage_keys
    report.tenant_id = tenant.id
    report.storage_type = storage_type

    return report


async def run(plan: DemoResetPlan) -> DemoResetReport:
    """Open a session, run the writing phases, then the two that must outlive the commit.

    `storage-sweep` (D16) and `clear-lock` (D9.5) run **after** the transaction and cannot fail
    the command: the object store and Redis share no transaction with Postgres, so a failure
    there happens over a database that is already consistent, and reporting the reset as failed
    would be a lie. They degrade with a note instead.
    """
    hasher = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)
    async with async_session_factory() as session:
        report = await apply_plan(session, plan, hasher)

    # Everything below is past the commit, and none of it may turn the run red (D16, D9.5).
    async with _phase("storage-sweep", report):
        report.notes.extend(
            await sweep_storage(
                report.storage_keys, report.tenant_id, report.storage_type
            )
        )

    async with _phase("clear-lock", report):
        uncleared = await clear_login_locks(report.converged_user_ids)
        if uncleared:
            report.notes.append(
                f"the login lockout of {len(uncleared)} account(s) could not be cleared "
                "(Redis unreachable). The reset itself succeeded; the lock expires on its own "
                "within the lockout window."
            )

    return report


def main() -> int:
    """Exit codes are the contract (D15): 0 done, 1 nothing written, 2 unexpected.

    The split between 1 and 2 is what the scheduled workflow reads: a 1 is an operator's
    problem — a missing variable, a tenant named after the demo — and nothing was written; a 2
    is a failure inside a phase, and the phase is named so the run can be diagnosed without
    the log carrying anything it must not carry.
    """
    try:
        plan = build_plan()
        refuse_if_the_working_tenant_is_the_demo_tenant()
        report = asyncio.run(run(plan))
    except DemoResetConfigurationError as exc:
        print(f"demo_reset: configuration: {exc}", file=sys.stderr)
        return 1
    except DemoResetRefusedError as exc:
        print(f"demo_reset: refusal: refusing to continue — {exc}", file=sys.stderr)
        return 1
    except PhaseError as exc:
        # Only the exception's CLASS. See `PhaseError`: the detail of a database error carries
        # the statement together with its parameters, and one of those is a bcrypt hash.
        print(
            f"demo_reset: {exc.phase}: failed with {exc.cause_class} (detail withheld on "
            "purpose — it would carry the statement and its parameters)",
            file=sys.stderr,
        )
        return 2
    except BaseException as exc:  # noqa: BLE001
        # The same catch-all `seed_demo.main()` keeps, and for the same reason. Without it,
        # anything raised OUTSIDE a `_phase` — building the hasher, entering or leaving the
        # session, a rollback that fails while a `PhaseError` is already propagating — escapes
        # as a traceback that prints the whole `__cause__` chain. The original SQLAlchemy error
        # is in that chain, and its `__str__` appends `[SQL: …] [parameters: (…)]` with the
        # bcrypt hashes this command just wrote. R2.5 and R5.5 forbid exactly that string, and
        # an escape would also exit 1 — the code D15 reserves for "nothing was written".
        #
        # `BaseException` and not `Exception`, which is wider than the precedent on purpose:
        # `KeyboardInterrupt` and `asyncio.CancelledError` are the ones that arrive on a
        # cancelled or timed-out scheduled run, and if one lands while a DBAPI error is already
        # in flight the interpreter prints the whole `__context__` chain — the `[SQL: …]
        # [parameters: (…)]` string with the hash in it. R5.5 says "sin volcar el detalle de una
        # excepción de base de datos" without carving out the interrupted case, and an operator
        # who pressed Ctrl-C still learns what happened from the class name.
        print(
            f"demo_reset: failed with {type(exc).__name__} outside any phase (detail withheld "
            "on purpose — it would carry the statement and its parameters)",
            file=sys.stderr,
        )
        return 2

    print(f"demo_reset: phases {' → '.join(report.phases)}")
    if report.counts:
        print(
            "demo_reset: "
            + ", ".join(f"{name}={count}" for name, count in sorted(report.counts.items()))
        )
    for note in report.notes:
        print(f"demo_reset: {note}", file=sys.stderr)
    if report.portal_url is not None:
        print(f"demo_reset: {PORTAL_LINE_PREFIX}: {report.portal_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
