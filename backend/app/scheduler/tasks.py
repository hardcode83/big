"""The four Celery tasks of PRD §8.3 (`celery-jobs` R1, design D2).

Thin by design: take the lock, wire the use case to a session the runner owns, return the
report. No rules live here — this is the scheduler's equivalent of a FastAPI router.

Names are the PRD's, literally: `check_checkin_windows`, `process_checkouts`,
`mark_occupied_estimated`, `check_sla_breaches`.
"""

import logging
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.application.use_cases import ProvisionAccessRecordsUseCase
from app.access.infrastructure.adapters import ManualAccessAdapter
from app.access.infrastructure.repositories import SqlAlchemyAccessRecordRepository
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.application.use_cases import ProvisionCleaningTaskUseCase
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyCleaningChecklistTemplateRepository,
    SqlAlchemyCleaningTaskRepository,
)
from app.core.config import settings
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.legal import SqlAlchemyLegalRegistrationInitialiser
from app.notifications.application.use_cases import (
    DispatchPendingNotificationsUseCase,
    EscalateBreachedSlasUseCase,
)
from app.notifications.infrastructure.adapters import adapter_registry
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.properties.application.use_cases import AdvancePropertyStatesUseCase
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.scheduler.locks import lock_ttl_for, task_lock
from app.scheduler.runner import (
    TenantRunReport,
    run_for_every_tenant,
    run_sync,
    worker_redis,
)
from app.scheduler.schedule import CADENCES
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository
from app.worker import celery_app

logger = logging.getLogger(__name__)


def _cleaning_provisioner(session: AsyncSession) -> ProvisionCleaningTaskUseCase:
    """Only `process_checkouts` builds one (`cleaning` design D1).

    It shares the session, and therefore the transaction, with the use case that calls it —
    which is the whole point of R2.3: the transition and the `CleaningTask` are one write or
    neither.
    """
    return ProvisionCleaningTaskUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(session),
        templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        users=SqlAlchemyUserRepository(session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
    )


async def _advance(session: AsyncSession, tenant_id, now: datetime, *, trigger):
    use_case = AdvancePropertyStatesUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
        provisioner=(
            _cleaning_provisioner(session)
            if trigger is PropertyStateTrigger.CHECKOUT_TIME_REACHED
            else None
        ),
    )
    return await use_case.execute(tenant_id=tenant_id, trigger=trigger, now=now)


async def _escalate(session: AsyncSession, tenant_id, now: datetime):
    use_case = EscalateBreachedSlasUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session),
        users=SqlAlchemyUserRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
    return await use_case.execute(tenant_id=tenant_id, now=now)


async def _provision_access(session: AsyncSession, tenant_id, now: datetime):
    use_case = ProvisionAccessRecordsUseCase(
        records=SqlAlchemyAccessRecordRepository(session),
        provider=ManualAccessAdapter(),
        timeline=SqlAlchemyTimelineEventRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        legal=SqlAlchemyLegalRegistrationInitialiser(session),
        uow=SqlAlchemyUnitOfWork(session),
        batch_size=settings.notification_batch_size,
    )
    return await use_case.execute(tenant_id=tenant_id, now=now)


async def _dispatch(session: AsyncSession, tenant_id, now: datetime):
    use_case = DispatchPendingNotificationsUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session),
        adapters=adapter_registry(),
        uow=SqlAlchemyUnitOfWork(session),
        max_attempts=settings.notification_max_attempts,
        batch_size=settings.notification_batch_size,
    )
    return await use_case.execute(tenant_id=tenant_id, now=now)


async def _guarded(name: str, cadence: timedelta, work) -> dict:
    """Take the lock, run for every tenant, and always return a serialisable report.

    Losing the lock is `skipped`, not a failure (R4.2): the previous run is still doing the
    work, and a Celery task that raised would look like a broken job to anyone reading the
    worker's log.
    """
    async with worker_redis() as redis:
        async with task_lock(redis, name, lock_ttl_for(cadence)) as acquired:
            if not acquired:
                logger.info("scheduler.skipped_locked", extra={"task": name})
                return asdict(TenantRunReport(task=name, skipped_locked=True))
            report = await run_for_every_tenant(name, work)
            return asdict(report)


def _clock_task(name: str, trigger: PropertyStateTrigger):
    async def work(session, tenant_id, now):
        return await _advance(session, tenant_id, now, trigger=trigger)

    return _guarded(name, CADENCES[name], work)


@celery_app.task(name="check_checkin_windows")
def check_checkin_windows() -> dict:
    """PRD §8.3, every 5 min: a confirmed reservation entering its check-in window."""
    return run_sync(
        _clock_task("check_checkin_windows", PropertyStateTrigger.CHECKIN_WINDOW_OPENED)
    )


@celery_app.task(name="mark_occupied_estimated")
def mark_occupied_estimated() -> dict:
    """PRD §8.3, every 5 min: the check-in hour has arrived."""
    return run_sync(
        _clock_task("mark_occupied_estimated", PropertyStateTrigger.CHECKIN_TIME_REACHED)
    )


@celery_app.task(name="process_checkouts")
def process_checkouts() -> dict:
    """PRD §8.3, every 5 min: the checkout hour has passed.

    Transitions to `AWAITING_CLEANING` **and creates the `CleaningTask`**, both in one
    transaction — the second half arrived with the `cleaning` change (its R2), which is also
    what stopped `AWAITING_CLEANING` from being a terminal state in practice. The creation
    honours `TenantConfig.auto_create_cleaning_task` and `Reservation.cleaning_required`, and
    a transition without a task is counted apart in the report (`transitioned_without_task`).
    """
    return run_sync(
        _clock_task("process_checkouts", PropertyStateTrigger.CHECKOUT_TIME_REACHED)
    )


@celery_app.task(name="check_sla_breaches")
def check_sla_breaches() -> dict:
    """PRD §14, every minute: escalate notifications whose SLA deadline has passed.

    **Inert until `access-notifications` shipped**, and worth recording because the
    behaviour of this task changed without its code changing: `list_sla_breach_candidates`
    requires `status = SENT`, and until `dispatch_notifications` existed nothing ever wrote
    that value, so every run found zero candidates.
    """
    return run_sync(_guarded("check_sla_breaches", CADENCES["check_sla_breaches"], _escalate))


@celery_app.task(name="dispatch_notifications")
def dispatch_notifications() -> dict:
    """PRD §14, every minute: deliver the notifications sitting in `PENDING`.

    Not one of PRD §8.3's four — see the divergence note in `schedule.py`. The lock is the
    same `task_lock` the others take, and it is what makes design D4's at-least-once bound
    hold: two overlapping runs would each burn their own attempt on the same row.
    """
    return run_sync(
        _guarded("dispatch_notifications", CADENCES["dispatch_notifications"], _dispatch)
    )


@celery_app.task(name="provision_access_records")
def provision_access_records() -> dict:
    """PRD §15, every 5 min: give every confirmed reservation its access record.

    Not one of PRD §8.3's four — see the divergence note in `schedule.py`. A **sweep** rather
    than a hook on the confirmation, and `access-notifications` design D2 says why: there are
    already confirmed reservations in the database, and a hook would only ever cover future
    ones.

    Also carries PRD §17 step 1 (`legal_registration_status = PENDING_GUEST_DATA`), which
    answers the same question about the same rows.
    """
    return run_sync(
        _guarded(
            "provision_access_records",
            CADENCES["provision_access_records"],
            _provision_access,
        )
    )
