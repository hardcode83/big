"""The one task the WhatsApp receiver dispatches (`whatsapp-cloud-adapter` D7, task 7.4).

**A module of its own, under `app/scheduler/`, and both halves of that are forced.** Under
`app/scheduler/` because `tests/test_layering.py` lets only `app/worker.py` and
`app/scheduler/**` import Celery — a task decorator anywhere else is how business rules end up
depending on a broker. Its own module rather than a tenth function in `tasks.py` because
everything in that file is clock-driven: it is organised around `CADENCES`, `_guarded`,
`_locked` and `lock_ttl_for`, and none of those apply to a task that fires once per inbound
message. Mixing them would invite the next reader to give this one a cadence.

**No `beat_schedule` entry, deliberately** (design D7). `.delay(event_id)` is the only thing
that starts it, from `app/messaging/api/dependencies.py`'s dispatcher, immediately after the
receiving route's transaction commits. `ON_DEMAND_TASKS` in `app/scheduler/schedule.py` is
where that absence is declared, so the guard that every registered task has a calendar entry
stays meaningful instead of being loosened.

**No `task_lock` either**, unlike every job in `tasks.py`. Those take one because two
overlapping runs of a *cadence* would each burn an attempt on the same rows; here the unit of
work is a single event, and its claim is a conditional `UPDATE ... WHERE processed_at IS NULL`
on that one row (`mark_processed`). A Redis lock would be a second, weaker answer to the same
question — and a global one, so two guests' messages could not be processed at once.

**Two sessions, and the order matters.** The event is located on a session that was NEVER
marked, because the row is what says which tenant the message belongs to and because its
`tenant_id` may be `NULL` (a delivery for an unprovisioned number, which is never dispatched
but may still be looked up). The work then runs in a session marked for that tenant, opened by
`run_in_marked_session` — the same two-phase shape `process_webhook_events` uses, and for the
same reason its docstring gives.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.unit_of_work import CallerOwnedUnitOfWork, SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.maintenance.application.use_cases import ReportIncidentFromConversationUseCase
from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository
from app.messaging.application.use_cases import ProcessInboundGuestMessageUseCase
from app.messaging.application.whatsapp_inbound import PostWhatsAppInboundMessageUseCase
from app.messaging.domain.entities import InboundWhatsAppEvent
from app.messaging.infrastructure.ai import MockAIAdapter
from app.messaging.infrastructure.channels import outbound_registry
from app.messaging.infrastructure.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
    SqlAlchemyWhatsAppInboundEventRepository,
)
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.scheduler.runner import run_in_marked_session, run_sync, worker_session_factory
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository
from app.worker import celery_app

logger = logging.getLogger(__name__)

#: The task's registered name, spelled once. `app/scheduler/schedule.py` declares the same
#: string in `ON_DEMAND_TASKS`, and the guard in `tests/scheduler/test_schedule.py` compares
#: the two — so a rename that misses one of them is red rather than a task nobody can find.
WHATSAPP_INBOUND_TASK = "process_inbound_whatsapp_message"


def _use_case(session: AsyncSession) -> PostWhatsAppInboundMessageUseCase:
    """Section 5's use case, wired the way `app/messaging/api/dependencies.py` wires it.

    Built here rather than imported from that module: `api/` is the request delivery layer and
    `scheduler/` is this one's, so reaching across would make one delivery layer depend on
    another's wiring — the shape `test_the_scheduler_never_reaches_into_a_domains_internals`
    exists to keep out of this package. Every collaborator below is a repository or an
    application-layer use case, which is exactly what `app/scheduler/tasks.py` already
    composes for the nine clock-driven jobs.

    `CallerOwnedUnitOfWork` for the incident port, and `SqlAlchemyUnitOfWork` for the
    pipeline: the single commit stays the pipeline's (`messaging-ai` R4.7), so an incident
    opened from this message cannot land without the message that opened it.
    """
    messages = SqlAlchemyMessageRepository(session)
    pipeline = ProcessInboundGuestMessageUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        messages=messages,
        ai=MockAIAdapter(),
        # The same instance `outbound_registry` needs to resolve the 24 h session window
        # (R2.4, D2) — not a second one.
        channels=outbound_registry(messages),
        incidents=ReportIncidentFromConversationUseCase(
            incidents=SqlAlchemyIncidentRepository(session),
            audit=SqlAlchemyAuditLogRepository(session),
            timeline=SqlAlchemyTimelineEventRepository(session),
            uow=CallerOwnedUnitOfWork(),
        ),
        timeline=SqlAlchemyTimelineEventRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        users=SqlAlchemyUserRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
    return PostWhatsAppInboundMessageUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        pipeline=pipeline,
    )


async def _locate(event_id: uuid.UUID) -> InboundWhatsAppEvent | None:
    """The event, read from a session that is never marked.

    Its own short-lived session, closed before any tenant work begins, exactly as
    `list_active_tenants` opens one for the tenant list: nothing of a tenant's domain data is
    ever read through it, and it cannot start to be, because it does not outlive this call.
    """
    async with worker_session_factory()() as session:
        return await SqlAlchemyWhatsAppInboundEventRepository(
            session
        ).locate_without_tenant_scoping(event_id)


async def _run(session: AsyncSession, event: InboundWhatsAppEvent, now: datetime) -> bool:
    """Claim the event, then run section 5's resolution. One transaction, one commit.

    The claim goes **first and in the same transaction** as the work: `mark_processed` is a
    conditional `UPDATE`, so a second run of the same task finds nothing to claim and returns
    without touching the conversation — and a failure anywhere below rolls the claim back with
    it, leaving the event retryable. Doing it the other way round would either process twice
    or, with a separate commit, mark an event processed that then failed.

    `tenant_id` is not `None` here: the caller checked `is_resolved` before opening this
    session, which is also what gave it a tenant to mark the session with.
    """
    assert event.tenant_id is not None and event.default_property_id is not None
    claimed = await SqlAlchemyWhatsAppInboundEventRepository(session).mark_processed(
        event.tenant_id, event.id, now=now
    )
    if not claimed:
        logger.info(
            "messaging.whatsapp_inbound_already_processed",
            extra={"event_id": str(event.id), "tenant_id": str(event.tenant_id)},
        )
        return False

    await _use_case(session).execute(
        tenant_id=event.tenant_id,
        default_property_id=event.default_property_id,
        inbound_message=event.message,
        now=now,
    )
    return True


async def _process_inbound_whatsapp_message(event_id: uuid.UUID) -> dict:
    now = datetime.now(UTC)
    event = await _locate(event_id)

    if event is None:
        # Not worth retrying for ever: the row is gone, so there is nothing to process and no
        # amount of redelivery will bring it back. Logged at `warning` because the only ways
        # to get here are a demo reset mid-flight and a bug of ours.
        logger.warning(
            "messaging.whatsapp_inbound_event_missing", extra={"event_id": str(event_id)}
        )
        return {"event_id": str(event_id), "processed": False, "reason": "missing"}

    if not event.is_resolved:
        # The receiver never dispatches one of these (R3.3 as amended: an unprovisioned
        # number is recorded and left alone), so arriving here means something else called
        # this task. Refused rather than guessed at: there is no tenant to run it for.
        logger.warning(
            "messaging.whatsapp_inbound_event_unresolved", extra={"event_id": str(event_id)}
        )
        return {"event_id": str(event_id), "processed": False, "reason": "unresolved"}

    result = await run_in_marked_session(
        WHATSAPP_INBOUND_TASK,
        event.tenant_id,
        lambda session: _run(session, event, now),
    )
    if result.failed:
        # `run_in_marked_session` has already rolled the session back and logged the
        # traceback with the tenant id. The claim went down with it, so the event is still
        # unprocessed and a retry — Meta's, or a manual one — can pick it up.
        return {"event_id": str(event_id), "processed": False, "reason": "failed"}
    return {"event_id": str(event_id), "processed": bool(result.value)}


@celery_app.task(name=WHATSAPP_INBOUND_TASK)
def process_inbound_whatsapp_message(event_id: str) -> dict:
    """One inbound WhatsApp message, through the pipeline the portal already uses (D7, R5.1).

    Takes the id as a **string** because Celery serialises arguments as JSON, which has no
    UUID; the dispatcher stringifies it and this parses it back. A malformed id raises here,
    which is right — it can only be a bug in the dispatcher, and a silent `return` would hide
    it in a worker log.
    """
    return run_sync(_process_inbound_whatsapp_message(uuid.UUID(event_id)))
