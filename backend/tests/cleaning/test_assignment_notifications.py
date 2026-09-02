"""R6 — the notification an assignment produces, and the SLA chain it feeds.

**The gap this file used to document is closed.** It said the chain was inert because
`list_sla_breach_candidates` requires `status = SENT` and nothing in the codebase set it, so
the escalation could only be exercised by marking the row `SENT` in the test. The sender
arrived with `access-notifications`, and `dispatch_notifications` now writes that value in
production — which is also why answering an assignment has to **close** the deadline
(`access-notifications` R5, its design D7), a thing `cleaning` recorded as owed and could not
build.

The tests below still set `SENT` by hand rather than running the dispatcher: what they are
about is the escalation policy, and going through a channel adapter to get there would couple
them to `access-notifications`' delivery semantics. The end-to-end path is
`tests/notifications/test_escalate_slas.py`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.notifications import RELATED_TYPE_CLEANING_TASK
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.application.use_cases import EscalateBreachedSlasUseCase
from app.notifications.domain.enums import NotificationChannel, NotificationStatus, NotificationType
from app.notifications.infrastructure.models import NotificationLogModel
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.properties.domain.enums import PropertyOperationalState
from app.tenants.infrastructure.models import TenantConfigModel
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
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
async def test_manual_assignment_fans_out_across_the_tenants_enabled_channels(
    api, db_session, tenant_a, property_a, users_by_role_a, task_a
):
    """R1, R2 — the manual assignment path (unlike `_auto_assign`) used to bypass the
    resolver entirely and always write a single IN_APP row regardless of the tenant's
    flags. Exercised end to end (real HTTP → `AssignCleaningTaskUseCase` → `dispatch_and_
    persist`) precisely because that is the path the earlier unit-only coverage of
    `channel_dispatch.py` could not catch this bypass through.
    """
    config = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_a.id)
        )
    ).scalar_one()
    config.notification_email_enabled = True
    config.notification_whatsapp_enabled = True
    cleaner = await _insert_cleaner(db_session, tenant_a)
    cleaner.phone = "+34600000000"
    db_session.add(cleaner)
    await db_session.flush()

    response = await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assert response.status_code == 200

    logs = await _logs_of(db_session, tenant_a.id)
    by_channel = {log.channel: log for log in logs}
    assert set(by_channel) == {
        NotificationChannel.IN_APP,
        NotificationChannel.EMAIL,
        NotificationChannel.WHATSAPP,
    }
    assert by_channel[NotificationChannel.IN_APP].recipient_contact == cleaner.email
    assert by_channel[NotificationChannel.EMAIL].recipient_contact == cleaner.email
    assert by_channel[NotificationChannel.WHATSAPP].recipient_contact == cleaner.phone
    # R4.1 — only the IN_APP row carries the SLA deadline.
    assert by_channel[NotificationChannel.IN_APP].sla_deadline_at is not None
    assert by_channel[NotificationChannel.EMAIL].sla_deadline_at is None
    assert by_channel[NotificationChannel.WHATSAPP].sla_deadline_at is None
    assert all(log.status is NotificationStatus.PENDING for log in logs)


@pytest.mark.asyncio
async def test_the_deadline_follows_the_tenants_configured_sla(
    api, db_session, tenant_a, users_by_role_a, task_a
):
    # `insert_tenant` (tests/auth/conftest.py) already seeds a `TenantConfigModel` row with
    # the channel flags pinned off — update it rather than inserting a second one, which
    # would collide with the unique constraint on `tenant_id`.
    config = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_a.id)
        )
    ).scalar_one()
    config.sla_medium_minutes = 30
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
    """R6.4, first half: answering does not produce another assignment row."""
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


# --- access-notifications R5: answering CLOSES the deadline -----------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["accept", "reject"])
async def test_answering_closes_the_assignment_deadline(
    api, db_session, tenant_a, users_by_role_a, task_a, answer
):
    """R5.1 — the second half of `cleaning`'s R6.4, paid by `access-notifications`.

    `cleaning` could only promise not to write a second row; cancelling the deadline needed a
    port method that did not exist and a `SENT` writer that did not exist either. Both landed
    with the sender, so the promise is now testable: after an answer the row has no deadline
    at all.
    """
    cleaner = await _insert_cleaner(db_session, tenant_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assignment = (await _logs_of(db_session, tenant_a.id))[0]
    assert assignment.sla_deadline_at is not None

    response = await api.post(f"{TASKS}/{task_a.id}/{answer}", headers=auth_header(api, cleaner))
    assert response.status_code == 200

    await db_session.refresh(assignment)
    assert assignment.sla_deadline_at is None
    # And nothing else moved: design D7 keeps the port narrow precisely so an answer cannot
    # claim a breach (`sla_breached`) or deny a delivery (`status`).
    assert assignment.sla_breached is False
    assert assignment.notification_type == NotificationType.CLEANING_TASK_ASSIGNED.value


@pytest.mark.asyncio
async def test_a_task_with_no_assignment_row_is_answered_without_error(
    api, db_session, tenant_a, users_by_role_a, task_a
):
    """R5.3 — zero rows cleared is the normal case, not a failure.

    A task assigned before this change exists in production with no deadline to cancel, and a
    cleaner accepting it must get a 200, not a 500.
    """
    cleaner = await _insert_cleaner(db_session, tenant_a)
    task_a.assigned_cleaner_id = cleaner.id
    task_a.status = CleaningTaskStatus.ASSIGNED
    await db_session.flush()
    assert await _logs_of(db_session, tenant_a.id) == []

    response = await api.post(f"{TASKS}/{task_a.id}/accept", headers=auth_header(api, cleaner))

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_a_deadline_already_closed_is_left_alone(
    api, db_session, tenant_a, users_by_role_a, task_a
):
    """R5.3, the idempotent half: answering twice changes nothing the second time."""
    cleaner = await _insert_cleaner(db_session, tenant_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assignment = (await _logs_of(db_session, tenant_a.id))[0]
    await api.post(f"{TASKS}/{task_a.id}/accept", headers=auth_header(api, cleaner))
    await db_session.refresh(assignment)
    assert assignment.sla_deadline_at is None
    before = len(await _logs_of(db_session, tenant_a.id))

    # A second acceptance is refused by the task's own state machine, so the path that
    # matters is the reject that follows — either way nothing about the closed row changes.
    await api.post(f"{TASKS}/{task_a.id}/reject", headers=auth_header(api, cleaner))

    await db_session.refresh(assignment)
    assert assignment.sla_deadline_at is None
    assert assignment.sla_breached is False
    assert len(await _logs_of(db_session, tenant_a.id)) == before


@pytest.mark.asyncio
async def test_an_answered_assignment_never_escalates(
    api, db_session, tenant_a, users_by_role_a, task_a
):
    """R5.4, and the whole reason this change inherited the debt.

    The row is marked `SENT` — which the dispatcher now really does in production — so it
    *would* be a breach candidate. Answering removes it, and the job finds nothing however
    long after the original deadline it runs.
    """
    cleaner = await _insert_cleaner(db_session, tenant_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assignment = (await _logs_of(db_session, tenant_a.id))[0]
    deadline = assignment.sla_deadline_at
    assignment.status = NotificationStatus.SENT
    await db_session.flush()

    await api.post(f"{TASKS}/{task_a.id}/accept", headers=auth_header(api, cleaner))

    report = await EscalateBreachedSlasUseCase(
        notifications=SqlAlchemyNotificationLogRepository(db_session),
        users=SqlAlchemyUserRepository(db_session),
        tenant_configs=SqlAlchemyTenantConfigRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    ).execute(tenant_id=tenant_a.id, now=deadline + timedelta(days=7))

    assert report.breached == 0
    assert report.escalated == 0
    logs = await _logs_of(db_session, tenant_a.id)
    assert [log for log in logs if log.notification_type == NotificationType.SLA_BREACH.value] == []


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
        tenant_configs=SqlAlchemyTenantConfigRepository(db_session),
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
    """`PENDING` is queued work, not a missed deadline — pinned so it stays that way.

    This used to document a gap: nothing wrote `SENT`, so the job found nothing however long
    ago the deadline passed. `access-notifications` closed it, and the invariant that
    survives is narrower and permanent: a notification **nobody has been sent yet** cannot
    have been ignored, so it is never a breach candidate. The clock on a cleaner's answer
    starts when they are told, which is what `dispatch_notifications` records.
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
        tenant_configs=SqlAlchemyTenantConfigRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    ).execute(
        tenant_id=tenant_a.id, now=assignment.sla_deadline_at + timedelta(days=7)
    )

    assert report.escalated == 0
    assert assignment.sla_breached is False
