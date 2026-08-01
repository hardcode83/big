"""SQLAlchemy adapter for the audit log port (R6.4, R7.8, design D2).

Append-only and never commits: the use case owns the transaction, which is what makes the
mutation and its audit row atomic (R6.4). The cross-tenant guard is here rather than in the
use case because the session filter of `app/core/db.py` does not cover INSERTs — limit 3 of
its own docstring.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.domain.entities import AuditLog
from app.audit.infrastructure.models import AuditLogModel
from app.core.tenancy import CrossTenantWriteError


class SqlAlchemyAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: uuid.UUID, entry: AuditLog) -> None:
        if entry.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="audit_log",
                entity_tenant_id=entry.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            AuditLogModel(
                id=entry.id,
                tenant_id=entry.tenant_id,
                actor_user_id=entry.actor_user_id,
                actor_ip=entry.actor_ip,
                action=entry.action,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                changes=entry.changes,
                created_at=entry.created_at,
            )
        )
