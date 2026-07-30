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
from dataclasses import dataclass

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
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel


class BootstrapConfigurationError(Exception):
    """A required BOOTSTRAP_* variable is missing."""


class BootstrapConflictError(Exception):
    """Proceeding would leave existing accounts unable to log in."""


@dataclass(frozen=True)
class SeedUser:
    name: str
    email: str
    password: str
    role: UserRole


@dataclass(frozen=True)
class BootstrapPlan:
    tenant_name: str
    billing_email: str
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
    """Idempotent: a second run over an initialised database changes nothing (R7.2)."""
    created = {"tenants": 0, "tenant_configs": 0, "users": 0}
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
        session.add(TenantConfigModel(id=uuid.uuid4(), tenant_id=tenant.id))
        created["tenant_configs"] = 1

    for seed in plan.users:
        # Checked ACROSS tenants before writing, and this is not belt-and-braces.
        # Idempotency keys on the tenant NAME, and `tenants` has no uniqueness on it,
        # so a re-run after any edit to BOOTSTRAP_TENANT_NAME — a rename, a typo —
        # would create a second tenant and insert these same addresses again. The
        # functional unique index is per tenant, so nothing stops it. Then
        # `find_by_email_across_tenants` returns two rows and D16's "exactly one" rule
        # refuses to authenticate BOTH accounts, permanently, in a product with no
        # public sign-up and no unlock endpoint. Recoverable only by hand-editing the
        # database, so it has to fail here instead.
        #
        # Deliberately through the PORT rather than a raw cross-tenant select: that
        # keeps `find_by_email_across_tenants` the only unscoped query in the system, so
        # D16's grep-based audit stays exhaustive. A second hand-rolled one here would
        # have made that claim false and the audit incomplete.
        elsewhere = [
            found.tenant_id
            for found in await users.find_by_email_across_tenants(seed.email)
            if found.tenant_id != tenant.id
        ]
        if elsewhere:
            raise BootstrapConflictError(
                f"The address of {seed.role.value} already exists under another tenant "
                f"({len(elsewhere)} found). Bootstrapping it again would leave every "
                "account with that address unable to log in. Check BOOTSTRAP_TENANT_NAME."
            )

        existing = (
            await session.execute(
                select(UserModel).where(
                    UserModel.tenant_id == tenant.id, UserModel.email == seed.email
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        session.add(
            UserModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                name=seed.name,
                email=seed.email,
                password_hash=hasher.hash(seed.password),
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
    # Counts, never the credentials.
    print(
        "bootstrap: created "
        f"{created['tenants']} tenant(s), {created['tenant_configs']} config(s), "
        f"{created['users']} user(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
