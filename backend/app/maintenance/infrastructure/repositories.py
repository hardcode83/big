"""SQLAlchemy adapter for `IncidentRepository` (R5.1, R5.4, design D15).

First writer of `incidents` in the system, and the row it writes has to be **ordinary**: R5.4
requires an incident opened by a guest to be indistinguishable, for the classification flow,
from any other one in `OPEN`. That is why nothing here is special-cased for the guest — the
entity's fields are mapped as they come, and `Incident`'s defaults for the four columns that
flow owns (`category`, `severity`, `ai_summary`, `ai_classification`) are the same values the
columns default to on their own. `tests/maintenance/test_repositories.py` pins that equality
against the DDL, so the two cannot drift apart into a row the classifier could spot.

Every field is mapped rather than letting the server defaults fill the four: a repository that
dropped columns it currently expects to be default would silently discard a category the day
`maintenance` passes one.

Never commits — the use case owns the transaction (R6.2, so the audit row and the incident
land together or not at all).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.maintenance.domain.entities import Incident
from app.maintenance.infrastructure.models import IncidentModel


class SqlAlchemyIncidentRepository:
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
