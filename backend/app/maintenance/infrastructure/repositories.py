"""SQLAlchemy adapters for the maintenance ports (`dashboard-api` R1 R2; `guest-portal-api` R5.1 R5.4).

The readers came first (`dashboard-api`) and the single writer second (`guest-portal-api`) —
`app/maintenance/domain/repositories.py` records why the two halves belong to different changes.

**What the writer has to get right, and it is not obvious.** R5.4 requires an incident opened by
a guest to be indistinguishable, for the classification flow, from any other one in `OPEN`. So
nothing here is special-cased for the guest: the entity's fields are mapped as they come, and
`Incident`'s defaults for the four columns that flow owns (`category`, `severity`, `ai_summary`,
`ai_classification`) are the same values the columns default to on their own.
`tests/maintenance/test_repositories.py` pins that equality against the DDL, so the two cannot
drift apart into a row the classifier — or the reader above — could spot.

Every field is mapped rather than letting the server defaults fill the four: an adapter that
dropped columns it currently expects to be default would silently discard a category the day
`maintenance` passes one.

The writer never commits — the use case owns the transaction (R6.2, so the audit row and the
incident land together or not at all).

Every statement filters `tenant_id` explicitly. The session listener of `app/core/db.py`
also covers both tables (they carry `TenantScopedMixin`), but it is the net and never the
mechanism — and for the INSERT it is not even the net, because the listener does not cover
INSERTs at all (limit 3 of that module), which is why the writer checks the tenant itself.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.maintenance.domain.entities import OPEN_INCIDENT_STATUSES, Incident
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


class SqlAlchemyIncidentRepository:
    """`IncidentRepository` — the one writer of `incidents` (`guest-portal-api` design D15)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: uuid.UUID, incident: Incident) -> None:
        if incident.tenant_id != tenant_id:
            # `app/core/db.py`'s third limit: the session's global filter does not cover
            # INSERTs, so this check is the only thing standing between a wiring mistake and
            # a row of another tenant — exactly as `SqlAlchemyAuditLogRepository.add` and
            # `SqlAlchemyTimelineEventRepository.add` document for the same reason.
            raise CrossTenantWriteError(
                entity="incident",
                entity_tenant_id=incident.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            IncidentModel(
                id=incident.id,
                tenant_id=incident.tenant_id,
                property_id=incident.property_id,
                reservation_id=incident.reservation_id,
                reported_by_user_id=incident.reported_by_user_id,
                # The digest, never the token (R5.1). Nothing here can tell the difference —
                # the column is a `VARCHAR(200)` that would hold either — so the guarantee
                # lives where the value is produced: `GuestSession.token_hash` is what the
                # authoriser resolved, and `tests/guests/test_portal_incident_api.py` pins
                # that the persisted value is the hash of the presented token.
                reported_by_guest_token=incident.reported_by_guest_token,
                source=incident.source,
                category=incident.category,
                severity=incident.severity,
                status=incident.status,
                title=incident.title,
                description=incident.description,
                ai_summary=incident.ai_summary,
                ai_classification=incident.ai_classification,
                assigned_technician_id=incident.assigned_technician_id,
                owner_approval_required=incident.owner_approval_required,
                estimated_cost=incident.estimated_cost,
                approved_cost=incident.approved_cost,
                final_cost=incident.final_cost,
                resolved_at=incident.resolved_at,
                created_at=incident.created_at,
                updated_at=incident.updated_at,
            )
        )
        await self._session.flush()
