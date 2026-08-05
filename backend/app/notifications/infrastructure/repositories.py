"""SQLAlchemy adapter for `NotificationLogRepository` (`celery-jobs` design D11).

Every statement filters `tenant_id` explicitly and both writes check it: the session
listener of `app/core/db.py` covers neither INSERTs nor the identity map (limits 3 and 4
of its own docstring). No method commits — the use case owns the transaction.

This adapter copies `subject`, `body` and `last_error` through verbatim; what may and may
not travel in them is rule 11 of `sdd/steering/security.md`, which binds every caller of
the port. It is cited, never restated — `models.py` says why.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationStatus
from app.notifications.domain.exceptions import NotificationLogNotFoundError
from app.notifications.infrastructure.models import NotificationLogModel


class SqlAlchemyNotificationLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_sla_breach_candidates(
        self, tenant_id: uuid.UUID, now: datetime
    ) -> Sequence[NotificationLog]:
        rows = await self._session.execute(
            select(NotificationLogModel)
            .where(
                NotificationLogModel.tenant_id == tenant_id,
                NotificationLogModel.status == NotificationStatus.SENT,
                NotificationLogModel.sla_deadline_at.is_not(None),
                NotificationLogModel.sla_deadline_at < now,
                NotificationLogModel.sla_breached.is_(False),
            )
            # Oldest breach first: if a run is cut short, what got escalated is the work
            # that had been waiting longest, not an arbitrary slice.
            .order_by(NotificationLogModel.sla_deadline_at, NotificationLogModel.id)
        )
        return [_to_log(model) for model in rows.scalars()]

    async def mark_breached(self, tenant_id: uuid.UUID, log: NotificationLog) -> None:
        if log.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="notification log",
                entity_tenant_id=log.tenant_id,
                acting_tenant_id=tenant_id,
            )
        result = await self._session.execute(
            update(NotificationLogModel)
            .where(
                NotificationLogModel.tenant_id == tenant_id,
                NotificationLogModel.id == log.id,
            )
            .values(sla_breached=True)
        )
        # A zero-row UPDATE here is the state R5.3 forbids, not a harmless no-op: the
        # escalation row is already written, so leaving the candidate unmarked makes the
        # one-minute job re-escalate it for ever. See the port for the full reasoning.
        if result.rowcount == 0:
            raise NotificationLogNotFoundError(log.id)

    async def add(self, tenant_id: uuid.UUID, log: NotificationLog) -> None:
        if log.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="notification log",
                entity_tenant_id=log.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            NotificationLogModel(
                id=log.id,
                tenant_id=log.tenant_id,
                recipient_user_id=log.recipient_user_id,
                recipient_contact=log.recipient_contact,
                channel=log.channel,
                notification_type=log.notification_type,
                subject=log.subject,
                body=log.body,
                status=log.status,
                attempts=log.attempts,
                last_error=log.last_error,
                sent_at=log.sent_at,
                related_type=log.related_type,
                related_id=log.related_id,
                sla_deadline_at=log.sla_deadline_at,
                sla_breached=log.sla_breached,
            )
        )
        await self._session.flush()


def _to_log(model: NotificationLogModel) -> NotificationLog:
    return NotificationLog(
        id=model.id,
        tenant_id=model.tenant_id,
        recipient_contact=model.recipient_contact,
        channel=model.channel,
        notification_type=model.notification_type,
        created_at=model.created_at,
        updated_at=model.updated_at,
        recipient_user_id=model.recipient_user_id,
        subject=model.subject,
        body=model.body,
        status=model.status,
        attempts=model.attempts,
        last_error=model.last_error,
        sent_at=model.sent_at,
        related_type=model.related_type,
        related_id=model.related_id,
        sla_deadline_at=model.sla_deadline_at,
        sla_breached=model.sla_breached,
    )
