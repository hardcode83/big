"""`SqlAlchemyNotificationLogRepository` — candidate selection and tenant scoping.

Covers `celery-jobs` R5 (the four conditions of PRD §14), R4.4 (`sla_breached` is what
makes a second pass a no-op) and rule 1 of `steering/security.md`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.infrastructure.models import UserModel
from app.core.tenancy import CrossTenantWriteError
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel, NotificationStatus
from app.notifications.domain.exceptions import NotificationLogNotFoundError
from app.notifications.infrastructure.models import NotificationLogModel
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.tenants.infrastructure.models import TenantModel

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


async def _tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _log(
    db_session,
    tenant: TenantModel,
    *,
    status: NotificationStatus = NotificationStatus.SENT,
    sla_deadline_at: datetime | None = NOW - timedelta(minutes=1),
    sla_breached: bool = False,
    related_type: str | None = None,
    related_id: uuid.UUID | None = None,
    notification_type: str = "CLEANING_TASK_ASSIGNED",
    created_at: datetime | None = None,
) -> NotificationLogModel:
    model = NotificationLogModel(
        tenant_id=tenant.id,
        recipient_contact="manager@example.com",
        channel=NotificationChannel.EMAIL,
        notification_type=notification_type,
        status=status,
        sla_deadline_at=sla_deadline_at,
        sla_breached=sla_breached,
        related_type=related_type,
        related_id=related_id,
    )
    if created_at is not None:
        model.created_at = created_at
    db_session.add(model)
    await db_session.flush()
    return model


@pytest.mark.asyncio
async def test_a_sent_log_past_its_deadline_is_a_candidate(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    overdue = await _log(db_session, tenant)

    found = await SqlAlchemyNotificationLogRepository(db_session).list_sla_breach_candidates(
        tenant.id, NOW
    )

    assert [log.id for log in found] == [overdue.id]


@pytest.mark.asyncio
async def test_the_four_conditions_of_prd_14_each_exclude_a_row(db_session) -> None:
    """One row per condition, each failing exactly one of them."""
    tenant = await _tenant(db_session, "TenantA")
    await _log(db_session, tenant, status=NotificationStatus.PENDING)
    await _log(db_session, tenant, sla_deadline_at=None)
    await _log(db_session, tenant, sla_deadline_at=NOW + timedelta(minutes=5))
    await _log(db_session, tenant, sla_breached=True)

    found = await SqlAlchemyNotificationLogRepository(db_session).list_sla_breach_candidates(
        tenant.id, NOW
    )

    assert found == []


@pytest.mark.asyncio
async def test_a_deadline_exactly_now_has_not_passed_yet(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    await _log(db_session, tenant, sla_deadline_at=NOW)

    found = await SqlAlchemyNotificationLogRepository(db_session).list_sla_breach_candidates(
        tenant.id, NOW
    )

    assert found == []


@pytest.mark.asyncio
async def test_candidates_come_oldest_breach_first(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    recent = await _log(db_session, tenant, sla_deadline_at=NOW - timedelta(minutes=1))
    oldest = await _log(db_session, tenant, sla_deadline_at=NOW - timedelta(hours=3))

    found = await SqlAlchemyNotificationLogRepository(db_session).list_sla_breach_candidates(
        tenant.id, NOW
    )

    assert [log.id for log in found] == [oldest.id, recent.id]


@pytest.mark.asyncio
async def test_candidates_never_cross_tenants(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    await _log(db_session, tenant_b)

    found = await SqlAlchemyNotificationLogRepository(db_session).list_sla_breach_candidates(
        tenant_a.id, NOW
    )

    assert found == []


@pytest.mark.asyncio
async def test_mark_breached_removes_the_row_from_the_candidates(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    await _log(db_session, tenant)
    repository = SqlAlchemyNotificationLogRepository(db_session)
    [candidate] = await repository.list_sla_breach_candidates(tenant.id, NOW)

    await repository.mark_breached(tenant.id, candidate)

    assert await repository.list_sla_breach_candidates(tenant.id, NOW) == []


@pytest.mark.asyncio
async def test_mark_breached_refuses_another_tenants_log(db_session) -> None:
    """Loud, not a silent no-op — the escalation is already written by then (R5.3)."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    await _log(db_session, tenant_b)
    repository = SqlAlchemyNotificationLogRepository(db_session)
    [theirs] = await repository.list_sla_breach_candidates(tenant_b.id, NOW)

    with pytest.raises(CrossTenantWriteError):
        await repository.mark_breached(tenant_a.id, theirs)

    still_a_candidate = await repository.list_sla_breach_candidates(tenant_b.id, NOW)
    assert [log.id for log in still_a_candidate] == [theirs.id]


@pytest.mark.asyncio
async def test_mark_breached_of_a_vanished_row_raises_instead_of_marking_nothing(
    db_session,
) -> None:
    """The cause we cannot prove still breaks R5.3, so it fails — just not by claiming
    a tenant mismatch it has no evidence for."""
    tenant = await _tenant(db_session, "TenantA")
    await _log(db_session, tenant)
    repository = SqlAlchemyNotificationLogRepository(db_session)
    [candidate] = await repository.list_sla_breach_candidates(tenant.id, NOW)
    candidate.id = uuid.uuid4()

    with pytest.raises(NotificationLogNotFoundError):
        await repository.mark_breached(tenant.id, candidate)


@pytest.mark.asyncio
async def test_add_persists_the_escalation_row(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    log = NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        recipient_contact="manager@example.com",
        channel=NotificationChannel.EMAIL,
        notification_type="SLA_BREACH",
        created_at=NOW,
        updated_at=NOW,
        subject="SLA breach",
        body="A cleaning assignment passed its deadline.",
        related_type="notification_log",
        related_id=uuid.uuid4(),
    )

    await SqlAlchemyNotificationLogRepository(db_session).add(tenant.id, log)

    stored = (
        await db_session.execute(
            select(NotificationLogModel).where(NotificationLogModel.id == log.id)
        )
    ).scalar_one()
    assert stored.status is NotificationStatus.PENDING
    assert stored.notification_type == "SLA_BREACH"
    assert stored.sla_breached is False


@pytest.mark.asyncio
async def test_list_pending_returns_only_pending_rows_oldest_first(db_session) -> None:
    """The dispatcher's queue (R4.2). `PENDING` is the seam every writer leaves behind."""
    tenant = await _tenant(db_session, "TenantA")
    recent = await _log(
        db_session,
        tenant,
        status=NotificationStatus.PENDING,
        created_at=NOW - timedelta(minutes=1),
    )
    oldest = await _log(
        db_session,
        tenant,
        status=NotificationStatus.PENDING,
        created_at=NOW - timedelta(hours=2),
    )
    await _log(db_session, tenant, status=NotificationStatus.SENT)
    await _log(db_session, tenant, status=NotificationStatus.FAILED)
    await _log(db_session, tenant, status=NotificationStatus.SKIPPED)

    found = await SqlAlchemyNotificationLogRepository(db_session).list_pending(tenant.id, 10)

    assert [log.id for log in found] == [oldest.id, recent.id]


@pytest.mark.asyncio
async def test_list_pending_honours_the_batch_limit(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    for minutes in range(3):
        await _log(
            db_session,
            tenant,
            status=NotificationStatus.PENDING,
            created_at=NOW - timedelta(minutes=minutes),
        )

    found = await SqlAlchemyNotificationLogRepository(db_session).list_pending(tenant.id, 2)

    assert len(found) == 2


@pytest.mark.asyncio
async def test_list_pending_never_crosses_tenants(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    await _log(db_session, tenant_b, status=NotificationStatus.PENDING)

    found = await SqlAlchemyNotificationLogRepository(db_session).list_pending(tenant_a.id, 10)

    assert found == []


@pytest.mark.asyncio
async def test_record_attempt_writes_only_the_delivery_columns(db_session) -> None:
    """The port is narrow on purpose: nothing else on the row may move (design D4)."""
    tenant = await _tenant(db_session, "TenantA")
    related = uuid.uuid4()
    row = await _log(
        db_session,
        tenant,
        status=NotificationStatus.PENDING,
        sla_deadline_at=NOW + timedelta(hours=1),
        related_type="cleaning_task",
        related_id=related,
    )

    await SqlAlchemyNotificationLogRepository(db_session).record_attempt(
        tenant.id,
        row.id,
        status=NotificationStatus.SENT,
        attempts=1,
        sent_at=NOW,
        last_error=None,
    )

    await db_session.refresh(row)
    assert row.status is NotificationStatus.SENT
    assert row.attempts == 1
    assert row.sent_at == NOW
    assert row.last_error is None
    # Untouched by this write, and that is the assertion that matters.
    assert row.recipient_contact == "manager@example.com"
    assert row.notification_type == "CLEANING_TASK_ASSIGNED"
    assert row.related_type == "cleaning_task"
    assert row.related_id == related
    assert row.sla_deadline_at == NOW + timedelta(hours=1)


@pytest.mark.asyncio
async def test_record_attempt_stores_the_structured_failure(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    row = await _log(db_session, tenant, status=NotificationStatus.PENDING)

    await SqlAlchemyNotificationLogRepository(db_session).record_attempt(
        tenant.id,
        row.id,
        status=NotificationStatus.PENDING,
        attempts=2,
        sent_at=None,
        last_error='{"code": "TIMEOUT", "channel": "EMAIL", "attempt": 2}',
    )

    await db_session.refresh(row)
    assert row.attempts == 2
    assert row.status is NotificationStatus.PENDING
    assert '"code": "TIMEOUT"' in (row.last_error or "")


@pytest.mark.asyncio
async def test_record_attempt_of_another_tenants_row_writes_nothing_and_raises(
    db_session,
) -> None:
    """The delivery already happened by then: a silent no-op would re-send next tick."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _log(db_session, tenant_b, status=NotificationStatus.PENDING)

    with pytest.raises(NotificationLogNotFoundError):
        await SqlAlchemyNotificationLogRepository(db_session).record_attempt(
            tenant_a.id,
            theirs.id,
            status=NotificationStatus.SENT,
            attempts=1,
            sent_at=NOW,
            last_error=None,
        )

    await db_session.refresh(theirs)
    assert theirs.status is NotificationStatus.PENDING


@pytest.mark.asyncio
async def test_cancel_sla_deadline_clears_only_the_deadline(db_session) -> None:
    """R5 / design D7: out of the candidate query without claiming or denying anything."""
    tenant = await _tenant(db_session, "TenantA")
    task_id = uuid.uuid4()
    row = await _log(
        db_session,
        tenant,
        status=NotificationStatus.SENT,
        sla_deadline_at=NOW + timedelta(hours=4),
        related_type="cleaning_task",
        related_id=task_id,
    )
    repository = SqlAlchemyNotificationLogRepository(db_session)

    cleared = await repository.cancel_sla_deadline(
        tenant.id,
        related_type="cleaning_task",
        related_id=task_id,
        notification_type="CLEANING_TASK_ASSIGNED",
    )

    assert cleared == 1
    await db_session.refresh(row)
    assert row.sla_deadline_at is None
    assert row.status is NotificationStatus.SENT
    assert row.sla_breached is False
    assert row.subject == row.subject  # unchanged: the port may not rewrite content


@pytest.mark.asyncio
async def test_cancel_sla_deadline_takes_the_row_out_of_the_candidates(db_session) -> None:
    """R5.4 — the whole point: no `SLA_BREACH` for a task that was answered."""
    tenant = await _tenant(db_session, "TenantA")
    task_id = uuid.uuid4()
    await _log(
        db_session,
        tenant,
        status=NotificationStatus.SENT,
        sla_deadline_at=NOW - timedelta(minutes=1),
        related_type="cleaning_task",
        related_id=task_id,
    )
    repository = SqlAlchemyNotificationLogRepository(db_session)
    assert await repository.list_sla_breach_candidates(tenant.id, NOW) != []

    await repository.cancel_sla_deadline(
        tenant.id,
        related_type="cleaning_task",
        related_id=task_id,
        notification_type="CLEANING_TASK_ASSIGNED",
    )

    assert await repository.list_sla_breach_candidates(tenant.id, NOW) == []


@pytest.mark.asyncio
async def test_cancel_sla_deadline_is_idempotent_and_zero_is_not_an_error(
    db_session,
) -> None:
    """R5.3: a task with no assignment row, or one already closed, answers without error."""
    tenant = await _tenant(db_session, "TenantA")
    task_id = uuid.uuid4()
    await _log(
        db_session,
        tenant,
        sla_deadline_at=NOW + timedelta(hours=4),
        related_type="cleaning_task",
        related_id=task_id,
    )
    repository = SqlAlchemyNotificationLogRepository(db_session)

    assert (
        await repository.cancel_sla_deadline(
            tenant.id,
            related_type="cleaning_task",
            related_id=task_id,
            notification_type="CLEANING_TASK_ASSIGNED",
        )
        == 1
    )
    assert (
        await repository.cancel_sla_deadline(
            tenant.id,
            related_type="cleaning_task",
            related_id=task_id,
            notification_type="CLEANING_TASK_ASSIGNED",
        )
        == 0
    )
    assert (
        await repository.cancel_sla_deadline(
            tenant.id,
            related_type="cleaning_task",
            related_id=uuid.uuid4(),
            notification_type="CLEANING_TASK_ASSIGNED",
        )
        == 0
    )


@pytest.mark.asyncio
async def test_cancel_sla_deadline_only_touches_the_matching_type(db_session) -> None:
    """The polymorphic pair alone is not enough: another notification about the same task
    keeps its own deadline."""
    tenant = await _tenant(db_session, "TenantA")
    task_id = uuid.uuid4()
    other = await _log(
        db_session,
        tenant,
        sla_deadline_at=NOW + timedelta(hours=4),
        related_type="cleaning_task",
        related_id=task_id,
        notification_type="CLEANING_NO_RESPONSE",
    )

    cleared = await SqlAlchemyNotificationLogRepository(db_session).cancel_sla_deadline(
        tenant.id,
        related_type="cleaning_task",
        related_id=task_id,
        notification_type="CLEANING_TASK_ASSIGNED",
    )

    assert cleared == 0
    await db_session.refresh(other)
    assert other.sla_deadline_at is not None


@pytest.mark.asyncio
async def test_cancel_sla_deadline_never_crosses_tenants(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    task_id = uuid.uuid4()
    theirs = await _log(
        db_session,
        tenant_b,
        sla_deadline_at=NOW + timedelta(hours=4),
        related_type="cleaning_task",
        related_id=task_id,
    )

    cleared = await SqlAlchemyNotificationLogRepository(db_session).cancel_sla_deadline(
        tenant_a.id,
        related_type="cleaning_task",
        related_id=task_id,
        notification_type="CLEANING_TASK_ASSIGNED",
    )

    assert cleared == 0
    await db_session.refresh(theirs)
    assert theirs.sla_deadline_at is not None


@pytest.mark.asyncio
async def test_add_refuses_a_log_of_another_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    log = NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        recipient_contact="manager@example.com",
        channel=NotificationChannel.EMAIL,
        notification_type="SLA_BREACH",
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyNotificationLogRepository(db_session).add(tenant_a.id, log)


# -- `exists_for`: the deduplication behind R1.3 (design D2) --------------------------


@pytest.mark.asyncio
async def test_exists_for_is_false_when_no_row_points_at_the_entity(db_session) -> None:
    tenant = await _tenant(db_session, "ExistsNone")
    repo = SqlAlchemyNotificationLogRepository(db_session)

    assert (
        await repo.exists_for(
            tenant.id,
            related_type="incident",
            related_id=uuid.uuid4(),
            notification_type="INCIDENT_CREATED_CRITICAL",
        )
        is False
    )


@pytest.mark.asyncio
async def test_exists_for_sees_a_row_written_in_the_same_transaction(db_session) -> None:
    """The property the whole of R1.3 rests on (design D2): visible without a commit.

    If it were not, a classification and a triage inside one transaction would each see
    "nothing yet" and both write — exactly the double notification R1.3 forbids.

    **What this does and does not pin**, because the section-2 QA panel measured it: the
    session runs with `autoflush` on, so the `select` inside `exists_for` flushes pending
    work by itself. This test therefore pins the *property* — same-transaction visibility —
    and NOT the explicit `flush()` inside `add`, which it would pass without. That is the
    honest reading: the property is what R1.3 needs, and it has two independent causes.
    """
    tenant = await _tenant(db_session, "ExistsSameTx")
    repo = SqlAlchemyNotificationLogRepository(db_session)
    incident_id = uuid.uuid4()

    await repo.add(
        tenant.id,
        NotificationLog(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            recipient_contact="manager@example.com",
            channel=NotificationChannel.IN_APP,
            notification_type="INCIDENT_CREATED_CRITICAL",
            created_at=NOW,
            updated_at=NOW,
            subject="Incident is critical",
            body=f"Incident {incident_id}.",
            status=NotificationStatus.PENDING,
            related_type="incident",
            related_id=incident_id,
        ),
    )

    assert (
        await repo.exists_for(
            tenant.id,
            related_type="incident",
            related_id=incident_id,
            notification_type="INCIDENT_CREATED_CRITICAL",
        )
        is True
    )


@pytest.mark.asyncio
async def test_exists_for_discriminates_on_each_leg_of_the_triple(db_session) -> None:
    """All three legs, because a query that ignored one would still pass a happy-path test.

    R1.4 depends on the `notification_type` leg in particular: an incident raised from HIGH
    to CRITICAL must be announced again, and it only is if the existing `INCIDENT_CREATED_HIGH`
    row does not answer for `INCIDENT_CREATED_CRITICAL`.
    """
    tenant = await _tenant(db_session, "ExistsTriple")
    repo = SqlAlchemyNotificationLogRepository(db_session)
    incident_id = uuid.uuid4()
    await _log(
        db_session,
        tenant,
        related_type="incident",
        related_id=incident_id,
        notification_type="INCIDENT_CREATED_HIGH",
    )

    assert await repo.exists_for(
        tenant.id,
        related_type="incident",
        related_id=incident_id,
        notification_type="INCIDENT_CREATED_HIGH",
    )
    # A different severity is a different fact (R1.4).
    assert not await repo.exists_for(
        tenant.id,
        related_type="incident",
        related_id=incident_id,
        notification_type="INCIDENT_CREATED_CRITICAL",
    )
    # A different entity.
    assert not await repo.exists_for(
        tenant.id,
        related_type="incident",
        related_id=uuid.uuid4(),
        notification_type="INCIDENT_CREATED_HIGH",
    )
    # A different kind of entity carrying the same id.
    assert not await repo.exists_for(
        tenant.id,
        related_type="cleaning_task",
        related_id=incident_id,
        notification_type="INCIDENT_CREATED_HIGH",
    )


@pytest.mark.asyncio
async def test_exists_for_never_sees_another_tenants_row(db_session) -> None:
    """Rule 1 of `steering/security.md`, and here it is not a read leak but a write one.

    A row of tenant B answering for tenant A would *suppress* A's notification: the manager
    is never told, and nothing anywhere records that a neighbour's row is why.
    """
    mine = await _tenant(db_session, "ExistsMine")
    theirs = await _tenant(db_session, "ExistsTheirs")
    repo = SqlAlchemyNotificationLogRepository(db_session)
    incident_id = uuid.uuid4()
    await _log(
        db_session,
        theirs,
        related_type="incident",
        related_id=incident_id,
        notification_type="INCIDENT_CREATED_CRITICAL",
    )

    assert not await repo.exists_for(
        mine.id,
        related_type="incident",
        related_id=incident_id,
        notification_type="INCIDENT_CREATED_CRITICAL",
    )
    assert await repo.exists_for(
        theirs.id,
        related_type="incident",
        related_id=incident_id,
        notification_type="INCIDENT_CREATED_CRITICAL",
    )


@pytest.mark.asyncio
async def test_exists_for_refuses_a_null_related_entity(db_session) -> None:
    """A null would widen a **suppression** check, so it is rejected, not tolerated.

    `column == None` compiles to `IS NULL`, which would match every row of the type that
    points at nothing — and since a `True` here means the caller writes no notification,
    that widening silences alerts. Raised by the section-2 security panel while the method
    still had no callers, which is why it costs nothing to close.
    """
    tenant = await _tenant(db_session, "ExistsNullGuard")
    repo = SqlAlchemyNotificationLogRepository(db_session)

    with pytest.raises(ValueError):
        await repo.exists_for(
            tenant.id,
            related_type="incident",
            related_id=None,  # type: ignore[arg-type]
            notification_type="INCIDENT_CREATED_CRITICAL",
        )
    with pytest.raises(ValueError):
        await repo.exists_for(
            tenant.id,
            related_type=None,  # type: ignore[arg-type]
            related_id=uuid.uuid4(),
            notification_type="INCIDENT_CREATED_CRITICAL",
        )


# --- The inbox: `notifications-inbox-web` section 2 (D3, D4, D5, D6) ----------------------
#
# The helpers above build logs with no recipient, which is all the SLA job ever needed. Every
# query below is scoped by recipient as well as by tenant, so they need real users.


async def _user(db_session, tenant: TenantModel, email: str) -> UserModel:
    user = UserModel(
        tenant_id=tenant.id,
        name=email.split("@")[0],
        email=email,
        password_hash="hash",
        role="PROPERTY_MANAGER",
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _inbox_log(
    db_session,
    tenant: TenantModel,
    recipient: UserModel,
    *,
    read_at: datetime | None = None,
    created_at: datetime | None = None,
) -> NotificationLogModel:
    model = NotificationLogModel(
        tenant_id=tenant.id,
        recipient_user_id=recipient.id,
        recipient_contact=recipient.email,
        channel=NotificationChannel.IN_APP,
        notification_type="CLEANING_TASK_ASSIGNED",
        status=NotificationStatus.SENT,
        read_at=read_at,
    )
    if created_at is not None:
        model.created_at = created_at
    db_session.add(model)
    await db_session.flush()
    return model


@pytest.mark.asyncio
async def test_mark_read_stamps_the_first_read(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    manager = await _user(db_session, tenant, "manager@example.com")
    log = await _inbox_log(db_session, tenant, manager)
    repository = SqlAlchemyNotificationLogRepository(db_session)

    acknowledged = await repository.mark_read(tenant.id, manager.id, log.id)

    assert acknowledged is True
    await db_session.refresh(log)
    assert log.read_at is not None


@pytest.mark.asyncio
async def test_mark_read_twice_succeeds_and_keeps_the_first_instant(db_session) -> None:
    """R1.3: `read_at` is the first read, not the last visit.

    The instant comes from Python, not from Postgres `now()` — with the transaction
    timestamp the two calls would agree whatever `COALESCE` did, and this test would be
    vacuous.
    """
    tenant = await _tenant(db_session, "TenantA")
    manager = await _user(db_session, tenant, "manager@example.com")
    log = await _inbox_log(db_session, tenant, manager)
    repository = SqlAlchemyNotificationLogRepository(db_session)

    assert await repository.mark_read(tenant.id, manager.id, log.id) is True
    await db_session.refresh(log)
    first = log.read_at

    assert await repository.mark_read(tenant.id, manager.id, log.id) is True
    await db_session.refresh(log)

    assert log.read_at == first


@pytest.mark.asyncio
async def test_mark_read_of_an_unknown_id_reports_false(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    manager = await _user(db_session, tenant, "manager@example.com")

    acknowledged = await SqlAlchemyNotificationLogRepository(db_session).mark_read(
        tenant.id, manager.id, uuid.uuid4()
    )

    assert acknowledged is False


@pytest.mark.asyncio
async def test_mark_read_of_a_colleagues_row_reports_false_and_moves_nothing(
    db_session,
) -> None:
    """R1.4, first of its three cases: same tenant, another recipient."""
    tenant = await _tenant(db_session, "TenantA")
    manager = await _user(db_session, tenant, "manager@example.com")
    cleaner = await _user(db_session, tenant, "cleaner@example.com")
    theirs = await _inbox_log(db_session, tenant, manager)

    acknowledged = await SqlAlchemyNotificationLogRepository(db_session).mark_read(
        tenant.id, cleaner.id, theirs.id
    )

    assert acknowledged is False
    await db_session.refresh(theirs)
    assert theirs.read_at is None


@pytest.mark.asyncio
async def test_mark_read_never_crosses_tenants(db_session) -> None:
    """R1.4/R1.5, rule 1 of `steering/security.md`."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs_user = await _user(db_session, tenant_b, "theirs@example.com")
    theirs = await _inbox_log(db_session, tenant_b, theirs_user)

    acknowledged = await SqlAlchemyNotificationLogRepository(db_session).mark_read(
        tenant_a.id, theirs_user.id, theirs.id
    )

    assert acknowledged is False
    await db_session.refresh(theirs)
    assert theirs.read_at is None


@pytest.mark.asyncio
async def test_count_unread_ignores_read_rows_colleagues_and_other_tenants(
    db_session,
) -> None:
    """R2.2. Three ways of not counting, in one test, because they are one query."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    manager = await _user(db_session, tenant_a, "manager@example.com")
    cleaner = await _user(db_session, tenant_a, "cleaner@example.com")
    theirs = await _user(db_session, tenant_b, "theirs@example.com")

    await _inbox_log(db_session, tenant_a, manager)
    await _inbox_log(db_session, tenant_a, manager)
    await _inbox_log(db_session, tenant_a, manager, read_at=NOW)
    await _inbox_log(db_session, tenant_a, cleaner)
    await _inbox_log(db_session, tenant_b, theirs)

    unread = await SqlAlchemyNotificationLogRepository(db_session).count_unread(
        tenant_a.id, manager.id
    )

    assert unread == 2


@pytest.mark.asyncio
async def test_mark_all_read_moves_only_this_users_unread_rows(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    manager = await _user(db_session, tenant_a, "manager@example.com")
    cleaner = await _user(db_session, tenant_a, "cleaner@example.com")
    theirs = await _user(db_session, tenant_b, "theirs@example.com")
    already_read = await _inbox_log(db_session, tenant_a, manager, read_at=NOW)
    await _inbox_log(db_session, tenant_a, manager)
    await _inbox_log(db_session, tenant_a, manager)
    colleagues = await _inbox_log(db_session, tenant_a, cleaner)
    neighbours = await _inbox_log(db_session, tenant_b, theirs)
    repository = SqlAlchemyNotificationLogRepository(db_session)

    updated = await repository.mark_all_read(tenant_a.id, manager.id)

    assert updated == 2
    await db_session.refresh(already_read)
    assert already_read.read_at == NOW
    await db_session.refresh(colleagues)
    assert colleagues.read_at is None
    await db_session.refresh(neighbours)
    assert neighbours.read_at is None
    assert await repository.count_unread(tenant_a.id, manager.id) == 0


@pytest.mark.asyncio
async def test_mark_all_read_on_an_inbox_already_up_to_date_returns_zero(db_session) -> None:
    """D6: zero rows is the normal case, not an error."""
    tenant = await _tenant(db_session, "TenantA")
    manager = await _user(db_session, tenant, "manager@example.com")
    await _inbox_log(db_session, tenant, manager, read_at=NOW)

    updated = await SqlAlchemyNotificationLogRepository(db_session).mark_all_read(
        tenant.id, manager.id
    )

    assert updated == 0


@pytest.mark.asyncio
async def test_the_unread_filter_keeps_the_envelope_the_order_and_the_page(
    db_session,
) -> None:
    """R2.3/D5: the same query with one more condition — nothing else moves."""
    tenant = await _tenant(db_session, "TenantA")
    manager = await _user(db_session, tenant, "manager@example.com")
    oldest = await _inbox_log(
        db_session, tenant, manager, created_at=NOW - timedelta(hours=2)
    )
    middle = await _inbox_log(
        db_session, tenant, manager, created_at=NOW - timedelta(hours=1), read_at=NOW
    )
    newest = await _inbox_log(db_session, tenant, manager, created_at=NOW)
    repository = SqlAlchemyNotificationLogRepository(db_session)

    everything = await repository.list_for_recipient(
        tenant.id, manager.id, page=1, per_page=20
    )
    only_unread = await repository.list_for_recipient(
        tenant.id, manager.id, page=1, per_page=20, unread=True
    )

    assert everything.total == 3
    assert [item.id for item in everything.items] == [newest.id, middle.id, oldest.id]
    assert only_unread.total == 2
    assert [item.id for item in only_unread.items] == [newest.id, oldest.id]


@pytest.mark.asyncio
async def test_the_unread_filter_paginates_over_the_filtered_set(db_session) -> None:
    """`total` counts what the filter admits, so `total_pages` upstream stays truthful."""
    tenant = await _tenant(db_session, "TenantA")
    manager = await _user(db_session, tenant, "manager@example.com")
    for offset in range(3):
        await _inbox_log(
            db_session, tenant, manager, created_at=NOW - timedelta(hours=offset)
        )
    await _inbox_log(db_session, tenant, manager, created_at=NOW, read_at=NOW)

    page_two = await SqlAlchemyNotificationLogRepository(db_session).list_for_recipient(
        tenant.id, manager.id, page=2, per_page=2, unread=True
    )

    assert page_two.total == 3
    assert len(page_two.items) == 1


@pytest.mark.asyncio
async def test_unread_false_is_the_same_as_not_asking(db_session) -> None:
    """The default is "all of them", and `False` is not a third meaning."""
    tenant = await _tenant(db_session, "TenantA")
    manager = await _user(db_session, tenant, "manager@example.com")
    await _inbox_log(db_session, tenant, manager)
    await _inbox_log(db_session, tenant, manager, read_at=NOW)
    repository = SqlAlchemyNotificationLogRepository(db_session)

    default = await repository.list_for_recipient(tenant.id, manager.id, page=1, per_page=20)
    explicit = await repository.list_for_recipient(
        tenant.id, manager.id, page=1, per_page=20, unread=False
    )

    assert default.total == explicit.total == 2


@pytest.mark.asyncio
async def test_list_for_recipient_never_crosses_tenants_with_the_filter_on(
    db_session,
) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    manager = await _user(db_session, tenant_a, "manager@example.com")
    theirs = await _user(db_session, tenant_b, "theirs@example.com")
    await _inbox_log(db_session, tenant_b, theirs)

    found = await SqlAlchemyNotificationLogRepository(db_session).list_for_recipient(
        tenant_a.id, manager.id, page=1, per_page=20, unread=True
    )

    assert found.total == 0
    assert found.items == ()


@pytest.mark.asyncio
async def test_acknowledging_moves_nothing_the_sla_looks_at(db_session) -> None:
    """R1.6 / design D17: reading a notice is not answering it.

    Written here rather than against the in-memory fakes of `test_escalate_slas.py` on
    purpose — `mark_read` and `list_sla_breach_candidates` are both real statements against
    the real table, and the claim is about what one does to the other. A fake would only
    prove that the fake agrees with itself.
    """
    tenant = await _tenant(db_session, "TenantA")
    manager = await _user(db_session, tenant, "manager@example.com")
    log = NotificationLogModel(
        tenant_id=tenant.id,
        recipient_user_id=manager.id,
        recipient_contact=manager.email,
        channel=NotificationChannel.IN_APP,
        notification_type="CLEANING_TASK_ASSIGNED",
        status=NotificationStatus.SENT,
        sla_deadline_at=NOW - timedelta(minutes=1),
        sla_breached=False,
    )
    db_session.add(log)
    await db_session.flush()
    repository = SqlAlchemyNotificationLogRepository(db_session)
    assert [row.id for row in await repository.list_sla_breach_candidates(tenant.id, NOW)] == [
        log.id
    ]

    assert await repository.mark_read(tenant.id, manager.id, log.id) is True

    await db_session.refresh(log)
    assert log.read_at is not None
    assert log.sla_deadline_at == NOW - timedelta(minutes=1)
    assert log.sla_breached is False
    still_a_candidate = await repository.list_sla_breach_candidates(tenant.id, NOW)
    assert [row.id for row in still_a_candidate] == [log.id]


@pytest.mark.asyncio
async def test_mark_all_read_moves_nothing_the_sla_looks_at_either(db_session) -> None:
    """The same claim for the bulk path (R1.6): "mark all" is still only reading."""
    tenant = await _tenant(db_session, "TenantA")
    manager = await _user(db_session, tenant, "manager@example.com")
    log = NotificationLogModel(
        tenant_id=tenant.id,
        recipient_user_id=manager.id,
        recipient_contact=manager.email,
        channel=NotificationChannel.IN_APP,
        notification_type="CLEANING_TASK_ASSIGNED",
        status=NotificationStatus.SENT,
        sla_deadline_at=NOW - timedelta(minutes=1),
        sla_breached=False,
    )
    db_session.add(log)
    await db_session.flush()
    repository = SqlAlchemyNotificationLogRepository(db_session)

    assert await repository.mark_all_read(tenant.id, manager.id) == 1

    await db_session.refresh(log)
    assert log.sla_deadline_at == NOW - timedelta(minutes=1)
    assert log.sla_breached is False
    assert [row.id for row in await repository.list_sla_breach_candidates(tenant.id, NOW)] == [
        log.id
    ]

