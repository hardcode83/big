"""`DispatchPendingNotificationsUseCase` — R4, design D4/D5.

Fakes in memory, no database: `steering/backend-architecture.md` puts `application/` tests
on in-memory fakes of the ports. What is being verified is the **ordering** and the state
machine of a delivery attempt, and both are pure orchestration.

The load-bearing assertion of the whole file is
`test_the_attempt_is_recorded_before_the_provider_is_called`: design D4's duplicate bound
holds only if that write happens first, and nothing else in the codebase would notice if a
refactor swapped the two lines.
"""

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.notifications.application.use_cases import DispatchPendingNotificationsUseCase
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel, NotificationStatus
from app.notifications.domain.repositories import NotificationLogPage
from app.notifications.domain.results import NotificationErrorCode, NotificationResult

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
TENANT = uuid.uuid4()


def _log(
    *,
    channel: NotificationChannel = NotificationChannel.EMAIL,
    attempts: int = 0,
    tenant_id: uuid.UUID = TENANT,
) -> NotificationLog:
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_contact="cleaner@example.com",
        channel=channel,
        notification_type="CLEANING_TASK_ASSIGNED",
        created_at=NOW,
        updated_at=NOW,
        subject="Cleaning assigned",
        body="A cleaning task has been assigned to you.",
        status=NotificationStatus.PENDING,
        attempts=attempts,
    )


class FakeNotificationLogRepository:
    """Records every `record_attempt` in order — the sequence IS the assertion."""

    def __init__(self, pending: list[NotificationLog]) -> None:
        self._pending = pending
        self.writes: list[dict] = []

    async def list_pending(self, tenant_id, limit):
        return [log for log in self._pending if log.tenant_id == tenant_id][:limit]

    async def record_attempt(
        self, tenant_id, log_id, *, status, attempts, sent_at, last_error
    ):
        self.writes.append(
            {
                "tenant_id": tenant_id,
                "log_id": log_id,
                "status": status,
                "attempts": attempts,
                "sent_at": sent_at,
                "last_error": last_error,
            }
        )

    # Unused by the dispatcher, present so the fake satisfies the port.
    async def list_sla_breach_candidates(self, tenant_id, now):  # pragma: no cover
        return []

    async def mark_breached(self, tenant_id, log):  # pragma: no cover
        return None

    async def add(self, tenant_id, log):  # pragma: no cover
        return None

    async def cancel_sla_deadline(self, tenant_id, **kwargs):  # pragma: no cover
        return 0

    async def list_for_recipient(self, tenant_id, recipient_user_id, *, page, per_page):
        return NotificationLogPage(items=(), total=0)  # pragma: no cover


class RecordingAdapter:
    def __init__(self, result: NotificationResult, journal: list[str]) -> None:
        self._result = result
        self._journal = journal
        self.calls: list[dict] = []

    async def send(self, *, recipient_contact, subject, body, channel):
        self._journal.append("send")
        self.calls.append(
            {
                "recipient_contact": recipient_contact,
                "subject": subject,
                "body": body,
                "channel": channel,
            }
        )
        return self._result


class FakeUnitOfWork:
    def __init__(self, journal: list[str] | None = None) -> None:
        self.commits = 0
        self._journal = journal

    async def commit(self) -> None:
        self.commits += 1
        if self._journal is not None:
            self._journal.append("commit")


def _use_case(repository, adapters, uow, *, max_attempts=3, batch_size=100):
    return DispatchPendingNotificationsUseCase(
        notifications=repository,
        adapters=adapters,
        uow=uow,
        max_attempts=max_attempts,
        batch_size=batch_size,
    )


@pytest.mark.asyncio
async def test_a_delivered_row_becomes_sent_with_its_timestamp() -> None:
    log = _log()
    repository = FakeNotificationLogRepository([log])
    adapters = {NotificationChannel.EMAIL: RecordingAdapter(NotificationResult.ok(), [])}

    report = await _use_case(repository, adapters, FakeUnitOfWork()).execute(
        tenant_id=TENANT, now=NOW
    )

    assert report.sent == 1
    assert report.considered == 1
    final = repository.writes[-1]
    assert final["status"] is NotificationStatus.SENT
    assert final["sent_at"] == NOW
    assert final["attempts"] == 1
    assert final["last_error"] is None


@pytest.mark.asyncio
async def test_the_attempt_is_recorded_before_the_provider_is_called() -> None:
    """Design D4, and the reason the duplicate bound exists at all.

    If the provider call came first, a process killed mid-send would leave `attempts` at its
    old value and the row would be retried without limit. The commit between them is what
    makes the record survive the crash.
    """
    journal: list[str] = []
    log = _log()
    repository = FakeNotificationLogRepository([log])
    adapters = {
        NotificationChannel.EMAIL: RecordingAdapter(NotificationResult.ok(), journal)
    }
    uow = FakeUnitOfWork(journal)

    original_record = repository.record_attempt

    async def journalling_record(*args, **kwargs):
        journal.append(f"record:{kwargs['status'].value}:{kwargs['attempts']}")
        return await original_record(*args, **kwargs)

    repository.record_attempt = journalling_record  # type: ignore[method-assign]

    await _use_case(repository, adapters, uow).execute(tenant_id=TENANT, now=NOW)

    assert journal == [
        "record:PENDING:1",
        "commit",
        "send",
        "record:SENT:1",
        "commit",
    ]


@pytest.mark.asyncio
async def test_a_failed_delivery_stays_pending_with_a_structured_error() -> None:
    log = _log()
    repository = FakeNotificationLogRepository([log])
    adapters = {
        NotificationChannel.EMAIL: RecordingAdapter(
            NotificationResult.failure(NotificationErrorCode.TIMEOUT), []
        )
    }

    report = await _use_case(repository, adapters, FakeUnitOfWork()).execute(
        tenant_id=TENANT, now=NOW
    )

    assert report.retrying == 1
    assert report.failed == 0
    final = repository.writes[-1]
    assert final["status"] is NotificationStatus.PENDING
    assert final["sent_at"] is None
    assert json.loads(final["last_error"]) == {
        "code": "TIMEOUT",
        "channel": "EMAIL",
        "attempt": 1,
    }


@pytest.mark.asyncio
async def test_the_last_attempt_moves_the_row_to_failed() -> None:
    """R4.4 — `notification_max_attempts` reached, and the row says we gave up."""
    log = _log(attempts=2)
    repository = FakeNotificationLogRepository([log])
    adapters = {
        NotificationChannel.EMAIL: RecordingAdapter(
            NotificationResult.failure(NotificationErrorCode.ADAPTER_ERROR), []
        )
    }

    report = await _use_case(repository, adapters, FakeUnitOfWork(), max_attempts=3).execute(
        tenant_id=TENANT, now=NOW
    )

    assert report.failed == 1
    assert report.retrying == 0
    final = repository.writes[-1]
    assert final["status"] is NotificationStatus.FAILED
    assert json.loads(final["last_error"])["code"] == "MAX_ATTEMPTS_EXCEEDED"


@pytest.mark.asyncio
async def test_a_channel_without_adapter_is_skipped_without_burning_an_attempt() -> None:
    """R4.5. `PUSH` has no adapter (`adapter_registry`), so the row leaves the queue instead
    of being picked up every minute for ever."""
    log = _log(channel=NotificationChannel.PUSH)
    repository = FakeNotificationLogRepository([log])

    report = await _use_case(repository, {}, FakeUnitOfWork()).execute(
        tenant_id=TENANT, now=NOW
    )

    assert report.skipped == 1
    [write] = repository.writes
    assert write["status"] is NotificationStatus.SKIPPED
    assert write["attempts"] == 0
    assert json.loads(write["last_error"])["code"] == "NO_ADAPTER_FOR_CHANNEL"


@pytest.mark.asyncio
async def test_sent_is_never_written_without_the_adapters_confirmation() -> None:
    """R4.6, asserted over every failure shape the adapter can report."""
    for code in NotificationErrorCode:
        repository = FakeNotificationLogRepository([_log()])
        adapters = {
            NotificationChannel.EMAIL: RecordingAdapter(
                NotificationResult.failure(code), []
            )
        }

        await _use_case(repository, adapters, FakeUnitOfWork()).execute(
            tenant_id=TENANT, now=NOW
        )

        assert all(
            write["status"] is not NotificationStatus.SENT for write in repository.writes
        ), code


class RaisingAdapter:
    """An adapter that breaks its own contract, which is the case worth testing.

    `NotificationAdapter.send` documents that it never raises for a delivery failure — but a
    docstring is not a type, and the next adapter to land is a real SMTP one whose library
    raises freely.
    """

    def __init__(self, exception: Exception) -> None:
        self._exception = exception
        self.calls = 0

    async def send(self, *, recipient_contact, subject, body, channel):
        self.calls += 1
        raise self._exception


@pytest.mark.asyncio
async def test_an_adapter_that_raises_is_a_failed_attempt_not_a_crash() -> None:
    """Found by the security panel of sections 1-2, and it was two bugs in one.

    Unguarded, the exception escaped to the scheduler's `logger.exception`, printing a
    traceback that a real SMTP library fills with the recipient and the server's response —
    the very content `adapters.py` refuses to log. And the row never reached the `FAILED`
    branch, so R4.4's terminal state was unreachable and `list_pending` re-picked it every
    minute for ever: design D4's "at-least-once, **bounded**" quietly became unbounded.
    """
    log = _log()
    repository = FakeNotificationLogRepository([log])
    adapter = RaisingAdapter(RuntimeError("smtp: 550 no such user guest@example.com"))

    report = await _use_case(
        repository, {NotificationChannel.EMAIL: adapter}, FakeUnitOfWork()
    ).execute(tenant_id=TENANT, now=NOW)

    assert adapter.calls == 1
    assert report.retrying == 1
    final = repository.writes[-1]
    assert final["status"] is NotificationStatus.PENDING
    assert json.loads(final["last_error"])["code"] == "ADAPTER_ERROR"
    # And the exception's own text is nowhere near the column.
    assert "550" not in final["last_error"]
    assert "guest@example.com" not in final["last_error"]


@pytest.mark.asyncio
async def test_a_permanently_raising_adapter_still_terminates_at_the_ceiling() -> None:
    """The bound, asserted directly: retries end, they do not go on for ever."""
    log = _log(attempts=2)
    repository = FakeNotificationLogRepository([log])
    adapter = RaisingAdapter(TimeoutError())

    report = await _use_case(
        repository, {NotificationChannel.EMAIL: adapter}, FakeUnitOfWork(), max_attempts=3
    ).execute(tenant_id=TENANT, now=NOW)

    assert report.failed == 1
    final = repository.writes[-1]
    assert final["status"] is NotificationStatus.FAILED
    assert json.loads(final["last_error"])["code"] == "MAX_ATTEMPTS_EXCEEDED"


@pytest.mark.asyncio
async def test_an_adapter_exception_never_reaches_the_log_verbatim(caplog) -> None:
    """The exception's class name is useful; its message is the payload we are containing."""
    import logging

    repository = FakeNotificationLogRepository([_log()])
    secret = "smtp: 550 mailbox unavailable for guest-7f3a@example.com"
    adapter = RaisingAdapter(RuntimeError(secret))

    with caplog.at_level(logging.DEBUG):
        await _use_case(
            repository, {NotificationChannel.EMAIL: adapter}, FakeUnitOfWork()
        ).execute(tenant_id=TENANT, now=NOW)

    emitted = "\n".join(
        record.getMessage()
        + " "
        + " ".join(str(value) for value in record.__dict__.values())
        for record in caplog.records
    )
    assert secret not in emitted
    assert "guest-7f3a@example.com" not in emitted
    # The type still comes through, so an operator can tell failure modes apart.
    assert "RuntimeError" in emitted


@pytest.mark.asyncio
async def test_the_batch_size_bounds_one_run() -> None:
    repository = FakeNotificationLogRepository([_log() for _ in range(5)])
    adapters = {NotificationChannel.EMAIL: RecordingAdapter(NotificationResult.ok(), [])}

    report = await _use_case(repository, adapters, FakeUnitOfWork(), batch_size=2).execute(
        tenant_id=TENANT, now=NOW
    )

    assert report.considered == 2


@pytest.mark.asyncio
async def test_the_adapter_receives_the_rows_own_subject_and_body() -> None:
    """Rule 11 of `steering/security.md` sanctions a masked access code in `body`, and the
    dispatcher is what carries it to the guest. It must forward the row, not rebuild it."""
    log = _log()
    repository = FakeNotificationLogRepository([log])
    adapter = RecordingAdapter(NotificationResult.ok(), [])

    await _use_case(repository, {NotificationChannel.EMAIL: adapter}, FakeUnitOfWork()).execute(
        tenant_id=TENANT, now=NOW
    )

    [call] = adapter.calls
    assert call["subject"] == log.subject
    assert call["body"] == log.body
    assert call["recipient_contact"] == log.recipient_contact
    assert call["channel"] is log.channel
