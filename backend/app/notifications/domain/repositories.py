"""Ports owned by the notifications domain (`celery-jobs` design D11).

Shaped by its two consumers: the SLA enforcement job of PRD §14 (find the logs whose
deadline has passed, mark them, append the escalation) and, since `access-notifications`,
the dispatcher that delivers them. Sending itself is still not here — the
`NotificationAdapter` of PRD §14 lives in `app/notifications/domain/ports.py`. **This port
never talks to a channel**; it only records what the dispatcher did.

**`add` is the write path into three cleartext sinks**, and the contract that governs
them is rule 11 of `sdd/steering/security.md` — read it there, it is not restated here
or anywhere else on purpose. It binds every caller of this port, not just the SLA job
that arrives with it: `access-notifications` will import this same port to write the
notifications it actually sends.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationStatus


@dataclass(frozen=True)
class NotificationLogPage:
    """One page plus the total the client needs for `total_pages` (PRD §23).

    Same shape as `app/reservations/domain/repositories.py:Page`, deliberately: the API
    envelope of PRD §23 is the same everywhere, so the repositories that feed it answer the
    same way.
    """

    items: tuple[NotificationLog, ...]
    total: int


class NotificationLogRepository(Protocol):
    async def list_sla_breach_candidates(
        self, tenant_id: uuid.UUID, now: datetime
    ) -> Sequence[NotificationLog]:
        """The four conditions of PRD §14, and no others.

        `status = SENT`, `sla_deadline_at` present and earlier than `now`, and
        `sla_breached = False`. That last one is the whole idempotency mechanism of the
        job (R4.4): a log already escalated stops being a candidate, so a second pass
        finds nothing to do without keeping any state of its own.

        `ix_notification_logs_tenant_id_status_sla_deadline_at` covers this exact shape.
        """
        ...

    async def mark_breached(self, tenant_id: uuid.UUID, log: NotificationLog) -> None:
        """Set `sla_breached = True` on a log of this tenant.

        Narrow like `PropertyRepository.save` and for the same reason: the SLA job has no
        business rewriting a notification's body, recipient or status, and a port that
        allowed it would be an open door for the change that comes next.

        **Takes the entity, not an id, and fails loudly when it marks nothing** — raises
        `CrossTenantWriteError` on a tenant mismatch and `NotificationLogNotFoundError`
        when the row is not there. A silent zero-row UPDATE is the one outcome R5.3
        cannot survive: the escalation is written, the candidate stays unmarked, and the
        one-minute job re-escalates it on every tick, so a mismatch that should fail one
        tenant instead produces `PENDING` rows without bound — which
        `access-notifications` would later actually deliver.
        """
        ...

    async def add(self, tenant_id: uuid.UUID, log: NotificationLog) -> None:
        """Append a notification row; refuses an entity of another tenant.

        The escalations this job writes arrive here with `status = PENDING`: they are
        queued work for `access-notifications`' sender, not a delivery that failed.

        **Precondition the caller owns**: `recipient_user_id` must have been resolved
        inside `tenant_id` before getting here. This adapter checks the row's own tenant
        and nothing else, exactly as `TimelineEventRepository.add` documents for its own
        references — `notification_logs`' foreign keys are not composite with
        `tenant_id`, so the database would accept a row pointing at a neighbour's user.
        """
        ...

    async def list_pending(self, tenant_id: uuid.UUID, limit: int) -> Sequence[NotificationLog]:
        """The dispatcher's work queue: rows in `PENDING`, oldest first (R4.2).

        `PENDING` is the seam every writer in this codebase leaves behind — `cleaning`'s
        assignment notification and the SLA job's escalations both land here — so this is
        the query that turns queued work into delivery.

        Bounded by `limit` (`notification_batch_size`) because the job runs every minute and
        a backlog must drain in slices rather than in one transaction that holds row locks
        for as long as the provider takes.
        """
        ...

    async def list_for_recipient(
        self,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        *,
        page: int,
        per_page: int,
        unread: bool | None = None,
    ) -> NotificationLogPage:
        """One page of the notifications addressed to **one user** (design D6).

        Scoped by recipient and not only by tenant: a cleaner and a manager share a tenant
        and must not read each other's notifications. The filter is applied here rather than
        in the router because the user id comes from the token, and a repository that
        accepted "all of the tenant's" would leave that restriction one forgetful caller
        away.

        Newest first — the opposite of `list_pending`, and on purpose: a queue is drained
        oldest-first, an inbox is read newest-first.

        `unread=True` narrows the page to `read_at IS NULL` (`notifications-inbox-web` D5).
        Default `None` means "all of them", which is what every caller before that change
        asked for; the envelope, the order and the page ceilings are untouched by the
        filter, because a filtered inbox is still the inbox of PRD §23.
        """
        ...

    async def mark_read(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, log_id: uuid.UUID
    ) -> bool:
        """Acknowledge one notification of this user, and say whether there was one.

        Narrow like `mark_breached` and `record_attempt`, and for the reason this port has
        repeated since `celery-jobs`: a reader has no business rewriting a notification's
        body, recipient or status, and a port that allowed it would be the open door for the
        change that comes next. `notifications-inbox-web` D2 rejected a `PATCH` on the whole
        resource for exactly that.

        **Idempotent, and it returns a fact rather than raising** (D3). The write keeps the
        FIRST read (`COALESCE`), because `read_at` records when the user read it, not the
        last time they looked at the inbox — so a second acknowledgement is a success that
        moves nothing (R1.3). `False` means one single thing: **no row with that id is
        visible to this user of this tenant**. It deliberately does not distinguish
        "missing" from "somebody else's" from "another tenant's" — R1.4 answers all three
        with the same `404`, and a repository that could tell them apart is a repository a
        careless caller could leak them from.
        """
        ...

    async def count_unread(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
        """How many of this user's notifications are unread (R2.2, design D4).

        Its own query rather than a field of the page envelope: this is the one question
        every connected client asks every 60 s, so it must not carry a page of rows it will
        not read. `ix_notification_logs_unread` — partial on `read_at IS NULL` — is the
        index that keeps its cost bounded as read rows accumulate.
        """
        ...

    async def mark_all_read(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
        """Acknowledge every unread notification of this user; returns how many moved.

        **Zero is the normal case, not an error** — same criterion as `cancel_sla_deadline`
        and the opposite of `mark_breached`: an inbox already up to date has nothing to move,
        and nothing has happened that a missing row would contradict (D6).

        Scope is fixed at **all** of the user's unread rows (R5.2), never the page or filter
        the client happens to be looking at: a button that says "all" and marks twenty is
        worse than no button.
        """
        ...

    async def record_attempt(
        self,
        tenant_id: uuid.UUID,
        log_id: uuid.UUID,
        *,
        status: NotificationStatus,
        attempts: int,
        sent_at: datetime | None,
        last_error: str | None,
    ) -> None:
        """Write the outcome of one delivery attempt, and nothing else.

        Narrow for the same reason as `mark_breached`: the dispatcher has no business
        rewriting `recipient_contact`, `subject`, `body`, `related_*` or `sla_deadline_at`,
        and a port that let it would be the open door for the change that comes next.

        **`last_error` is a cleartext sink governed by rule 11 of
        `sdd/steering/security.md`** — read it there, it is not restated here or anywhere
        else on purpose. What makes the contract hold in practice is upstream of this
        method: `NotificationAdapter` can only report a `NotificationErrorCode`, so there is
        no provider text for any caller to serialise. This signature takes the already
        encoded `str` because the column is one.

        Takes an id rather than the entity: the dispatcher re-reads nothing between the
        attempt and the record, so handing a stale entity back would invite a caller to
        write the rest of its fields too.
        """
        ...

    async def cancel_sla_deadline(
        self,
        tenant_id: uuid.UUID,
        *,
        related_type: str,
        related_id: uuid.UUID,
        notification_type: str,
    ) -> int:
        """Clear `sla_deadline_at` on the rows that point at one entity (R5, design D7).

        The debt `cleaning` recorded when it recut its R6.4: answering an assignment must
        close the pending deadline, so `check_sla_breaches` does not escalate a cleaning the
        cleaner accepted in seconds. Clearing the deadline is what removes the row from
        `list_sla_breach_candidates` — through its second condition (`sla_deadline_at IS NOT
        NULL`) — **without touching `status` or `sla_breached`**, which would respectively
        deny a delivery that happened or claim a breach that did not.

        Matched through the polymorphic pair plus the type, so it can only reach the
        assignment row of one task; `ix_notification_logs_related_type_related_id` covers
        that shape.

        **Zero rows is the normal case, not an error** — the opposite of `mark_breached`. A
        task created before this change has no deadline to cancel, and a cleaner who answers
        twice finds it already cleared. Returns how many rows it cleared, so a caller that
        cares can log it.
        """
        ...
