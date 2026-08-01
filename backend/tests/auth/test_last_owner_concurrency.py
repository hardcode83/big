"""The last-owner invariant survives two simultaneous demotions (R3.6, design D6).

This is the test the lock exists for, and it needs real Postgres: what is being proved is
that `SELECT ... FOR UPDATE` serialises two transactions, which no fake can show.

Why the lock and not the single-statement idiom of `SessionRepository.consume`: that works
because Postgres re-evaluates the WHERE of an UPDATE against the new row version when it
unblocks — but only for the row being written. The owner count looks at OTHER rows, evaluated
against each transaction's snapshot, so two demotions of two different owners would each see
the other as still active and both would be allowed through.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.application.user_admin import UpdateUserUseCase
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.exceptions import LastOwnerError
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.repositories import (
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.tenants.infrastructure.models import TenantModel
from tests.auth.conftest import utc_now

async def _seed_two_owners(engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A tenant with exactly two ACTIVE owners plus the actor, all committed.

    The actor is seeded as a real row because `audit_logs.actor_user_id` carries a foreign key
    to `users.id` — a made-up actor id fails the INSERT, which the first version of this test
    found the hard way. It is a PROPERTY_MANAGER so it does not change the owner count.
    """
    tenant_id = uuid.uuid4()
    first, second, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(
            TenantModel(id=tenant_id, name=f"t-{tenant_id.hex[:8]}", billing_email="o@x.com")
        )
        # Flushed before the users: SQLAlchemy would otherwise batch all three INSERTs into
        # one statement and the FK on `users.tenant_id` would fire.
        await session.flush()
        for user_id, suffix, role in (
            (first, "a", UserRole.TENANT_OWNER),
            (second, "b", UserRole.TENANT_OWNER),
            (actor, "admin", UserRole.PROPERTY_MANAGER),
        ):
            session.add(
                UserModel(
                    id=user_id,
                    tenant_id=tenant_id,
                    name=f"Owner {suffix}",
                    email=f"owner-{user_id.hex[:8]}@example.com",
                    password_hash="hashed",
                    role=role,
                    status=UserStatus.ACTIVE,
                )
            )
        await session.commit()
    return tenant_id, first, second, actor


def _use_case(session: AsyncSession) -> UpdateUserUseCase:
    return UpdateUserUseCase(
        users=SqlAlchemyUserRepository(session),
        sessions=SqlAlchemySessionRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


async def _demote(engine, tenant_id: uuid.UUID, user_id: uuid.UUID, actor: uuid.UUID) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await _use_case(session).execute(
            tenant_id=tenant_id,
            actor_user_id=actor,
            actor_ip=None,
            user_id=user_id,
            changes={"role": UserRole.CLEANER},
            now=utc_now(),
        )


@pytest.mark.asyncio
async def test_two_simultaneous_demotions_leave_one_owner_standing(test_engine) -> None:
    tenant_id, first, second, actor = await _seed_two_owners(test_engine)

    results = await asyncio.gather(
        _demote(test_engine, tenant_id, first, actor),
        _demote(test_engine, tenant_id, second, actor),
        return_exceptions=True,
    )

    refused = [result for result in results if isinstance(result, LastOwnerError)]
    succeeded = [result for result in results if result is None]
    assert len(refused) == 1, f"expected exactly one refusal, got {results}"
    assert len(succeeded) == 1, f"expected exactly one success, got {results}"

    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        owners = (
            await session.execute(
                select(UserModel).where(
                    UserModel.tenant_id == tenant_id,
                    UserModel.role == UserRole.TENANT_OWNER,
                    UserModel.status == UserStatus.ACTIVE,
                )
            )
        ).scalars().all()
    assert len(owners) == 1


@pytest.mark.asyncio
async def test_two_simultaneous_demotions_of_the_same_owner_leave_it_standing(
    test_engine,
) -> None:
    """The same row twice: one demotion wins, the other finds no owner left and is refused."""
    tenant_id, first, _second, actor = await _seed_two_owners(test_engine)

    results = await asyncio.gather(
        _demote(test_engine, tenant_id, first, actor),
        _demote(test_engine, tenant_id, first, actor),
        return_exceptions=True,
    )

    # Both targeted the same user, so the second sees it already demoted and changes nothing.
    assert not [r for r in results if isinstance(r, BaseException) and not isinstance(r, LastOwnerError)], results

    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        owners = (
            await session.execute(
                select(UserModel).where(
                    UserModel.tenant_id == tenant_id,
                    UserModel.role == UserRole.TENANT_OWNER,
                    UserModel.status == UserStatus.ACTIVE,
                )
            )
        ).scalars().all()
    assert len(owners) == 1


@pytest.mark.asyncio
async def test_sequential_demotions_refuse_the_second_one(test_engine) -> None:
    """The non-concurrent baseline: without it, a passing concurrent test proves nothing.

    If the rule were broken outright, the concurrent test above could still show "one
    refusal" by accident of timing. This pins the rule itself.
    """
    tenant_id, first, second, actor = await _seed_two_owners(test_engine)

    await _demote(test_engine, tenant_id, first, actor)

    with pytest.raises(LastOwnerError):
        await _demote(test_engine, tenant_id, second, actor)


class _UnlockedUserRepository(SqlAlchemyUserRepository):
    """The same adapter with the tenant lock removed and the race made deterministic.

    The barrier is what makes this test trustworthy rather than lucky. Its first version had no
    barrier and relied on the two transactions happening to interleave; under the load of the
    full suite they sometimes serialised anyway and it failed intermittently — caught by two
    reviewers of the sections 2-6 panel. A flaky test is worse than no test, so the interleaving
    the scenario is ABOUT is now forced: both transactions finish counting before either writes.
    """

    def __init__(self, session, barrier: asyncio.Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    async def lock_tenant_for_admin(self, tenant_id: uuid.UUID) -> None:
        return None

    async def count_active_owners_excluding(self, tenant_id, user_id) -> int:
        count = await super().count_active_owners_excluding(tenant_id, user_id)
        # Both callers hold their count here, before either has written anything: exactly the
        # window that `SELECT ... FOR UPDATE` closes.
        await self._barrier.wait()
        return count


async def _demote_without_the_lock(engine, tenant_id, user_id, actor, barrier) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await UpdateUserUseCase(
            users=_UnlockedUserRepository(session, barrier),
            sessions=SqlAlchemySessionRepository(session),
            audit=SqlAlchemyAuditLogRepository(session),
            uow=SqlAlchemyUnitOfWork(session),
        ).execute(
            tenant_id=tenant_id,
            actor_user_id=actor,
            actor_ip=None,
            user_id=user_id,
            changes={"role": UserRole.CLEANER},
            now=utc_now(),
        )


@pytest.mark.asyncio
async def test_without_the_lock_the_tenant_loses_every_owner(test_engine) -> None:
    """Proof that the test above is not passing in a vacuum (design D6).

    Same scenario with `lock_tenant_for_admin` neutered: both transactions read the owner
    count before either commits, each sees the other as still active, and the tenant ends up
    with **no** administrator. This is the failure the lock prevents; if this test ever starts
    finding one owner standing, the concurrent test above has stopped proving anything and
    both need rethinking.
    """
    tenant_id, first, second, actor = await _seed_two_owners(test_engine)
    barrier = asyncio.Barrier(2)

    await asyncio.gather(
        _demote_without_the_lock(test_engine, tenant_id, first, actor, barrier),
        _demote_without_the_lock(test_engine, tenant_id, second, actor, barrier),
        return_exceptions=True,
    )

    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        owners = (
            await session.execute(
                select(UserModel).where(
                    UserModel.tenant_id == tenant_id,
                    UserModel.role == UserRole.TENANT_OWNER,
                    UserModel.status == UserStatus.ACTIVE,
                )
            )
        ).scalars().all()

    assert owners == [], (
        "both demotions were expected to slip through without the lock; if they did not, "
        "the concurrency test above is no longer proving that the lock is what stops them"
    )
