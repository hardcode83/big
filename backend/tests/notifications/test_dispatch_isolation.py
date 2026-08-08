"""Tenant isolation of the dispatcher (R4.7, rule 1 of `steering/security.md`).

Against the real repository and a real database, unlike `test_dispatch.py`: the guarantee
being checked is the SQL `WHERE tenant_id = :tenant_id`, and a fake repository would assert
the fake's own filter. DoD §28.18 requires this test per module.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.notifications.application.use_cases import DispatchPendingNotificationsUseCase
from app.notifications.domain.enums import NotificationChannel, NotificationStatus
from app.notifications.domain.exceptions import NotificationLogNotFoundError
from app.notifications.domain.results import NotificationResult
from app.notifications.infrastructure.models import NotificationLogModel
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.tenants.infrastructure.models import TenantModel

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


class SpyAdapter:
    def __init__(self) -> None:
        self.recipients: list[str] = []

    async def send(self, *, recipient_contact, subject, body, channel):
        self.recipients.append(recipient_contact)
        return NotificationResult.ok()


async def _tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _pending(db_session, tenant: TenantModel, contact: str) -> NotificationLogModel:
    model = NotificationLogModel(
        tenant_id=tenant.id,
        recipient_contact=contact,
        channel=NotificationChannel.EMAIL,
        notification_type="CLEANING_TASK_ASSIGNED",
        status=NotificationStatus.PENDING,
        subject="Cleaning assigned",
        body="A cleaning task has been assigned to you.",
    )
    db_session.add(model)
    await db_session.flush()
    return model


class _Uow:
    def __init__(self, session) -> None:
        self._session = session

    async def commit(self) -> None:
        # `flush`, not `commit`: the test fixture owns the outer transaction, and committing
        # here would end it mid-test. The ordering guarantee of design D4 is covered by
        # `test_dispatch.py`; what this file checks is the tenant predicate in the SQL.
        await self._session.flush()


@pytest.mark.asyncio
async def test_a_run_delivers_only_its_own_tenants_rows(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _pending(db_session, tenant_a, "mine@example.com")
    theirs = await _pending(db_session, tenant_b, "theirs@example.com")
    adapter = SpyAdapter()

    report = await DispatchPendingNotificationsUseCase(
        notifications=SqlAlchemyNotificationLogRepository(db_session),
        adapters={NotificationChannel.EMAIL: adapter},
        uow=_Uow(db_session),
        max_attempts=3,
        batch_size=100,
    ).execute(tenant_id=tenant_a.id, now=NOW)

    assert report.sent == 1
    # The neighbour's contact was never handed to a provider — R4.7 is about the send, not
    # only about the row.
    assert adapter.recipients == ["mine@example.com"]
    await db_session.refresh(mine)
    await db_session.refresh(theirs)
    assert mine.status is NotificationStatus.SENT
    assert theirs.status is NotificationStatus.PENDING
    assert theirs.attempts == 0


@pytest.mark.asyncio
async def test_a_tenant_with_nothing_pending_writes_nothing(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    await _pending(db_session, tenant_b, "theirs@example.com")
    adapter = SpyAdapter()

    report = await DispatchPendingNotificationsUseCase(
        notifications=SqlAlchemyNotificationLogRepository(db_session),
        adapters={NotificationChannel.EMAIL: adapter},
        uow=_Uow(db_session),
        max_attempts=3,
        batch_size=100,
    ).execute(tenant_id=tenant_a.id, now=NOW)

    assert report == type(report)()
    assert adapter.recipients == []


@pytest.mark.asyncio
async def test_record_attempt_cannot_reach_a_neighbours_row(db_session) -> None:
    """The repository's own guard, exercised through the id path the dispatcher uses."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _pending(db_session, tenant_b, "theirs@example.com")
    repository = SqlAlchemyNotificationLogRepository(db_session)

    with pytest.raises(NotificationLogNotFoundError):
        await repository.record_attempt(
            tenant_a.id,
            theirs.id,
            status=NotificationStatus.SENT,
            attempts=1,
            sent_at=NOW,
            last_error=None,
        )

    await db_session.refresh(theirs)
    assert theirs.status is NotificationStatus.PENDING


@pytest.mark.asyncio
async def test_a_uuid_that_belongs_to_nobody_is_refused_too(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyNotificationLogRepository(db_session)

    with pytest.raises(NotificationLogNotFoundError):
        await repository.record_attempt(
            tenant.id,
            uuid.uuid4(),
            status=NotificationStatus.SENT,
            attempts=1,
            sent_at=NOW,
            last_error=None,
        )
