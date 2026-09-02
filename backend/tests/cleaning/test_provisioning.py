"""R2, R3.1, R3.2 — the cleaning task a closed checkout implies.

Driven through the **real** `AdvancePropertyStatesUseCase` with real repositories rather
than through the provisioner alone: R2.3 is a statement about the transaction the two share,
and a test that called the provisioner directly could not observe it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.application.use_cases import ProvisionCleaningTaskUseCase
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.infrastructure.models import CleaningTaskModel
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyCleaningChecklistTemplateRepository,
    SqlAlchemyCleaningTaskRepository,
)
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.properties.application.use_cases import AdvancePropertyStatesUseCase
from app.properties.domain.enums import PropertyOperationalState
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.infrastructure.models import PropertyStateTransitionModel
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.models import TenantConfigModel
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository
from tests.cleaning.conftest import insert_template

NOW = datetime(2026, 8, 6, 15, 0, tzinfo=UTC)


def _advance(session, *, with_provisioner=True):
    provisioner = (
        ProvisionCleaningTaskUseCase(
            tasks=SqlAlchemyCleaningTaskRepository(session),
            templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
            configs=SqlAlchemyTenantConfigRepository(session),
            users=SqlAlchemyUserRepository(session),
            transitions=SqlAlchemyPropertyStateTransitionRepository(session),
            timeline=SqlAlchemyTimelineEventRepository(session),
            properties=SqlAlchemyPropertyRepository(session),
            notifications=SqlAlchemyNotificationLogRepository(session),
        )
        if with_provisioner
        else None
    )
    return AdvancePropertyStatesUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
        provisioner=provisioner,
    )


@pytest_asyncio.fixture
async def due_checkout(db_session, tenant_a, property_a):
    """A property whose guest left yesterday, sitting in `OCCUPIED_ESTIMATED`."""
    property_a.current_operational_state = PropertyOperationalState.OCCUPIED_ESTIMATED
    db_session.add(property_a)

    reservation = ReservationModel(
        tenant_id=tenant_a.id,
        property_id=property_a.id,
        channel="DIRECT",
        check_in_date=(NOW - timedelta(days=3)).date(),
        check_out_date=(NOW - timedelta(days=1)).date(),
        nights=2,
        status=ReservationStatus.CHECKED_IN_ESTIMATED,
        cleaning_required=True,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation


async def _tasks_of(session, tenant_id):
    rows = await session.execute(
        select(CleaningTaskModel).where(CleaningTaskModel.tenant_id == tenant_id)
    )
    return list(rows.scalars())


@pytest.mark.asyncio
async def test_checkout_creates_the_cleaning_task(
    db_session, tenant_a, property_a, template_a, due_checkout
):
    """R2.1 — the second half of PRD §8.3 that `celery-jobs` left undone."""
    report = await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    assert report.transitioned == 1
    assert report.transitioned_without_task == 0

    tasks = await _tasks_of(db_session, tenant_a.id)
    assert len(tasks) == 1
    assert tasks[0].property_id == property_a.id
    assert tasks[0].reservation_id == due_checkout.id


@pytest.mark.asyncio
async def test_the_task_and_the_transition_share_the_transaction(
    db_session, tenant_a, template_a, due_checkout
):
    """R2.3 — a property in `AWAITING_CLEANING` without its task is the state this closes."""
    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    transitions = await db_session.execute(
        select(PropertyStateTransitionModel).where(
            PropertyStateTransitionModel.tenant_id == tenant_a.id
        )
    )
    assert [t.to_state for t in transitions.scalars()] == [
        PropertyOperationalState.AWAITING_CLEANING
    ]
    assert len(await _tasks_of(db_session, tenant_a.id)) == 1


@pytest.mark.asyncio
async def test_a_failure_inside_the_provisioner_takes_the_transition_with_it(
    db_session, tenant_a, property_a, template_a, due_checkout
):
    """R2.3, the other direction — and the one that was only inferred from reading.

    The QA panel of section 4 pointed out that the happy path proved the two writes land
    together but nothing proved they *fail* together. Here the provisioner's own timeline
    repository explodes after the transition has been written, and the assertion is that
    neither the transition nor the task survives the rollback.
    """
    boom = RuntimeError("timeline is down")

    class ExplodingTimeline:
        def __init__(self, inner):
            self._inner = inner
            self._calls = 0

        async def add(self, tenant_id, event):
            self._calls += 1
            # The first `add` is the caller's own `AWAITING_CLEANING` transition; the second is
            # the provisioner's `CLEANER_ASSIGNED`. Failing the second is what puts the
            # already-written transition at risk.
            if self._calls >= 2:
                raise boom
            return await self._inner.add(tenant_id, event)

    await _insert_cleaner(db_session, tenant_a)
    real_timeline = SqlAlchemyTimelineEventRepository(db_session)
    shared_timeline = ExplodingTimeline(real_timeline)

    provisioner = ProvisionCleaningTaskUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(db_session),
        templates=SqlAlchemyCleaningChecklistTemplateRepository(db_session),
        configs=SqlAlchemyTenantConfigRepository(db_session),
        users=SqlAlchemyUserRepository(db_session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(db_session),
        timeline=shared_timeline,
        properties=SqlAlchemyPropertyRepository(db_session),
        notifications=SqlAlchemyNotificationLogRepository(db_session),
    )
    use_case = AdvancePropertyStatesUseCase(
        properties=SqlAlchemyPropertyRepository(db_session),
        reservations=SqlAlchemyReservationRepository(db_session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(db_session),
        timeline=shared_timeline,
        configs=SqlAlchemyTenantConfigRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        provisioner=provisioner,
    )

    with pytest.raises(RuntimeError):
        await use_case.execute(
            tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
        )

    # What `run_for_every_tenant` does on any escaping exception (`scheduler/runner.py:139-148`).
    await db_session.rollback()

    transitions = await db_session.execute(
        select(PropertyStateTransitionModel).where(
            PropertyStateTransitionModel.tenant_id == tenant_a.id
        )
    )
    assert list(transitions.scalars()) == []
    assert await _tasks_of(db_session, tenant_a.id) == []


@pytest.mark.asyncio
async def test_scheduled_window_is_derived(
    db_session, tenant_a, property_a, template_a, due_checkout
):
    """R2.6 — start at the effective checkout, end at the next confirmed arrival."""
    next_stay = ReservationModel(
        tenant_id=tenant_a.id,
        property_id=property_a.id,
        channel="DIRECT",
        check_in_date=(NOW + timedelta(days=1)).date(),
        check_out_date=(NOW + timedelta(days=3)).date(),
        nights=2,
        status=ReservationStatus.CONFIRMED,
    )
    db_session.add(next_stay)
    await db_session.flush()

    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    task = (await _tasks_of(db_session, tenant_a.id))[0]
    assert task.scheduled_start is not None
    assert task.scheduled_end is not None
    assert task.scheduled_start < task.scheduled_end


@pytest.mark.asyncio
async def test_without_a_next_stay_the_deadline_is_unset(
    db_session, tenant_a, template_a, due_checkout
):
    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    assert (await _tasks_of(db_session, tenant_a.id))[0].scheduled_end is None


@pytest.mark.asyncio
async def test_config_off_transitions_without_creating(
    db_session, tenant_a, template_a, due_checkout
):
    """R2.2 — `TenantConfig.auto_create_cleaning_task` is honoured, and counted apart."""
    # `insert_tenant` (tests/auth/conftest.py) already seeds a `TenantConfigModel` row —
    # update it rather than inserting a second one, which would collide with the unique
    # constraint on `tenant_id`.
    config = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_a.id)
        )
    ).scalar_one()
    config.auto_create_cleaning_task = False
    await db_session.flush()

    report = await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    assert report.transitioned == 1
    assert report.transitioned_without_task == 1
    assert await _tasks_of(db_session, tenant_a.id) == []


@pytest.mark.asyncio
async def test_cleaning_not_required_transitions_without_creating(
    db_session, tenant_a, template_a, due_checkout
):
    """R2.2 — the other half: the reservation's own flag."""
    due_checkout.cleaning_required = False
    await db_session.flush()

    report = await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    assert report.transitioned == 1
    assert report.transitioned_without_task == 1
    assert await _tasks_of(db_session, tenant_a.id) == []


@pytest.mark.asyncio
async def test_no_resolvable_template_transitions_without_creating(
    db_session, tenant_a, due_checkout
):
    """R2.4 — no template is a job for a person, not a failed run for the whole tenant."""
    report = await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    assert report.transitioned == 1
    assert report.transitioned_without_task == 1
    assert await _tasks_of(db_session, tenant_a.id) == []


@pytest.mark.asyncio
async def test_two_active_templates_transition_without_creating(
    db_session, tenant_a, property_a, due_checkout
):
    """R1.4 reaching the job: ambiguity is refused, not tie-broken."""
    await insert_template(db_session, tenant_a, property_id=property_a.id, name="a")
    await insert_template(db_session, tenant_a, property_id=property_a.id, name="b")

    report = await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    assert report.transitioned_without_task == 1
    assert await _tasks_of(db_session, tenant_a.id) == []


@pytest.mark.asyncio
async def test_the_property_template_beats_the_tenant_default(
    db_session, tenant_a, property_a, template_a, due_checkout
):
    own = await insert_template(db_session, tenant_a, property_id=property_a.id, name="own")

    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    assert (await _tasks_of(db_session, tenant_a.id))[0].checklist_template_id == own.id


@pytest.mark.asyncio
async def test_a_second_run_does_not_create_a_second_task(
    db_session, tenant_a, template_a, due_checkout
):
    """R2.5 — and the property has left the source state, so it is not even a candidate."""
    for _ in range(2):
        await _advance(db_session).execute(
            tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
        )

    assert len(await _tasks_of(db_session, tenant_a.id)) == 1


# --- auto-assignment --------------------------------------------------------------


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


@pytest.mark.asyncio
async def test_one_active_cleaner_is_assigned_and_the_property_is_scheduled(
    db_session, tenant_a, property_a, template_a, due_checkout
):
    """R3.1 — and the second transition of the run, `CLEANER_ASSIGNED`."""
    cleaner = await _insert_cleaner(db_session, tenant_a)

    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    task = (await _tasks_of(db_session, tenant_a.id))[0]
    assert task.status is CleaningTaskStatus.ASSIGNED
    assert task.assigned_cleaner_id == cleaner.id

    refreshed = await SqlAlchemyPropertyRepository(db_session).get(tenant_a.id, property_a.id)
    assert refreshed.current_operational_state is PropertyOperationalState.CLEANING_SCHEDULED

    transitions = await db_session.execute(
        select(PropertyStateTransitionModel)
        .where(PropertyStateTransitionModel.tenant_id == tenant_a.id)
        .order_by(PropertyStateTransitionModel.created_at)
    )
    assert [t.to_state for t in transitions.scalars()] == [
        PropertyOperationalState.AWAITING_CLEANING,
        PropertyOperationalState.CLEANING_SCHEDULED,
    ]


@pytest.mark.asyncio
async def test_no_cleaner_leaves_the_task_unassigned(
    db_session, tenant_a, property_a, template_a, due_checkout
):
    """R3.2 — "si no queda pendiente", and the property stays in `AWAITING_CLEANING`."""
    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    task = (await _tasks_of(db_session, tenant_a.id))[0]
    assert task.status is CleaningTaskStatus.CREATED
    assert task.assigned_cleaner_id is None

    refreshed = await SqlAlchemyPropertyRepository(db_session).get(tenant_a.id, property_a.id)
    assert refreshed.current_operational_state is PropertyOperationalState.AWAITING_CLEANING


@pytest.mark.asyncio
async def test_two_active_cleaners_leave_the_choice_to_the_manager(
    db_session, tenant_a, template_a, due_checkout
):
    """R3.2 — more than one active cleaner is not a tie to break."""
    await _insert_cleaner(db_session, tenant_a)
    await _insert_cleaner(db_session, tenant_a)

    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    task = (await _tasks_of(db_session, tenant_a.id))[0]
    assert task.status is CleaningTaskStatus.CREATED


@pytest.mark.asyncio
async def test_an_inactive_cleaner_is_not_assigned(
    db_session, tenant_a, template_a, due_checkout
):
    await _insert_cleaner(db_session, tenant_a, status=UserStatus.INACTIVE)

    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    assert (await _tasks_of(db_session, tenant_a.id))[0].assigned_cleaner_id is None


@pytest.mark.asyncio
async def test_a_cleaner_of_another_tenant_is_not_assigned(
    db_session, tenant_a, tenant_b, template_a, due_checkout
):
    """Rule 1 reaching the roster: the assignee comes from this tenant or from nobody."""
    await _insert_cleaner(db_session, tenant_b)

    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    assert (await _tasks_of(db_session, tenant_a.id))[0].assigned_cleaner_id is None


@pytest.mark.asyncio
async def test_a_cleaner_who_already_rejected_this_reservation_is_not_reassigned(
    db_session, tenant_a, property_a, template_a, due_checkout
):
    """Design D3 — otherwise the single cleaner of a tenant gets the replacement for ever.

    The rejected task is seeded directly: the reject *endpoint* is section 5, but the guard
    lives here and this is where it can be demonstrated.
    """
    from tests.cleaning.conftest import insert_task

    cleaner = await _insert_cleaner(db_session, tenant_a)
    await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        reservation=due_checkout,
        status=CleaningTaskStatus.REJECTED,
        cleaner=cleaner,
    )

    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    live = [
        task
        for task in await _tasks_of(db_session, tenant_a.id)
        if task.status is not CleaningTaskStatus.REJECTED
    ]
    assert len(live) == 1
    assert live[0].assigned_cleaner_id is None


@pytest.mark.asyncio
async def test_a_late_run_still_records_the_next_arrival(
    db_session, tenant_a, property_a, template_a, due_checkout
):
    """R2.6 — the window is anchored to the stay, not to when the job ran.

    `process_checkouts` recovers a backlog up to `CANDIDATE_LOOKBEHIND` (30 days), so a
    same-day turnover can be processed after the next guest has already arrived. A first
    version filtered candidates on `now` and dropped `scheduled_end` in exactly that case —
    reproduced by the QA panel of section 4.
    """
    next_stay = ReservationModel(
        tenant_id=tenant_a.id,
        property_id=property_a.id,
        channel="DIRECT",
        # Starts the same day the previous guest left, i.e. BEFORE the (late) `now`.
        check_in_date=(NOW - timedelta(days=1)).date(),
        check_out_date=(NOW + timedelta(days=1)).date(),
        nights=2,
        status=ReservationStatus.CONFIRMED,
    )
    db_session.add(next_stay)
    await db_session.flush()

    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    task = (await _tasks_of(db_session, tenant_a.id))[0]
    assert task.scheduled_end is not None
    assert task.scheduled_end < NOW


@pytest.mark.asyncio
async def test_an_unconfirmed_next_stay_is_not_a_deadline(
    db_session, tenant_a, property_a, template_a, due_checkout
):
    """R2.6 — only a CONFIRMED arrival is a deadline; a pending one is not a commitment."""
    for status in (ReservationStatus.PENDING, ReservationStatus.CANCELLED):
        db_session.add(
            ReservationModel(
                tenant_id=tenant_a.id,
                property_id=property_a.id,
                channel="DIRECT",
                check_in_date=(NOW + timedelta(days=1)).date(),
                check_out_date=(NOW + timedelta(days=2)).date(),
                nights=1,
                status=status,
            )
        )
    await db_session.flush()

    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    assert (await _tasks_of(db_session, tenant_a.id))[0].scheduled_end is None


@pytest.mark.asyncio
async def test_the_earliest_of_two_future_stays_is_the_deadline(
    db_session, tenant_a, property_a, template_a, due_checkout
):
    for days in (5, 2):
        db_session.add(
            ReservationModel(
                tenant_id=tenant_a.id,
                property_id=property_a.id,
                channel="DIRECT",
                check_in_date=(NOW + timedelta(days=days)).date(),
                check_out_date=(NOW + timedelta(days=days + 1)).date(),
                nights=1,
                status=ReservationStatus.CONFIRMED,
            )
        )
    await db_session.flush()

    await _advance(db_session).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    task = (await _tasks_of(db_session, tenant_a.id))[0]
    assert task.scheduled_end is not None
    assert task.scheduled_end < NOW + timedelta(days=3)


@pytest.mark.asyncio
async def test_without_a_provisioner_no_task_is_created(
    db_session, tenant_a, property_a, template_a, due_checkout
):
    """Design D1 — the collaborator is what creates tasks; nothing else does.

    Renamed after the QA panel of section 4: the previous name claimed to cover "the other
    clock triggers" while calling `CHECKOUT_TIME_REACHED` with the collaborator forced off.
    The real gating of the other two jobs is `test_the_other_clock_jobs_get_no_provisioner`.
    """
    report = await _advance(db_session, with_provisioner=False).execute(
        tenant_id=tenant_a.id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=NOW
    )

    assert report.transitioned == 1
    assert report.transitioned_without_task == 0
    assert await _tasks_of(db_session, tenant_a.id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trigger",
    [PropertyStateTrigger.CHECKIN_WINDOW_OPENED, PropertyStateTrigger.CHECKIN_TIME_REACHED],
)
async def test_the_other_clock_jobs_create_no_task(
    db_session, tenant_a, property_a, template_a, trigger
):
    """Design D1 — through the real `scheduler/tasks.py::_advance`, not a test helper.

    This is where the gating actually lives (`trigger is CHECKOUT_TIME_REACHED`), and nothing
    covered it: the previous test forced the collaborator off while still passing the checkout
    trigger, so it could not have caught a widened condition. Named by the QA panel of
    section 4.

    A property in `VACANT_READY` with a reservation arriving today is a genuine candidate for
    `CHECKIN_WINDOW_OPENED`, so the job does real work here — it just must not create a
    cleaning task while doing it.
    """
    from app.scheduler.tasks import _advance

    property_a.current_operational_state = PropertyOperationalState.VACANT_READY
    db_session.add(property_a)
    db_session.add(
        ReservationModel(
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            channel="DIRECT",
            check_in_date=NOW.date(),
            check_out_date=(NOW + timedelta(days=2)).date(),
            nights=2,
            status=ReservationStatus.CONFIRMED,
        )
    )
    await db_session.flush()

    report = await _advance(db_session, tenant_a.id, NOW, trigger=trigger)

    assert report.transitioned_without_task == 0
    assert await _tasks_of(db_session, tenant_a.id) == []
