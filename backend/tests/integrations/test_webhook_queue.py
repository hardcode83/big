"""The reading half of the webhook queue (`reservations-webhooks` R5.1, R5.3, R5.5, R1.8, D9, D11).

Integration against real Postgres, and it has to be: what these tests pin is the interaction
between the `attempts`/`next_attempt_at` predicates of D9 and the **global tenant filter**, and
neither is visible without a database. A fake session would assert the query this module happens
to build rather than the rows Postgres returns for it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_session_to_tenant
from app.integrations.domain.entities import (
    MAX_WEBHOOK_ATTEMPTS,
    PROVIDER_UNAVAILABLE,
    UNATTRIBUTED,
    WebhookEventFailure,
)
from app.integrations.infrastructure.models import WebhookEventModel
from app.integrations.infrastructure.repositories import SqlAlchemyWebhookEventRepository

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


async def _queued(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    received_at: datetime = NOW,
    processed: bool = False,
    attempts: int = 0,
    next_attempt_at: datetime | None = None,
) -> uuid.UUID:
    event = WebhookEventModel(
        tenant_id=tenant_id,
        provider="BEDS24",
        event_type="booking.modified",
        payload={"irrelevant": "the job never reads this"},
        received_at=received_at,
        processed=processed,
        attempts=attempts,
        next_attempt_at=next_attempt_at,
    )
    session.add(event)
    await session.flush()
    return event.id


@pytest.mark.asyncio
async def test_an_unattributed_notice_is_visible_to_the_queue_and_hidden_from_a_marked_session(
    db_session: AsyncSession, tenant_a
) -> None:
    """R5.5 and R1.8, and the reason D11 forbids reading the queue from a marked session.

    `webhook_events.tenant_id` is nullable, so the global filter's `tenant_id = X` predicate
    does not error on the `NULL` rows — it silently omits them. They are exactly the rows the
    job must reach in order to exhaust them, so a marked session would leave them pending
    forever with no symptom at all.
    """
    unattributed = await _queued(db_session)
    attributed = await _queued(db_session, tenant_id=tenant_a.id)
    repository = SqlAlchemyWebhookEventRepository(db_session)

    from_unmarked = await repository.select_pending(now=NOW, limit=10)

    assert {event.id for event in from_unmarked} == {unattributed, attributed}

    db_session.expunge_all()
    bind_session_to_tenant(db_session, tenant_a.id)
    from_marked = await repository.select_pending(now=NOW, limit=10)

    assert {event.id for event in from_marked} == {attributed}


@pytest.mark.asyncio
async def test_the_batch_carries_no_payload(db_session: AsyncSession, tenant_a) -> None:
    """D13: the body says nothing the job is allowed to act on, so it is not even selected."""
    await _queued(db_session, tenant_id=tenant_a.id)

    [event] = await SqlAlchemyWebhookEventRepository(db_session).select_pending(
        now=NOW, limit=10
    )

    assert not hasattr(event, "payload")
    assert event.provider == "BEDS24"
    assert event.attempts == 0


@pytest.mark.asyncio
async def test_a_processed_notice_is_not_selected(db_session: AsyncSession, tenant_a) -> None:
    await _queued(db_session, tenant_id=tenant_a.id, processed=True)

    assert await SqlAlchemyWebhookEventRepository(db_session).select_pending(
        now=NOW, limit=10
    ) == []


@pytest.mark.asyncio
async def test_an_exhausted_notice_is_not_selected(db_session: AsyncSession, tenant_a) -> None:
    """D9's middle predicate: `attempts < 3` is what stops a poisoned notice from being
    retried on every tick for ever."""
    await _queued(db_session, tenant_id=tenant_a.id, attempts=MAX_WEBHOOK_ATTEMPTS)

    assert await SqlAlchemyWebhookEventRepository(db_session).select_pending(
        now=NOW, limit=10
    ) == []


@pytest.mark.asyncio
async def test_a_notice_waiting_out_its_backoff_is_not_selected(
    db_session: AsyncSession, tenant_a
) -> None:
    due = await _queued(
        db_session,
        tenant_id=tenant_a.id,
        attempts=1,
        next_attempt_at=NOW - timedelta(seconds=1),
    )
    await _queued(
        db_session,
        tenant_id=tenant_a.id,
        attempts=1,
        next_attempt_at=NOW + timedelta(seconds=1),
    )

    pending = await SqlAlchemyWebhookEventRepository(db_session).select_pending(
        now=NOW, limit=10
    )

    assert [event.id for event in pending] == [due]


@pytest.mark.asyncio
async def test_the_batch_is_oldest_first_and_bounded(
    db_session: AsyncSession, tenant_a
) -> None:
    oldest = await _queued(
        db_session, tenant_id=tenant_a.id, received_at=NOW - timedelta(minutes=10)
    )
    middle = await _queued(
        db_session, tenant_id=tenant_a.id, received_at=NOW - timedelta(minutes=5)
    )
    await _queued(db_session, tenant_id=tenant_a.id, received_at=NOW)

    pending = await SqlAlchemyWebhookEventRepository(db_session).select_pending(
        now=NOW, limit=2
    )

    assert [event.id for event in pending] == [oldest, middle]


@pytest.mark.asyncio
async def test_marking_processed_clears_the_previous_failure(
    db_session: AsyncSession, tenant_a
) -> None:
    """A notice that finally lands is not still carrying the reason it did not, earlier."""
    event_id = await _queued(
        db_session,
        tenant_id=tenant_a.id,
        attempts=1,
        next_attempt_at=NOW - timedelta(minutes=1),
    )
    repository = SqlAlchemyWebhookEventRepository(db_session)
    await repository.record_failure(
        [event_id],
        failure=WebhookEventFailure(code=PROVIDER_UNAVAILABLE),
        next_attempt_at=NOW,
    )

    await repository.mark_processed([event_id], now=NOW)

    row = await db_session.get(WebhookEventModel, event_id)
    await db_session.refresh(row)
    assert row.processed is True
    assert row.processed_at == NOW
    assert row.error is None


@pytest.mark.asyncio
async def test_recording_a_failure_increments_attempts_in_sql(
    db_session: AsyncSession, tenant_a
) -> None:
    """The increment is `attempts + 1` in the UPDATE, never a value this process read first.

    Two runs that somehow overlapped would otherwise both write `attempts = 1`, and the retry
    budget of R5.3 would be spent twice over without ever reaching its ceiling.
    """
    event_id = await _queued(db_session, tenant_id=tenant_a.id, attempts=1)
    repository = SqlAlchemyWebhookEventRepository(db_session)
    retry_at = NOW + timedelta(minutes=2)

    await repository.record_failure(
        [event_id],
        failure=WebhookEventFailure(code=PROVIDER_UNAVAILABLE),
        next_attempt_at=retry_at,
    )

    row = await db_session.get(WebhookEventModel, event_id)
    await db_session.refresh(row)
    assert row.attempts == 2
    assert row.next_attempt_at == retry_at
    assert row.error == '{"code":"PROVIDER_UNAVAILABLE"}'
    # Still FALSE: R5.3 leaves a failed notice unprocessed with its cause, so the queue reads
    # as "these never landed" rather than as "these are done".
    assert row.processed is False


@pytest.mark.asyncio
async def test_exhausting_takes_a_notice_out_of_the_queue_for_good(
    db_session: AsyncSession,
) -> None:
    """D11's `tenant_id IS NULL` branch: counted, explained, and never selected again."""
    event_id = await _queued(db_session)
    repository = SqlAlchemyWebhookEventRepository(db_session)

    await repository.exhaust(
        [event_id], failure=WebhookEventFailure(code=UNATTRIBUTED, field="tenant_id")
    )

    assert await repository.select_pending(now=NOW, limit=10) == []
    stored = await db_session.scalar(
        select(WebhookEventModel.error).where(WebhookEventModel.id == event_id)
    )
    assert stored == '{"code":"UNATTRIBUTED","field":"tenant_id"}'


@pytest.mark.asyncio
async def test_the_write_methods_are_no_ops_on_an_empty_group(
    db_session: AsyncSession, tenant_a
) -> None:
    """An empty group is an ordinary outcome — a tenant whose whole batch failed elsewhere —
    and an unfiltered `UPDATE ... WHERE id IN ()` is the shape that would touch every row."""
    untouched = await _queued(db_session, tenant_id=tenant_a.id)
    repository = SqlAlchemyWebhookEventRepository(db_session)

    await repository.mark_processed([], now=NOW)
    await repository.record_failure(
        [], failure=WebhookEventFailure(code=PROVIDER_UNAVAILABLE), next_attempt_at=NOW
    )
    await repository.exhaust([], failure=WebhookEventFailure(code=UNATTRIBUTED))

    [event] = await repository.select_pending(now=NOW, limit=10)
    assert event.id == untouched
    assert event.attempts == 0
