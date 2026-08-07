"""R6 — the notification an assignment produces, and the SLA chain it feeds.

The chain has a measured gap and this file is where it is visible rather than assumed:
`list_sla_breach_candidates` requires `status = SENT`
(`app/notifications/infrastructure/repositories.py:37`) and nothing in the codebase sets
`SENT`, because the sender belongs to `access-notifications`. So the escalation is exercised
by marking the row `SENT` **in the test**, which is what that sender will do, and the change's
`BLOCKED.md` (OQ1) records that in production the escalation stays inert until then.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.domain.notifications import RELATED_TYPE_CLEANING_TASK
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.application.use_cases import EscalateBreachedSlasUseCase
from app.notifications.domain.enums import NotificationStatus, NotificationType
from app.notifications.infrastructure.models import NotificationLogModel
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.properties.domain.enums import PropertyOperationalState
from app.tenants.infrastructure.models import TenantConfigModel
from tests.cleaning.conftest import auth_header, insert_task

TASKS = "/api/v1/cleaning-tasks"
NOW = datetime.now(UTC)


async def _insert_cleaner(session, tenant, *, status=UserStatus.ACTIVE):
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Limpiadora",
        email=f"cleaner-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x" * 60,
        role=UserRole.CLEANER,
        status=status,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def task_a(db_session, tenant_a, property_a, template_a):
    property_a.current_operational_state = PropertyOperationalState.AWAITING_CLEANING
    db_session.add(property_a)
    task = await insert_task(db_session, tenant_a, property_a, template_a)
    await db_session.flush()
    return task


async def _logs_of(db_session, tenant_id):
    rows = await db_session.execute(
        select(NotificationLogModel)
        .where(NotificationLogModel.tenant_id == tenant_id)
        .order_by(NotificationLogModel.created_at, NotificationLogModel.id)
    )
    return list(rows.scalars())


# --- R6.1: the assignment notification --------------------------------------------


@pytest.mark.asyncio
async def test_manual_assignment_writes_the_notification_with_its_deadline(
    api, db_session, tenant_a, property_a, users_by_role_a, task_a
):
    cleaner = await _insert_cleaner(db_session, tenant_a)

    response = await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assert response.status_code == 200

    logs = await _logs_of(db_session, tenant_a.id)
    assert len(logs) == 1
    log = logs[0]
    assert log.notification_type == NotificationType.CLEANING_TASK_ASSIGNED.value
    assert log.recipient_user_id == cleaner.id
    assert log.recipient_contact == cleaner.email
    assert log.related_type == RELATED_TYPE_CLEANING_TASK
    assert log.related_id == task_a.id
    # `PENDING`, not `SENT`: nothing has been sent (design D9).
    assert log.status is NotificationStatus.PENDING
    assert log.sla_breached is False
    # R6.1: `TenantConfig.sla_medium_minutes`, default 240 (PRD §11).
    assert log.sla_deadline_at is not None
    assert timedelta(minutes=239) < (log.sla_deadline_at - log.created_at) < timedelta(
        minutes=241
    )


@pytest.mark.asyncio
async def test_the_deadline_follows_the_tenants_configured_sla(
    api, db_session, tenant_a, users_by_role_a, task_a
):
    db_session.add(TenantConfigModel(tenant_id=tenant_a.id, sla_medium_minutes=30))
    cleaner = await _insert_cleaner(db_session, tenant_a)
    await db_session.flush()

    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    log = (await _logs_of(db_session, tenant_a.id))[0]
    assert (log.sla_deadline_at - log.created_at) < timedelta(minutes=31)


@pytest.mark.asyncio
async def test_the_body_carries_ids_and_not_the_content_of_other_rows(
    api, db_session, tenant_a, property_a, users_by_role_a, task_a
):
    """Rule 11 — the contract `celery-jobs` fixed for `subject`/`body`, complied with.

    The reader follows `related_id`; the body does not forward another row's text. There is no
    access code near a cleaning assignment today, and this is the shape that keeps it so when
    somebody later wants to add the property's WiFi to the message.
    """
    cleaner = await _insert_cleaner(db_session, tenant_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    log = (await _logs_of(db_session, tenant_a.id))[0]
    assert str(task_a.id) in log.body
    assert str(property_a.id) in log.body
    assert cleaner.email not in log.body
    assert "password" not in log.body.lower()


# --- R6.3: nobody to assign -------------------------------------------------------


@pytest.mark.asyncio
async def test_no_cleaner_alerts_the_manager_without_a_deadline(
    db_session, tenant_a, template_a, users_by_role_a
):
    """PRD §11 "alertar a manager inmediatamente" — a deadline here would escalate the
    manager to the manager."""
    from app.properties.domain.transition_enums import PropertyStateTrigger
    from app.reservations.domain.enums import ReservationStatus
    from app.reservations.infrastructure.models import ReservationModel
    from tests.cleaning.conftest import insert_property
    from tests.cleaning.test_provisioning import NOW as PROVISION_NOW
    from tests.cleaning.test_provisioning import _advance

    # The roster fixture creates one user per role, so the tenant already has an active
    # cleaner. Deactivating them is what makes "nobody to assign" the case under test.
    users_by_role_a[UserRole.CLEANER].status = UserStatus.INACTIVE
    db_session.add(users_by_role_a[UserRole.CLEANER])

    property_ = await insert_property(db_session, tenant_a, code="NOCLEANER")
    property_.current_operational_state = PropertyOperationalState.OCCUPIED_ESTIMATED
    db_session.add(property_)
    db_session.add(
        ReservationModel(
            tenant_id=tenant_a.id,
            property_id=property_.id,
            channel="DIRECT",
            check_in_date=(PROVISION_NOW - timedelta(days=3)).date(),
            check_out_date=(PROVISION_NOW - timedelta(days=1)).date(),
            nights=2,
            status=ReservationStatus.CHECKED_IN_ESTIMATED,
        )
    )
    await db_session.flush()

    await _advance(db_session).execute(
        tenant_id=tenant_a.id,
        trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED,
        now=PROVISION_NOW,
    )

    logs = await _logs_of(db_session, tenant_a.id)
    assert logs, "the manager must be told there is nobody to assign"
    alert = logs[0]
    assert alert.notification_type == NotificationType.CLEANING_NO_RESPONSE.value
    assert alert.recipient_user_id == users_by_role_a[UserRole.PROPERTY_MANAGER].id
    assert alert.sla_deadline_at is None


# --- R6.4: answering does not write a second notification -------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["accept", "reject"])
async def test_answering_writes_no_second_assignment_notification(
    api, db_session, tenant_a, users_by_role_a, task_a, answer
):
    """R6.4, recorded honestly (design D9).

    What this change can do is **not write another row**. It cannot cancel the pending SLA:
    `NotificationLogRepository` exposes only `mark_breached`, deliberately narrow, and there is
    no candidate to cancel anyway while nothing marks a row `SENT`. Closing the deadline on an
    answer is `access-notifications`' work, and `BLOCKED.md` OQ1 says so.
    """
    cleaner = await _insert_cleaner(db_session, tenant_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    before = len(await _logs_of(db_session, tenant_a.id))

    response = await api.post(f"{TASKS}/{task_a.id}/{answer}", headers=auth_header(api, cleaner))
    assert response.status_code == 200

    assert len(await _logs_of(db_session, tenant_a.id)) == before


# --- R6.5: the escalation chain ---------------------------------------------------


@pytest.mark.asyncio
async def test_an_unanswered_assignment_escalates_to_the_manager(
    api, db_session, tenant_a, users_by_role_a, task_a
):
    """R6.5 — `CLEANING_TASK_ASSIGNED` → `SLA_BREACH` to the `PROPERTY_MANAGER`.

    That policy has existed since `celery-jobs` (`notifications/domain/escalation.py:53-57`)
    and has **never run**, because nothing wrote a row of that type. This change is its first
    writer.

    The `SENT` below is the test standing in for the sender of `access-notifications`: the job
    only considers logs it believes were delivered, and marking it here is what makes the rest
    of the chain observable without asserting a delivery that did not happen.
    """
    cleaner = await _insert_cleaner(db_session, tenant_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assignment = (await _logs_of(db_session, tenant_a.id))[0]

    assignment.status = NotificationStatus.SENT
    await db_session.flush()

    report = await EscalateBreachedSlasUseCase(
        notifications=SqlAlchemyNotificationLogRepository(db_session),
        users=SqlAlchemyUserRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    ).execute(
        tenant_id=tenant_a.id,
        now=assignment.sla_deadline_at + timedelta(minutes=1),
    )

    assert report.escalated == 1
    logs = await _logs_of(db_session, tenant_a.id)
    breach = [
        log for log in logs if log.notification_type == NotificationType.SLA_BREACH.value
    ]
    assert len(breach) == 1
    assert breach[0].recipient_user_id == users_by_role_a[UserRole.PROPERTY_MANAGER].id
    assert breach[0].related_id == assignment.id
    # The original is marked so the one-minute job does not escalate it again.
    assert assignment.sla_breached is True


@pytest.mark.asyncio
async def test_a_pending_assignment_is_not_a_breach_candidate(
    api, db_session, tenant_a, users_by_role_a, task_a
):
    """The measured gap of design D9, pinned so it cannot be forgotten.

    Without the `SENT` of the previous test the job finds nothing, however long ago the
    deadline passed. That is not a bug in this change — it is `access-notifications`' half of
    the chain, and `BLOCKED.md` OQ1 carries the decision.
    """
    cleaner = await _insert_cleaner(db_session, tenant_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assignment = (await _logs_of(db_session, tenant_a.id))[0]

    report = await EscalateBreachedSlasUseCase(
        notifications=SqlAlchemyNotificationLogRepository(db_session),
        users=SqlAlchemyUserRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    ).execute(
        tenant_id=tenant_a.id, now=assignment.sla_deadline_at + timedelta(days=7)
    )

    assert report.escalated == 0
    assert assignment.sla_breached is False
