"""SLA enforcement and delivery (`celery-jobs` R5 + `access-notifications` R4, PRD §14).

Two passes over the same table, and the seam between them is `NotificationStatus`:

- `EscalateBreachedSlasUseCase` (`celery-jobs`) turns a breached deadline into a **queued**
  escalation — a new row in `PENDING`.
- `DispatchPendingNotificationsUseCase` (`access-notifications`) drains `PENDING` through a
  channel adapter and owns `status` from there on.

Until the second one existed, `list_sla_breach_candidates` could never return anything: it
requires `status = SENT` and nothing marked it. That is the hole this module now closes.

--- (original docstring of the escalation pass follows) ---

SLA enforcement (`celery-jobs` R5, PRD §14, design D11 and D17).

Finds the notifications whose deadline has passed, marks them breached and leaves the
escalation written as queued work. **It sends nothing**: the `NotificationAdapter` of
PRD §14 belongs to `access-notifications`, and a row in `PENDING` is exactly the seam
between the two — queued work for its sender, not a delivery that failed.

Idempotence costs no code of its own (R4.4): `sla_breached = False` is part of the
candidate query, so a log this job has already handled stops being a candidate.

**And that is why nothing is marked unless a row was written.** The first draft marked the
breach even when the tenant had no recipient at all, which is the alternative design D17
explicitly rejects ("pierde el aviso en silencio, que es el fallo que este job existe para
evitar") — the mark would have made the breach permanently unescalatable while the database
claimed it was handled. Caught by the section-4 security panel.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole
from app.auth.domain.ports import UserRepository
from app.auth.domain.recipients import RoleRecipients
from app.core.unit_of_work import UnitOfWork
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel, NotificationStatus
from app.notifications.domain.escalation import Escalation, escalation_for
from app.notifications.domain.exceptions import NotificationNotFoundError
from app.notifications.domain.ports import NotificationAdapter
from app.notifications.domain.repositories import NotificationLogRepository
from app.notifications.domain.results import NotificationErrorCode, NotificationResult

logger = logging.getLogger(__name__)

#: The page bound and the reason for it now live on `RoleRecipients` (design D1), which is
#: the one place the roster question is answered since this change absorbed the second copy
#: of it. What stays here is what is local: the *counter* this job folds truncation into
#: (`EscalationReport.recipients_truncated`) and the log key that names this site.


@dataclass
class EscalationReport:
    """What one run did.

    `escalated`, `without_action` and `without_recipient` partition the candidates.
    `without_action` is R5.6's case — a `notification_type` with no escalation defined,
    marked and recorded rather than given an invented recipient. `without_recipient` is a
    tenant with neither an active manager nor an active owner: the escalation was owed and
    could not be addressed, so the breach is **left unmarked** and stays a candidate. That
    is deliberate (design D17): a configuration an operator must fix, retried until they do.
    """

    breached: int = 0
    escalated: int = 0
    without_action: int = 0
    without_recipient: int = 0
    rows_written: int = 0
    recipients_truncated: int = 0


class EscalateBreachedSlasUseCase:
    def __init__(
        self,
        *,
        notifications: NotificationLogRepository,
        users: UserRepository,
        uow: UnitOfWork,
    ) -> None:
        self._notifications = notifications
        # The port is kept only to build the roster service, and is deliberately not held as
        # a second attribute: nothing in this class queries users directly any more, so a
        # spare handle would be an open door back to the inline query this change removed.
        # Built here rather than injected because it is a pure domain service over a port the
        # constructor already receives — widening the signature would make every wiring site
        # name a collaborator that carries no state and no configuration.
        self._recipients = RoleRecipients(users=users)
        self._uow = uow

    async def execute(self, *, tenant_id: uuid.UUID, now: datetime) -> EscalationReport:
        report = EscalationReport()
        candidates = await self._notifications.list_sla_breach_candidates(tenant_id, now)
        if not candidates:
            return report

        # Keyed by role, not a single nullable list. The roster does not change inside a
        # transaction, but the *role* does: `_resolve_recipients` reads
        # `escalation.recipient_role`, so caching on nothing addressed a candidate's
        # escalation to whichever role the previous candidate happened to need. Both panel
        # reviewers of section 4 found it, and QA reproduced the misroute.
        rosters: dict[UserRole, list[User]] = {}

        for candidate in candidates:
            report.breached += 1
            escalation = escalation_for(candidate.notification_type)
            if escalation is None:
                # R5.6. Marked so it stops being a candidate — the breach happened, and
                # re-reporting it every minute would bury the ones that do have an action.
                await self._notifications.mark_breached(tenant_id, candidate)
                report.without_action += 1
                logger.info(
                    "scheduler.sla_breached_without_escalation",
                    extra={
                        "tenant_id": str(tenant_id),
                        "notification_log_id": str(candidate.id),
                        "notification_type": candidate.notification_type,
                    },
                )
                continue

            if escalation.recipient_role not in rosters:
                rosters[escalation.recipient_role] = await self._resolve_recipients(
                    tenant_id, escalation, report
                )
            recipients = rosters[escalation.recipient_role]

            if not recipients:
                # Not marked, on purpose: marking would make this breach unescalatable for
                # ever while the row claimed it was handled (design D17's rejected option).
                report.without_recipient += 1
                logger.error(
                    "scheduler.escalation_without_recipient",
                    extra={
                        "tenant_id": str(tenant_id),
                        "notification_log_id": str(candidate.id),
                        "role": escalation.recipient_role.value,
                    },
                )
                continue

            for recipient in recipients:
                await self._notifications.add(
                    tenant_id,
                    _escalation_row(
                        tenant_id=tenant_id,
                        breached_id=candidate.id,
                        breached_type=candidate.notification_type,
                        escalation=escalation,
                        recipient=recipient,
                        now=now,
                    ),
                )
                report.rows_written += 1
            # Marked after the rows exist, so the invariant R5.3 protects can only fail in
            # the safe direction: never a breach marked without its escalation.
            await self._notifications.mark_breached(tenant_id, candidate)
            report.escalated += 1

        await self._uow.commit()
        return report

    async def _resolve_recipients(
        self, tenant_id: uuid.UUID, escalation: Escalation, report: EscalationReport
    ) -> list[User]:
        """Every active holder of the role, falling back to the owner (design D17).

        The fallback is not decoration: `TENANT_OWNER` always exists —
        `count_active_owners_excluding` of `user-management` protects that invariant — so a
        tenant with no manager still gets its warning instead of losing it.
        """
        holders = await self._active_holders(
            tenant_id, escalation.recipient_role, report
        )
        if holders:
            return holders
        if escalation.recipient_role is UserRole.TENANT_OWNER:
            # The fallback IS the owner; asking again would just repeat the empty answer.
            return []
        return await self._active_holders(tenant_id, UserRole.TENANT_OWNER, report)

    async def _active_holders(
        self, tenant_id: uuid.UUID, role: UserRole, report: EscalationReport
    ) -> list[User]:
        """One page of active holders of `role`, counting anyone the page left out.

        Both the primary role and the owner fallback come through here. They used to be two
        inline queries and only the first counted its truncation, so a tenant with more than
        one page of owners and no manager would have notified a subset with
        `recipients_truncated` still at zero — the silent partial notification that counter
        exists to prevent. Caught by the section-4 QA re-review.

        **The query itself now belongs to `RoleRecipients`** (design D1): this was one of the
        two places that had written the roster question out by hand, and leaving it here
        while five new writers asked the same question elsewhere is what R5.1 forbids. What
        does not move is the pair of things that are this job's own — the counter it folds
        the truncation into, and the log key that names *this* site rather than the helper.
        """
        resolved = await self._recipients.active_holders(tenant_id, role)
        if resolved.dropped > 0:
            report.recipients_truncated += resolved.dropped
            logger.warning(
                "scheduler.escalation_recipients_truncated",
                extra={
                    "tenant_id": str(tenant_id),
                    "role": role.value,
                    "total": len(resolved.users) + resolved.dropped,
                    "notified": len(resolved.users),
                },
            )
        return list(resolved.users)


def _escalation_row(
    *,
    tenant_id: uuid.UUID,
    breached_id: uuid.UUID,
    breached_type: str,
    escalation: Escalation,
    recipient: User,
    now: datetime,
) -> NotificationLog:
    """The queued escalation.

    **Takes the breached notification's id and type, never the entity.** That is what makes
    rule 11 of `steering/security.md` hold by construction: `subject` and `body` cannot
    forward the original's own `subject`/`body` — rule 11's single sanctioned carrier of a
    masked access code — because they are not in scope here. The earlier version received
    the whole `NotificationLog`, so the guarantee was one keystroke from being untrue and
    rested on care rather than construction; the section-4 security panel named the gap.
    The reader follows `related_id` to the original.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=recipient.id,
        recipient_contact=recipient.email,
        channel=NotificationChannel.IN_APP,
        notification_type=escalation.notification_type.value,
        created_at=now,
        updated_at=now,
        subject="SLA breach",
        body=f"A {breached_type} notification passed its SLA deadline "
        f"({escalation.reason}). See notification log {breached_id}.",
        status=NotificationStatus.PENDING,
        related_type="notification_log",
        related_id=breached_id,
    )


@dataclass
class DispatchReport:
    """What one delivery run did (R4).

    `sent`, `retrying`, `failed` and `skipped` partition the rows the run looked at.
    `retrying` is a row that failed and still has attempts left — deliberately named apart
    from `failed`, because an operator reading "3 failed" when all three will be retried in
    sixty seconds is being told the wrong thing.
    """

    considered: int = 0
    sent: int = 0
    retrying: int = 0
    failed: int = 0
    skipped: int = 0


class DispatchPendingNotificationsUseCase:
    """Drain the `PENDING` queue through the channel adapters (R4, design D3/D4/D5).

    **The attempt is recorded before the send, and committed.** That is the whole ordering
    decision of design D4, and it buys one property: a process killed between the provider
    call and the result write has already burned an attempt, so the redelivery it causes is
    bounded by `notification_max_attempts` instead of repeating for ever. The alternative —
    an intermediate `SENDING` state — needs an `ALTER TYPE` and leaves rows stuck in it when
    the process dies, which is the failure mode we would be trading *up* to.

    So the semantics are **at-least-once, bounded**, and `SENT` is never written on a row
    the adapter did not confirm (R4.6). Concurrency between runs is handled a layer up, by
    the Redis `task_lock` the scheduler already takes for every job.
    """

    def __init__(
        self,
        *,
        notifications: NotificationLogRepository,
        adapters: dict[NotificationChannel, NotificationAdapter],
        uow: UnitOfWork,
        max_attempts: int,
        batch_size: int,
    ) -> None:
        self._notifications = notifications
        self._adapters = adapters
        self._uow = uow
        self._max_attempts = max_attempts
        self._batch_size = batch_size

    async def execute(self, *, tenant_id: uuid.UUID, now: datetime) -> DispatchReport:
        report = DispatchReport()
        pending = await self._notifications.list_pending(tenant_id, self._batch_size)
        for log in pending:
            report.considered += 1
            adapter = self._adapters.get(log.channel)
            if adapter is None:
                await self._skip_unroutable(tenant_id, log)
                report.skipped += 1
                continue
            await self._deliver(tenant_id, log, adapter, now, report)
        return report

    async def _skip_unroutable(
        self, tenant_id: uuid.UUID, log: NotificationLog
    ) -> None:
        """R4.5 — a channel with no adapter is `SKIPPED`, not retried for ever.

        No attempt is burned: nothing was attempted. `SKIPPED` takes the row out of
        `list_pending`, which is what stops the job from picking it up every minute until
        somebody registers an adapter for that channel.
        """
        await self._notifications.record_attempt(
            tenant_id,
            log.id,
            status=NotificationStatus.SKIPPED,
            attempts=log.attempts,
            sent_at=None,
            last_error=_encode_error(
                NotificationErrorCode.NO_ADAPTER_FOR_CHANNEL, log.channel, log.attempts
            ),
        )
        await self._uow.commit()
        logger.warning(
            "notifications.channel_without_adapter",
            extra={
                "tenant_id": str(tenant_id),
                "notification_log_id": str(log.id),
                "channel": log.channel.value,
            },
        )

    async def _deliver(
        self,
        tenant_id: uuid.UUID,
        log: NotificationLog,
        adapter: NotificationAdapter,
        now: datetime,
        report: DispatchReport,
    ) -> None:
        attempt = log.attempts + 1
        # Recorded and committed BEFORE the provider call — design D4. Everything about the
        # duplicate bound depends on this line running first.
        await self._notifications.record_attempt(
            tenant_id,
            log.id,
            status=NotificationStatus.PENDING,
            attempts=attempt,
            sent_at=None,
            last_error=log.last_error,
        )
        await self._uow.commit()

        try:
            result = await adapter.send(
                recipient_contact=log.recipient_contact,
                subject=log.subject,
                body=log.body,
                channel=log.channel,
            )
        except Exception as exc:
            # `NotificationAdapter.send` documents that it never raises for a delivery
            # failure — but that is prose, and the next adapter to land is a real SMTP one
            # whose library exceptions carry the recipient and the server's response text.
            # Without this catch, two things went wrong at once, and the security panel of
            # sections 1-2 found both:
            #
            #   1. the traceback reached `scheduler/runner.py`'s `logger.exception`, putting
            #      the provider's message — routinely the very content that failed to send —
            #      into an application log with no retention policy and no tenant scoping.
            #      That is precisely the sink `infrastructure/adapters.py` refuses for
            #      `subject`/`body`;
            #   2. the row never reached the `FAILED` branch below, so R4.4's terminal state
            #      was unreachable and `list_pending` re-picked it every minute for ever —
            #      the "at-least-once, **bounded**" claim of design D4 quietly became
            #      unbounded.
            #
            # The exception's **class name** is logged and its message is not, and neither
            # is `exc_info`: the type tells an operator which failure mode they are looking
            # at (`TimeoutError` vs `SMTPRecipientsRefused`) and carries none of the payload.
            # That is the same length-not-content discipline `infrastructure/adapters.py`
            # applies to `subject`/`body`.
            logger.error(
                "notifications.adapter_raised",
                extra={
                    "tenant_id": str(tenant_id),
                    "notification_log_id": str(log.id),
                    "channel": log.channel.value,
                    "attempt": attempt,
                    "exception_type": type(exc).__name__,
                },
            )
            result = NotificationResult.failure(NotificationErrorCode.ADAPTER_ERROR)

        if result.delivered:
            await self._notifications.record_attempt(
                tenant_id,
                log.id,
                status=NotificationStatus.SENT,
                attempts=attempt,
                sent_at=now,
                last_error=None,
            )
            await self._uow.commit()
            report.sent += 1
            # The adapters log the shape of what they sent and no identifier; this is the
            # layer that knows which row and which tenant, so the two halves join here.
            # Neither half carries an address or the message.
            logger.info(
                "notifications.delivered",
                extra={
                    "tenant_id": str(tenant_id),
                    "notification_log_id": str(log.id),
                    "channel": log.channel.value,
                    "attempt": attempt,
                },
            )
            return

        exhausted = attempt >= self._max_attempts
        # The code that goes on the row is the adapter's while retries remain, and
        # `MAX_ATTEMPTS_EXCEEDED` once we stop: an operator looking at a `FAILED` row needs
        # to know we gave up, and the last provider code is still one `attempts` value away
        # in the log line below.
        code = (
            NotificationErrorCode.MAX_ATTEMPTS_EXCEEDED
            if exhausted
            else (result.error_code or NotificationErrorCode.ADAPTER_ERROR)
        )
        await self._notifications.record_attempt(
            tenant_id,
            log.id,
            status=NotificationStatus.FAILED if exhausted else NotificationStatus.PENDING,
            attempts=attempt,
            sent_at=None,
            last_error=_encode_error(code, log.channel, attempt),
        )
        await self._uow.commit()
        if exhausted:
            report.failed += 1
        else:
            report.retrying += 1
        logger.warning(
            "notifications.delivery_failed",
            extra={
                "tenant_id": str(tenant_id),
                "notification_log_id": str(log.id),
                "channel": log.channel.value,
                "attempt": attempt,
                "error_code": (result.error_code or NotificationErrorCode.ADAPTER_ERROR).value,
                "exhausted": exhausted,
            },
        )


def _encode_error(
    code: NotificationErrorCode, channel: NotificationChannel, attempt: int
) -> str:
    """The structured form rule 11 of `sdd/steering/security.md` requires for `last_error`.

    Three fields, all of them ours: a code from a closed enum, the channel, and which
    attempt produced it. There is no path here for provider text — `NotificationAdapter`
    cannot return any — so the guarantee is structural rather than a habit this function
    has to keep.
    """
    return json.dumps({"code": code.value, "channel": channel.value, "attempt": attempt})


@dataclass(frozen=True)
class NotificationPage:
    """One page of a user's own notifications (R4, design D6)."""

    items: list[NotificationLog]
    total: int
    page: int
    per_page: int


class ListOwnNotificationsUseCase:
    """The in-app channel's read side (design D6).

    Without it, `InAppNotificationAdapter` marks rows `SENT` that nobody can read — which
    would make "delivered" a claim rather than a fact. Scoped to the requesting user, not
    just to the tenant: a manager and a cleaner in the same tenant must not see each
    other's notifications.
    """

    def __init__(self, *, notifications: NotificationLogRepository) -> None:
        self._notifications = notifications

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        page: int,
        per_page: int,
        unread: bool | None = None,
    ) -> NotificationPage:
        found = await self._notifications.list_for_recipient(
            tenant_id, user_id, page=page, per_page=per_page, unread=unread
        )
        return NotificationPage(
            items=list(found.items), total=found.total, page=page, per_page=per_page
        )


class MarkNotificationReadUseCase:
    """The acknowledgement of R1.2, and the place the `404` of R1.4 is decided.

    One call to `mark_read`, whose `False` means "no row with that id is visible to this
    user of this tenant" and nothing more precise (design D3). Turning that into
    `NotificationNotFoundError` here — rather than letting the repository raise — is what
    keeps the three cases of R1.4 indistinguishable: this use case never learns which one it
    was, so it cannot leak it.

    **It writes no `AuditLog`** (design D8, confirming the proposal's A2): rule 9 of
    `steering/security.md` enumerates Reservation, property states, Guest documents,
    AccessRecord, PricingRule/PriceRecommendation, OwnerApproval, User roles and Incident.
    Reading one's own notice is none of those, is not an operation on somebody else's data
    and grants no permission.
    """

    def __init__(self, *, notifications: NotificationLogRepository, uow: UnitOfWork) -> None:
        self._notifications = notifications
        self._uow = uow

    async def execute(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, notification_id: uuid.UUID
    ) -> None:
        acknowledged = await self._notifications.mark_read(
            tenant_id, user_id, notification_id
        )
        if not acknowledged:
            raise NotificationNotFoundError()
        await self._uow.commit()


class CountUnreadNotificationsUseCase:
    """The bell's counter (R2.2, design D4). One `count(*)`, no page of rows."""

    def __init__(self, *, notifications: NotificationLogRepository) -> None:
        self._notifications = notifications

    async def execute(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
        return await self._notifications.count_unread(tenant_id, user_id)


class MarkAllNotificationsReadUseCase:
    """"Mark all as read" (R5.2, design D6); returns how many rows it moved.

    Zero is the normal case of an inbox already up to date, so it raises nothing — the
    opposite of `MarkNotificationReadUseCase`, where zero means the caller named a row it
    cannot see. Scope is every unread row of the token's user, never the page or filter the
    client is looking at.
    """

    def __init__(self, *, notifications: NotificationLogRepository, uow: UnitOfWork) -> None:
        self._notifications = notifications
        self._uow = uow

    async def execute(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
        updated = await self._notifications.mark_all_read(tenant_id, user_id)
        await self._uow.commit()
        return updated
