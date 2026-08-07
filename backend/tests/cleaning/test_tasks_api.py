"""R3, R4, R5, R7 — the cleaning task endpoints, end to end over ASGI.

The full operational flow of PRD §11 is exercised in `test_the_whole_flow_...`: assign →
accept → start → checklist → complete, with the property's state read back at each step. The
rest are the edges: the authorisation matrix, the 404s that must be indistinguishable, the
validation rule, and the idempotence of the checklist.
"""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.audit.domain import actions as audit_actions
from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus
from app.cleaning.infrastructure.models import CleaningTaskModel
from app.maintenance.domain.enums import IncidentSeverity, IncidentSource, IncidentStatus
from app.maintenance.infrastructure.models import IncidentModel
from app.properties.domain.enums import PropertyOperationalState
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from tests.cleaning.conftest import auth_header, insert_task

TASKS = "/api/v1/cleaning-tasks"
NOW = datetime.now(UTC)


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


@pytest_asyncio.fixture
async def cleaner_a(db_session, tenant_a):
    return await _insert_cleaner(db_session, tenant_a)


@pytest_asyncio.fixture
async def task_a(db_session, tenant_a, property_a, template_a):
    """A property awaiting cleaning, with an unassigned task — what a checkout leaves."""
    property_a.current_operational_state = PropertyOperationalState.AWAITING_CLEANING
    db_session.add(property_a)
    task = await insert_task(db_session, tenant_a, property_a, template_a)
    await db_session.flush()
    return task


async def _state_of(db_session, property_id):
    from app.properties.infrastructure.models import PropertyModel

    return await db_session.scalar(
        select(PropertyModel.current_operational_state).where(PropertyModel.id == property_id)
    )


async def _audit_actions_of(db_session, tenant_id):
    rows = await db_session.execute(
        select(AuditLogModel.action)
        .where(AuditLogModel.tenant_id == tenant_id)
        .order_by(AuditLogModel.created_at)
    )
    return list(rows.scalars())


# --- the whole flow ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_whole_flow_from_assignment_to_completion(
    api, db_session, tenant_a, property_a, users_by_role_a, cleaner_a, task_a
):
    manager = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    cleaner = auth_header(api, cleaner_a)

    assigned = await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner_a.id)},
        headers=manager,
    )
    assert assigned.status_code == 200
    assert assigned.json()["status"] == CleaningTaskStatus.ASSIGNED.value
    assert (
        await _state_of(db_session, property_a.id)
        is PropertyOperationalState.CLEANING_SCHEDULED
    )

    accepted = await api.post(f"{TASKS}/{task_a.id}/accept", headers=cleaner)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == CleaningTaskStatus.ACCEPTED.value

    started = await api.post(f"{TASKS}/{task_a.id}/start", headers=cleaner)
    assert started.status_code == 200
    assert (
        await _state_of(db_session, property_a.id)
        is PropertyOperationalState.CLEANING_IN_PROGRESS
    )

    # R5.1: the two required items of the standard template must be ticked first.
    blocked = await api.post(f"{TASKS}/{task_a.id}/complete", headers=cleaner)
    assert blocked.status_code == 409
    assert "kitchen" in blocked.json()["error"]["message"]

    for item in ("kitchen", "bathroom"):
        ticked = await api.post(
            f"{TASKS}/{task_a.id}/checklist/{item}/complete", headers=cleaner
        )
        assert ticked.status_code == 204

    done = await api.post(f"{TASKS}/{task_a.id}/complete", headers=cleaner)
    assert done.status_code == 200
    assert done.json()["status"] == CleaningTaskStatus.COMPLETED.value
    assert done.json()["validation_status"] == CleaningValidationStatus.PASSED.value

    # R5.4: no booking at all, so the contextual destination is VACANT_READY.
    assert await _state_of(db_session, property_a.id) is PropertyOperationalState.VACANT_READY

    # Rule 9: every one of those was a person, so every one wrote its row.
    assert await _audit_actions_of(db_session, tenant_a.id) == [
        audit_actions.CLEANING_TASK_ASSIGNED,
        audit_actions.CLEANING_TASK_ACCEPTED,
        audit_actions.CLEANING_TASK_STARTED,
        audit_actions.CLEANING_TASK_COMPLETED,
    ]


async def _drive_to_completable(api, task_id, cleaner_user, manager_user):
    """assign → accept → start → tick both required items, leaving the task closable."""
    cleaner = auth_header(api, cleaner_user)
    await api.patch(
        f"{TASKS}/{task_id}",
        json={"assigned_cleaner_id": str(cleaner_user.id)},
        headers=auth_header(api, manager_user),
    )
    await api.post(f"{TASKS}/{task_id}/accept", headers=cleaner)
    await api.post(f"{TASKS}/{task_id}/start", headers=cleaner)
    for item in ("kitchen", "bathroom"):
        await api.post(f"{TASKS}/{task_id}/checklist/{item}/complete", headers=cleaner)
    return cleaner


@pytest.mark.asyncio
async def test_completion_with_a_future_booking_is_ready_for_next_guest(
    api, db_session, tenant_a, property_a, users_by_role_a, cleaner_a, task_a
):
    """R5.4 — the destination is contextual, not fixed.

    The property's timezone is pinned to UTC, like the `AWAITING_CHECKIN` sibling below and
    for the same reason. With the fixture's `Europe/Madrid`, `NOW + 1 día` computed on the
    **UTC** date lands on the property's *local* today whenever the suite runs late enough in
    the UTC evening — the local clock is already the next day — so the resolver answered
    `AWAITING_CHECKIN` and this failed. It passed for two days and broke on the third at the
    date boundary, which is exactly how a clock-dependent test hides.
    """
    property_a.timezone = "UTC"
    db_session.add(property_a)
    db_session.add(
        ReservationModel(
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            channel="DIRECT",
            check_in_date=(NOW + timedelta(days=1)).date(),
            check_out_date=(NOW + timedelta(days=3)).date(),
            nights=2,
            status=ReservationStatus.CONFIRMED,
        )
    )
    await db_session.flush()
    cleaner = await _drive_to_completable(
        api, task_a.id, cleaner_a, users_by_role_a[UserRole.PROPERTY_MANAGER]
    )

    done = await api.post(f"{TASKS}/{task_a.id}/complete", headers=cleaner)

    assert done.status_code == 200
    assert (
        await _state_of(db_session, property_a.id)
        is PropertyOperationalState.READY_FOR_NEXT_GUEST
    )


@pytest.mark.asyncio
async def test_completion_with_a_booking_arriving_today_awaits_checkin(
    api, db_session, tenant_a, property_a, users_by_role_a, cleaner_a, task_a
):
    """R5.4 — the third destination.

    The booking has to arrive **later today**, not merely today: once its check-in hour has
    passed the guest counts as in, and the resolver refuses instead of resolving (the next
    test).

    Both the property's timezone and its check-in hour are pinned here, and the first is the
    one that matters. With the fixture's `Europe/Madrid` the local clock runs two hours ahead
    of `NOW`, so a 23:00 check-in is already in the past whenever the suite runs after 21:00
    UTC — which is exactly how this test failed once. On UTC at 23:59 the window only closes in
    the last minute of the day.
    """
    property_a.timezone = "UTC"
    property_a.default_check_in_time = time(23, 59)
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
    cleaner = await _drive_to_completable(
        api, task_a.id, cleaner_a, users_by_role_a[UserRole.PROPERTY_MANAGER]
    )

    done = await api.post(f"{TASKS}/{task_a.id}/complete", headers=cleaner)

    assert done.status_code == 200
    assert (
        await _state_of(db_session, property_a.id)
        is PropertyOperationalState.AWAITING_CHECKIN
    )


@pytest.mark.asyncio
async def test_closing_a_cleaning_while_a_guest_is_in_is_a_conflict(
    api, db_session, tenant_a, property_a, users_by_role_a, cleaner_a, task_a
):
    """R5.4's other edge, and the one that was a 500 until the panel of section 5.

    `after_cleaning_completion` refuses to resolve with an active booking
    (`state_resolution.py:128-131`), and that error belongs to the **properties** domain,
    which has no error handler — so it escaped as an unhandled 500 until
    `PropertyStateBlocksCleaningError` gave it a home. The design's risk note had already
    promised a 409 here.
    """
    db_session.add(
        ReservationModel(
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            channel="DIRECT",
            check_in_date=(NOW - timedelta(days=1)).date(),
            check_out_date=(NOW + timedelta(days=2)).date(),
            nights=3,
            status=ReservationStatus.CHECKED_IN_ESTIMATED,
        )
    )
    await db_session.flush()
    cleaner = await _drive_to_completable(
        api, task_a.id, cleaner_a, users_by_role_a[UserRole.PROPERTY_MANAGER]
    )

    blocked = await api.post(f"{TASKS}/{task_a.id}/complete", headers=cleaner)

    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_a_critical_incident_blocks_completion(
    api, db_session, tenant_a, property_a, users_by_role_a, cleaner_a, task_a
):
    """R5.2 — implemented against the `incidents` table even though `maintenance` has no
    application layer yet, so the row is inserted directly."""
    cleaner = auth_header(api, cleaner_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner_a.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    await api.post(f"{TASKS}/{task_a.id}/accept", headers=cleaner)
    await api.post(f"{TASKS}/{task_a.id}/start", headers=cleaner)
    for item in ("kitchen", "bathroom"):
        await api.post(f"{TASKS}/{task_a.id}/checklist/{item}/complete", headers=cleaner)

    db_session.add(
        IncidentModel(
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            title="Fuga de agua",
            description="En el baño",
            source=IncidentSource.CLEANER,
            severity=IncidentSeverity.CRITICAL,
            status=IncidentStatus.OPEN,
        )
    )
    await db_session.flush()

    blocked = await api.post(f"{TASKS}/{task_a.id}/complete", headers=cleaner)

    assert blocked.status_code == 409
    assert "CRITICAL" in blocked.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_critical_incident_of_another_tenant_does_not_block(
    api, db_session, tenant_a, tenant_b, property_b, users_by_role_a, cleaner_a, task_a
):
    """R5.2 scoped by tenant — the gap the tenancy reviewer noted without filing.

    `SqlAlchemyBlockingIncidentQuery` filters by `tenant_id` **and** `property_id`. The second
    already makes a collision impossible in practice, so nothing pinned the first; if someone
    dropped it, no test went red.
    """
    cleaner = await _drive_to_completable(
        api, task_a.id, cleaner_a, users_by_role_a[UserRole.PROPERTY_MANAGER]
    )
    db_session.add(
        IncidentModel(
            tenant_id=tenant_b.id,
            property_id=property_b.id,
            title="Del vecino",
            description="x",
            source=IncidentSource.CLEANER,
            severity=IncidentSeverity.CRITICAL,
            status=IncidentStatus.OPEN,
        )
    )
    await db_session.flush()

    assert (await api.post(f"{TASKS}/{task_a.id}/complete", headers=cleaner)).status_code == 200


@pytest.mark.asyncio
async def test_a_resolved_critical_incident_does_not_block(
    api, db_session, tenant_a, property_a, users_by_role_a, cleaner_a, task_a
):
    cleaner = auth_header(api, cleaner_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner_a.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    await api.post(f"{TASKS}/{task_a.id}/accept", headers=cleaner)
    await api.post(f"{TASKS}/{task_a.id}/start", headers=cleaner)
    for item in ("kitchen", "bathroom"):
        await api.post(f"{TASKS}/{task_a.id}/checklist/{item}/complete", headers=cleaner)

    db_session.add(
        IncidentModel(
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            title="Ya resuelta",
            description="x",
            source=IncidentSource.CLEANER,
            severity=IncidentSeverity.CRITICAL,
            status=IncidentStatus.RESOLVED,
        )
    )
    await db_session.flush()

    assert (await api.post(f"{TASKS}/{task_a.id}/complete", headers=cleaner)).status_code == 200


# --- rejection and its replacement ------------------------------------------------


@pytest.mark.asyncio
async def test_rejection_is_terminal_and_leaves_a_replacement(
    api, db_session, tenant_a, property_a, users_by_role_a, cleaner_a, task_a
):
    """R3.5, design D3 — the property must never be left with no live task."""
    cleaner = auth_header(api, cleaner_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner_a.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    rejected = await api.post(f"{TASKS}/{task_a.id}/reject", headers=cleaner)

    assert rejected.status_code == 200
    replacement = rejected.json()
    assert replacement["id"] != str(task_a.id)
    assert replacement["status"] == CleaningTaskStatus.CREATED.value
    assert replacement["assigned_cleaner_id"] is None

    rows = await db_session.execute(
        select(CleaningTaskModel).where(CleaningTaskModel.tenant_id == tenant_a.id)
    )
    tasks = {task.id: task for task in rows.scalars()}
    assert len(tasks) == 2
    # The rejected row keeps its assignee: that column is the record of who declined.
    assert tasks[task_a.id].status is CleaningTaskStatus.REJECTED
    assert tasks[task_a.id].assigned_cleaner_id == cleaner_a.id

    assert (
        await _state_of(db_session, property_a.id)
        is PropertyOperationalState.AWAITING_CLEANING
    )


# --- assignment edges -------------------------------------------------------------


@pytest.mark.asyncio
async def test_assigning_a_non_cleaner_is_refused(
    api, users_by_role_a, task_a
):
    """R3.3 — the person named must hold `CLEANER`."""
    response = await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(users_by_role_a[UserRole.TECHNICIAN].id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_assigning_a_deactivated_cleaner_is_refused(
    api, db_session, tenant_a, users_by_role_a, task_a
):
    """The asymmetry the security panel of `/sdd:review` named.

    The automatic path filters the roster by `ACTIVE`; the manual one only checked the role,
    so a manager could hand work to somebody the tenant had deactivated — and that writes a
    notification to their address.
    """
    retired = await _insert_cleaner(db_session, tenant_a, status=UserStatus.INACTIVE)

    response = await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(retired.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_assigning_a_cleaner_of_another_tenant_is_refused(
    api, db_session, tenant_b, users_by_role_a, task_a
):
    """Rule 1 — `assigned_cleaner_id` is a plain FK, so the database would have accepted it."""
    neighbour = await _insert_cleaner(db_session, tenant_b)

    response = await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(neighbour.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_accepting_a_task_assigned_to_someone_else_is_a_404(
    api, db_session, tenant_a, users_by_role_a, cleaner_a, task_a
):
    """R7.2, R7.3 — and the body must equal the one an unknown id produces."""
    other = await _insert_cleaner(db_session, tenant_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(other.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    response = await api.post(f"{TASKS}/{task_a.id}/accept", headers=auth_header(api, cleaner_a))
    unknown = await api.post(
        f"{TASKS}/{uuid.uuid4()}/accept", headers=auth_header(api, cleaner_a)
    )

    assert response.status_code == 404
    assert unknown.status_code == 404
    assert response.json() == unknown.json()


@pytest.mark.asyncio
async def test_starting_before_accepting_is_a_conflict(
    api, users_by_role_a, cleaner_a, task_a
):
    """R3.7 — the assignee in a wrong state gets 409, not 404."""
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner_a.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    response = await api.post(f"{TASKS}/{task_a.id}/start", headers=auth_header(api, cleaner_a))

    assert response.status_code == 409


# --- checklist --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_checklist_is_driven_by_the_template(api, users_by_role_a, task_a):
    """R4.1 — untouched items appear, with their `required` flag."""
    response = await api.get(
        f"{TASKS}/{task_a.id}/checklist",
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 200
    items = {row["item_id"]: row for row in response.json()["data"]}
    assert set(items) == {"kitchen", "bathroom", "balcony"}
    assert items["kitchen"]["required"] is True
    assert items["balcony"]["required"] is False
    assert all(row["completed"] is False for row in items.values())


@pytest.mark.asyncio
async def test_ticking_the_same_item_twice_is_idempotent(
    api, users_by_role_a, cleaner_a, task_a
):
    """R4.4 — against `uq_cleaning_checklist_completions_cleaning_task_id_item_id`."""
    cleaner = auth_header(api, cleaner_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner_a.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    await api.post(f"{TASKS}/{task_a.id}/accept", headers=cleaner)
    await api.post(f"{TASKS}/{task_a.id}/start", headers=cleaner)

    for _ in range(2):
        assert (
            await api.post(f"{TASKS}/{task_a.id}/checklist/kitchen/complete", headers=cleaner)
        ).status_code == 204

    checklist = await api.get(f"{TASKS}/{task_a.id}/checklist", headers=cleaner)
    ticked = [row for row in checklist.json()["data"] if row["completed"]]
    assert [row["item_id"] for row in ticked] == ["kitchen"]


@pytest.mark.asyncio
async def test_an_unknown_checklist_item_is_a_404(api, users_by_role_a, cleaner_a, task_a):
    """R4.3."""
    cleaner = auth_header(api, cleaner_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner_a.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    await api.post(f"{TASKS}/{task_a.id}/accept", headers=cleaner)
    await api.post(f"{TASKS}/{task_a.id}/start", headers=cleaner)

    response = await api.post(f"{TASKS}/{task_a.id}/checklist/garden/complete", headers=cleaner)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_the_checklist_cannot_be_filled_before_starting(
    api, users_by_role_a, cleaner_a, task_a
):
    """R4.5."""
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner_a.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    response = await api.post(
        f"{TASKS}/{task_a.id}/checklist/kitchen/complete", headers=auth_header(api, cleaner_a)
    )

    assert response.status_code == 409


# --- manual validation ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_manager_records_a_verdict(
    api, db_session, tenant_a, users_by_role_a, cleaner_a, task_a
):
    """R5.5."""
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    cleaner = auth_header(api, cleaner_a)
    await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(cleaner_a.id)},
        headers=auth_header(api, manager),
    )
    await api.post(f"{TASKS}/{task_a.id}/accept", headers=cleaner)
    await api.post(f"{TASKS}/{task_a.id}/start", headers=cleaner)
    for item in ("kitchen", "bathroom"):
        await api.post(f"{TASKS}/{task_a.id}/checklist/{item}/complete", headers=cleaner)
    await api.post(f"{TASKS}/{task_a.id}/complete", headers=cleaner)

    response = await api.post(
        f"{TASKS}/{task_a.id}/validate",
        json={"validation_status": CleaningValidationStatus.WAIVED.value},
        headers=auth_header(api, manager),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["validation_status"] == CleaningValidationStatus.WAIVED.value
    assert body["validated_by_user_id"] == str(manager.id)
    assert audit_actions.CLEANING_TASK_VALIDATED in await _audit_actions_of(
        db_session, tenant_a.id
    )


@pytest.mark.asyncio
async def test_pending_is_not_an_acceptable_verdict(api, users_by_role_a, task_a):
    response = await api.post(
        f"{TASKS}/{task_a.id}/validate",
        json={"validation_status": CleaningValidationStatus.PENDING.value},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 409


# --- manual creation --------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_manager_creates_a_task_by_hand(
    api, users_by_role_a, property_a, template_a
):
    response = await api.post(
        TASKS,
        json={"property_id": str(property_a.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 201
    assert response.json()["checklist_template_id"] == str(template_a.id)


@pytest.mark.asyncio
async def test_creating_against_another_tenants_property_is_a_404(
    api, users_by_role_a, property_b, template_a
):
    """R7.3 — same body as an unknown id (the derived obligation of design D6)."""
    response = await api.post(
        TASKS,
        json={"property_id": str(property_b.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    unknown = await api.post(
        TASKS,
        json={"property_id": str(uuid.uuid4())},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 404
    assert response.json() == unknown.json()


@pytest.mark.asyncio
async def test_creating_against_another_tenants_reservation_is_a_404(
    api, db_session, tenant_b, property_b, users_by_role_a, property_a, template_a
):
    """The second of the three identifiers `add` cannot vet itself."""
    neighbour_reservation = ReservationModel(
        tenant_id=tenant_b.id,
        property_id=property_b.id,
        channel="DIRECT",
        check_in_date=NOW.date(),
        check_out_date=(NOW + timedelta(days=1)).date(),
        nights=1,
    )
    db_session.add(neighbour_reservation)
    await db_session.flush()

    response = await api.post(
        TASKS,
        json={
            "property_id": str(property_a.id),
            "reservation_id": str(neighbour_reservation.id),
        },
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_creating_a_second_live_task_for_one_reservation_is_a_conflict(
    api, db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """R2.5 through the manual path — the partial index is the authority."""
    from tests.cleaning.conftest import insert_reservation

    reservation = await insert_reservation(db_session, tenant_a, property_a)
    manager = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    payload = {"property_id": str(property_a.id), "reservation_id": str(reservation.id)}

    assert (await api.post(TASKS, json=payload, headers=manager)).status_code == 201
    assert (await api.post(TASKS, json=payload, headers=manager)).status_code == 409


@pytest.mark.asyncio
async def test_creating_without_a_resolvable_template_is_a_404(
    api, users_by_role_a, property_a
):
    """R1.3 reaching the manual path: there is nothing to point the task at."""
    response = await api.post(
        TASKS,
        json={"property_id": str(property_a.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 404


# --- listing, isolation and the authorisation matrix ------------------------------


@pytest.mark.asyncio
async def test_the_listing_is_scoped_to_the_tenant(
    api, db_session, tenant_b, property_b, template_b, users_by_role_a, task_a
):
    await insert_task(db_session, tenant_b, property_b, template_b)

    response = await api.get(
        TASKS, headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )

    assert response.json()["total"] == 1
    assert [row["id"] for row in response.json()["data"]] == [str(task_a.id)]


@pytest.mark.asyncio
async def test_a_cleaner_sees_only_their_own_tasks(
    api, db_session, tenant_a, property_a, template_a, users_by_role_a, cleaner_a, task_a
):
    """R7.2 — the row-level restriction, derived from the role."""
    other = await _insert_cleaner(db_session, tenant_a)
    mine = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.ASSIGNED,
        cleaner=cleaner_a,
    )
    await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.ASSIGNED,
        cleaner=other,
    )

    response = await api.get(TASKS, headers=auth_header(api, cleaner_a))

    assert [row["id"] for row in response.json()["data"]] == [str(mine.id)]
    assert response.json()["total"] == 1


@pytest.mark.asyncio
async def test_a_cleaner_cannot_read_another_cleaners_task(
    api, db_session, tenant_a, property_a, template_a, cleaner_a
):
    other = await _insert_cleaner(db_session, tenant_a)
    theirs = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.ASSIGNED,
        cleaner=other,
    )

    response = await api.get(f"{TASKS}/{theirs.id}", headers=auth_header(api, cleaner_a))

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_cleaner_cannot_read_another_cleaners_checklist(
    api, db_session, tenant_a, property_a, template_a, cleaner_a
):
    """R7.2 on the checklist read — the security panel of `/sdd:review` found it untested.

    The rule *was* applied in `GetChecklistUseCase`; what was missing is the test that would
    go red if a refactor dropped it, on the one table with no `tenant_id` behind it.
    """
    other = await _insert_cleaner(db_session, tenant_a)
    theirs = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=other,
    )

    response = await api.get(
        f"{TASKS}/{theirs.id}/checklist", headers=auth_header(api, cleaner_a)
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_cleaner_cannot_tick_another_cleaners_checklist(
    api, db_session, tenant_a, property_a, template_a, cleaner_a
):
    """R7.2 on the checklist write — the path that reaches the table with no net."""
    other = await _insert_cleaner(db_session, tenant_a)
    theirs = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=other,
    )

    response = await api.post(
        f"{TASKS}/{theirs.id}/checklist/kitchen/complete", headers=auth_header(api, cleaner_a)
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_the_checklist_of_another_tenants_task_is_a_404(
    api, db_session, tenant_b, property_b, template_b, users_by_role_a
):
    """R7.3 on both checklist endpoints, with the body identical to an unknown id."""
    neighbour = await insert_task(
        db_session, tenant_b, property_b, template_b, status=CleaningTaskStatus.IN_PROGRESS
    )
    manager = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    read = await api.get(f"{TASKS}/{neighbour.id}/checklist", headers=manager)
    unknown = await api.get(f"{TASKS}/{uuid.uuid4()}/checklist", headers=manager)

    assert read.status_code == 404
    assert read.json() == unknown.json()


@pytest.mark.asyncio
async def test_reading_another_tenants_task_is_a_404(
    api, db_session, tenant_b, property_b, template_b, users_by_role_a
):
    """R7.3."""
    neighbour = await insert_task(db_session, tenant_b, property_b, template_b)
    manager = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    response = await api.get(f"{TASKS}/{neighbour.id}", headers=manager)
    unknown = await api.get(f"{TASKS}/{uuid.uuid4()}", headers=manager)

    assert response.status_code == 404
    assert response.json() == unknown.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["?per_page=101", "?page=0", "?page=100001"])
async def test_pagination_bounds_are_enforced(api, users_by_role_a, query):
    response = await api.get(
        f"{TASKS}{query}", headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "listing", "assignment", "acceptance"),
    [
        #                          GET /   PATCH /{id}   POST /{id}/accept
        (UserRole.SUPER_ADMIN, 403, 403, 403),
        (UserRole.TENANT_OWNER, 200, 403, 403),
        # 422: holds MANAGE, so it gets past the permission and is refused by the business
        # rule — the cleaner id is a random UUID, not a `CLEANER` of this tenant.
        (UserRole.PROPERTY_MANAGER, 200, 422, 403),
        # 404: holds EXECUTE, and the task is unassigned, so for this cleaner it does not
        # exist (R7.2). That is the concrete code the old `!= 403` assertion was hiding.
        (UserRole.CLEANER, 200, 403, 404),
        (UserRole.TECHNICIAN, 403, 403, 403),
    ],
)
async def test_authorization_matrix(
    api, users_by_role_a, task_a, role, listing, assignment, acceptance
):
    """R7.4 — every role against one endpoint of each permission class, on the exact code.

    It used to assert `status_code != 403`, which the QA reviewer of `/sdd:review` called
    vacuous and was right to: it would have passed just as happily on a `500`, which is
    precisely the regression an authorisation smoke test is there to catch. Pinning the exact
    code costs nothing and documents *why* a permitted role is still refused.
    """
    headers = auth_header(api, users_by_role_a[role])

    assert (await api.get(TASKS, headers=headers)).status_code == listing

    patched = await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"assigned_cleaner_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert patched.status_code == assignment

    accepted = await api.post(f"{TASKS}/{task_a.id}/accept", headers=headers)
    assert accepted.status_code == acceptance


@pytest.mark.asyncio
async def test_every_endpoint_requires_authentication(api, task_a):
    assert (await api.get(TASKS)).status_code == 401
    assert (await api.post(TASKS, json={"property_id": str(uuid.uuid4())})).status_code == 401
    assert (await api.get(f"{TASKS}/{task_a.id}")).status_code == 401
    assert (await api.post(f"{TASKS}/{task_a.id}/accept")).status_code == 401
    assert (await api.get(f"{TASKS}/{task_a.id}/checklist")).status_code == 401
    assert (
        await api.post(f"{TASKS}/{task_a.id}/checklist/kitchen/complete")
    ).status_code == 401


@pytest.mark.asyncio
async def test_the_response_never_carries_notes(api, users_by_role_a, task_a):
    """Design D13 — `notes` is neither writable nor readable in this change."""
    response = await api.get(
        f"{TASKS}/{task_a.id}",
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert "notes" not in response.json()


@pytest.mark.asyncio
async def test_the_patch_refuses_anything_but_the_assignee(api, users_by_role_a, task_a):
    """The status moves only through the lifecycle endpoints, so the machine is never bypassed."""
    response = await api.patch(
        f"{TASKS}/{task_a.id}",
        json={"status": "COMPLETED"},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 422
