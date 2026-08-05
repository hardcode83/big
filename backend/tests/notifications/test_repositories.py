"""`SqlAlchemyNotificationLogRepository` — candidate selection and tenant scoping.

Covers `celery-jobs` R5 (the four conditions of PRD §14), R4.4 (`sla_breached` is what
makes a second pass a no-op) and rule 1 of `steering/security.md`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.tenancy import CrossTenantWriteError
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel, NotificationStatus
from app.notifications.domain.exceptions import NotificationLogNotFoundError
from app.notifications.infrastructure.models import NotificationLogModel
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.tenants.infrastructure.models import TenantModel

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


async def _tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _log(
    db_session,
    tenant: TenantModel,
    *,
    status: NotificationStatus = NotificationStatus.SENT,
    sla_deadline_at: datetime | None = NOW - timedelta(minutes=1),
    sla_breached: bool = False,
) -> NotificationLogModel:
    model = NotificationLogModel(
        tenant_id=tenant.id,
        recipient_contact="manager@example.com",
        channel=NotificationChannel.EMAIL,
        notification_type="CLEANING_TASK_ASSIGNED",
        status=status,
        sla_deadline_at=sla_deadline_at,
        sla_breached=sla_breached,
    )
    db_session.add(model)
    await db_session.flush()
    return model


@pytest.mark.asyncio
async def test_a_sent_log_past_its_deadline_is_a_candidate(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    overdue = await _log(db_session, tenant)

    found = await SqlAlchemyNotificationLogRepository(db_session).list_sla_breach_candidates(
        tenant.id, NOW
    )

    assert [log.id for log in found] == [overdue.id]


@pytest.mark.asyncio
async def test_the_four_conditions_of_prd_14_each_exclude_a_row(db_session) -> None:
    """One row per condition, each failing exactly one of them."""
    tenant = await _tenant(db_session, "TenantA")
    await _log(db_session, tenant, status=NotificationStatus.PENDING)
    await _log(db_session, tenant, sla_deadline_at=None)
    await _log(db_session, tenant, sla_deadline_at=NOW + timedelta(minutes=5))
    await _log(db_session, tenant, sla_breached=True)

    found = await SqlAlchemyNotificationLogRepository(db_session).list_sla_breach_candidates(
        tenant.id, NOW
    )

    assert found == []


@pytest.mark.asyncio
async def test_a_deadline_exactly_now_has_not_passed_yet(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    await _log(db_session, tenant, sla_deadline_at=NOW)

    found = await SqlAlchemyNotificationLogRepository(db_session).list_sla_breach_candidates(
        tenant.id, NOW
    )

    assert found == []


@pytest.mark.asyncio
async def test_candidates_come_oldest_breach_first(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    recent = await _log(db_session, tenant, sla_deadline_at=NOW - timedelta(minutes=1))
    oldest = await _log(db_session, tenant, sla_deadline_at=NOW - timedelta(hours=3))

    found = await SqlAlchemyNotificationLogRepository(db_session).list_sla_breach_candidates(
        tenant.id, NOW
    )

    assert [log.id for log in found] == [oldest.id, recent.id]


@pytest.mark.asyncio
async def test_candidates_never_cross_tenants(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    await _log(db_session, tenant_b)

    found = await SqlAlchemyNotificationLogRepository(db_session).list_sla_breach_candidates(
        tenant_a.id, NOW
    )

    assert found == []


@pytest.mark.asyncio
async def test_mark_breached_removes_the_row_from_the_candidates(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    await _log(db_session, tenant)
    repository = SqlAlchemyNotificationLogRepository(db_session)
    [candidate] = await repository.list_sla_breach_candidates(tenant.id, NOW)

    await repository.mark_breached(tenant.id, candidate)

    assert await repository.list_sla_breach_candidates(tenant.id, NOW) == []


@pytest.mark.asyncio
async def test_mark_breached_refuses_another_tenants_log(db_session) -> None:
    """Loud, not a silent no-op — the escalation is already written by then (R5.3)."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    await _log(db_session, tenant_b)
    repository = SqlAlchemyNotificationLogRepository(db_session)
    [theirs] = await repository.list_sla_breach_candidates(tenant_b.id, NOW)

    with pytest.raises(CrossTenantWriteError):
        await repository.mark_breached(tenant_a.id, theirs)

    still_a_candidate = await repository.list_sla_breach_candidates(tenant_b.id, NOW)
    assert [log.id for log in still_a_candidate] == [theirs.id]


@pytest.mark.asyncio
async def test_mark_breached_of_a_vanished_row_raises_instead_of_marking_nothing(
    db_session,
) -> None:
    """The cause we cannot prove still breaks R5.3, so it fails — just not by claiming
    a tenant mismatch it has no evidence for."""
    tenant = await _tenant(db_session, "TenantA")
    await _log(db_session, tenant)
    repository = SqlAlchemyNotificationLogRepository(db_session)
    [candidate] = await repository.list_sla_breach_candidates(tenant.id, NOW)
    candidate.id = uuid.uuid4()

    with pytest.raises(NotificationLogNotFoundError):
        await repository.mark_breached(tenant.id, candidate)


@pytest.mark.asyncio
async def test_add_persists_the_escalation_row(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    log = NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        recipient_contact="manager@example.com",
        channel=NotificationChannel.EMAIL,
        notification_type="SLA_BREACH",
        created_at=NOW,
        updated_at=NOW,
        subject="SLA breach",
        body="A cleaning assignment passed its deadline.",
        related_type="notification_log",
        related_id=uuid.uuid4(),
    )

    await SqlAlchemyNotificationLogRepository(db_session).add(tenant.id, log)

    stored = (
        await db_session.execute(
            select(NotificationLogModel).where(NotificationLogModel.id == log.id)
        )
    ).scalar_one()
    assert stored.status is NotificationStatus.PENDING
    assert stored.notification_type == "SLA_BREACH"
    assert stored.sla_breached is False


@pytest.mark.asyncio
async def test_add_refuses_a_log_of_another_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    log = NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        recipient_contact="manager@example.com",
        channel=NotificationChannel.EMAIL,
        notification_type="SLA_BREACH",
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyNotificationLogRepository(db_session).add(tenant_a.id, log)
