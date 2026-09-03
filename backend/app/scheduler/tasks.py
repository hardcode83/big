"""The periodic Celery tasks (`celery-jobs` R1, design D2).

Thin by design: take the lock, wire the use case to a session the runner owns, return the
report. No rules live here — this is the scheduler's equivalent of a FastAPI router.

**Four of PRD §8.3, plus one that is not in it.** The four carry the PRD's names literally —
`check_checkin_windows`, `process_checkouts`, `mark_occupied_estimated`, `check_sla_breaches`
— and run the same per-tenant loop. The fifth, `process_webhook_events`, arrived with
`reservations-webhooks`: the PRD never named it because §16 describes the queue without a
drainer, and its shape differs too — it reads a queue first and only then knows which tenants
it concerns, so it takes the lock through `_locked` without going through `_guarded`.

**And one that runs daily rather than on a period**: `generate_price_recommendations`
(`revenue-pricing` R4.1). It is the ordinary per-tenant shape, with one difference that
matters — its lock TTL comes from `DAILY_JOBS`, not from `lock_ttl_for`, because cadence x 3
on a daily job is three days of wedge after a dead worker (D8).

**And one that runs monthly**: `generate_owner_statements` (`revenue-statements` R1.1, D11).
Same per-tenant shape as the daily job, but its lock TTL comes from `MONTHLY_JOBS` for the
same reason — `lock_ttl_for` would not even know what cadence to derive from. The
`actor=None` it passes the generator is what makes the path exempt from `AuditLog` under
the sixth named exception to rule 9 of `steering/security.md` (D5/D12); the
`TimelineEvent OWNER_STATEMENT_GENERATED` the generator emits is the trail.
"""

import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

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
from app.notifications.application.use_cases import (
    DispatchPendingNotificationsUseCase,
    EscalateBreachedSlasUseCase,
)
from app.notifications.infrastructure.adapters import adapter_registry
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.pricing.application.use_cases import GeneratePriceRecommendationsUseCase
from app.pricing.infrastructure.repositories import (
    SqlAlchemyPriceRecommendationRepository,
    SqlAlchemyPricingRuleRepository,
)
from app.reviews.application.use_cases import ClassifyPendingReviewsUseCase
from app.reviews.domain.ports import (
    AIReviewAnalyzer,
    AIReviewDraftGenerator,
)
from app.reviews.infrastructure.ai import MockReviewAnalyzer, MockReviewDraftGenerator
from app.reviews.infrastructure.repositories import (
    SqlAlchemyReviewRepository,
    SqlAlchemyReviewResponseDraftRepository,
)
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
from app.scheduler.schedule import CADENCES, DAILY_JOBS, MONTHLY_JOBS
from app.statements.application.use_cases import GenerateOwnerStatementUseCase
from app.statements.application.reconciliation import (
    ReconcileOwnerApprovalsForExpensesUseCase,
)
from app.statements.infrastructure.repositories import (
    SqlAlchemyExpenseRepository,
    SqlAlchemyOwnerStatementRepository,
)
from app.statements.infrastructure.reconciliation import (
    SqlAlchemyReconciliationStore,
)
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository
from app.maintenance.application.use_cases import (
    ClassifyIncidentUseCase,
    ClassifyPendingIncidentsUseCase,
)
from app.maintenance.infrastructure.classifier import RuleBasedIncidentClassifier
from app.maintenance.infrastructure.repositories import (
    SqlAlchemyIncidentReader,
    SqlAlchemyIncidentRepository,
    SqlAlchemyLiveCleaningTaskQuery,
)
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
        tenant_configs=SqlAlchemyTenantConfigRepository(session),
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


async def _classify_incidents(session: AsyncSession, tenant_id, now: datetime):
    use_case = ClassifyPendingIncidentsUseCase(
        reader=SqlAlchemyIncidentReader(session),
        classify=ClassifyIncidentUseCase(
            classifier=RuleBasedIncidentClassifier(),
            configs=SqlAlchemyTenantConfigRepository(session),
            # R1: the nightly classification is the path that most needs to notify — there
            # is no human watching it, which is the whole reason the gap was worth closing.
            users=SqlAlchemyUserRepository(session),
            notifications=SqlAlchemyNotificationLogRepository(session),
            incidents=SqlAlchemyIncidentRepository(session),
            reader=SqlAlchemyIncidentReader(session),
            properties=SqlAlchemyPropertyRepository(session),
            transitions=SqlAlchemyPropertyStateTransitionRepository(session),
            timeline=SqlAlchemyTimelineEventRepository(session),
            reservations=SqlAlchemyReservationRepository(session),
            cleaning_tasks=SqlAlchemyLiveCleaningTaskQuery(session),
            audit=SqlAlchemyAuditLogRepository(session),
            uow=SqlAlchemyUnitOfWork(session),
        ),
        batch_size=settings.notification_batch_size,
    )
    return await use_case.execute(tenant_id=tenant_id, now=now)


async def _classify_reviews(
    session: AsyncSession,
    tenant_id,
    now: datetime,
    *,
    analyzer: AIReviewAnalyzer,
    draft_generator: AIReviewDraftGenerator,
):
    """`revenue-reviews` (R2, design D2, D16): put every unclassified `NEW` review
    through the pipeline.

    Same shape as `classify_incidents`: the use case commits per-review, the loop walks
    the tenant, and a tenant whose pipeline is down all night still keeps what it
    classified so far. `MockReviewAnalyzer` and `MockReviewDraftGenerator` are the
    only implementers this change ships; a real provider replaces them at the same
    wiring point.
    """
    use_case = ClassifyPendingReviewsUseCase(
        reviews=SqlAlchemyReviewRepository(session),
        drafts=SqlAlchemyReviewResponseDraftRepository(session),
        analyzer=analyzer,
        draft_generator=draft_generator,
        configs=SqlAlchemyTenantConfigRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
    return await use_case.execute(tenant_id=tenant_id, now=now)


async def _generate_price_recommendations(session: AsyncSession, tenant_id, now: datetime):
    """`revenue-pricing` R4.1: the whole portfolio's 60-day horizon, once a day.

    No `property_id` — the sweep is the point — and `actor=None`, which is what makes the run
    anonymous and therefore exempt from `AuditLog` under the fifth named exception to rule 9
    of `steering/security.md`. The endpoint of the same use case passes an actor and is not
    exempt.
    """
    use_case = GeneratePriceRecommendationsUseCase(
        rules=SqlAlchemyPricingRuleRepository(session),
        recommendations=SqlAlchemyPriceRecommendationRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        # R4.5 — the nightly sweep writes the same row the HTTP route does; it is the path
        # with no human watching, which is why the notification matters most here.
        users=SqlAlchemyUserRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        tenant_configs=SqlAlchemyTenantConfigRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
    return await use_case.execute(tenant_id=tenant_id, now=now, property_id=None, actor=None)


async def _generate_owner_statements(session: AsyncSession, tenant_id, now: datetime):
    """`revenue-statements` R1.1, D5, D11: every property's monthly liquidation.

    No `property_id` — the sweep is the point — and `actor=None`, which is what makes the
    run anonymous and therefore exempt from `AuditLog` under the **sixth** named exception
    to rule 9 of `steering/security.md` (D5/D12). The endpoint `POST /owner-statements/generate`
    of the same use case passes an actor and is not exempt. The `TimelineEvent
    OWNER_STATEMENT_GENERATED` the generator emits per property is the trail for the clock path.

    `period_end` is left to the use case's default — `Period.previous_month(today=now.date())` —
    so a run on 1 August at 02:00 UTC always targets the closed July period, deterministically.
    """
    use_case = GenerateOwnerStatementUseCase(
        statements=SqlAlchemyOwnerStatementRepository(session),
        expenses=SqlAlchemyExpenseRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
    return await use_case.execute(tenant_id=tenant_id, now=now, property_id=None, actor=None)


async def _reconcile_owner_approvals_for_expenses(
    session: AsyncSession, tenant_id, now: datetime
):
    """`revenue-statements` R5.7, design D4: materialise owner answers on `expenses`.

    The use case runs every five minutes; the SQL is idempotent on row state, so a faster
    cadence would buy nothing but a tighter feedback loop on the manager screen. `now` is
    accepted to keep the signature parallel with the other per-tenant use cases; the
    reconciliation does not filter on it (D4: there is no cursor and no temporal window —
    the JOIN on `responded_at IS NOT NULL` plus the row-state guards is the contract).
    """

    async def _commit() -> None:
        await session.commit()

    return await ReconcileOwnerApprovalsForExpensesUseCase(
        store=SqlAlchemyReconciliationStore(session),
        commit=_commit,
    ).execute(now=now)


async def _locked(name: str, ttl: timedelta, run, *, skipped) -> dict:
    """Take the lock, run `run()`, and always return a serialisable report.

    Losing the lock is `skipped`, not a failure (R4.2): the previous run is still doing the
    work, and a Celery task that raised would look like a broken job to anyone reading the
    worker's log.

    Split out from `_guarded` when `process_webhook_events` arrived: that job is not a
    per-tenant loop — it reads a queue first and only then knows which tenants it concerns
    (`reservations-webhooks` D11) — but it needs exactly the same mutual exclusion. `skipped`
    is the report to hand back on contention, and it differs per job because the reports do.

    **The TTL arrives already computed** rather than derived from a cadence here, since
    `generate_price_recommendations` joined: a daily job has no cadence to derive from, and
    the derivation that is right for the periodic jobs is precisely wrong for it
    (`revenue-pricing` D8). One lock mechanism; `_guarded` and `_guarded_daily` are the two
    ways of sizing it.
    """
    async with worker_redis() as redis:
        async with task_lock(redis, name, ttl) as acquired:
            if not acquired:
                logger.info("scheduler.skipped_locked", extra={"task": name})
                return asdict(skipped)
            return asdict(await run())


async def _guarded(name: str, cadence: timedelta, work) -> dict:
    """The per-tenant shape: lock, then run `work` once for every active tenant."""
    return await _locked(
        name,
        lock_ttl_for(cadence),
        lambda: run_for_every_tenant(name, work),
        skipped=TenantRunReport(task=name, skipped_locked=True),
    )


async def _guarded_daily(name: str, work) -> dict:
    """`_guarded` for a job on `DAILY_JOBS`, whose TTL is written down instead of derived.

    A separate entry point rather than a parameter on `_guarded`, so the seven periodic jobs
    keep passing the cadence they always passed: D8 rejected its alternative precisely because
    it "toca las siete tareas vivas y sus TTL derivados para acomodar la octava".
    """
    return await _locked(
        name,
        DAILY_JOBS[name].lock_ttl,
        lambda: run_for_every_tenant(name, work),
        skipped=TenantRunReport(task=name, skipped_locked=True),
    )


async def _guarded_monthly(name: str, work) -> dict:
    """`_guarded` for a job on `MONTHLY_JOBS`, whose TTL is written down instead of derived.

    A separate entry point, parallel to `_guarded_daily` (`revenue-statements` design D11):
    a monthly job has no cadence to derive from, and `lock_ttl_for` would either fail or
    give a number that has nothing to do with the run. The TTL comes from the entry in
    `MONTHLY_JOBS`, just like the daily job's comes from `DAILY_JOBS`.
    """
    return await _locked(
        name,
        MONTHLY_JOBS[name].lock_ttl,
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
    """PRD §14, every minute: escalate notifications whose SLA deadline has passed.

    **Inert until `access-notifications` shipped**, and worth recording because the
    behaviour of this task changed without its code changing: `list_sla_breach_candidates`
    requires `status = SENT`, and until `dispatch_notifications` existed nothing ever wrote
    that value, so every run found zero candidates.
    """
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
            lock_ttl_for(CADENCES[WEBHOOK_TASK]),
            _process_webhook_events,
            skipped=WebhookProcessingReport(skipped_locked=True),
        )
    )


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


@celery_app.task(name="classify_incidents")
def classify_incidents() -> dict:
    """PRD §12, every 5 min: put every unlooked-at `OPEN` incident through the classifier.

    Not one of PRD §8.3's four — see the divergence note in `schedule.py`. It is a job and
    not part of the request that opens the incident, and `maintenance`'s design D2 gives
    three reasons, of which the first is security: the only writer of `incidents` in `OPEN`
    today is **an anonymous request from the internet** (the guest portal), so hanging the
    classifier off that request is the shape rule 12(d) of `steering/security.md` forbids —
    "la re-lectura por API desacoplada del volumen de peticiones" — and with a real AI
    provider behind the port it would be a per-request cost a third party decides.

    The second reason is R1.6: "never lose it" is free for a job that re-reads whatever is
    still `OPEN`, and expensive for a `try/except` inline.
    """
    return run_sync(
        _guarded("classify_incidents", CADENCES["classify_incidents"], _classify_incidents)
    )


REVIEW_TASK = "classify_reviews"


@celery_app.task(name=REVIEW_TASK)
def classify_reviews() -> dict:
    """`revenue-reviews` (R2, design D2): every `NEW` review through the pipeline.

    Same cadence and same reasoning as `classify_incidents` — PRD §18 declares the
    pipeline and says nothing about what triggers it, and the day a real AI provider
    sits behind the port, the cadence is the ceiling on what it is asked.

    The mocks are constructed here, at the wiring point, and a real provider replaces
    them here too: `MockReviewAnalyzer` and `MockReviewDraftGenerator` are the only
    implementers this change ships (`EXTERNAL_DEPENDENCY`).
    """
    return run_sync(
        _guarded(
            REVIEW_TASK,
            CADENCES[REVIEW_TASK],
            lambda session, tenant_id, now: _classify_reviews(
                session,
                tenant_id,
                now,
                analyzer=MockReviewAnalyzer(),
                draft_generator=MockReviewDraftGenerator(),
            ),
        )
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


PRICING_TASK = "generate_price_recommendations"


@celery_app.task(name=PRICING_TASK)
def generate_price_recommendations() -> dict:
    """PRD §8.3, daily at 06:00 UTC: every property's 60-day price horizon.

    The only daily job on the calendar, so it is the only one whose lock TTL does not come
    from a cadence: `DAILY_JOBS` carries three hours explicitly, because `lock_ttl_for` on a
    daily job would be three days and a worker killed mid-run would wedge it for three
    windows (`revenue-pricing` D8).

    Idempotent by construction rather than by luck, which is what makes a repeated run safe
    (R4.2): the writer upserts on `(property_id, date)` and its `ON CONFLICT` predicate
    refuses to touch a recommendation a person has already approved or applied (D9). So beat
    firing twice, or an operator re-running it by hand, re-prices the undecided days and
    leaves the decided ones exactly as the manager left them.
    """
    return run_sync(_guarded_daily(PRICING_TASK, _generate_price_recommendations))


# --- `revenue-statements`: monthly liquidation + owner-approval reconciliation ----------


STATEMENTS_MONTHLY_TASK = "generate_owner_statements"


@celery_app.task(name=STATEMENTS_MONTHLY_TASK)
def generate_owner_statements() -> dict:
    """`revenue-statements` R1.1, D11: every property's monthly liquidation, day 1 at 02:00 UTC.

    The only monthly job on the calendar, so it is the only one whose lock TTL does not
    come from a cadence or from `lock_ttl_for`: `MONTHLY_JOBS` carries six hours explicitly,
    because deriving a TTL from a non-existent cadence would either fail or give a number
    unrelated to the run, and the next monthly window would have to wait that long after a
    dead worker (`revenue-statements` D11).

    Idempotent by construction (R1.3, R2.3): `find_by_unique_key` short-circuits when the
    `(tenant, property, period_start, period_end)` already has a row, and the manual path
    through `POST /owner-statements/generate` does the same lookup before it inserts. So a
    late beat firing, a manual re-run by an operator, or the clock firing twice for any
    reason all leave the existing statement exactly as it was and count the candidate in
    `skipped`, not `failed`.
    """
    return run_sync(
        _guarded_monthly(STATEMENTS_MONTHLY_TASK, _generate_owner_statements)
    )


STATEMENTS_RECONCILE_TASK = "reconcile_owner_approvals_for_expenses"


@celery_app.task(name=STATEMENTS_RECONCILE_TASK)
def reconcile_owner_approvals_for_expenses() -> dict:
    """`revenue-statements` R5.7, design D4: every 5 minutes, materialise owner answers.

    Idempotent by SQL row-state guard, not by external state — D4 deliberately rejected a
    Redis cursor so a slow approval landing while a tick is running is caught by the next
    tick's JOIN. The lock TTL comes from `CADENCES` (cadence x 3), because the cadence
    exists and the derivation is right for this job (the converse of the daily/monthly jobs).
    """
    return run_sync(
        _guarded(
            STATEMENTS_RECONCILE_TASK,
            CADENCES[STATEMENTS_RECONCILE_TASK],
            _reconcile_owner_approvals_for_expenses,
        )
    )
