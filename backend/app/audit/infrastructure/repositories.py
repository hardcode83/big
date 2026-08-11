"""SQLAlchemy adapter for the audit log port (R6.4, R7.8, design D2).

Append-only and never commits: the use case owns the transaction, which is what makes the
mutation and its audit row atomic (R6.4). The cross-tenant guard is here rather than in the
use case because the session filter of `app/core/db.py` does not cover INSERTs — limit 3 of
its own docstring.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.domain.entities import AuditLog
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.services import is_guest_token_digest
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
        if entry.actor_guest_token_hash is not None and not is_guest_token_digest(
            entry.actor_guest_token_hash
        ):
            # Re-checked here and not only in `AuditLogFactory`, for the reason the guard
            # above is here too: `AuditLog` is a plain mutable dataclass, so a caller can
            # build one directly or mutate the field after `build()` returned, and this is
            # the last place before an append-only row carrying a live guest token
            # (`guest-portal-api` R1.2, R6.4). The column also carries a CHECK, which is the
            # durable half; this one exists to name the field instead of dying at the driver
            # with an error that says nothing — the same trade `ChangeSet._storable` makes.
            raise AuditContractError(
                "actor_guest_token_hash must be a SHA-256 hex digest, not the token itself: "
                "R6.4 keeps the cleartext guest token out of audit_logs entirely."
            )
        self._session.add(
            AuditLogModel(
                id=entry.id,
                tenant_id=entry.tenant_id,
                actor_user_id=entry.actor_user_id,
                actor_guest_token_hash=entry.actor_guest_token_hash,
                actor_ip=entry.actor_ip,
                action=entry.action,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                changes=entry.changes,
                created_at=entry.created_at,
            )
        )
