"""The retry budget of a queued notice (`reservations-webhooks` R5.3, R1.8, D9, D11, PRD §16).

Two halves, and they are tested apart because they can fail apart. The **spacing** is a pure
domain rule with a real invariant, so it is unit-tested against `webhook_retry_delay`
(`steering/testing.md`: TDD in `domain/` with a real invariant). The **ceiling** is a property
of a SQL predicate meeting a row, so it is exercised by driving the same notice through repeated
executions against real Postgres — the only way to prove the fourth attempt does not happen is
to try to make it happen.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.integrations.application.webhooks import (
    BATCH_LEASE,
    ProcessWebhookEventsUseCase,
    TenantWebhookOutcome,
)
from app.integrations.domain.entities import (
    MAX_WEBHOOK_ATTEMPTS,
    RETRY_BASE_DELAY,
    webhook_retry_delay,
)
from app.integrations.infrastructure.models import WebhookEventModel
from app.integrations.infrastructure.repositories import SqlAlchemyWebhookEventRepository

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


# --- The spacing is a domain rule ------------------------------------------------------------


def test_the_wait_doubles_with_every_failed_attempt() -> None:
    """"Backoff exponencial" of PRD §16, as an invariant rather than three magic numbers."""
    delays = [webhook_retry_delay(attempts) for attempts in (1, 2, 3)]

    assert delays == [RETRY_BASE_DELAY, RETRY_BASE_DELAY * 2, RETRY_BASE_DELAY * 4]
    assert all(later > earlier for earlier, later in zip(delays, delays[1:]))


def test_a_delay_before_the_first_failure_is_a_programming_error() -> None:
    """`attempts` is the count AFTER the failure being recorded, so zero cannot be asked for.

    Loud rather than clamped: a caller passing the count from BEFORE the failure would get a
    plausible-looking `RETRY_BASE_DELAY / 2` and shift every subsequent wait, which is a bug no
    assertion downstream would notice.
    """
    with pytest.raises(ValueError):
        webhook_retry_delay(0)


# --- The ceiling is a property of the queue --------------------------------------------------


async def _failing_notice(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    event = WebhookEventModel(
        tenant_id=tenant_id,
        provider="MOCK",
        event_type="booking.modified",
        payload={},
        received_at=NOW,
    )
    session.add(event)
    await session.flush()
    await session.commit()
    return event.id


def _always_failing_batch(db_session: AsyncSession) -> ProcessWebhookEventsUseCase:
    """A run in which every tenant's transaction rolls back, so every notice is charged."""

    async def run_for_tenant(tenant_id, events, now):
        return None

    return ProcessWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(db_session),
        run_for_tenant=run_for_tenant,
        uow=SqlAlchemyUnitOfWork(db_session),
    )


@pytest.mark.asyncio
async def test_three_attempts_happen_with_growing_spacing_and_the_fourth_does_not(
    db_session: AsyncSession, tenant_a
) -> None:
    """R5.3 end to end, driven by the clock rather than asserted about it.

    Each tick runs at the exact instant the previous failure scheduled, which is the earliest a
    retry may be picked up. The notice is therefore selected as often as the rules allow, and
    what the assertions record is where that stops.
    """
    event_id = await _failing_notice(db_session, tenant_a.id)
    use_case = _always_failing_batch(db_session)
    scheduled: list[datetime] = []
    at = NOW

    # Four ticks for three attempts: the fourth is the one that must find nothing to do.
    for _ in range(4):
        report = await use_case.execute(now=at)
        if report.selected == 0:
            break
        row = await db_session.get(WebhookEventModel, event_id)
        await db_session.refresh(row)
        scheduled.append(row.next_attempt_at)
        at = row.next_attempt_at

    row = await db_session.get(WebhookEventModel, event_id)
    await db_session.refresh(row)
    assert row.attempts == MAX_WEBHOOK_ATTEMPTS
    assert len(scheduled) == MAX_WEBHOOK_ATTEMPTS
    gaps = [slot - anchor for slot, anchor in zip(scheduled, [NOW, *scheduled])]
    assert gaps == [RETRY_BASE_DELAY, RETRY_BASE_DELAY * 2, RETRY_BASE_DELAY * 4]
    # And the fourth: not "it failed again", but "it was never selected".
    assert (await use_case.execute(now=at + timedelta(days=1))).selected == 0


@pytest.mark.asyncio
async def test_an_exhausted_notice_is_not_reselected_on_every_tick(
    db_session: AsyncSession, tenant_a
) -> None:
    """The poisoned-queue mitigation of the design's risk list, checked over many ticks.

    `attempts < 3` is what makes an exhausted notice free rather than merely unsuccessful: a
    dead row that kept being selected would consume the batch, and every healthy notice behind
    it would wait for a provider that is never coming back.
    """
    event_id = await _failing_notice(db_session, tenant_a.id)
    use_case = _always_failing_batch(db_session)
    at = NOW

    for _ in range(MAX_WEBHOOK_ATTEMPTS):
        await use_case.execute(now=at)
        row = await db_session.get(WebhookEventModel, event_id)
        await db_session.refresh(row)
        at = row.next_attempt_at

    for tick in range(10):
        assert (
            await use_case.execute(now=at + timedelta(hours=tick + 1))
        ).selected == 0


@pytest.mark.asyncio
async def test_a_notice_is_invisible_until_its_wait_has_passed(
    db_session: AsyncSession, tenant_a
) -> None:
    """Without this the backoff would be decorative: the notice would be re-picked on the very
    next tick and the three attempts would be spent inside three minutes."""
    event_id = await _failing_notice(db_session, tenant_a.id)
    use_case = _always_failing_batch(db_session)

    await use_case.execute(now=NOW)
    row = await db_session.get(WebhookEventModel, event_id)
    await db_session.refresh(row)

    assert (await use_case.execute(now=row.next_attempt_at - timedelta(seconds=1))).selected == 0
    assert (await use_case.execute(now=row.next_attempt_at)).selected == 1


@pytest.mark.asyncio
async def test_notices_with_different_histories_get_different_slots(
    db_session: AsyncSession, tenant_a
) -> None:
    """`_schedule_retry` groups by CURRENT `attempts` (R5.3, D9).

    Two notices that fail together in the same group can have failed a different number of
    times before, and the backoff is a function of that history. Issuing one statement for the
    whole group would give the veteran the newcomer's slot — a silent shortening of its wait,
    which is the one way an exponential backoff stops being exponential. Nothing pinned this
    until the QA panel of this section asked for it.
    """
    fresh = WebhookEventModel(
        tenant_id=tenant_a.id,
        provider="MOCK",
        event_type="booking.modified",
        payload={},
        received_at=NOW,
        attempts=0,
    )
    veteran = WebhookEventModel(
        tenant_id=tenant_a.id,
        provider="MOCK",
        event_type="booking.modified",
        payload={},
        received_at=NOW,
        attempts=1,
    )
    db_session.add_all([fresh, veteran])
    await db_session.flush()
    await db_session.commit()

    await _always_failing_batch(db_session).execute(now=NOW)

    await db_session.refresh(fresh)
    await db_session.refresh(veteran)
    assert (fresh.attempts, veteran.attempts) == (1, 2)
    # First failure waits one base delay; the second waits two.
    assert fresh.next_attempt_at == NOW + RETRY_BASE_DELAY
    assert veteran.next_attempt_at == NOW + RETRY_BASE_DELAY * 2


@pytest.mark.asyncio
async def test_the_batch_is_claimed_before_any_work_begins(
    db_session: AsyncSession, tenant_a
) -> None:
    """R6.2 and D10: the outbound-call ceiling must not depend on the Redis lock's TTL.

    `select_pending` takes no row lock, so two overlapping runs would otherwise select the SAME
    notices and each re-read the same destination — and runs CAN overlap, because `task_lock`'s
    TTL is finite by design (`celery-jobs` D9 prefers expiry to a permanent wedge). The lease is
    what makes a concurrent run see the claim instead of the rows. Found by the security panel
    of this section.
    """
    event_id = await _failing_notice(db_session, tenant_a.id)
    claimed: list[int] = []

    async def run_for_tenant(tenant_id, events, now):
        # Mid-run: a second execution starting here must find nothing to do.
        concurrent = await SqlAlchemyWebhookEventRepository(db_session).select_pending(
            now=now, limit=10
        )
        claimed.append(len(concurrent))
        return TenantWebhookOutcome(processed=0)

    await ProcessWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(db_session),
        run_for_tenant=run_for_tenant,
        uow=SqlAlchemyUnitOfWork(db_session),
    ).execute(now=NOW)

    assert claimed == [0], "a concurrent run could still see the leased batch"
    # The claim costs the notice no retry budget: a run that dies mid-batch must not spend an
    # attempt the notice never got.
    row = await db_session.get(WebhookEventModel, event_id)
    await db_session.refresh(row)
    assert row.attempts == 0
    assert row.next_attempt_at == NOW + BATCH_LEASE


@pytest.mark.asyncio
async def test_the_lease_lapses_so_a_dead_runs_batch_is_not_stranded(
    db_session: AsyncSession, tenant_a
) -> None:
    """The other half of the trade: a claim nobody releases must expire on its own."""
    await _failing_notice(db_session, tenant_a.id)
    reached: list[datetime] = []

    async def dies(tenant_id, events, now):
        reached.append(now)
        raise RuntimeError("the worker died before recording anything")

    use_case = ProcessWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(db_session),
        run_for_tenant=dies,
        uow=SqlAlchemyUnitOfWork(db_session),
    )
    with pytest.raises(RuntimeError):
        await use_case.execute(now=NOW)

    assert reached == [NOW]
    # Still claimed a moment before the lease ends: nothing reached the runner.
    assert (
        await use_case.execute(now=NOW + BATCH_LEASE - timedelta(seconds=1))
    ).selected == 0
    assert reached == [NOW]

    # And the moment it lapses, the batch is workable again — the claim expired on its own,
    # with the retry budget untouched, so nothing was stranded by the death of its owner.
    lapsed = NOW + BATCH_LEASE
    with pytest.raises(RuntimeError):
        await use_case.execute(now=lapsed)
    assert reached == [NOW, lapsed]


@pytest.mark.asyncio
async def test_a_notice_that_succeeds_after_failing_keeps_no_debt(
    db_session: AsyncSession, tenant_a
) -> None:
    """A retry that lands is a success, not a success with an asterisk."""
    event_id = await _failing_notice(db_session, tenant_a.id)
    await _always_failing_batch(db_session).execute(now=NOW)
    row = await db_session.get(WebhookEventModel, event_id)
    await db_session.refresh(row)

    async def run_for_tenant(tenant_id, events, now):
        await SqlAlchemyWebhookEventRepository(db_session).mark_processed(
            [event.id for event in events], now=now
        )
        await db_session.commit()
        return TenantWebhookOutcome(processed=len(events))

    report = await ProcessWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(db_session),
        run_for_tenant=run_for_tenant,
        uow=SqlAlchemyUnitOfWork(db_session),
    ).execute(now=row.next_attempt_at)

    assert report.processed == 1
    row = await db_session.get(WebhookEventModel, event_id)
    await db_session.refresh(row)
    assert row.processed is True
    assert row.error is None
