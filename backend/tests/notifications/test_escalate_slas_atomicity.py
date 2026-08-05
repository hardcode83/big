"""R5.3 against a real database: the mark and its escalation rows are one transaction.

The unit tests of `test_escalate_slas.py` run against a dict, which cannot roll anything
back and so can only demonstrate the happy path. The QA panel of section 4 pointed out that
section 3 had an equivalent integration test (`test_advance_states_atomicity.py`) and this
one did not — the invariant was verified by a throwaway probe rather than by the suite.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.core.db import bind_session_to_tenant
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.application.use_cases import EscalateBreachedSlasUseCase
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.notifications.domain.exceptions import NotificationLogNotFoundError
from app.notifications.infrastructure.models import NotificationLogModel
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.tenants.infrastructure.models import TenantModel

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


class ExplodingOnSecondMark(SqlAlchemyNotificationLogRepository):
    """Fails on the second `mark_breached`, after the first candidate is fully written."""

    def __init__(self, session) -> None:
        super().__init__(session)
        self.calls = 0

    async def mark_breached(self, tenant_id, log) -> None:
        self.calls += 1
        if self.calls == 2:
            raise NotificationLogNotFoundError(log.id)
        await super().mark_breached(tenant_id, log)


async def _seed(db_session):
    tenant = TenantModel(name="TenantA", billing_email="a@example.com")
    db_session.add(tenant)
    await db_session.flush()
    db_session.add(
        UserModel(
            tenant_id=tenant.id,
            name="Ana",
            email=f"ana-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="x",
            role=UserRole.PROPERTY_MANAGER,
            status=UserStatus.ACTIVE,
        )
    )
    breaches = []
    for minutes in (30, 10):
        log = NotificationLogModel(
            tenant_id=tenant.id,
            recipient_contact="cleaner@example.com",
            channel=NotificationChannel.EMAIL,
            notification_type=NotificationType.CLEANING_TASK_ASSIGNED.value,
            status=NotificationStatus.SENT,
            sla_deadline_at=NOW - timedelta(minutes=minutes),
        )
        db_session.add(log)
        breaches.append(log)
    await db_session.flush()
    return tenant, breaches


def _use_case(db_session, *, notifications=None):
    return EscalateBreachedSlasUseCase(
        notifications=notifications or SqlAlchemyNotificationLogRepository(db_session),
        users=SqlAlchemyUserRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )


@pytest.mark.asyncio
async def test_both_breaches_are_marked_and_escalated(db_session) -> None:
    tenant, _ = await _seed(db_session)

    report = await _use_case(db_session).execute(tenant_id=tenant.id, now=NOW)

    assert report.escalated == 2
    assert report.rows_written == 2
    escalations = (
        await db_session.execute(
            select(NotificationLogModel).where(
                NotificationLogModel.notification_type == NotificationType.SLA_BREACH.value
            )
        )
    ).scalars().all()
    assert len(escalations) == 2
    assert all(row.status is NotificationStatus.PENDING for row in escalations)


@pytest.mark.asyncio
async def test_a_failure_midway_leaves_neither_marks_nor_escalations(db_session) -> None:
    tenant, breaches = await _seed(db_session)
    tenant_id = tenant.id
    breach_ids = [breach.id for breach in breaches]
    await db_session.commit()

    with pytest.raises(NotificationLogNotFoundError):
        await _use_case(
            db_session, notifications=ExplodingOnSecondMark(db_session)
        ).execute(tenant_id=tenant_id, now=NOW)

    # What the scheduler's runner does for a failing tenant (design D12).
    await db_session.rollback()

    escalations = await db_session.scalar(
        select(func.count())
        .select_from(NotificationLogModel)
        .where(NotificationLogModel.notification_type == NotificationType.SLA_BREACH.value)
    )
    marked = await db_session.scalar(
        select(func.count())
        .select_from(NotificationLogModel)
        .where(
            NotificationLogModel.id.in_(breach_ids),
            NotificationLogModel.sla_breached.is_(True),
        )
    )

    # The first candidate was fully written before the second one blew up; the rollback
    # is what makes "no `sla_breached = TRUE` without its escalation" hold across the run.
    assert escalations == 0
    assert marked == 0


@pytest.mark.asyncio
async def test_a_neighbours_manager_never_receives_an_escalation(db_session) -> None:
    """Rule 1 with the session **unmarked** — this is what proves the explicit filters.

    `app/core/db.py` is explicit that the authoritative mechanism is the `tenant_id` every
    repository method takes, and that the global loader-criteria net is only a net. With the
    session unmarked the net is off, so this test fails if any explicit filter goes missing —
    verified by deleting `UserModel.tenant_id == tenant_id` from
    `SqlAlchemyUserRepository.list` and watching it go red.

    Its sibling below runs the same flow with the session bound. Neither is redundant, and
    the reason is worth knowing: with the session **bound**, the net silently compensates for
    a dropped explicit filter, so the bound test stays green on that exact bug. One proves the
    mechanism, the other proves the configuration production actually runs.
    """
    mine, my_breaches = await _seed(db_session)
    theirs, their_breaches = await _seed(db_session)
    my_manager = (
        await db_session.execute(select(UserModel).where(UserModel.tenant_id == mine.id))
    ).scalar_one()
    their_manager = (
        await db_session.execute(select(UserModel).where(UserModel.tenant_id == theirs.id))
    ).scalar_one()
    assert my_manager.id != their_manager.id

    report = await _use_case(db_session).execute(tenant_id=mine.id, now=NOW)

    assert report.escalated == len(my_breaches)
    escalations = (
        await db_session.execute(
            select(NotificationLogModel).where(
                NotificationLogModel.notification_type == NotificationType.SLA_BREACH.value
            )
        )
    ).scalars().all()
    assert {row.tenant_id for row in escalations} == {mine.id}
    assert {row.recipient_user_id for row in escalations} == {my_manager.id}
    assert {row.recipient_contact for row in escalations} == {my_manager.email}
    # The quiet shape the assertions above cannot see: the neighbour's rows marked or
    # escalated without their manager ever being named.
    untouched = await db_session.scalar(
        select(func.count())
        .select_from(NotificationLogModel)
        .where(
            NotificationLogModel.tenant_id == theirs.id,
            NotificationLogModel.sla_breached.is_(False),
        )
    )
    assert untouched == len(their_breaches)


@pytest.mark.asyncio
async def test_the_same_flow_holds_on_a_session_bound_the_way_production_binds_it(
    db_session, test_engine
) -> None:
    """The other half of rule 1: the configuration `app/scheduler/runner.py` actually runs.

    Every real execution of this use case happens on a session bound with
    `bind_session_to_tenant`, which switches on the global loader-criteria net *in addition*
    to the explicit filters. Nothing else in the suite exercises this use case that way.

    The neighbour is inspected through a second, unmarked session on purpose: once the first
    is bound it cannot see the neighbour's rows at all — which is the net doing its job, and
    is why the sibling test above has to exist to prove the explicit filters separately.
    """
    mine, _ = await _seed(db_session)
    theirs, their_breaches = await _seed(db_session)
    my_manager_id = (
        await db_session.execute(select(UserModel.id).where(UserModel.tenant_id == mine.id))
    ).scalar_one()
    their_id, their_breach_count = theirs.id, len(their_breaches)
    await db_session.commit()

    bind_session_to_tenant(db_session, mine.id)
    report = await _use_case(db_session).execute(tenant_id=mine.id, now=NOW)

    assert report.escalated == 2
    escalations = (
        await db_session.execute(
            select(NotificationLogModel).where(
                NotificationLogModel.notification_type == NotificationType.SLA_BREACH.value
            )
        )
    ).scalars().all()
    assert {row.recipient_user_id for row in escalations} == {my_manager_id}

    async with AsyncSession(test_engine, expire_on_commit=False) as onlooker:
        untouched = await onlooker.scalar(
            select(func.count())
            .select_from(NotificationLogModel)
            .where(
                NotificationLogModel.tenant_id == their_id,
                NotificationLogModel.sla_breached.is_(False),
            )
        )
        theirs_escalations = await onlooker.scalar(
            select(func.count())
            .select_from(NotificationLogModel)
            .where(
                NotificationLogModel.tenant_id == their_id,
                NotificationLogModel.notification_type == NotificationType.SLA_BREACH.value,
            )
        )
    assert untouched == their_breach_count
    assert theirs_escalations == 0
