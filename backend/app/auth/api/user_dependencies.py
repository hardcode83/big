"""Wiring for the user-administration endpoints: one builder per use case.

Separate module from `app/auth/api/dependencies.py` on purpose: that one is imported by every
router in the application for `require(...)` and `get_authenticated_request`, and it must not
grow a dependency on the administration use cases just to host their builders.

The repositories take the session from `get_db_session` — the same session
`get_authenticated_request` has already marked with the tenant, so the listener of
`app/core/db.py` scopes ORM reads too, as a net under the explicit `tenant_id` argument.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.api.dependencies import get_password_hasher
from app.auth.application.user_admin import (
    CreateUserUseCase,
    DeactivateUserUseCase,
    GetUserUseCase,
    ListUsersUseCase,
    ResetUserPasswordUseCase,
    UpdateUserUseCase,
)
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.repositories import (
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
HasherDep = Annotated[BcryptPasswordHasher, Depends(get_password_hasher)]


def get_create_user_use_case(session: SessionDep, hasher: HasherDep) -> CreateUserUseCase:
    return CreateUserUseCase(
        users=SqlAlchemyUserRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        hasher=hasher,
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_list_users_use_case(session: SessionDep) -> ListUsersUseCase:
    return ListUsersUseCase(users=SqlAlchemyUserRepository(session))


def get_user_use_case(session: SessionDep) -> GetUserUseCase:
    return GetUserUseCase(users=SqlAlchemyUserRepository(session))


def get_update_user_use_case(session: SessionDep) -> UpdateUserUseCase:
    return UpdateUserUseCase(
        users=SqlAlchemyUserRepository(session),
        sessions=SqlAlchemySessionRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_deactivate_user_use_case(session: SessionDep) -> DeactivateUserUseCase:
    return DeactivateUserUseCase(
        users=SqlAlchemyUserRepository(session),
        sessions=SqlAlchemySessionRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_reset_password_use_case(
    session: SessionDep, hasher: HasherDep
) -> ResetUserPasswordUseCase:
    return ResetUserPasswordUseCase(
        users=SqlAlchemyUserRepository(session),
        sessions=SqlAlchemySessionRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        hasher=hasher,
        uow=SqlAlchemyUnitOfWork(session),
    )
