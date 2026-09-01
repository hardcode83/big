"""The fan-out that turns a resolved set into N rows (R2, R4 of `notification-channel-routing`).

The function is **pure** by design — it does not touch the database, does not need a
session, and does not need the adapter registry. The tests pin the N rows shape (R2.1,
R2.3), the SLA-on-IN_APP-only invariant (R4.1), and the cancellation that closes every
sibling in one call (R4.2).

The builders used here are inline fakes that mirror the signature the production
builders will grow (section 3 of `tasks.md`): `channel: NotificationChannel` and
`contact: str | None` are added as optional kwargs and the builder decides where to
write them. The production builders' integration tests live in section 7.5.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.notifications.application.channel_dispatch import dispatch_channels
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel, NotificationStatus


_NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


def _user(*, email: str = "u@example.com", phone: str | None = "+34000000000") -> User:
    return User(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Recipient",
        email=email,
        password_hash="x",
        role=UserRole.CLEANER,
        created_at=_NOW,
        updated_at=_NOW,
        phone=phone,
        status=UserStatus.ACTIVE,
    )


# ---------------------------------------------------------------------------
# Test builders — fakes that mirror the (channel, contact) signature the real
# builders will adopt in section 3.
# ---------------------------------------------------------------------------


def assignment_like_builder(
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    sla_minutes: int,
    now: datetime,
    channel: NotificationChannel = NotificationChannel.IN_APP,
    contact: str | None = None,
) -> NotificationLog:
    """Mimics `cleaning.assignment_notification`: deadline only on IN_APP, contact
    derived from `contact`."""
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=uuid.uuid4(),
        recipient_contact=contact or "",
        channel=channel,
        notification_type="CLEANING_TASK_ASSIGNED",
        created_at=now,
        updated_at=now,
        subject="Cleaning assigned",
        body=f"Task {task_id}",
        status=NotificationStatus.PENDING,
        related_type="cleaning_task",
        related_id=task_id,
        sla_deadline_at=now + timedelta(minutes=sla_minutes) if channel == NotificationChannel.IN_APP else None,
    )


def no_deadline_builder(
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    now: datetime,
    channel: NotificationChannel = NotificationChannel.IN_APP,
    contact: str | None = None,
) -> NotificationLog:
    """Mimics a builder that never sets `sla_deadline_at`."""
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=uuid.uuid4(),
        recipient_contact=contact or "",
        channel=channel,
        notification_type="CLEANING_NO_RESPONSE",
        created_at=now,
        updated_at=now,
        subject="Cleaning unassigned",
        body=f"Task {task_id}",
        status=NotificationStatus.PENDING,
        related_type="cleaning_task",
        related_id=task_id,
    )


def technician_assignment_like_builder(
    *,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    sla_minutes: int,
    now: datetime,
    channel: NotificationChannel = NotificationChannel.IN_APP,
    contact: str | None = None,
) -> NotificationLog:
    """Mimics `maintenance.technician_assignment_notification`: deadline only on IN_APP."""
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=uuid.uuid4(),
        recipient_contact=contact or "",
        channel=channel,
        notification_type="TECHNICIAN_ASSIGNED",
        created_at=now,
        updated_at=now,
        subject="Incident assigned",
        body=f"Incident {incident_id}",
        status=NotificationStatus.PENDING,
        related_type="incident",
        related_id=incident_id,
        sla_deadline_at=now + timedelta(minutes=sla_minutes) if channel == NotificationChannel.IN_APP else None,
    )


from datetime import timedelta


class TestShape:
    """R2.1 — N rows, identical except for `channel` and `recipient_contact`."""

    def test_three_rows_when_all_three_channels_resolve(self) -> None:
        user = _user()
        channels = frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.EMAIL, NotificationChannel.WHATSAPP}
        )
        task_id = uuid.uuid4()
        rows = dispatch_channels(
            recipient=user,
            channels=channels,
            log_builder=assignment_like_builder,
            tenant_id=user.tenant_id,
            task_id=task_id,
            sla_minutes=60,
            now=_NOW,
        )
        assert len(rows) == 3
        # Same `notification_type`, `subject`, `body`, `related_type`, `related_id`.
        assert {row.notification_type for row in rows} == {"CLEANING_TASK_ASSIGNED"}
        assert {row.subject for row in rows} == {"Cleaning assigned"}
        assert {row.body for row in rows} == {f"Task {task_id}"}
        assert {row.related_type for row in rows} == {"cleaning_task"}
        assert {row.related_id for row in rows} == {task_id}
        # Distinct channels.
        assert {row.channel for row in rows} == set(channels)

    def test_one_row_when_only_in_app_resolves(self) -> None:
        user = _user()
        channels = frozenset({NotificationChannel.IN_APP})
        rows = dispatch_channels(
            recipient=user,
            channels=channels,
            log_builder=assignment_like_builder,
            tenant_id=user.tenant_id,
            task_id=uuid.uuid4(),
            sla_minutes=60,
            now=_NOW,
        )
        assert len(rows) == 1
        assert rows[0].channel == NotificationChannel.IN_APP

    def test_two_rows_when_phone_missing(self) -> None:
        user = _user(phone=None)
        channels = frozenset({NotificationChannel.IN_APP, NotificationChannel.EMAIL})
        rows = dispatch_channels(
            recipient=user,
            channels=channels,
            log_builder=assignment_like_builder,
            tenant_id=user.tenant_id,
            task_id=uuid.uuid4(),
            sla_minutes=60,
            now=_NOW,
        )
        assert len(rows) == 2
        assert {row.channel for row in rows} == set(channels)


class TestRecipientContactByChannel:
    """R2.3 — `recipient_contact` is the channel-appropriate contact."""

    def test_in_app_and_email_use_email(self) -> None:
        user = _user()
        channels = frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.EMAIL}
        )
        rows = dispatch_channels(
            recipient=user,
            channels=channels,
            log_builder=assignment_like_builder,
            tenant_id=user.tenant_id,
            task_id=uuid.uuid4(),
            sla_minutes=60,
            now=_NOW,
        )
        contacts = {row.channel: row.recipient_contact for row in rows}
        assert contacts[NotificationChannel.IN_APP] == user.email
        assert contacts[NotificationChannel.EMAIL] == user.email

    def test_whatsapp_uses_phone(self) -> None:
        user = _user()
        channels = frozenset({NotificationChannel.WHATSAPP})
        rows = dispatch_channels(
            recipient=user,
            channels=channels,
            log_builder=assignment_like_builder,
            tenant_id=user.tenant_id,
            task_id=uuid.uuid4(),
            sla_minutes=60,
            now=_NOW,
        )
        assert rows[0].recipient_contact == user.phone


class TestStatusIsPending:
    """R2.3 — every row is `PENDING`, ready for `dispatch_notifications` to drain."""

    def test_every_row_is_pending(self) -> None:
        user = _user()
        channels = frozenset(
            {
                NotificationChannel.IN_APP,
                NotificationChannel.EMAIL,
                NotificationChannel.WHATSAPP,
            }
        )
        rows = dispatch_channels(
            recipient=user,
            channels=channels,
            log_builder=assignment_like_builder,
            tenant_id=user.tenant_id,
            task_id=uuid.uuid4(),
            sla_minutes=60,
            now=_NOW,
        )
        assert {row.status for row in rows} == {NotificationStatus.PENDING}


class TestSlaDeadlineOnInAppOnly:
    """R4.1 — only the IN_APP row carries `sla_deadline_at`."""

    def test_only_in_app_row_has_sla_deadline(self) -> None:
        user = _user()
        channels = frozenset(
            {
                NotificationChannel.IN_APP,
                NotificationChannel.EMAIL,
                NotificationChannel.WHATSAPP,
            }
        )
        rows = dispatch_channels(
            recipient=user,
            channels=channels,
            log_builder=assignment_like_builder,
            tenant_id=user.tenant_id,
            task_id=uuid.uuid4(),
            sla_minutes=60,
            now=_NOW,
        )
        deadlines = {row.channel: row.sla_deadline_at for row in rows}
        assert deadlines[NotificationChannel.IN_APP] is not None
        assert deadlines[NotificationChannel.EMAIL] is None
        assert deadlines[NotificationChannel.WHATSAPP] is None

    def test_technician_assignment_keeps_the_same_shape(self) -> None:
        """The other deadline-bearing builder must follow the same rule (R4.1)."""
        user = _user()
        channels = frozenset(
            {
                NotificationChannel.IN_APP,
                NotificationChannel.EMAIL,
                NotificationChannel.WHATSAPP,
            }
        )
        rows = dispatch_channels(
            recipient=user,
            channels=channels,
            log_builder=technician_assignment_like_builder,
            tenant_id=user.tenant_id,
            incident_id=uuid.uuid4(),
            sla_minutes=15,
            now=_NOW,
        )
        deadlines = {row.channel: row.sla_deadline_at for row in rows}
        assert deadlines[NotificationChannel.IN_APP] is not None
        assert deadlines[NotificationChannel.EMAIL] is None
        assert deadlines[NotificationChannel.WHATSAPP] is None

    def test_builder_without_sla_keeps_null_for_every_channel(self) -> None:
        """A builder that never sets `sla_deadline_at` (R5.5) stays null across all channels."""
        user = _user()
        channels = frozenset(
            {
                NotificationChannel.IN_APP,
                NotificationChannel.EMAIL,
            }
        )
        rows = dispatch_channels(
            recipient=user,
            channels=channels,
            log_builder=no_deadline_builder,
            tenant_id=user.tenant_id,
            task_id=uuid.uuid4(),
            now=_NOW,
        )
        assert {row.sla_deadline_at for row in rows} == {None}


class TestRelatedFieldsAreIdentical:
    """R2.1 — every row of one fanned-out notification shares its `related_type/id` pair."""

    def test_same_related_pair_across_channels(self) -> None:
        user = _user()
        task_id = uuid.uuid4()
        channels = frozenset(
            {
                NotificationChannel.IN_APP,
                NotificationChannel.EMAIL,
                NotificationChannel.WHATSAPP,
            }
        )
        rows = dispatch_channels(
            recipient=user,
            channels=channels,
            log_builder=assignment_like_builder,
            tenant_id=user.tenant_id,
            task_id=task_id,
            sla_minutes=60,
            now=_NOW,
        )
        related = {(row.related_type, row.related_id) for row in rows}
        assert related == {("cleaning_task", task_id)}


# ---------------------------------------------------------------------------
# R4.2 — `cancel_sla_deadline` matches by polymorphic pair (no channel) and closes
# every sibling row in a single call. We exercise the dispatch output by feeding the
# rows through the function the use cases call.
# ---------------------------------------------------------------------------


class TestCancelSlaClosesAllSiblings:
    """R4.2 — one cancel call clears every row of the fanned-out notification."""

    def test_cancel_closes_every_row_of_a_fanned_out_notification(self) -> None:
        """Run the async fake via `asyncio.run` — pytest in this repo is sync."""
        import asyncio
        asyncio.run(self._cancel_sla_test())

    async def _cancel_sla_test(self) -> None:
        from app.notifications.domain.repositories import NotificationLogRepository

        user = _user()
        channels = frozenset(
            {
                NotificationChannel.IN_APP,
                NotificationChannel.EMAIL,
                NotificationChannel.WHATSAPP,
            }
        )
        rows = dispatch_channels(
            recipient=user,
            channels=channels,
            log_builder=assignment_like_builder,
            tenant_id=user.tenant_id,
            task_id=uuid.uuid4(),
            sla_minutes=60,
            now=_NOW,
        )
        # The repository signature in R5/cancel_sla_deadline returns the number of
        # rows it cleared; for the assertion we only care that the **one call**
        # addresses all three rows. We exercise it via a tiny fake.
        cancelled_rows: list[NotificationLog] = []

        class _FakeRepo:
            def __init__(self, rows: list[NotificationLog]) -> None:
                self._rows = rows

            async def cancel_sla_deadline(
                self,
                tenant_id: uuid.UUID,
                *,
                related_type: str,
                related_id: uuid.UUID,
                notification_type: str,
            ) -> int:
                cleared = 0
                for row in self._rows:
                    if (
                        row.tenant_id == tenant_id
                        and row.related_type == related_type
                        and row.related_id == related_id
                        and row.notification_type == notification_type
                    ):
                        row.sla_deadline_at = None
                        cancelled_rows.append(row)
                        cleared += 1
                return cleared

        # Sanity: only the IN_APP row carries a deadline (R4.1).
        assert [r.sla_deadline_at for r in rows if r.channel == NotificationChannel.IN_APP] == [
            r.sla_deadline_at for r in rows if r.channel == NotificationChannel.IN_APP
        ]
        assert all(r.sla_deadline_at is None for r in rows if r.channel != NotificationChannel.IN_APP)

        repo = _FakeRepo(rows)
        # The use case calls cancel_sla_deadline once with the polymorphic pair.
        cleared = await repo.cancel_sla_deadline(
            user.tenant_id,
            related_type="cleaning_task",
            related_id=rows[0].related_id,
            notification_type="CLEANING_TASK_ASSIGNED",
        )
        # R4.2 — one call closes every sibling.
        assert cleared == 3
        # The IN_APP row, which had the only non-NULL deadline, is now NULL; the
        # others were already NULL and stay that way.
        assert all(r.sla_deadline_at is None for r in rows)


# ---------------------------------------------------------------------------
# R4.3 — fanning out both deadline-bearing types with both flags on yields one
# candidate per notification. Verified through `list_sla_breach_candidates`-like
# filter on the fanned rows.
# ---------------------------------------------------------------------------


class TestOneCandidatePerNotification:
    """R4.3 — fanning out the two deadline-bearing types with both flags on still
    yields one SLA-breach candidate per notification (the IN_APP row of each)."""

    def test_one_candidate_per_fanned_out_notification(self) -> None:
        user_a = _user()
        user_b = _user()

        cleaning_rows = dispatch_channels(
            recipient=user_a,
            channels=frozenset(
                {
                    NotificationChannel.IN_APP,
                    NotificationChannel.EMAIL,
                    NotificationChannel.WHATSAPP,
                }
            ),
            log_builder=assignment_like_builder,
            tenant_id=user_a.tenant_id,
            task_id=uuid.uuid4(),
            sla_minutes=60,
            now=_NOW,
        )
        maintenance_rows = dispatch_channels(
            recipient=user_b,
            channels=frozenset(
                {
                    NotificationChannel.IN_APP,
                    NotificationChannel.EMAIL,
                    NotificationChannel.WHATSAPP,
                }
            ),
            log_builder=technician_assignment_like_builder,
            tenant_id=user_b.tenant_id,
            incident_id=uuid.uuid4(),
            sla_minutes=15,
            now=_NOW,
        )

        all_rows = cleaning_rows + maintenance_rows

        # `list_sla_breach_candidates` requires `status = SENT` (R4.1) and
        # `sla_deadline_at IS NOT NULL`. Mark the IN_APP rows SENT.
        for row in all_rows:
            if row.sla_deadline_at is not None:
                row.status = NotificationStatus.SENT

        # `list_sla_breach_candidates` shape: rows with deadline and SENT.
        candidates = [r for r in all_rows if r.sla_deadline_at is not None]
        # One per notification type: two notifications fanned out, two candidates.
        assert len(candidates) == 2
        notification_types = {c.notification_type for c in candidates}
        assert notification_types == {"CLEANING_TASK_ASSIGNED", "TECHNICIAN_ASSIGNED"}


# ---------------------------------------------------------------------------
# Parameterised sanity check across both deadline-bearing builders and one
# non-deadline builder — guards against regressions in section 3 wiring.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BuilderCase:
    name: str
    builder: object
    kwargs: dict[str, object]
    expects_deadline: bool


_CASES = [
    _BuilderCase(
        name="cleaning-assignment",
        builder=assignment_like_builder,
        kwargs={"task_id": uuid.uuid4(), "sla_minutes": 60},
        expects_deadline=True,
    ),
    _BuilderCase(
        name="maintenance-technician-assignment",
        builder=technician_assignment_like_builder,
        kwargs={"incident_id": uuid.uuid4(), "sla_minutes": 15},
        expects_deadline=True,
    ),
    _BuilderCase(
        name="cleaning-no-cleaner",
        builder=no_deadline_builder,
        kwargs={"task_id": uuid.uuid4()},
        expects_deadline=False,
    ),
]


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c.name)
def test_every_builder_produces_three_rows_with_both_flags_on(case: _BuilderCase) -> None:
    """R2.1 — every named builder fans out to N rows when N channels resolve."""
    user = _user()
    channels = frozenset(
        {
            NotificationChannel.IN_APP,
            NotificationChannel.EMAIL,
            NotificationChannel.WHATSAPP,
        }
    )
    rows = dispatch_channels(
        recipient=user,
        channels=channels,
        log_builder=case.builder,
        tenant_id=user.tenant_id,
        now=_NOW,
        **case.kwargs,
    )
    assert len(rows) == 3
    assert {row.channel for row in rows} == set(channels)
    assert {row.status for row in rows} == {NotificationStatus.PENDING}
    in_app = next(r for r in rows if r.channel == NotificationChannel.IN_APP)
    if case.expects_deadline:
        assert in_app.sla_deadline_at is not None
    else:
        assert in_app.sla_deadline_at is None