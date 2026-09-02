"""`EscalateBreachedSlasUseCase` — SLA enforcement (`celery-jobs` R5, R4.4).

Unit tests with in-memory fakes. The one thing they must not let pass is a row that
carries a rule-3 value forward into `subject`/`body` (rule 11 of `steering/security.md`).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from app.auth.domain.entities import User
from app.core.tenancy import CrossTenantWriteError
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.repositories import UserFilters, UserPage
from app.notifications.application.use_cases import EscalateBreachedSlasUseCase
from app.tenants.domain.entities import TenantConfig
from app.tenants.domain.enums import StorageType
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.exceptions import NotificationLogNotFoundError
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from tests.reservations.doubles import FakeUnitOfWork

TENANT = uuid.uuid4()
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


@dataclass
class FakeNotificationLogRepository:
    logs: dict[uuid.UUID, NotificationLog] = field(default_factory=dict)

    def seed(self, log: NotificationLog) -> NotificationLog:
        self.logs[log.id] = log
        return log

    async def list_sla_breach_candidates(self, tenant_id, now):
        rows = [
            log
            for log in self.logs.values()
            if log.tenant_id == tenant_id
            and log.status is NotificationStatus.SENT
            and log.sla_deadline_at is not None
            and log.sla_deadline_at < now
            and not log.sla_breached
        ]
        return sorted(rows, key=lambda log: (log.sla_deadline_at, str(log.id)))

    async def mark_breached(self, tenant_id, log) -> None:
        # Mirrors the real adapter, which raises rather than marking nothing — a fake that
        # is more permissive would make these tests prove less than they claim.
        if log.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="notification log",
                entity_tenant_id=log.tenant_id,
                acting_tenant_id=tenant_id,
            )
        if log.id not in self.logs:
            raise NotificationLogNotFoundError(log.id)
        self.logs[log.id].sla_breached = True

    async def add(self, tenant_id, log) -> None:
        if log.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="notification log",
                entity_tenant_id=log.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self.logs[log.id] = log

    @property
    def escalations(self) -> list[NotificationLog]:
        return [
            log
            for log in self.logs.values()
            if log.notification_type == NotificationType.SLA_BREACH.value
        ]


@dataclass
class FakeUserRepository:
    users: list[User] = field(default_factory=list)

    def add_user(
        self,
        *,
        role: UserRole,
        status: UserStatus = UserStatus.ACTIVE,
        name="Ana",
        tenant_id: uuid.UUID | None = None,
    ):
        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant_id or TENANT,
            name=name,
            email=f"{name.lower()}-{uuid.uuid4().hex[:6]}@example.com",
            password_hash="x",
            role=role,
            created_at=NOW,
            updated_at=NOW,
            status=status,
        )
        self.users.append(user)
        return user

    async def list(self, tenant_id, filters: UserFilters, *, page: int, per_page: int) -> UserPage:
        rows = [
            user
            for user in self.users
            if user.tenant_id == tenant_id
            and (filters.role is None or user.role is filters.role)
            and (filters.status is None or user.status is filters.status)
        ]
        # `name ASC, id ASC`, like `SqlAlchemyUserRepository.list`: a fake with a
        # different order would drop different people under truncation than production.
        rows.sort(key=lambda user: (user.name, str(user.id)))
        start = (page - 1) * per_page
        return UserPage(items=tuple(rows[start : start + per_page]), total=len(rows))


def _breached(
    *,
    notification_type: str = NotificationType.CLEANING_TASK_ASSIGNED.value,
    subject: str | None = "Cleaning assigned",
    body: str | None = None,
    minutes_late: int = 5,
) -> NotificationLog:
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        recipient_contact="cleaner@example.com",
        channel=NotificationChannel.EMAIL,
        notification_type=notification_type,
        created_at=NOW,
        updated_at=NOW,
        status=NotificationStatus.SENT,
        subject=subject,
        body=body,
        sla_deadline_at=NOW - timedelta(minutes=minutes_late),
    )


class FakeTenantConfigRepository:
    """Minimal `TenantConfigRepository` for the escalation harness — `notification-channel-routing`.

    Default has both flags off so the resolver returns `{IN_APP}` only — matching the
    expectations this file carried before the fan-out was wired through. Tests that want
    to exercise R3 (contact missing) or the multi-channel fan-out pass `email_enabled=True`
    or `whatsapp_enabled=True`.
    """

    def __init__(
        self,
        *,
        email_enabled: bool = False,
        whatsapp_enabled: bool = False,
    ) -> None:
        self._email_enabled = email_enabled
        self._whatsapp_enabled = whatsapp_enabled

    async def get_or_create(
        self, tenant_id: uuid.UUID, now: datetime
    ) -> TenantConfig:
        return TenantConfig(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            created_at=now,
            updated_at=now,
            notification_email_enabled=self._email_enabled,
            notification_whatsapp_enabled=self._whatsapp_enabled,
            storage_type=StorageType.LOCAL,
        )


class Harness:
    def __init__(self) -> None:
        self.notifications = FakeNotificationLogRepository()
        self.users = FakeUserRepository()
        self.tenant_configs = FakeTenantConfigRepository()
        self.uow = FakeUnitOfWork()

    async def run(self, now: datetime = NOW):
        return await EscalateBreachedSlasUseCase(
            notifications=self.notifications,
            users=self.users,
            tenant_configs=self.tenant_configs,
            uow=self.uow,
        ).execute(tenant_id=TENANT, now=now)


@pytest.mark.asyncio
async def test_a_breached_technician_assignment_writes_a_technician_no_response_row() -> None:
    """R3.1 end to end: the row the job actually writes, not just what `_POLICY` returns.

    Added because the section-3 QA panel found R3.1's headline clause covered only at the
    pure-policy layer (`escalation_for`), one level above where `_escalation_row` composes
    the row — so a regression between the policy and the write would have passed the suite.
    QA proved the behaviour with a throwaway probe; this is that probe made permanent.

    `escalations` filters on `SLA_BREACH`, so it deliberately does **not** collect this row:
    reading the log store directly is the point, since the whole change is that this row is
    no longer an `SLA_BREACH`.
    """
    harness = Harness()
    manager = harness.users.add_user(role=UserRole.PROPERTY_MANAGER)
    breached = harness.notifications.seed(
        _breached(
            notification_type=NotificationType.TECHNICIAN_ASSIGNED.value,
            subject="Incident assigned",
        )
    )

    report = await harness.run()

    assert report.escalated == 1
    written = [
        log
        for log in harness.notifications.logs.values()
        if log.id != breached.id
    ]
    # Default harness config has both flags off → resolver returns `{IN_APP}` only.
    assert [log.notification_type for log in written] == [
        NotificationType.TECHNICIAN_NO_RESPONSE.value
    ]
    assert [log.channel for log in written] == [NotificationChannel.IN_APP]
    # R3.1 keeps recipient and reason: only the type moved (design D8).
    assert written[0].recipient_user_id == manager.id
    assert written[0].related_id == breached.id
    # R3.2's other half, asserted here rather than assumed: no `SLA_BREACH` was written.
    assert harness.notifications.escalations == []


@pytest.mark.asyncio
async def test_a_breached_assignment_is_marked_and_escalated_to_the_manager() -> None:
    harness = Harness()
    manager = harness.users.add_user(role=UserRole.PROPERTY_MANAGER)
    breached = harness.notifications.seed(_breached())

    report = await harness.run()

    assert report.breached == 1
    assert report.escalated == 1
    assert harness.notifications.logs[breached.id].sla_breached is True
    [escalation] = harness.notifications.escalations
    assert escalation.recipient_user_id == manager.id
    assert escalation.recipient_contact == manager.email
    assert escalation.related_id == breached.id
    assert harness.uow.commits == 1


@pytest.mark.asyncio
async def test_the_escalation_is_queued_never_sent() -> None:
    """The seam with `access-notifications` (design D11): PENDING, not SENT, not FAILED."""
    harness = Harness()
    harness.users.add_user(role=UserRole.PROPERTY_MANAGER)
    harness.notifications.seed(_breached())

    await harness.run()

    [escalation] = harness.notifications.escalations
    assert escalation.status is NotificationStatus.PENDING
    assert escalation.sent_at is None
    assert escalation.attempts == 0
    assert escalation.sla_breached is False


@pytest.mark.asyncio
async def test_every_active_manager_gets_a_row() -> None:
    """Design D17: choosing one could hand the warning to whoever is on holiday."""
    harness = Harness()
    first = harness.users.add_user(role=UserRole.PROPERTY_MANAGER, name="Ana")
    second = harness.users.add_user(role=UserRole.PROPERTY_MANAGER, name="Bea")
    harness.users.add_user(role=UserRole.PROPERTY_MANAGER, name="Ines", status=UserStatus.INACTIVE)
    harness.notifications.seed(_breached())

    report = await harness.run()

    assert report.rows_written == 2
    assert {row.recipient_user_id for row in harness.notifications.escalations} == {
        first.id,
        second.id,
    }


@pytest.mark.asyncio
async def test_without_a_manager_it_falls_back_to_the_owner() -> None:
    harness = Harness()
    owner = harness.users.add_user(role=UserRole.TENANT_OWNER, name="Marta")
    harness.notifications.seed(_breached())

    report = await harness.run()

    assert report.escalated == 1
    [escalation] = harness.notifications.escalations
    assert escalation.recipient_user_id == owner.id


@pytest.mark.asyncio
async def test_with_nobody_at_all_the_breach_stays_a_candidate() -> None:
    """Design D17 rejects marking without a recipient outright.

    `sla_breached = False` is the candidate filter, so marking here would make the breach
    permanently unescalatable while the row claimed it had been handled. Leaving it unmarked
    means the run retries every minute until somebody fixes the roster — noisy on purpose.
    """
    harness = Harness()
    breached = harness.notifications.seed(_breached())

    report = await harness.run()

    assert report.without_recipient == 1
    assert report.escalated == 0
    assert report.rows_written == 0
    assert harness.notifications.logs[breached.id].sla_breached is False

    # ...and once an owner exists, the very next run escalates it.
    owner = harness.users.add_user(role=UserRole.TENANT_OWNER, name="Marta")
    second = await harness.run()

    assert second.escalated == 1
    assert harness.notifications.escalations[0].recipient_user_id == owner.id
    assert harness.notifications.logs[breached.id].sla_breached is True


@pytest.mark.asyncio
async def test_a_type_without_an_escalation_is_marked_and_recorded() -> None:
    """R5.6: no invented recipient, but it stops being a candidate."""
    harness = Harness()
    harness.users.add_user(role=UserRole.PROPERTY_MANAGER)
    breached = harness.notifications.seed(
        _breached(notification_type=NotificationType.CHECKOUT_REMINDER.value)
    )

    report = await harness.run()

    assert report.without_action == 1
    assert report.escalated == 0
    assert harness.notifications.escalations == []
    assert harness.notifications.logs[breached.id].sla_breached is True


@pytest.mark.asyncio
async def test_an_unknown_notification_type_does_not_break_the_run() -> None:
    harness = Harness()
    harness.users.add_user(role=UserRole.PROPERTY_MANAGER)
    harness.notifications.seed(_breached(notification_type="INVENTED_BY_A_LATER_CHANGE"))
    harness.notifications.seed(_breached())

    report = await harness.run()

    assert report.without_action == 1
    assert report.escalated == 1


@pytest.mark.asyncio
async def test_a_second_pass_escalates_nothing_new() -> None:
    """R4.4. The `sla_breached = False` filter is the whole mechanism."""
    harness = Harness()
    harness.users.add_user(role=UserRole.PROPERTY_MANAGER)
    harness.notifications.seed(_breached())

    first = await harness.run()
    rows_after_first = len(harness.notifications.escalations)
    second = await harness.run()

    assert first.escalated == 1
    assert second.breached == 0
    assert len(harness.notifications.escalations) == rows_after_first


@pytest.mark.asyncio
async def test_nothing_to_do_does_not_open_a_transaction() -> None:
    harness = Harness()

    report = await harness.run()

    assert report.breached == 0
    assert harness.uow.commits == 0


class TestRule11:
    """The contract of `steering/security.md` rule 11 for `subject`/`body`."""

    @pytest.mark.asyncio
    async def test_the_body_of_the_breached_notification_is_never_copied_forward(self) -> None:
        """The original may legitimately carry a masked access code (rule 11's single
        exception). The escalation is a different row for a different audience, so it
        carries a reference, not the text."""
        harness = Harness()
        harness.users.add_user(role=UserRole.PROPERTY_MANAGER)
        breached = harness.notifications.seed(
            _breached(body="Your access code is ****47 and the WiFi is on the fridge")
        )

        await harness.run()

        [escalation] = harness.notifications.escalations
        assert "****47" not in (escalation.body or "")
        assert "WiFi" not in (escalation.body or "")
        assert str(breached.id) in (escalation.body or "")

    @pytest.mark.asyncio
    async def test_the_subject_of_the_breached_notification_is_never_copied_forward(self) -> None:
        """`subject` is the other half of that row's contract, and it had no test.

        A future `subject=f"SLA breach: {breached.subject}"` would have passed the whole
        suite while forwarding a value out of the breached row. It cannot be written now —
        `_escalation_row` never receives the entity — and this fails if that changes.
        """
        harness = Harness()
        harness.users.add_user(role=UserRole.PROPERTY_MANAGER)
        harness.notifications.seed(
            _breached(subject="Door code ****91 for tonight", body="also ****91")
        )

        await harness.run()

        [escalation] = harness.notifications.escalations
        assert "****91" not in (escalation.subject or "")
        assert "****91" not in (escalation.body or "")
        assert escalation.subject == "SLA breach"

    @pytest.mark.asyncio
    async def test_this_use_case_never_writes_last_error(self) -> None:
        """`last_error` is the structured-form sink of rule 11 and belongs to the sender
        in `access-notifications`; nothing here has a delivery diagnostic to record."""
        harness = Harness()
        harness.users.add_user(role=UserRole.PROPERTY_MANAGER)
        harness.notifications.seed(_breached())

        await harness.run()

        assert all(row.last_error is None for row in harness.notifications.escalations)


class TestTenantIsolation:
    """Rule 1 of `steering/security.md` for this module, and the promise task 4.2 made.

    Section 3 set the shape (`test_the_transition_is_anchored_to_a_property_of_the_acting_tenant`):
    the port cannot verify that `recipient_user_id` belongs to the tenant, so the guarantee
    is pinned here, where the reference is resolved.
    """

    @pytest.mark.asyncio
    async def test_a_neighbours_manager_never_receives_the_escalation(self) -> None:
        other = uuid.uuid4()
        harness = Harness()
        mine = harness.users.add_user(role=UserRole.PROPERTY_MANAGER, name="Ana")
        harness.users.add_user(role=UserRole.PROPERTY_MANAGER, name="Zoe", tenant_id=other)
        harness.notifications.seed(_breached())

        report = await harness.run()

        assert report.rows_written == 1
        [escalation] = harness.notifications.escalations
        assert escalation.recipient_user_id == mine.id
        assert escalation.tenant_id == TENANT

    @pytest.mark.asyncio
    async def test_a_neighbours_breach_is_not_a_candidate(self) -> None:
        other = uuid.uuid4()
        harness = Harness()
        harness.users.add_user(role=UserRole.PROPERTY_MANAGER)
        theirs = _breached()
        theirs.tenant_id = other
        harness.notifications.seed(theirs)

        report = await harness.run()

        assert report.breached == 0
        assert harness.notifications.escalations == []
        assert harness.notifications.logs[theirs.id].sla_breached is False


class TestRecipientRoleIsNotCachedAcrossRoles:
    @pytest.mark.asyncio
    async def test_two_escalations_with_different_roles_reach_different_people(
        self, monkeypatch
    ) -> None:
        """The misroute QA reproduced: the roster used to be memoised on nothing, so the
        second candidate inherited whichever role the first one happened to need."""
        from app.notifications.domain import escalation as escalation_module
        from app.notifications.domain.escalation import Escalation

        monkeypatch.setitem(
            escalation_module._POLICY,
            NotificationType.TECHNICIAN_ASSIGNED,
            Escalation(
                notification_type=NotificationType.SLA_BREACH,
                recipient_role=UserRole.TENANT_OWNER,
                reason="technician_assignment_unanswered_no_phone_adapter",
            ),
        )
        harness = Harness()
        manager = harness.users.add_user(role=UserRole.PROPERTY_MANAGER, name="Ana")
        owner = harness.users.add_user(role=UserRole.TENANT_OWNER, name="Marta")
        # The manager-bound breach is older, so it is processed first.
        harness.notifications.seed(_breached(minutes_late=30))
        harness.notifications.seed(
            _breached(
                notification_type=NotificationType.TECHNICIAN_ASSIGNED.value, minutes_late=5
            )
        )

        report = await harness.run()

        assert report.escalated == 2
        by_recipient = {row.recipient_user_id for row in harness.notifications.escalations}
        assert by_recipient == {manager.id, owner.id}


class TestRecipientTruncation:
    @pytest.mark.asyncio
    async def test_more_recipients_than_one_page_writes_every_row(self) -> None:
        """A tenant with more managers than one page used to get a silent partial
        notification: the page capped, the counter recorded the gap, and the escalation
        rows went out to the truncated subset. R6.2 closes the gap end-to-end, so this
        test now pins the post-fix contract: every active manager is notified and
        `recipients_truncated` stays at zero."""
        from app.auth.domain.recipients import RoleRecipients

        harness = Harness()
        for index in range(RoleRecipients.PAGE_SIZE + 3):
            harness.users.add_user(role=UserRole.PROPERTY_MANAGER, name=f"Mgr{index:03d}")
        harness.notifications.seed(_breached())

        report = await harness.run()

        assert report.rows_written == RoleRecipients.PAGE_SIZE + 3
        assert report.recipients_truncated == 0

    @pytest.mark.asyncio
    async def test_the_owner_fallback_writes_every_row_too(self) -> None:
        """The fallback used to skip the page boundary, so a tenant with more owners than
        one page and no manager reintroduced the silent partial notification the counter
        exists to prevent. The end-to-end loop closes it; this test pins the fallback
        path at a roster larger than one page (R6.2). Found by the section-4 QA re-review."""
        from app.auth.domain.recipients import RoleRecipients

        harness = Harness()
        for index in range(RoleRecipients.PAGE_SIZE + 2):
            harness.users.add_user(role=UserRole.TENANT_OWNER, name=f"Own{index:03d}")
        harness.notifications.seed(_breached())

        report = await harness.run()

        assert report.rows_written == RoleRecipients.PAGE_SIZE + 2
        assert report.recipients_truncated == 0
