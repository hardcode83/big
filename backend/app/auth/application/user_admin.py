"""Use cases of user administration (R1, R2, R3, R4; design D1, D5, D6, D9, D21).

One use case is one business operation and one transaction: it orchestrates the aggregate and
its ports and calls `commit()` exactly once. No business rule lives here — the invariants are
in `User` and in `app/auth/domain/services.py` — and no `sqlalchemy` import either, which
`tests/test_layering.py` enforces for this layer.

Every mutating use case writes the change **and** its `AuditLog` before that single commit, so
a failure recording the trail leaves the user unchanged (R6.4). Same contract with which
`reservations` writes its `TimelineEvent`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.audit.domain import actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.auth.domain.entities import User
from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.domain.exceptions import UserNotFoundError
from app.auth.domain.passwords import generate_temporary_password
from app.auth.domain.ports import PasswordHasher, SessionRepository, UnitOfWork, UserRepository
from app.auth.domain.repositories import UserFilters, UserPage
from app.auth.domain.services import assert_tenant_keeps_an_owner
from app.auth.domain.value_objects import normalize_email

# Profile columns a PATCH may carry, plus the two with their own invariants. Kept here rather
# than inferred from the request schema so the rule does not live in `api/`.
PATCHABLE = ("name", "email", "phone", "preferred_language", "role", "status")


@dataclass(frozen=True)
class CreateUserCommand:
    """What `POST /api/v1/users` accepts (R1.1).

    No `password`: the system generates it (design D9). No `status` either — a new account is
    ACTIVE, and creating one already disabled is not a thing to do in one step.
    """

    name: str
    email: str
    role: UserRole
    phone: str | None = None
    preferred_language: str = "es"


@dataclass(frozen=True)
class CreatedUser:
    """The user plus the one-time secret. Never persisted in this shape."""

    user: User
    temporary_password: str


class _AuditWriter:
    """Builds and appends an audit entry, so no use case constructs one by hand (design D2)."""

    def __init__(self, audit: AuditLogRepository) -> None:
        self._audit = audit

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        actor_ip: str | None,
        changes: ChangeSet,
        now: datetime,
    ) -> None:
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=changes,
                now=now,
            ),
        )


class CreateUserUseCase:
    def __init__(
        self,
        *,
        users: UserRepository,
        audit: AuditLogRepository,
        hasher: PasswordHasher,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._audit = _AuditWriter(audit)
        self._hasher = hasher
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        command: CreateUserCommand,
        now: datetime,
    ) -> CreatedUser:
        """Create an account and hand back its one-time password (R1.1, R1.2).

        The order matters: the user is inserted (and its address vetted by the unique index)
        BEFORE the audit row is built, so a `409` leaves no trace of a creation that did not
        happen. `add` flushes, which is what makes the duplicate surface here rather than at
        commit.
        """
        temporary_password = generate_temporary_password()
        user = User.create(
            tenant_id=tenant_id,
            name=command.name,
            email=normalize_email(command.email),
            password_hash=await self._hasher.hash(temporary_password),
            role=command.role,
            now=now,
            phone=command.phone,
            preferred_language=command.preferred_language,
        )

        await self._users.add(tenant_id, user)
        await self._audit.record(
            tenant_id=tenant_id,
            action=actions.USER_CREATED,
            entity_type=actions.ENTITY_USER,
            entity_id=user.id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            # The address and the role are recorded; the password only as "it changed"
            # (rule 11 of steering/security.md). `ChangeSet` would refuse the alternative.
            changes=(
                ChangeSet(actions.ENTITY_USER)
                .diff("email", None, user.email)
                .diff("role", None, user.role)
                .redacted("password")
            ),
            now=now,
        )
        await self._uow.commit()
        return CreatedUser(user=user, temporary_password=temporary_password)


class ListUsersUseCase:
    def __init__(self, *, users: UserRepository) -> None:
        self._users = users

    async def execute(
        self, *, tenant_id: uuid.UUID, filters: UserFilters, page: int, per_page: int
    ) -> UserPage:
        return await self._users.list(tenant_id, filters, page=page, per_page=per_page)


class GetUserUseCase:
    def __init__(self, *, users: UserRepository) -> None:
        self._users = users

    async def execute(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
        user = await self._users.get(tenant_id, user_id)
        if user is None:
            # Also the answer for a user of another tenant: the repository returns None for
            # both, so this cannot distinguish them and neither can the response (R7.1).
            raise UserNotFoundError("User does not exist")
        return user


class UpdateUserUseCase:
    def __init__(
        self,
        *,
        users: UserRepository,
        sessions: SessionRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        user_id: uuid.UUID,
        changes: dict[str, object],
        now: datetime,
    ) -> User:
        """Apply a partial update (R3.1) and record what changed (R3.4).

        A PATCH that changes nothing — no fields, or fields carrying the values already
        stored — writes neither a row nor an audit entry (design D15): `audit_logs` is
        evidence of change, not of requests.
        """
        touches_population = "role" in changes or "status" in changes
        if touches_population:
            # Before reading, so the count below cannot be invalidated between the read and
            # the write by a concurrent demotion of a different owner (design D6).
            await self._users.lock_tenant_for_admin(tenant_id)

        user = await self._users.get(tenant_id, user_id)
        if user is None:
            raise UserNotFoundError("User does not exist")

        if touches_population:
            assert_tenant_keeps_an_owner(
                target=user,
                new_role=changes.get("role"),  # type: ignore[arg-type]
                new_status=changes.get("status"),  # type: ignore[arg-type]
                other_active_owners=await self._users.count_active_owners_excluding(
                    tenant_id, user_id
                ),
            )

        record = ChangeSet(actions.ENTITY_USER)
        written: dict[str, object] = {}

        previous_role = user.role
        if "role" in changes:
            new_role: UserRole = changes["role"]  # type: ignore[assignment]
            if user.change_role(new_role, actor_user_id=actor_user_id):
                written["role"] = new_role
                record = record.diff("role", previous_role, new_role)

        previous_status = user.status
        if "status" in changes:
            new_status: UserStatus = changes["status"]  # type: ignore[assignment]
            if user.change_status(new_status, actor_user_id=actor_user_id):
                written["status"] = new_status
                record = record.diff("status", previous_status, new_status)

        if "email" in changes:
            previous_email = user.email
            # Through the entity, not a bare `user.email = ...`: that assignment was the one
            # field of `User` that bypassed its own methods, which the feature-scale
            # architecture review flagged against the "no arbitrary setters" rule of
            # `steering/backend-architecture.md` and design D5.
            if user.change_email(str(changes["email"])):
                written["email"] = user.email
                record = record.diff("email", previous_email, user.email)

        profile = {
            field: changes[field]
            for field in ("name", "phone", "preferred_language")
            if field in changes
        }
        if profile:
            before = {field: getattr(user, field) for field in profile}
            for field in user.update_profile(**profile):  # type: ignore[arg-type]
                written[field] = getattr(user, field)
                record = record.diff(field, before[field], getattr(user, field))

        if not written:
            return user

        await self._users.apply_changes(tenant_id, user_id, written)

        # A role change gets its own action so rule 9 of steering/security.md ("AuditLog
        # para … roles de User") is satisfied by an indexed `action` filter rather than by a
        # JSONB query. A PATCH that changes the role AND the profile is still ONE row, with
        # every field in `changes` (design D4).
        await self._audit.record(
            tenant_id=tenant_id,
            action=(
                actions.USER_ROLE_CHANGED if "role" in written else actions.USER_UPDATED
            ),
            entity_type=actions.ENTITY_USER,
            entity_id=user.id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            changes=record,
            now=now,
        )

        if _locks_the_account_out(written.get("status")):
            # `POST /auth/refresh` never revalidates the user's status, so without this a
            # disabled account keeps minting pairs for the whole refresh lifetime (R3.7).
            await self._sessions.revoke_all_for_user(
                tenant_id, user_id, SessionRevokedReason.USER_DEACTIVATED, now
            )

        await self._uow.commit()
        return user


class DeactivateUserUseCase:
    """The `DELETE` of R3.8: logical, never physical."""

    def __init__(
        self,
        *,
        users: UserRepository,
        sessions: SessionRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        user_id: uuid.UUID,
        now: datetime,
    ) -> None:
        await self._users.lock_tenant_for_admin(tenant_id)
        user = await self._users.get(tenant_id, user_id)
        if user is None:
            raise UserNotFoundError("User does not exist")

        assert_tenant_keeps_an_owner(
            target=user,
            new_role=None,
            new_status=UserStatus.INACTIVE,
            other_active_owners=await self._users.count_active_owners_excluding(
                tenant_id, user_id
            ),
        )

        previous_status = user.status
        if not user.deactivate(actor_user_id=actor_user_id):
            # Already INACTIVE: idempotent, and no second audit row (R3.9).
            return

        await self._users.apply_changes(tenant_id, user_id, {"status": user.status})
        await self._audit.record(
            tenant_id=tenant_id,
            action=actions.USER_DEACTIVATED,
            entity_type=actions.ENTITY_USER,
            entity_id=user.id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            changes=ChangeSet(actions.ENTITY_USER).diff(
                "status", previous_status, user.status
            ),
            now=now,
        )
        await self._sessions.revoke_all_for_user(
            tenant_id, user_id, SessionRevokedReason.USER_DEACTIVATED, now
        )
        await self._uow.commit()


class ResetUserPasswordUseCase:
    def __init__(
        self,
        *,
        users: UserRepository,
        sessions: SessionRepository,
        audit: AuditLogRepository,
        hasher: PasswordHasher,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._audit = _AuditWriter(audit)
        self._hasher = hasher
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        user_id: uuid.UUID,
        now: datetime,
    ) -> CreatedUser:
        """Issue a new temporary password for somebody else (R4.1, R4.2, R4.3)."""
        user = await self._users.get(tenant_id, user_id)
        if user is None:
            raise UserNotFoundError("User does not exist")

        temporary_password = generate_temporary_password()
        user.set_password_hash(await self._hasher.hash(temporary_password))

        await self._users.apply_changes(
            tenant_id, user_id, {"password_hash": user.password_hash}
        )
        await self._audit.record(
            tenant_id=tenant_id,
            action=actions.USER_PASSWORD_RESET,
            entity_type=actions.ENTITY_USER,
            entity_id=user.id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            # Neither the password nor its hash: only that it changed (R4.3).
            changes=ChangeSet(actions.ENTITY_USER).redacted("password"),
            now=now,
        )
        # A reset that leaves the previous sessions alive does not recover the account, it
        # just adds one more credential to it (R4.2).
        await self._sessions.revoke_all_for_user(
            tenant_id, user_id, SessionRevokedReason.PASSWORD_RESET, now
        )
        await self._uow.commit()
        return CreatedUser(user=user, temporary_password=temporary_password)


def _locks_the_account_out(status: object) -> bool:
    """Whether a new status stops the user from authenticating.

    SUSPENDED as much as INACTIVE: `get_active_by_id` resolves neither, so both have to take
    the refresh tokens down with them.
    """
    return status in (UserStatus.INACTIVE, UserStatus.SUSPENDED)
