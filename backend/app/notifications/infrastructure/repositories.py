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

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationStatus
from app.notifications.domain.exceptions import NotificationLogNotFoundError
from app.notifications.domain.repositories import NotificationLogPage
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

    async def list_pending(
        self, tenant_id: uuid.UUID, limit: int
    ) -> Sequence[NotificationLog]:
        rows = await self._session.execute(
            select(NotificationLogModel)
            .where(
                NotificationLogModel.tenant_id == tenant_id,
                NotificationLogModel.status == NotificationStatus.PENDING,
            )
            # Oldest first, same reasoning as the candidate query: a run cut short by the
            # batch limit has delivered the work that had been waiting longest.
            .order_by(NotificationLogModel.created_at, NotificationLogModel.id)
            .limit(limit)
        )
        return [_to_log(model) for model in rows.scalars()]

    async def list_for_recipient(
        self, tenant_id: uuid.UUID, recipient_user_id: uuid.UUID, *, page: int, per_page: int
    ) -> NotificationLogPage:
        conditions = (
            NotificationLogModel.tenant_id == tenant_id,
            NotificationLogModel.recipient_user_id == recipient_user_id,
        )
        total = await self._session.scalar(
            select(func.count()).select_from(NotificationLogModel).where(*conditions)
        )
        rows = await self._session.execute(
            select(NotificationLogModel)
            .where(*conditions)
            # Newest first: this is an inbox, not a queue.
            .order_by(NotificationLogModel.created_at.desc(), NotificationLogModel.id)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return NotificationLogPage(
            items=tuple(_to_log(model) for model in rows.scalars()),
            total=total or 0,
        )

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
        result = await self._session.execute(
            update(NotificationLogModel)
            .where(
                NotificationLogModel.tenant_id == tenant_id,
                NotificationLogModel.id == log_id,
            )
            .values(
                status=status,
                attempts=attempts,
                sent_at=sent_at,
                last_error=last_error,
            )
        )
        # Loud for the same reason as `mark_breached`: the delivery already happened by the
        # time this runs, so a zero-row UPDATE means the dispatcher would re-send the row on
        # the next tick believing it never went out. That is the one failure the attempt
        # counter exists to bound.
        if result.rowcount == 0:
            raise NotificationLogNotFoundError(log_id)

    async def exists_for(
        self,
        tenant_id: uuid.UUID,
        *,
        related_type: str,
        related_id: uuid.UUID,
        notification_type: str,
    ) -> bool:
        if related_type is None or related_id is None:
            # `== None` compiles to `IS NULL`, which would match every row of this type that
            # points at nothing — and because the caller writes no notification when this
            # returns True, that widening silences alerts rather than surfacing them. The
            # annotations do not stop it: this backend runs neither mypy nor ruff, in the
            # tree or in CI. Section 2's security panel raised it before the first caller
            # existed, which is the only cheap moment to close it.
            raise ValueError(
                "exists_for needs a related_type and a related_id: a null would widen the "
                "check from one entity to every row of that type without one."
            )
        result = await self._session.execute(
            select(NotificationLogModel.id)
            .where(
                NotificationLogModel.tenant_id == tenant_id,
                NotificationLogModel.related_type == related_type,
                NotificationLogModel.related_id == related_id,
                NotificationLogModel.notification_type == notification_type,
            )
            # Existence, not a count: the caller only asks whether to write, and a `COUNT`
            # over a duplicated pair would scan rows to answer a question `LIMIT 1` settles.
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def cancel_sla_deadline(
        self,
        tenant_id: uuid.UUID,
        *,
        related_type: str,
        related_id: uuid.UUID,
        notification_type: str,
    ) -> int:
        result = await self._session.execute(
            update(NotificationLogModel)
            .where(
                NotificationLogModel.tenant_id == tenant_id,
                NotificationLogModel.related_type == related_type,
                NotificationLogModel.related_id == related_id,
                NotificationLogModel.notification_type == notification_type,
                NotificationLogModel.sla_deadline_at.is_not(None),
            )
            .values(sla_deadline_at=None)
        )
        # No `NotificationLogNotFoundError` here, unlike the two writes above, and the port
        # says why: nothing has happened yet that a missing row would contradict. Zero is a
        # task with no assignment notification, or one whose deadline is already closed.
        return result.rowcount

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
