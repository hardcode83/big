"""The nightly pricing job (`revenue-pricing` R4.1, R4.2, R4.7; design D8).

Thin like every other task in `app/scheduler/tasks.py` — take the lock, wire the use case,
return the report — so what is worth testing here is the wiring, not the pricing. What the
generator does with a horizon, an approved day or a rejected one is
`tests/pricing/test_use_cases.py`'s subject and is covered there.

**Two things are only true here, and each is tested against something that can fail.**

The first is the lock TTL: this is the one job whose TTL comes from `DAILY_JOBS` instead of
`lock_ttl_for`, and getting it wrong is silent — a three-day lock looks exactly like a
working job until a worker dies mid-run — so what reaches `task_lock` is asserted, not the
constant in the table.

The second is the per-tenant sweep, and it is tested in two halves on purpose. The Celery
task reaches the database through `worker_session_factory()`, built from
`settings.database_url` — the **dev** database, which `tests/conftest.py` deliberately does
not touch (it builds its own `<db>_test_<suffix>`). That database has no tenants, so
`run_for_every_tenant` never enters its loop and any assertion on the report of a real task
call is vacuous: the QA panel of this section proved it by making the job body raise on its
first line and watching every test still pass. So the loop is tested with the tenant list
stubbed, and the wiring the loop invokes is tested directly against the real test-database
session.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.audit.infrastructure.models import AuditLogModel
from app.core.config import settings
from app.pricing.application.use_cases import (
    GeneratePriceRecommendationsUseCase,
    GenerationOutcome,
    PricingActor,
)
from app.pricing.infrastructure.models import PriceRecommendationModel
from app.scheduler.locks import lock_ttl_for, task_lock
from app.scheduler.schedule import CADENCES, DAILY_JOBS, beat_schedule
from app.scheduler.tasks import (
    PRICING_TASK,
    _generate_price_recommendations,
    generate_price_recommendations,
)

from tests.pricing.conftest import NOW  # noqa: F401
from tests.pricing.conftest import flow, world  # noqa: F401

BASE_RULE = {
    "name": "Madrid base",
    "base_price": Decimal("100.00"),
    "min_price": Decimal("50.00"),
    "max_price": Decimal("200.00"),
}

#: R4.1: 60 days starting tomorrow.
HORIZON_DAYS = 60


@pytest_asyncio.fixture
async def redis():
    """Own client per test, same reasoning as `test_locks.py`."""
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def _count_rows(session, property_id) -> int:
    rows = await session.execute(
        select(func.count())
        .select_from(PriceRecommendationModel)
        .where(PriceRecommendationModel.property_id == property_id)
    )
    return rows.scalar_one()


async def _audit_count(session, tenant_id) -> int:
    """Audit rows of the tenant, whatever the entity or action.

    Counted rather than filtered by action on purpose: the claim being tested is that the
    sweep writes **nothing**, so a filter by the action we expect it not to write would miss
    a regression that wrote a different one.
    """
    rows = await session.execute(
        select(func.count())
        .select_from(AuditLogModel)
        .where(AuditLogModel.tenant_id == tenant_id)
    )
    return rows.scalar_one()


# --- the calendar -----------------------------------------------------------------------


def test_the_task_is_registered_under_the_name_the_calendar_uses() -> None:
    from app.worker import celery_app

    assert PRICING_TASK in DAILY_JOBS
    assert PRICING_TASK not in CADENCES
    assert PRICING_TASK in celery_app.tasks
    assert any(entry["task"] == PRICING_TASK for entry in beat_schedule().values())


def test_the_lock_ttl_is_the_daily_one_and_not_three_times_a_cadence(monkeypatch) -> None:
    """D8's whole point, at the only place it can actually be observed.

    Every other task derives its TTL from the cadence beat reads; this one cannot, because
    cadence x 3 on a daily job is a three-day lock and a worker killed mid-run would wedge the
    job for three windows. Asserting the constant in `DAILY_JOBS` would only prove the table;
    this asserts what the task hands to `task_lock`.
    """
    taken: list[timedelta] = []

    @asynccontextmanager
    async def recording_lock(redis, name: str, ttl: timedelta):
        taken.append(ttl)
        async with task_lock(redis, name, ttl) as acquired:
            yield acquired

    monkeypatch.setattr("app.scheduler.tasks.task_lock", recording_lock)

    generate_price_recommendations()

    assert taken == [DAILY_JOBS[PRICING_TASK].lock_ttl]
    assert taken[0] != lock_ttl_for(timedelta(days=1))


# --- the lock ---------------------------------------------------------------------------


def test_a_run_that_loses_the_lock_skips_without_pricing_anything(redis) -> None:
    """R4.2: a losing run is `skipped`, not a failure.

    Two overlapping sweeps would each read the same horizon and upsert over it, and the one
    that started first would be the one whose numbers lose.
    """

    async def hold_and_run() -> dict:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            async with task_lock(client, PRICING_TASK, timedelta(seconds=10)):
                return await asyncio.to_thread(generate_price_recommendations)
        finally:
            await client.aclose()

    report = asyncio.run(hold_and_run())

    assert report["skipped_locked"] is True
    assert report["task"] == PRICING_TASK


def test_the_lock_is_released_so_the_next_night_is_not_skipped(redis) -> None:
    """The shape of `test_repeated_execution.py`, applied to the job that runs once a day.

    Two things at once, and neither is visible with a single execution per process: the
    second `asyncio.run` must not inherit a Redis client bound to the first one's closed
    loop, and the first run must have released its lock — a job whose lock outlived its run
    would skip every night after the first and report success while doing nothing.
    """
    first = generate_price_recommendations()
    second = generate_price_recommendations()

    assert first["skipped_locked"] is False
    assert second["skipped_locked"] is False


# --- the per-tenant sweep ---------------------------------------------------------------


def test_it_calls_the_generator_once_per_active_tenant_with_no_property_and_no_actor(
    redis, monkeypatch
) -> None:
    """R4.1's loop, with the tenant list stubbed so the assertion can fail.

    Against the real dev database this reports zero tenants and proves nothing — the module
    docstring says why. What is pinned here is what section 7 actually owns: one call per
    active tenant, each with its own tenant id, `property_id=None` because the sweep is the
    whole portfolio, and `actor=None` because the clock is not a person (which is the whole
    scope of the fifth named exception to rule 9 of `steering/security.md`).

    **The stub goes on `GeneratePriceRecommendationsUseCase.execute`, not on
    `_generate_price_recommendations`**, and that is the difference between this test and a
    green one that proves nothing. Replacing the helper would replace the very lines that
    choose `property_id` and `actor`, so the two claims in this test's name would be
    unverifiable by its own assertions — the QA panel of this section measured exactly that:
    with the helper stubbed, swapping `actor=None` for a real actor left every test green.
    Stubbing one level down leaves the real helper running and its arguments observable.
    """
    tenants = [uuid.uuid4(), uuid.uuid4()]
    calls: list[dict] = []

    async def recording_execute(
        self, tenant_id, *, now, property_id=None, actor=None
    ) -> GenerationOutcome:
        calls.append(
            {"tenant_id": tenant_id, "property_id": property_id, "actor": actor}
        )
        return GenerationOutcome()

    async def stub_tenants() -> list[uuid.UUID]:
        return tenants

    monkeypatch.setattr("app.scheduler.runner.list_active_tenants", stub_tenants)
    monkeypatch.setattr(GeneratePriceRecommendationsUseCase, "execute", recording_execute)

    report = generate_price_recommendations()

    assert report["skipped_locked"] is False
    assert report["failed"] == 0
    assert report["tenants"] == len(tenants)
    assert [call["tenant_id"] for call in calls] == tenants
    # R4.1: the sweep is the whole portfolio, so the job never narrows to one property.
    assert all(call["property_id"] is None for call in calls)
    # Rule 9's fifth named exception is scoped to the run with no actor. The endpoint of the
    # same use case passes one; this path must not.
    assert all(call["actor"] is None for call in calls)


@pytest.mark.asyncio
async def test_the_wiring_the_loop_invokes_really_prices_the_portfolio(
    flow, world, db_session
) -> None:
    """R4.1 end to end for one tenant, over the real test database.

    The counterpart to the test above: that one pins the loop with the generator stubbed,
    this one pins the generator with the loop removed, so between them nothing in the path is
    only assumed. Calling `_generate_price_recommendations` directly is what makes this
    possible at all — the Celery task would go to the dev database, where there is nothing to
    price.
    """
    # Creating the rule needs a real actor — that path is audited and `_AuditWriter` refuses
    # `None` (design D12). Only the *generation* is anonymous, which is the whole scope of
    # the fifth named exception to rule 9 of `steering/security.md`.
    await flow.create_rule.execute(
        tenant_id=world.tenant.id,
        actor=PricingActor(user_id=world.manager.id, ip="10.0.0.1"),
        now=NOW,
        **BASE_RULE,
    )

    # Creating the rule audited itself; the sweep must add nothing to that.
    audited_before = await _audit_count(db_session, world.tenant.id)

    outcome = await _generate_price_recommendations(db_session, world.tenant.id, NOW)

    # Two active properties in the world, each getting the full horizon.
    assert outcome.created == HORIZON_DAYS * 2
    assert await _count_rows(db_session, world.property.id) == HORIZON_DAYS
    # R4.1 says "cada propiedad activa": the other tenant's property is not this sweep's.
    assert await _count_rows(db_session, world.other_property.id) == 0
    # And the run is anonymous: **not one `AuditLog` row** from the clock-driven sweep, which
    # is the whole scope of the fifth named exception to rule 9 of `steering/security.md`.
    # Asserted here rather than only in `tests/pricing/test_use_cases.py`, because that one
    # hands the use case `actor=None` itself — it cannot notice a regression in which *this
    # wiring* starts passing a real actor. Raised by the QA panel of this section.
    assert await _audit_count(db_session, world.tenant.id) == audited_before


@pytest.mark.asyncio
async def test_a_repeated_sweep_updates_instead_of_duplicating(
    flow, world, db_session
) -> None:
    """R4.2, at the job's own entry point rather than the use case's.

    `tests/pricing/test_use_cases.py` already proves the upsert against the live
    `UNIQUE (property_id, date)`. What this adds is that the job's wiring — a fresh use case
    per call, built the way `_generate_price_recommendations` builds it — does not turn a
    second night into a second horizon.
    """
    # Creating the rule needs a real actor — that path is audited and `_AuditWriter` refuses
    # `None` (design D12). Only the *generation* is anonymous, which is the whole scope of
    # the fifth named exception to rule 9 of `steering/security.md`.
    await flow.create_rule.execute(
        tenant_id=world.tenant.id,
        actor=PricingActor(user_id=world.manager.id, ip="10.0.0.1"),
        now=NOW,
        **BASE_RULE,
    )

    first = await _generate_price_recommendations(db_session, world.tenant.id, NOW)
    second = await _generate_price_recommendations(db_session, world.tenant.id, NOW)

    assert first.created == HORIZON_DAYS * 2
    assert (second.created, second.updated) == (0, HORIZON_DAYS * 2)
    assert await _count_rows(db_session, world.property.id) == HORIZON_DAYS
