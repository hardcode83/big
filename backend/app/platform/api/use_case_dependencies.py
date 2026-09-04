"""Wiring for the platform endpoints: one builder per use case (R1.1, R3.1, design D2, D3).

Separate module from `app/platform/api/dependencies.py` on purpose: that one is imported by
every platform router for the `require(...)` alias, and it must not grow a dependency on the
infrastructure repositories just to host its builders.

The repositories take the session from `get_db_session` — the same session every other
authenticated request gets. The platform routes are reached only by `SUPER_ADMIN` (`R5.3`),
so the session is unmarked — but NOT because `tenant_scoped_classes()` (`app/core/db.py`)
fails to cover the tables the platform endpoints touch. It does cover three of the four:
`tenant_configs`, `users` and `audit_logs` each carry a `tenant_id` column, so all three are
tenant-scoped classes (`tenants` itself is the one exception — it IS the tenant, so it has
no such column to be scoped by). What actually leaves the session unmarked is the caller,
not the schema: `get_authenticated_request` only calls `bind_session_to_tenant` when
`context.tenant_id` is not `None`, and `SUPER_ADMIN` always authenticates with
`context.tenant_id is None` (`super-admin-identity` R1). A marked session over these same
tables would silently narrow every tenant-scoped join or query to one tenant instead of
raising — `super-admin-console`'s `ListTenantsUseCase` guards exactly this failure mode at
the repository (`TenantRepository.list_page` calls `require_unmarked_session`) precisely
because the join it runs touches `tenant_configs`, one of the three scoped tables here.
Design D5's whole point is that the **audit row's `tenant_id`** comes from the entity being
audited (the path's tenant id, never the actor's), and that holds because the session
carries no marker to inherit.

`CreateUserInTenantUseCase` does NOT take a `UnitOfWork` (note 4.3, design D3): the wrapped
`CreateUserUseCase` owns its own `commit()`, and the inner `UnitOfWork` and the outer one
are NOT nested — `db_session` per-request gives a single transaction (the same pattern
`app.auth.api.user_dependencies.get_create_user_use_case` uses, which builds
`CreateUserUseCase` with `uow=SqlAlchemyUnitOfWork(session)`). The wrapper's docstring in
`app.platform.application.use_cases` records why this is one `commit()` and not a
`SAVEPOINT`, so a future reader does not "fix" the signature by adding a `uow` parameter.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.api.dependencies import get_password_hasher
from app.auth.application.user_admin import CreateUserUseCase
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.platform.application.use_cases import (
    CreateTenantUseCase,
    CreateUserInTenantUseCase,
    ListTenantsUseCase,
)
from app.tenants.infrastructure.repositories import (
    SqlAlchemyTenantConfigRepository,
    SqlAlchemyTenantRepository,
)

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
HasherDep = Annotated[BcryptPasswordHasher, Depends(get_password_hasher)]


def get_create_tenant_use_case(session: SessionDep) -> CreateTenantUseCase:
    return CreateTenantUseCase(
        tenants=SqlAlchemyTenantRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_create_user_in_tenant_use_case(
    session: SessionDep,
    hasher: HasherDep,
) -> CreateUserInTenantUseCase:
    """The wrapper around `CreateUserUseCase` (R3.1, design D3).

    `CreateUserUseCase` is built here with the SAME `SqlAlchemyUnitOfWork(session)` the
    platform endpoint would have used if the wrapper had one: one transaction per request,
    not a nested `SAVEPOINT`. The wrapper does NOT commit — `CreateUserUseCase.execute`'s
    own `uow.commit()` is what lands the row, and that is exactly the pattern
    `get_create_user_use_case` in `app.auth.api.user_dependencies` uses for the
    tenants-scoped `POST /api/v1/users`. Two builders, one wiring shape, no divergence to
    debug.
    """
    return CreateUserInTenantUseCase(
        tenants=SqlAlchemyTenantRepository(session),
        create_user=CreateUserUseCase(
            users=SqlAlchemyUserRepository(session),
            audit=SqlAlchemyAuditLogRepository(session),
            hasher=hasher,
            uow=SqlAlchemyUnitOfWork(session),
        ),
    )


def get_list_tenants_use_case(session: SessionDep) -> ListTenantsUseCase:
    return ListTenantsUseCase(tenants=SqlAlchemyTenantRepository(session))


__all__ = [
    "get_create_tenant_use_case",
    "get_create_user_in_tenant_use_case",
    "get_list_tenants_use_case",
]
