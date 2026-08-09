"""SQLAlchemy adapters for the maintenance read ports (`dashboard-api` R1, R2).

First readers of `incidents` and `owner_approvals`. There are no writers here and the ports
declare none — see `app/maintenance/domain/repositories.py` for why.

Every statement filters `tenant_id` explicitly. The session listener of `app/core/db.py`
also covers both tables (they carry `TenantScopedMixin`), but it is the net and never the
mechanism.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.maintenance.domain.entities import OPEN_INCIDENT_STATUSES
from app.maintenance.domain.enums import OwnerApprovalStatus
from app.maintenance.domain.value_objects import IncidentSummary, OwnerApprovalSummary
from app.maintenance.infrastructure.models import IncidentModel, OwnerApprovalModel

# Sorted so the emitted `IN` is stable across runs, which keeps query logs and the
# statement-count test of R1.7 comparable. Same device the cleaning adapter uses.
_OPEN_STATUSES = sorted(OPEN_INCIDENT_STATUSES, key=lambda status: status.value)


class SqlAlchemyIncidentReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_open_for_properties(
        self, tenant_id: uuid.UUID, property_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        if not property_ids:
            return {}
        rows = await self._session.execute(
            select(IncidentModel.property_id, func.count())
            .where(
                IncidentModel.tenant_id == tenant_id,
                IncidentModel.property_id.in_(list(property_ids)),
                IncidentModel.status.in_(_OPEN_STATUSES),
            )
            .group_by(IncidentModel.property_id)
        )
        # `GROUP BY` already omits properties with no open incident, which is exactly the
        # sparse mapping the port promises — no post-filtering needed.
        return {property_id: int(count) for property_id, count in rows.all()}

    async def list_open_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[IncidentSummary]:
        """Selects the four projected columns, not the row.

        `select(Model)` would fetch `description`, `ai_classification` and the rest into
        memory only for `_to_summary` to drop them. Naming the columns means the sensitive
        ones are never read at all — the same guarantee one layer earlier, and cheaper.
        """
        rows = await self._session.execute(
            select(
                IncidentModel.id,
                IncidentModel.category,
                IncidentModel.severity,
                IncidentModel.created_at,
            )
            .where(
                IncidentModel.tenant_id == tenant_id,
                IncidentModel.property_id == property_id,
                IncidentModel.status.in_(_OPEN_STATUSES),
            )
            .order_by(IncidentModel.created_at.desc(), IncidentModel.id.desc())
        )
        return [
            IncidentSummary(
                id=row.id, category=row.category, severity=row.severity, opened_at=row.created_at
            )
            for row in rows.all()
        ]


class SqlAlchemyOwnerApprovalReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_pending_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[OwnerApprovalSummary]:
        """Selects the four projected columns, not the row — see the sibling reader."""
        rows = await self._session.execute(
            select(
                OwnerApprovalModel.id,
                OwnerApprovalModel.related_type,
                OwnerApprovalModel.amount,
                OwnerApprovalModel.requested_at,
            )
            .where(
                OwnerApprovalModel.tenant_id == tenant_id,
                OwnerApprovalModel.property_id == property_id,
                OwnerApprovalModel.status == OwnerApprovalStatus.PENDING,
            )
            # Oldest request first: a to-do list, not a feed. `id` breaks a shared instant
            # so the order is total.
            .order_by(OwnerApprovalModel.requested_at, OwnerApprovalModel.id)
        )
        return [
            OwnerApprovalSummary(
                id=row.id,
                related_type=row.related_type,
                amount=row.amount,
                requested_at=row.requested_at,
            )
            for row in rows.all()
        ]
