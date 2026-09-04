"""R4.7, against a real transaction rather than against a commit counter.

**Why this file exists separately from `test_use_cases.py`.** That file drives the pipeline
against in-memory fakes, and its atomicity test can only assert `uow.commits == 0` — the fakes
keep their rows whatever happens, so they can never demonstrate the thing R4.7 actually
promises: "un fallo no deje el mensaje persistido sin evento de timeline ni la conversación
escalada sin notificación". The QA panel of sections 5-6 pointed out that the assertion was a
proxy for the claim and not the claim.

So this drives the **real** adapters over the **real** session, forces a failure part-way
through the pipeline, and then reads back through a **second, independent session** — the only
vantage point from which "it never landed" is a fact rather than a hope.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.unit_of_work import CallerOwnedUnitOfWork, SqlAlchemyUnitOfWork
from app.messaging.application.use_cases import ProcessInboundGuestMessageUseCase
from app.messaging.domain.enums import ConversationChannel, ConversationStatus
from app.messaging.domain.exceptions import PMSChannelUnavailableError
from app.messaging.domain.value_objects import InboundMessageActor
from app.messaging.infrastructure.ai import MockAIAdapter
from app.messaging.infrastructure.channels import outbound_registry
from app.messaging.infrastructure.models import ConversationModel, MessageModel
from app.messaging.infrastructure.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
)
from app.audit.infrastructure.models import AuditLogModel
from app.maintenance.infrastructure.models import IncidentModel
from app.notifications.infrastructure.models import NotificationLogModel
from app.timeline.domain.enums import TimelineActorType
from app.timeline.infrastructure.models import TimelineEventModel
from tests.messaging.conftest import (
    NOW,
    seed_conversation,
    seed_property,
    seed_tenant,
    seed_user,
)

pytestmark = pytest.mark.asyncio

#: A message that trips **both** branches at once, which is what the two escalation tests
#: below need — and finding one takes care. "sangre" is an emergency keyword of
#: `escalation.py` but **not** a keyword of `MockAIAdapter`'s `EMERGENCY` row, so the
#: classifier falls through to `MAINTENANCE_ISSUE` ("caldera", "rota") while the escalation
#: policy fires on the word itself. A message saying "humo" would classify as `EMERGENCY` and
#: open no incident, which is how the first draft of these tests quietly tested nothing.
ESCALATES_AND_OPENS_AN_INCIDENT = "Hay sangre y la caldera esta rota"


class ExplodingIncidentPort:
    """An `IncidentReportingPort` that fails, to reach the **other** failure shape of R4.7.

    The channel-less conversation below fails inside the reply branch, which a message that
    escalates never enters — so without this there is no test in which the escalation's own
    writes (the conversation's new status, its timeline event, the manager's notification) are
    in the session when something goes wrong. The QA panel of sections 7-9 pointed that out:
    the assertion "no notification rows" was true for want of ever having tried to write one.
    """

    async def report(self, **_: object) -> uuid.UUID:
        raise RuntimeError("incident reporting failed after the conversation escalated")


def build_pipeline(
    session: AsyncSession, *, channels, incidents=None
) -> ProcessInboundGuestMessageUseCase:
    """The real wiring, with only the channel registry and the incident port under control."""
    from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
    from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
    from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
    from app.maintenance.application.use_cases import (
        ReportIncidentFromConversationUseCase,
    )
    from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository
    from app.notifications.infrastructure.repositories import (
        SqlAlchemyNotificationLogRepository,
    )
    from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
    from app.reservations.infrastructure.repositories import (
        SqlAlchemyReservationRepository,
    )
    from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
    from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

    return ProcessInboundGuestMessageUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        messages=SqlAlchemyMessageRepository(session),
        ai=MockAIAdapter(),
        channels=channels,
        incidents=incidents
        or ReportIncidentFromConversationUseCase(
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


async def count_rows(engine, model) -> int:
    """Read through a **second session**, which is the whole point: the first one's uncommitted
    work is invisible from here, so a non-zero count means the row really landed."""
    async with AsyncSession(engine) as observer:
        return int(await observer.scalar(select(func.count()).select_from(model)) or 0)


async def test_the_whole_pipeline_lands_together(db_session, test_engine) -> None:
    """The positive control. Without it, the failure test below would pass against a pipeline
    that writes nothing at all."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    manager = await seed_user(db_session, tenant, "manager@example.com")
    conversation = await seed_conversation(
        db_session, tenant, prop, channel=ConversationChannel.MANUAL
    )
    tenant_id, conversation_id, actor_id = tenant.id, conversation.id, manager.id
    await db_session.commit()

    pipeline = build_pipeline(
        db_session, channels=outbound_registry(SqlAlchemyMessageRepository(db_session))
    )
    await pipeline.execute(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        content="El wifi no funciona",
        actor=InboundMessageActor(user_id=actor_id, ip=None),
        now=NOW,
    )

    assert await count_rows(test_engine, MessageModel) == 2
    assert await count_rows(test_engine, TimelineEventModel) == 2


async def test_a_failure_part_way_through_leaves_nothing_behind(
    db_session, test_engine
) -> None:
    """**R4.7 as a fact about the database.**

    The conversation is on `BOOKING_MSG`, which has no outbound adapter (R6.3), so the
    pipeline raises *after* it has written the guest's message and its timeline event into the
    session. Nothing commits, the transaction is rolled back, and a second session sees none
    of it — which is what "no deje el mensaje persistido sin evento de timeline" means.

    Asserted on `messages`, `timeline_events` **and** `notification_logs`, because R4.7 names
    two failure shapes and the third table is where the second one would show up.
    """
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    manager = await seed_user(db_session, tenant, "manager@example.com")
    conversation = await seed_conversation(
        db_session, tenant, prop, channel=ConversationChannel.BOOKING_MSG
    )
    tenant_id, conversation_id, actor_id = tenant.id, conversation.id, manager.id
    await db_session.commit()

    before = await count_rows(test_engine, MessageModel)
    pipeline = build_pipeline(
        db_session, channels=outbound_registry(SqlAlchemyMessageRepository(db_session))
    )

    with pytest.raises(PMSChannelUnavailableError):
        await pipeline.execute(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            content="El wifi no funciona",
            actor=InboundMessageActor(user_id=actor_id, ip=None),
            now=NOW,
        )
    await db_session.rollback()

    assert await count_rows(test_engine, MessageModel) == before
    assert await count_rows(test_engine, TimelineEventModel) == 0
    assert await count_rows(test_engine, NotificationLogModel) == 0


async def test_an_escalation_is_not_left_half_written_by_a_later_failure(
    db_session, test_engine
) -> None:
    """**The second failure shape R4.7 names**: "ni la conversación escalada sin notificación".

    The message trips an emergency keyword *and* classifies as a maintenance issue, so the
    pipeline escalates — writing the conversation's new status, its `AI_ESCALATED_TO_HUMAN`
    event and the manager's `GUEST_ESCALATION` row — and then opens an incident, which is
    where this test makes it fail. Everything the escalation wrote is in the session at that
    moment, and none of it may survive.

    Without it the suite only ever failed inside the *reply* branch, which a message that
    escalates never enters: the "no notification rows" assertion was true for want of ever
    having tried to write one.
    """
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    manager = await seed_user(db_session, tenant, "manager@example.com")
    conversation = await seed_conversation(
        db_session, tenant, prop, channel=ConversationChannel.MANUAL
    )
    tenant_id, conversation_id, actor_id = tenant.id, conversation.id, manager.id
    await db_session.commit()

    pipeline = build_pipeline(
        db_session,
        channels=outbound_registry(SqlAlchemyMessageRepository(db_session)),
        incidents=ExplodingIncidentPort(),
    )
    with pytest.raises(RuntimeError):
        await pipeline.execute(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            content=ESCALATES_AND_OPENS_AN_INCIDENT,
            actor=InboundMessageActor(user_id=actor_id, ip=None),
            now=NOW,
        )
    await db_session.rollback()

    assert await count_rows(test_engine, NotificationLogModel) == 0
    assert await count_rows(test_engine, TimelineEventModel) == 0
    assert await count_rows(test_engine, MessageModel) == 0
    async with AsyncSession(test_engine) as observer:
        row = (
            await observer.execute(
                select(
                    ConversationModel.status, ConversationModel.escalation_status
                ).where(ConversationModel.id == conversation_id)
            )
        ).one()
    assert row.status is ConversationStatus.OPEN
    assert row.escalation_status.value == "NONE"


async def test_the_escalation_path_really_does_write_all_three_rows(
    db_session, test_engine
) -> None:
    """The positive control for the test above: without it, that one would pass against a
    pipeline whose escalation branch wrote nothing at all."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    manager = await seed_user(db_session, tenant, "manager@example.com")
    conversation = await seed_conversation(
        db_session, tenant, prop, channel=ConversationChannel.MANUAL
    )
    tenant_id, conversation_id, actor_id = tenant.id, conversation.id, manager.id
    await db_session.commit()

    pipeline = build_pipeline(
        db_session, channels=outbound_registry(SqlAlchemyMessageRepository(db_session))
    )
    await pipeline.execute(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        content=ESCALATES_AND_OPENS_AN_INCIDENT,
        actor=InboundMessageActor(user_id=actor_id, ip=None),
        now=NOW,
    )

    assert await count_rows(test_engine, NotificationLogModel) == 1
    assert await count_rows(test_engine, MessageModel) == 1
    # The guest's message, the escalation and the derived incident.
    assert await count_rows(test_engine, TimelineEventModel) == 3


async def test_the_conversation_is_not_left_half_moved_by_a_failure(
    db_session, test_engine
) -> None:
    """The other half of R4.7: `register_message` and `save` run before the failure, so
    without the transaction the inbox would show a conversation whose `last_message_at` points
    at a message that does not exist."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    manager = await seed_user(db_session, tenant, "manager@example.com")
    conversation = await seed_conversation(
        db_session, tenant, prop, channel=ConversationChannel.AIRBNB_MSG
    )
    # Captured before the rollback below: a rollback expires every instance of the session, so
    # reading `conversation.id` afterwards would trigger a refresh — synchronous IO from an
    # async test, which asyncpg answers with `MissingGreenlet` rather than a value.
    tenant_id, conversation_id, actor_id = tenant.id, conversation.id, manager.id
    await db_session.commit()

    pipeline = build_pipeline(
        db_session, channels=outbound_registry(SqlAlchemyMessageRepository(db_session))
    )
    with pytest.raises(PMSChannelUnavailableError):
        await pipeline.execute(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            content="El wifi no funciona",
            actor=InboundMessageActor(user_id=actor_id, ip=None),
            now=NOW,
        )
    await db_session.rollback()

    async with AsyncSession(test_engine) as observer:
        # Columns and not the entity: hydrating an ORM object here would attach it to a
        # session this test is about to close, and the assertions would then be reads against
        # a detached instance rather than against the database.
        row = (
            await observer.execute(
                select(
                    ConversationModel.last_message_at, ConversationModel.status
                ).where(ConversationModel.id == conversation_id)
            )
        ).one()

    assert row.last_message_at is None
    assert row.status is ConversationStatus.OPEN


# --- The second actor, against real persistence (`guest-portal-messaging` R4.1, D8) --------


async def read_one(engine, model):
    """The single row of `model`, read through a second session like `count_rows` above."""
    async with AsyncSession(engine) as observer:
        return (await observer.execute(select(model))).scalars().one()


async def test_a_token_bearer_drives_the_whole_pipeline_and_is_named_in_every_row(
    db_session, test_engine
) -> None:
    """R4.1 against the real adapters, not against fakes.

    `tests/maintenance/test_report_incident_from_conversation.py` covers both branches of the
    derivation, but over in-memory repositories — so it cannot speak to what the database
    accepts. The column this branch fills, `audit_logs.actor_guest_token_hash`, carries a
    CHECK constraint (`ck_audit_logs_actor_guest_token_hash_is_a_digest`) that only a real
    INSERT can exercise, and `actor_user_id` goes NULL on a table where the other branch
    always fills it. This is the same argument the module docstring above makes for R4.7: an
    assertion over fakes is a proxy for the claim and not the claim.

    The QA panel of section 2 found that every call site in this file passed a user actor, so
    the token-bearer half of R4.1 was proven nowhere against real persistence.
    """
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    await seed_user(db_session, tenant, "manager@example.com")
    conversation = await seed_conversation(
        db_session, tenant, prop, channel=ConversationChannel.MANUAL
    )
    tenant_id, conversation_id = tenant.id, conversation.id
    await db_session.commit()

    digest = "c" * 64
    pipeline = build_pipeline(
        db_session, channels=outbound_registry(SqlAlchemyMessageRepository(db_session))
    )
    await pipeline.execute(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        content=ESCALATES_AND_OPENS_AN_INCIDENT,
        actor=InboundMessageActor(token_hash=digest, ip="203.0.113.7"),
        now=NOW,
    )

    # The pipeline ran whole: the guest's message, the escalation and the derived incident.
    assert await count_rows(test_engine, MessageModel) == 1
    assert await count_rows(test_engine, TimelineEventModel) == 3
    assert await count_rows(test_engine, IncidentModel) == 1

    entry = await read_one(test_engine, AuditLogModel)
    assert entry.actor_guest_token_hash == digest
    assert entry.actor_user_id is None
    assert entry.actor_ip == "203.0.113.7"

    incident = await read_one(test_engine, IncidentModel)
    assert incident.reported_by_guest_token == digest
    assert incident.reported_by_user_id is None

    # The third derivation. `TimelineEventFactory` admits `actor_user_id` only alongside
    # `USER`, so a branch that picked `USER` here would have to claim a user that does not
    # exist — asserted rather than left to that factory, because "it would have raised" is
    # not the same as "it chose correctly".
    async with AsyncSession(test_engine) as observer:
        actors = set(
            (await observer.execute(select(TimelineEventModel.actor_type))).scalars().all()
        )
    # `USER not in actors` is the load-bearing half and the reason this reads the whole set.
    # `GUEST in actors` would hold anyway — `GUEST_MESSAGE_RECEIVED` hardcodes `GUEST` for
    # every actor — so it is kept only as a positive control that the events were written at
    # all. What it cannot catch, and this can: a branch naming some *other* user, which is
    # internally consistent and so passes `TimelineEventFactory` untouched. The QA panel of
    # section 2 drew that distinction.
    assert TimelineActorType.GUEST in actors
    assert TimelineActorType.USER not in actors
