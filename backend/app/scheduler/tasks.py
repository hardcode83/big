"""The four Celery tasks of PRD §8.3 (`celery-jobs` R1, design D2).

Thin by design: take the lock, wire the use case to a session the runner owns, return the
report. No rules live here — this is the scheduler's equivalent of a FastAPI router.

Names are the PRD's, literally: `check_checkin_windows`, `process_checkouts`,
`mark_occupied_estimated`, `check_sla_breaches`.
"""

import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.application.use_cases import ProvisionCleaningTaskUseCase
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyCleaningChecklistTemplateRepository,
    SqlAlchemyCleaningTaskRepository,
)
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
from app.integrations.application.webhooks import (
    ProcessTenantWebhookEventsUseCase,
    ProcessWebhookEventsUseCase,
    WebhookProcessingReport,
)
from app.integrations.infrastructure.pms_factory import SqlAlchemyPMSAdapterFactory
from app.integrations.infrastructure.repositories import (
    SqlAlchemyPmsCredentialRepository,
    SqlAlchemyWebhookEventRepository,
)
from app.notifications.application.use_cases import EscalateBreachedSlasUseCase
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
    run_in_marked_session,
    run_sync,
    worker_redis,
    worker_session_factory,
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


async def _locked(name: str, cadence: timedelta, run, *, skipped) -> dict:
    """Take the lock, run `run()`, and always return a serialisable report.

    Losing the lock is `skipped`, not a failure (R4.2): the previous run is still doing the
    work, and a Celery task that raised would look like a broken job to anyone reading the
    worker's log.

    Split out from `_guarded` when `process_webhook_events` arrived: that job is not a
    per-tenant loop — it reads a queue first and only then knows which tenants it concerns
    (`reservations-webhooks` D11) — but it needs exactly the same mutual exclusion. `skipped`
    is the report to hand back on contention, and it differs per job because the reports do.
    """
    async with worker_redis() as redis:
        async with task_lock(redis, name, lock_ttl_for(cadence)) as acquired:
            if not acquired:
                logger.info("scheduler.skipped_locked", extra={"task": name})
                return asdict(skipped)
            return asdict(await run())


async def _guarded(name: str, cadence: timedelta, work) -> dict:
    """The per-tenant shape: lock, then run `work` once for every active tenant."""
    return await _locked(
        name,
        cadence,
        lambda: run_for_every_tenant(name, work),
        skipped=TenantRunReport(task=name, skipped_locked=True),
    )


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
    """PRD §14, every minute: escalate notifications whose SLA deadline has passed."""
    return run_sync(_guarded("check_sla_breaches", CADENCES["check_sla_breaches"], _escalate))


# --- `reservations-webhooks`: the queue a stranger fills and only this drains ----------------

WEBHOOK_TASK = "process_webhook_events"


def _webhook_tenant_use_case(
    session: AsyncSession, tenant_id: uuid.UUID
) -> ProcessTenantWebhookEventsUseCase:
    """One tenant's processing, wired to the session the runner just marked for it.

    Everything below the provider is real, and the re-read is
    `SyncReservationsFromPmsUseCase` rather than a second implementation of it — D14: that use
    case already feeds `ReservationIngestor` as the single upsert route and already records
    credential reads at the granularity rule 9 narrows by name.
    """
    return ProcessTenantWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(session),
        sync=SyncReservationsFromPmsUseCase(
            factory=SqlAlchemyPMSAdapterFactory(
                credentials=SqlAlchemyPmsCredentialRepository(session)
            ),
            reservations=SqlAlchemyReservationRepository(session),
            properties=SqlAlchemyPropertyRepository(session),
            guests=SqlAlchemyGuestRepository(session),
            timeline=SqlAlchemyTimelineEventRepository(session),
            uow=SqlAlchemyUnitOfWork(session),
            audit=SqlAlchemyAuditLogRepository(session),
        ),
        # `AdvancePropertyStatesUseCase` unmodified, satisfying `PropertyStateAdvancer`
        # structurally (D12). No provisioner: that collaborator belongs to the checkout
        # trigger, and this job's trigger is a cancellation before check-in.
        advance=AdvancePropertyStatesUseCase(
            properties=SqlAlchemyPropertyRepository(session),
            reservations=SqlAlchemyReservationRepository(session),
            transitions=SqlAlchemyPropertyStateTransitionRepository(session),
            timeline=SqlAlchemyTimelineEventRepository(session),
            configs=SqlAlchemyTenantConfigRepository(session),
            uow=SqlAlchemyUnitOfWork(session),
        ),
        uow=SqlAlchemyUnitOfWork(session),
    )


async def _run_webhook_tenant(tenant_id, events, now):
    result = await run_in_marked_session(
        WEBHOOK_TASK,
        tenant_id,
        lambda session: _webhook_tenant_use_case(session, tenant_id).execute(
            tenant_id=tenant_id, events=events, now=now
        ),
    )
    # `None` is what the batch use case reads as "this tenant rolled back, charge its notices
    # a retry on your own session". The runner has already logged the traceback.
    return None if result.failed else result.value


async def _process_webhook_events() -> WebhookProcessingReport:
    now = datetime.now(UTC)
    # NEVER marked, and that is R5.5 rather than a convention: `webhook_events.tenant_id` is
    # nullable, and a marked session's global filter hides the `NULL` rows without erroring —
    # the rows D11 exists to exhaust. Each tenant's own work then gets its own marked session,
    # opened by `run_in_marked_session`, never this one.
    async with worker_session_factory()() as session:
        return await ProcessWebhookEventsUseCase(
            queue=SqlAlchemyWebhookEventRepository(session),
            run_for_tenant=_run_webhook_tenant,
            uow=SqlAlchemyUnitOfWork(session),
        ).execute(now=now)


@celery_app.task(name=WEBHOOK_TASK)
def process_webhook_events() -> dict:
    """`reservations-webhooks` R5.1, every 60 s: turn queued notices into reservations.

    Not a PRD §8.3 job — it arrives with the webhook receiver, and its cadence is what bounds
    the outbound API traffic (see `CADENCES`).
    """
    return run_sync(
        _locked(
            WEBHOOK_TASK,
            CADENCES[WEBHOOK_TASK],
            _process_webhook_events,
            skipped=WebhookProcessingReport(skipped_locked=True),
        )
    )
