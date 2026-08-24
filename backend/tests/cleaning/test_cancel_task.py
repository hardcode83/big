"""R3.1-R3.5 — retiring a cleaning that is not going to be completed.

Driven through the **real** `CancelCleaningTaskUseCase` with real repositories, because what
matters here is what lands in the database: the design calls this coverage the minimum the change
cannot be declared done without, and most of it is statements about rows in three tables and about
a column that must *not* have been written by hand.

The headline case is REDES11 as it actually was in `dev` on 2026-08-22: `CLEANING_IN_PROGRESS`
since the 16th, a stay running from the 19th to the 23rd, and no legitimate way out.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.audit.domain import actions as audit_actions
from app.auth.domain.enums import UserRole
from app.audit.infrastructure.models import AuditLogModel
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.cleaning.application.use_cases import CancelCleaningTaskUseCase, CleaningActor
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import (
    CleaningTaskNotFoundError,
    InvalidCleaningTransitionError,
    PropertyStateBlocksCleaningError,
)
from app.cleaning.infrastructure.models import (
    CleaningChecklistCompletionModel,
    CleaningPhotoModel,
    CleaningTaskModel,
)
from app.cleaning.infrastructure.repositories import SqlAlchemyCleaningTaskRepository
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.notifications.infrastructure.models import NotificationLogModel
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.cleaning.domain.notifications import RELATED_TYPE_CLEANING_TASK
from app.properties.domain.enums import PropertyOperationalState
from app.properties.infrastructure.models import PropertyModel, PropertyStateTransitionModel
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository
from tests.cleaning.conftest import insert_template

# Anchored to today, because the stay has to be *running now* for the REDES11 case to be the
# REDES11 case. A literal date would have made these tests describe August 2026 and then quietly
# stop describing anything — the same trap the blocked-transitions API tests fell into first.
#
# The margins are what make this stable, and they are stated so nobody has to re-derive them: the
# check-in is three days behind and the checkout two days ahead, so a midnight crossing between two
# calls, a CI box in another timezone, or a DST shift in `Europe/Madrid` moves the boundary by at
# most a day and cannot move `now` outside the stay. Raised by the section-5 CI panel and cleared
# on the same arithmetic the section-4 panel used for the equivalent helper.
def _dates(started_days_ago=3, ends_in_days=2):
    return (
        date.today() - timedelta(days=started_days_ago),
        date.today() + timedelta(days=ends_in_days),
    )


def _use_case(session) -> CancelCleaningTaskUseCase:
    return CancelCleaningTaskUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


async def _property(session, tenant, state, *, code="REDES11"):
    prop = PropertyModel(
        tenant_id=tenant.id,
        name="Redes 11",
        internal_code=code,
        pms_external_id=f"PMS-{code}-{uuid.uuid4().hex[:6]}",
        max_guests=4,
        timezone="Europe/Madrid",
        current_operational_state=state,
        default_check_in_time=time(15, 0),
        default_check_out_time=time(11, 0),
    )
    session.add(prop)
    await session.flush()
    return prop


async def _reservation(
    session, tenant, prop, *, started_days_ago=3, ends_in_days=2, status=ReservationStatus.CONFIRMED
):
    """`CONFIRMED` explicitly: the column defaults to `PENDING`, which is **not** an active stay.

    Worth stating, because the first version of these tests left the default and the REDES11 case
    quietly resolved to `AWAITING_CLEANING` — `_active_reservations` only counts `CONFIRMED` and
    `CHECKED_IN_ESTIMATED`, so a `PENDING` booking means nobody is in the flat.
    """
    check_in, check_out = _dates(started_days_ago, ends_in_days)
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel="DIRECT",
        check_in_date=check_in,
        check_out_date=check_out,
        nights=(check_out - check_in).days,
        status=status,
    )
    session.add(reservation)
    await session.flush()
    return reservation


async def _task(session, tenant, prop, template, *, status, reservation=None, cleaner=None):
    task = CleaningTaskModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        checklist_template_id=template.id,
        reservation_id=reservation.id if reservation is not None else None,
        assigned_cleaner_id=cleaner,
        status=status,
    )
    session.add(task)
    await session.flush()
    return task


def _actor(users_by_role_a):
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    return CleaningActor(user_id=manager.id, role=UserRole.PROPERTY_MANAGER, ip="10.0.0.1")


async def _count(session, model, **where):
    stmt = select(func.count()).select_from(model)
    for column, value in where.items():
        stmt = stmt.where(getattr(model, column) == value)
    return (await session.execute(stmt)).scalar_one()


# --- (a) the REDES11 case, end to end (R3.2) ---


@pytest.mark.asyncio
async def test_redes11_lands_in_occupied_estimated_with_no_replacement(
    db_session, tenant_a, users_by_role_a
) -> None:
    """The whole point of the change, in one test.

    A guest has been in the flat since the 19th and the cleaning was never closed. Cancelling it
    resolves the flat to the state the check-in never got to write — and creates **no**
    replacement, because a cleaning with the guest inside is impossible by the system's own
    decision (design D8, exception 1).
    """
    prop = await _property(db_session, tenant_a, PropertyOperationalState.CLEANING_IN_PROGRESS)
    template = await insert_template(db_session, tenant_a)
    stay = await _reservation(db_session, tenant_a, prop)
    task = await _task(
        db_session,
        tenant_a,
        prop,
        template,
        status=CleaningTaskStatus.IN_PROGRESS,
        reservation=stay,
    )

    cancelled = await _use_case(db_session).execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        actor=_actor(users_by_role_a),
        reason="the cleaner never came back",
        now=datetime.now(UTC),
    )

    assert cancelled.status is CleaningTaskStatus.CANCELLED
    await db_session.refresh(prop)
    assert prop.current_operational_state is PropertyOperationalState.OCCUPIED_ESTIMATED
    assert await _count(db_session, CleaningTaskModel, property_id=prop.id) == 1


# --- (b) no stay running → AWAITING_CLEANING with an unassigned replacement (D8) ---


@pytest.mark.asyncio
async def test_without_a_guest_the_flat_awaits_cleaning_and_a_replacement_exists(
    db_session, tenant_a, users_by_role_a
) -> None:
    """D8: the replacement is what stops the system declaring a half-cleaned flat ready.

    Without it the resolver would answer `VACANT_READY` — a lie about a flat nobody cleaned,
    against principle 1 of `product.md`.
    """
    prop = await _property(db_session, tenant_a, PropertyOperationalState.CLEANING_IN_PROGRESS)
    template = await insert_template(db_session, tenant_a)
    task = await _task(
        db_session, tenant_a, prop, template, status=CleaningTaskStatus.IN_PROGRESS
    )

    await _use_case(db_session).execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        actor=_actor(users_by_role_a),
        reason="abandoned",
        now=datetime.now(UTC),
    )

    await db_session.refresh(prop)
    assert prop.current_operational_state is PropertyOperationalState.AWAITING_CLEANING
    replacements = (
        (
            await db_session.execute(
                select(CleaningTaskModel).where(
                    CleaningTaskModel.property_id == prop.id,
                    CleaningTaskModel.id != task.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(replacements) == 1
    assert replacements[0].status is CleaningTaskStatus.CREATED
    assert replacements[0].assigned_cleaner_id is None
    assert replacements[0].checklist_template_id == template.id


# --- (c) D8's second exception, and why it cannot fire (design D8) ---


@pytest.mark.asyncio
async def test_two_live_tasks_cannot_share_a_reservation(
    db_session, tenant_a, users_by_role_a
) -> None:
    """D8 exception 2 is defence in depth against a state the schema already forbids.

    The exception says: if another live task already covers this reservation, do not create a
    replacement, because `uq_cleaning_tasks_live_reservation` would reject it. Implementing it
    showed the situation is **unreachable while that index holds** — the index is partial on
    `reservation_id IS NOT NULL AND status IN (live)`, so no second live task can share the
    reservation *while ours is still live*, and cancelling requires ours to be live. After the
    cancellation exactly zero live tasks carry it.

    So what is testable is the invariant the exception leans on, and that is what this asserts.
    The guard stays in the use case because it costs one query and would matter the day the index
    changes; recorded in D8 so the next reader does not mistake it for a live branch.
    """
    prop = await _property(db_session, tenant_a, PropertyOperationalState.CLEANING_IN_PROGRESS)
    template = await insert_template(db_session, tenant_a)
    stay = await _reservation(db_session, tenant_a, prop)
    await _task(
        db_session,
        tenant_a,
        prop,
        template,
        status=CleaningTaskStatus.IN_PROGRESS,
        reservation=stay,
    )

    with pytest.raises(IntegrityError):
        await _task(
            db_session,
            tenant_a,
            prop,
            template,
            status=CleaningTaskStatus.CREATED,
            reservation=stay,
        )
    # Explicit, though the fixture's context manager would also unwind it: a deliberately aborted
    # transaction left for the next test to inherit is what `steering/testing.md` warns blocks its
    # row-wipe — "un test que deje una transacción abierta bloquea el vaciado del siguiente".
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_manual_task_is_replaced_without_touching_a_reservations_slot(
    db_session, tenant_a, users_by_role_a
) -> None:
    """The reachable half: a task with no reservation, cancelled beside a live one that has one.

    `task.reservation_id is None` so there is no slot to collide with, and the replacement is
    created with `reservation_id=None` too — which is why the index is untroubled.
    """
    prop = await _property(db_session, tenant_a, PropertyOperationalState.CLEANING_IN_PROGRESS)
    template = await insert_template(db_session, tenant_a)
    manual = await _task(
        db_session, tenant_a, prop, template, status=CleaningTaskStatus.IN_PROGRESS
    )

    await _use_case(db_session).execute(
        tenant_id=tenant_a.id,
        task_id=manual.id,
        actor=_actor(users_by_role_a),
        reason="created against the wrong flat",
        now=datetime.now(UTC),
    )

    replacement = (
        (
            await db_session.execute(
                select(CleaningTaskModel).where(
                    CleaningTaskModel.property_id == prop.id,
                    CleaningTaskModel.id != manual.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert replacement.reservation_id is None
    assert replacement.status is CleaningTaskStatus.CREATED


# --- the assignment SLA, which is why this use case is on `_AnswersAnAssignmentBase` ---


@pytest.mark.asyncio
async def test_cancelling_an_assigned_task_closes_its_assignment_sla(
    db_session, tenant_a, users_by_role_a
) -> None:
    """The whole reason `CancelCleaningTaskUseCase` inherits `_AnswersAnAssignmentBase` (D8).

    Cancelling is not answering an assignment, but it can happen *from* `ASSIGNED`, where the
    assignment's SLA deadline is still live. Left open, `check_sla_breaches` escalates to a manager
    about a task that no longer exists — a false alarm this change would have introduced, because
    cancelling from `ASSIGNED` is new.

    Asserted rather than assumed: the section-5 QA panel found that every other cancel test used a
    status with no live deadline, so the clearing branch was only ever exercised as a no-op and a
    wrong `notification_type` or `related_id` here would have gone unnoticed.
    """
    prop = await _property(db_session, tenant_a, PropertyOperationalState.CLEANING_SCHEDULED)
    template = await insert_template(db_session, tenant_a)
    cleaner = users_by_role_a[UserRole.CLEANER]
    task = await _task(
        db_session,
        tenant_a,
        prop,
        template,
        status=CleaningTaskStatus.ASSIGNED,
        cleaner=cleaner.id,
    )
    deadline = datetime.now(UTC) + timedelta(hours=4)
    db_session.add(
        NotificationLogModel(
            tenant_id=tenant_a.id,
            recipient_user_id=cleaner.id,
            notification_type=NotificationType.CLEANING_TASK_ASSIGNED.value,
            channel=NotificationChannel.EMAIL.value,
            status=NotificationStatus.SENT.value,
            related_type=RELATED_TYPE_CLEANING_TASK,
            related_id=task.id,
            subject="Nueva limpieza",
            body="...",
            recipient_contact="cleaner@example.com",
            sla_deadline_at=deadline,
        )
    )
    await db_session.flush()

    await _use_case(db_session).execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        actor=_actor(users_by_role_a),
        reason="the flat is occupied, this should never have been assigned",
        now=datetime.now(UTC),
    )

    remaining = await db_session.scalar(
        select(NotificationLogModel.sla_deadline_at).where(
            NotificationLogModel.related_id == task.id
        )
    )
    assert remaining is None


# --- overlapping active stays: a 409, never a 500 (section-5 security panel) ---


@pytest.mark.asyncio
async def test_two_overlapping_stays_answer_a_conflict_not_a_crash(
    db_session, tenant_a, users_by_role_a
) -> None:
    """A double-booked flat must not turn a legitimate cancellation into an unhandled `500`.

    `ContextualStateResolver._active_reservations` refuses when more than one `CONFIRMED` stay is
    running at `now`, which is a real state after a PMS sync anomaly rather than a hypothetical.
    `IncompatibleTransitionContextError` is a `PropertyDomainError` and no handler maps it, so
    before the fix it escaped as a `500`; now the replacement is skipped and `_transition` reaches
    the same resolver, whose refusal is translated into this module's `PropertyStateBlocksCleaningError`.

    And nothing is written: the cancellation never commits, so the task is still live afterwards.
    """
    prop = await _property(db_session, tenant_a, PropertyOperationalState.CLEANING_IN_PROGRESS)
    template = await insert_template(db_session, tenant_a)
    first = await _reservation(db_session, tenant_a, prop, started_days_ago=3, ends_in_days=2)
    await _reservation(db_session, tenant_a, prop, started_days_ago=2, ends_in_days=3)
    task = await _task(
        db_session,
        tenant_a,
        prop,
        template,
        status=CleaningTaskStatus.IN_PROGRESS,
        reservation=first,
    )

    with pytest.raises(PropertyStateBlocksCleaningError):
        await _use_case(db_session).execute(
            tenant_id=tenant_a.id,
            task_id=task.id,
            actor=_actor(users_by_role_a),
            reason="abandoned",
            now=datetime.now(UTC),
        )

    assert await _count(db_session, PropertyStateTransitionModel, property_id=prop.id) == 0
    assert await _count(db_session, AuditLogModel) == 0


@pytest.mark.asyncio
async def test_a_past_stay_gets_a_replacement_that_inherits_its_reservation(
    db_session, tenant_a, users_by_role_a
) -> None:
    """The only path that reaches the live-task lookup of D8's exception 2 at all.

    Every other case returns earlier — a guest inside short-circuits on `has_active_stay`, and a
    manual task has no `reservation_id` to look up.

    **What this does and does not prove.** It executes the lookup, which was previously never run,
    and it pins the behaviour that matters operationally: the replacement carries the same
    reservation, so the cleaning still owed to that stay is still owed to *it*. It does **not**
    pin the `other.id != task.id` comparison — the QA panel of this section inverted it and this
    test still passed. The reason is the same one that makes `return None` unreachable: by the time
    `_replacement_for` runs, the cancelled task is already persisted as `CANCELLED` and excluded by
    `list_live_for_reservation`'s `LIVE_STATUSES` filter, and `uq_cleaning_tasks_live_reservation`
    forbids a second live task on that reservation — so `live` is always empty here and `any(...)`
    is `False` whichever way the comparison points. The comparison is untestable, not just
    untested, and an earlier version of this docstring claimed otherwise.
    """
    prop = await _property(db_session, tenant_a, PropertyOperationalState.CLEANING_IN_PROGRESS)
    template = await insert_template(db_session, tenant_a)
    # Checked out five days ago: nobody is in the flat, so the replacement is created.
    past = await _reservation(db_session, tenant_a, prop, started_days_ago=9, ends_in_days=-5)
    task = await _task(
        db_session,
        tenant_a,
        prop,
        template,
        status=CleaningTaskStatus.IN_PROGRESS,
        reservation=past,
    )

    await _use_case(db_session).execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        actor=_actor(users_by_role_a),
        reason="abandoned after checkout",
        now=datetime.now(UTC),
    )

    replacement = (
        (
            await db_session.execute(
                select(CleaningTaskModel).where(
                    CleaningTaskModel.property_id == prop.id,
                    CleaningTaskModel.id != task.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert replacement.reservation_id == past.id
    assert replacement.status is CleaningTaskStatus.CREATED
    await db_session.refresh(prop)
    assert prop.current_operational_state is PropertyOperationalState.AWAITING_CLEANING


# --- (d) the three rows, and the column nobody wrote by hand (R3.2, R3.3) ---


@pytest.mark.asyncio
async def test_the_transition_the_timeline_and_the_audit_row_are_all_written(
    db_session, tenant_a, users_by_role_a
) -> None:
    """R3.3, and rule 9 of `steering/security.md`: a `USER` transition is not exempt.

    The `property_state_transitions` row is also what proves the column went through the machine
    rather than being written directly (R3.2) — rule 9 requires the row in the same transaction
    as any write of `current_operational_state`, so its absence would mean a bypass.
    """
    prop = await _property(db_session, tenant_a, PropertyOperationalState.CLEANING_IN_PROGRESS)
    template = await insert_template(db_session, tenant_a)
    stay = await _reservation(db_session, tenant_a, prop)
    task = await _task(
        db_session,
        tenant_a,
        prop,
        template,
        status=CleaningTaskStatus.IN_PROGRESS,
        reservation=stay,
    )
    manager = _actor(users_by_role_a)

    await _use_case(db_session).execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        actor=manager,
        reason="guest is still in the flat",
        now=datetime.now(UTC),
    )

    transition = (
        (
            await db_session.execute(
                select(PropertyStateTransitionModel).where(
                    PropertyStateTransitionModel.property_id == prop.id
                )
            )
        )
        .scalars()
        .one()
    )
    assert transition.from_state is PropertyOperationalState.CLEANING_IN_PROGRESS
    assert transition.to_state is PropertyOperationalState.OCCUPIED_ESTIMATED
    assert transition.metadata_["trigger"] == "CLEANING_CANCELLED"
    assert transition.triggered_by_user_id == manager.user_id

    assert await _count(db_session, TimelineEventModel, property_id=prop.id) == 1

    audit = (
        (
            await db_session.execute(
                select(AuditLogModel).where(
                    AuditLogModel.action == audit_actions.CLEANING_TASK_CANCELLED
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.entity_id == task.id
    assert audit.actor_user_id == manager.user_id


# --- (e) the partial evidence survives (R3.5) ---


@pytest.mark.asyncio
async def test_partial_evidence_is_kept_whole(
    db_session, tenant_a, users_by_role_a
) -> None:
    """R3.5 and design D9: the checklist items and the photos are not touched.

    The load-bearing reason is that photos are objects in a store no transaction rolls back, so a
    partial delete would leave orphans on one side or the other depending on where it failed. The
    work that *was* done is also exactly what a manager needs in order to decide whether the
    cleaning has to be repeated.
    """
    prop = await _property(db_session, tenant_a, PropertyOperationalState.CLEANING_IN_PROGRESS)
    template = await insert_template(db_session, tenant_a)
    stay = await _reservation(db_session, tenant_a, prop)
    task = await _task(
        db_session,
        tenant_a,
        prop,
        template,
        status=CleaningTaskStatus.IN_PROGRESS,
        reservation=stay,
    )
    cleaner = users_by_role_a[UserRole.CLEANER]
    db_session.add(
        CleaningChecklistCompletionModel(
            cleaning_task_id=task.id, item_id="kitchen", completed=True
        )
    )
    db_session.add(
        CleaningPhotoModel(
            cleaning_task_id=task.id,
            uploaded_by=cleaner.id,
            photo_type="kitchen",
            storage_key=f"tenants/{tenant_a.id}/cleaning-tasks/{task.id}/x.jpg",
        )
    )
    await db_session.flush()

    await _use_case(db_session).execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        actor=_actor(users_by_role_a),
        reason="abandoned",
        now=datetime.now(UTC),
    )

    assert await _count(db_session, CleaningChecklistCompletionModel, cleaning_task_id=task.id) == 1
    assert await _count(db_session, CleaningPhotoModel, cleaning_task_id=task.id) == 1


# --- R3.4: already terminal writes nothing ---


@pytest.mark.asyncio
async def test_cancelling_a_cancelled_task_writes_nothing(
    db_session, tenant_a, users_by_role_a
) -> None:
    """R3.4: the second attempt is refused, and refused *before* anything is persisted."""
    prop = await _property(db_session, tenant_a, PropertyOperationalState.CLEANING_IN_PROGRESS)
    template = await insert_template(db_session, tenant_a)
    task = await _task(
        db_session, tenant_a, prop, template, status=CleaningTaskStatus.CANCELLED
    )

    with pytest.raises(InvalidCleaningTransitionError):
        await _use_case(db_session).execute(
            tenant_id=tenant_a.id,
            task_id=task.id,
            actor=_actor(users_by_role_a),
            reason="again",
            now=datetime.now(UTC),
        )

    assert await _count(db_session, PropertyStateTransitionModel, property_id=prop.id) == 0
    assert await _count(db_session, TimelineEventModel, property_id=prop.id) == 0
    assert await _count(db_session, AuditLogModel) == 0
    await db_session.refresh(prop)
    assert prop.current_operational_state is PropertyOperationalState.CLEANING_IN_PROGRESS


# --- D8: a cancellation that moves nothing is still a cancellation ---


@pytest.mark.asyncio
async def test_a_cancellation_that_does_not_move_the_flat_still_happens(
    db_session, tenant_a, users_by_role_a
) -> None:
    """`NoOperationalStateChangeError` is not an error (design D8).

    Cancelling the only `CREATED` task of a flat that is already `AWAITING_CLEANING` leaves it
    where it is: the replacement keeps the resolver answering `AWAITING_CLEANING`, so the machine
    reports "no change". The task is still cancelled and the audit row still explains why.
    """
    prop = await _property(db_session, tenant_a, PropertyOperationalState.AWAITING_CLEANING)
    template = await insert_template(db_session, tenant_a)
    task = await _task(db_session, tenant_a, prop, template, status=CleaningTaskStatus.CREATED)

    cancelled = await _use_case(db_session).execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        actor=_actor(users_by_role_a),
        reason="wrong flat",
        now=datetime.now(UTC),
    )

    assert cancelled.status is CleaningTaskStatus.CANCELLED
    await db_session.refresh(prop)
    assert prop.current_operational_state is PropertyOperationalState.AWAITING_CLEANING
    assert await _count(db_session, PropertyStateTransitionModel, property_id=prop.id) == 0
    assert await _count(db_session, AuditLogModel) == 1


# --- tenant isolation (rule 1 of `steering/security.md`) ---


@pytest.mark.asyncio
async def test_a_neighbours_task_cannot_be_cancelled(
    db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    prop = await _property(
        db_session, tenant_b, PropertyOperationalState.CLEANING_IN_PROGRESS, code="THEIRS"
    )
    template = await insert_template(db_session, tenant_b)
    task = await _task(
        db_session, tenant_b, prop, template, status=CleaningTaskStatus.IN_PROGRESS
    )

    with pytest.raises(CleaningTaskNotFoundError):
        await _use_case(db_session).execute(
            tenant_id=tenant_a.id,
            task_id=task.id,
            actor=_actor(users_by_role_a),
            reason="not mine",
            now=datetime.now(UTC),
        )

    await db_session.refresh(task)
    assert task.status is CleaningTaskStatus.IN_PROGRESS
