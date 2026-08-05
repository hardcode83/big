"""Ports owned by the notifications domain (`celery-jobs` design D11).

Shaped by its only consumer today, the SLA enforcement job of PRD §14: find the logs
whose deadline has passed, mark them, and append the escalation. Sending is not here and
will not be — the `NotificationAdapter` of PRD §14 belongs to `access-notifications`,
which owns delivery. This port never talks to a channel.

**`add` is the write path into three cleartext sinks**, and the contract that governs
them is rule 11 of `sdd/steering/security.md` — read it there, it is not restated here
or anywhere else on purpose. It binds every caller of this port, not just the SLA job
that arrives with it: `access-notifications` will import this same port to write the
notifications it actually sends.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.notifications.domain.entities import NotificationLog


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
