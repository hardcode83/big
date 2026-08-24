"""Creates the initial tenant and its first two users (R7, design D14).

Run with `make bootstrap`, or `python -m app.cli.bootstrap` inside the container.

Deliberately NOT an Alembic data migration: that would mix schema with content, could
not be parameterised per environment, and cannot be safely re-run. It is also NOT
hooked into `make up`, so the local stack still starts with no manual steps.

The product has no public sign-up — the owner and the manager are two real people —
so this is the only way into a freshly deployed environment.
"""

import asyncio
import sys
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.models_registry  # noqa: F401
from app.auth.domain.enums import UserRole
from app.auth.domain.value_objects import normalize_email
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.core.config import settings
from app.core.db import async_session_factory
from app.tenants.domain.enums import StorageType
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel


class BootstrapConfigurationError(Exception):
    """A required BOOTSTRAP_* variable is missing."""


class BootstrapConflictError(Exception):
    """Proceeding would leave existing accounts unable to log in."""


@dataclass(frozen=True)
class SeedUser:
    name: str
    email: str
    # `repr=False` (change `demo-user`): the generated `__repr__` rendered this in cleartext,
    # so any `logger.debug(f"{plan!r}")` — or a pytest assertion failure that happened to embed
    # a plan in its diff — printed a real user password. No caller does that today, which is
    # exactly the state in which it is cheap to close. It matters most for the demonstration
    # tenant, whose password `demo-user` R2.5 forbids emitting anywhere, but the reasoning is
    # not specific to it: none of these passwords should be printable by accident.
    password: str = field(repr=False)
    role: UserRole


@dataclass(frozen=True)
class BootstrapPlan:
    tenant_name: str
    billing_email: str
    storage_type: StorageType
    users: tuple[SeedUser, ...]


def build_plan() -> BootstrapPlan:
    """Validates everything BEFORE any transaction is opened (R7.3).

    Reporting every missing variable at once, rather than one per run, because the
    operator is filling in a `.env` and wants the whole list.
    """
    required = {
        "BOOTSTRAP_TENANT_NAME": settings.bootstrap_tenant_name,
        "BOOTSTRAP_TENANT_BILLING_EMAIL": settings.bootstrap_tenant_billing_email,
        "BOOTSTRAP_OWNER_NAME": settings.bootstrap_owner_name,
        "BOOTSTRAP_OWNER_EMAIL": settings.bootstrap_owner_email,
        "BOOTSTRAP_OWNER_PASSWORD": settings.bootstrap_owner_password,
        "BOOTSTRAP_MANAGER_NAME": settings.bootstrap_manager_name,
        "BOOTSTRAP_MANAGER_EMAIL": settings.bootstrap_manager_email,
        "BOOTSTRAP_MANAGER_PASSWORD": settings.bootstrap_manager_password,
    }
    missing = sorted(name for name, value in required.items() if not value.strip())
    if missing:
        raise BootstrapConfigurationError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return BootstrapPlan(
        tenant_name=settings.bootstrap_tenant_name.strip(),
        billing_email=normalize_email(settings.bootstrap_tenant_billing_email),
        # Not in `required` above: unlike the eight names there it ships a working default
        # (`LOCAL`), and `Settings` has already refused any value outside the enum, so by here
        # it can only be a member.
        storage_type=StorageType(settings.bootstrap_storage_type),
        users=(
            SeedUser(
                name=settings.bootstrap_owner_name.strip(),
                # Normalised here as well as in the repository (design D19): stored
                # mixed-case, the login lookup would never match and the only
                # administrative account of a fresh deployment could not get in.
                email=normalize_email(settings.bootstrap_owner_email),
                password=settings.bootstrap_owner_password,
                role=UserRole.TENANT_OWNER,
            ),
            SeedUser(
                name=settings.bootstrap_manager_name.strip(),
                email=normalize_email(settings.bootstrap_manager_email),
                password=settings.bootstrap_manager_password,
                role=UserRole.PROPERTY_MANAGER,
            ),
        ),
    )


async def apply_plan(session: AsyncSession, plan: BootstrapPlan, hasher: BcryptPasswordHasher) -> dict[str, int]:
    """Convergent: a second run leaves the state the configuration declares (R7.2, D10).

    It used to be described as *idempotent* — "a second run changes nothing" — and that stopped
    being the whole truth with `object-storage-provisioning`: `storage_type` is applied on
    creation **and updated when it differs**, because in `dev` the tenant and its config already
    exist, so a create-only setting would never arrive without a hand-written `UPDATE` — exactly
    what the IaC-first norm and R1.5 refuse. Everything else is still create-only, so a re-run
    with an unchanged configuration is still a no-op.
    """
    created = {"tenants": 0, "tenant_configs": 0, "tenant_configs_converged": 0, "users": 0}
    users = SqlAlchemyUserRepository(session)

    tenant = (
        await session.execute(select(TenantModel).where(TenantModel.name == plan.tenant_name))
    ).scalar_one_or_none()
    if tenant is None:
        tenant = TenantModel(
            id=uuid.uuid4(), name=plan.tenant_name, billing_email=plan.billing_email
        )
        session.add(tenant)
        await session.flush()
        created["tenants"] = 1

    config = (
        await session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant.id)
        )
    ).scalar_one_or_none()
    if config is None:
        # Other modules assume a tenant always has its config.
        session.add(
            TenantConfigModel(
                id=uuid.uuid4(), tenant_id=tenant.id, storage_type=plan.storage_type
            )
        )
        created["tenant_configs"] = 1
    elif config.storage_type is not plan.storage_type:
        # The convergence half of D10, and the only field this CLI updates. It is what makes
        # `BOOTSTRAP_STORAGE_TYPE` reach an environment whose tenant was seeded long ago.
        config.storage_type = plan.storage_type
        created["tenant_configs_converged"] = 1

    for seed in plan.users:
        # One global lookup answers both questions, because a normalised email is
        # unique across the whole installation now (design D16, ADR 0005): if the
        # address exists at all, either it is ours — a re-run, skip it — or it belongs
        # to another tenant, which must not proceed.
        #
        # `uq_users_lower_email` would refuse the INSERT anyway, so this check is about
        # the MESSAGE, not the invariant: what a re-run after a typo in
        # BOOTSTRAP_TENANT_NAME gets is an explanation naming the variable to look at,
        # instead of an IntegrityError mentioning an index nobody has heard of.
        # Idempotency keys on the tenant NAME, and `tenants` has no uniqueness on it,
        # so that typo creates a second tenant and then tries these same addresses.
        #
        # Deliberately through the PORT rather than a raw cross-tenant select: an unscoped
        # query is something the system accounts for one by one, and a hand-rolled one here
        # would add to that list without appearing in it. The list is not prose: the reads that
        # resolve a tenant out of the row call `require_unmarked_session` (`app/core/db.py`), and
        # `tests/test_unscoped_reads.py` asserts that set is exactly the declared one — no count
        # here, deliberately: every prose copy of that number has been wrong, this one included
        # when it said four. The test holds it; read it there. It also names the
        # unmarked-session reads that fall outside that census.
        #
        # This comment used to say the audit was grep-based, over the two `*_globally` names.
        # `guest-portal-api` added a third unscoped query that carries neither name, so the
        # grep stopped being exhaustive; it then named one docstring as the home of the
        # enumeration, and that went stale too. A test cannot.
        existing = await users.find_by_email_globally(seed.email)
        if existing is not None and existing.tenant_id != tenant.id:
            raise BootstrapConflictError(
                f"The address of {seed.role.value} already exists under another tenant. "
                "Emails are unique across the whole installation, so this address cannot "
                "be bootstrapped again here. Check BOOTSTRAP_TENANT_NAME."
            )
        if existing is not None:
            continue
        session.add(
            UserModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                name=seed.name,
                email=seed.email,
                password_hash=await hasher.hash(seed.password),
                role=seed.role,
            )
        )
        created["users"] += 1

    await session.commit()
    return created


async def run() -> dict[str, int]:
    plan = build_plan()
    hasher = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)
    async with async_session_factory() as session:
        return await apply_plan(session, plan, hasher)


def main() -> int:
    try:
        created = asyncio.run(run())
    except BootstrapConfigurationError as exc:
        print(f"bootstrap: {exc}", file=sys.stderr)
        print(
            "bootstrap: fill them in your .env — no defaults are shipped for user "
            "passwords (see .env.example).",
            file=sys.stderr,
        )
        return 1
    except BootstrapConflictError as exc:
        print(f"bootstrap: refusing to continue — {exc}", file=sys.stderr)
        return 1
    # Counts, never the credentials. The converged count is reported separately from the
    # created one because a re-run that only moves `storage_type` creates nothing, and a line
    # saying "created 0 config(s)" would read as "did nothing" when it did the one thing asked.
    print(
        "bootstrap: created "
        f"{created['tenants']} tenant(s), {created['tenant_configs']} config(s), "
        f"{created['users']} user(s); converged "
        f"{created['tenant_configs_converged']} config(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
