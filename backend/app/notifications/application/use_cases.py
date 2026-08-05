"""SLA enforcement (`celery-jobs` R5, PRD §14, design D11 and D17).

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

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.ports import UserRepository
from app.auth.domain.repositories import UserFilters
from app.core.unit_of_work import UnitOfWork
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel, NotificationStatus
from app.notifications.domain.escalation import Escalation, escalation_for
from app.notifications.domain.repositories import NotificationLogRepository

logger = logging.getLogger(__name__)

#: A tenant's roster is small (PRD §1: two flats, a handful of people) and the roles that
#: receive escalations are the two administrative ones, so one page is the whole answer.
#: Should a tenant ever exceed this, `EscalationReport.recipients_truncated` says so — a
#: silent partial notification is the failure mode worth surfacing in the return value and
#: not only in a log nobody reads.
_MAX_RECIPIENTS = 100


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
        self._users = users
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
        """
        page = await self._users.list(
            tenant_id,
            UserFilters(role=role, status=UserStatus.ACTIVE),
            page=1,
            per_page=_MAX_RECIPIENTS,
        )
        dropped = page.total - len(page.items)
        if dropped > 0:
            report.recipients_truncated += dropped
            logger.warning(
                "scheduler.escalation_recipients_truncated",
                extra={
                    "tenant_id": str(tenant_id),
                    "role": role.value,
                    "total": page.total,
                    "notified": len(page.items),
                },
            )
        return list(page.items)


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
