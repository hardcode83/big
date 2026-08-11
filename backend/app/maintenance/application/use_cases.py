"""`maintenance`'s first use case: a guest opens an incident (R5.1, R5.4, R6.1-R6.4; D15, D12, D13).

The module `sdd/specs/domain-foundation-ops.md:12` says this change owes `maintenance`, and
nothing more than that: creating an incident in `OPEN`. Classifying it, asking the owner for
approval, assigning a technician and resolving it are `maintenance`'s own flow.

**It takes the stay's identifiers, not a `GuestSession`.** The values all come from the token
(R2.1) and the caller is the guest portal, so passing that dataclass would be the obvious
shortcut — and it would make `maintenance` depend on `guests`, in the direction that has no
reason to exist: an incident reported by a cleaner or raised by a lock alert will arrive
through the same use case with no portal anywhere in sight. The layering test would not catch
it (it bans framework imports and outer layers, not sibling domains), which is precisely why
it is stated here.

**Not idempotent, and not asked to be** (D13). A retried `POST` opens a second incident in
`OPEN`; what bounds that is the per-token rate limit of D6, and it is recorded as known debt
rather than dressed up as a feature.
"""

import uuid
from datetime import datetime

from app.audit.domain import actions as audit_actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.core.unit_of_work import UnitOfWork
from app.maintenance.domain.entities import Incident
from app.maintenance.domain.enums import IncidentSource, IncidentStatus
from app.maintenance.domain.repositories import IncidentRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.domain.repositories import TimelineEventRepository
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData

#: What the timeline says happened. A constant, **never the guest's own title**: `timeline_events`
#: is append-only (`steering/architecture.md`: "nunca se editan eventos pasados"), so free text an
#: anonymous caller typed could never be redacted afterwards. Same reasoning D12 applies to
#: `metadata`, one column over.
_TIMELINE_TITLE = "Guest reported an incident"


class ReportGuestIncidentUseCase:
    """Create the incident, audit it, and put it on the property's timeline — one transaction.

    The order is the contract, not a preference:

    1. the incident, so it has an id to audit;
    2. the `AuditLog` (R6.1), **before** the response that acknowledges it (R6.2);
    3. the `TimelineEvent` (R6.3), so the milestone appears in the property's timeline like any
       other transition;
    4. one `commit()`.

    All four in one transaction, so there is no state in which an incident exists that nobody
    can attribute — which is the whole point of auditing an anonymous surface.

    **What the audit row says, and what it deliberately does not.** `AUDITABLE_FIELDS` gives
    `INCIDENT` exactly `source`, `status` and `reservation_id`; `title` and `description` are
    absent because they are free text written from outside and `audit_logs.changes` is a rule-11
    sink. `ChangeSet` enforces that by construction — naming a field outside the allowlist
    raises — so this class cannot leak a word the guest typed even by trying. The actor is the
    bearer of the link, named by the digest (R6.4): `AuditLogFactory` refuses a row that claims
    both a user and a token bearer, and refuses a `token_hash` that is not a SHA-256 digest,
    which is what keeps the cleartext token out of an append-only table.
    """

    def __init__(
        self,
        *,
        incidents: IncidentRepository,
        audit: AuditLogRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._incidents = incidents
        self._audit = audit
        self._timeline = timeline
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        reservation_id: uuid.UUID,
        reporter_token_hash: str,
        title: str,
        description: str,
        ip: str | None,
        now: datetime,
    ) -> Incident:
        incident = Incident(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=property_id,
            source=IncidentSource.GUEST,
            title=title,
            description=description,
            created_at=now,
            updated_at=now,
            reservation_id=reservation_id,
            # R5.1: the non-reversible reference, never the value. The digest arrives already
            # resolved by the authoriser, so this method never sees a cleartext token at all.
            reported_by_guest_token=reporter_token_hash,
        )
        # R5.4: `category`, `severity`, `ai_summary` and `ai_classification` are not passed.
        # `Incident`'s defaults for them are the values the columns default to on their own
        # (pinned against the DDL in `tests/maintenance/test_repositories.py`), so the row is
        # indistinguishable from any other `OPEN` incident for the classification flow.
        await self._incidents.add(tenant_id, incident)

        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=audit_actions.INCIDENT_CREATED,
                entity_type=audit_actions.ENTITY_INCIDENT,
                entity_id=incident.id,
                actor_user_id=None,
                actor_guest_token_hash=reporter_token_hash,
                actor_ip=ip,
                changes=ChangeSet(audit_actions.ENTITY_INCIDENT)
                .diff("source", None, IncidentSource.GUEST)
                .diff("status", None, IncidentStatus.OPEN)
                .diff("reservation_id", None, reservation_id),
                now=now,
            ),
        )

        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                TimelineEventData(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    property_id=property_id,
                    actor_type=TimelineActorType.GUEST,
                    # The only combination the factory allows for an actor that is not a
                    # `USER` — and the honest one: there is no user to name (D12).
                    actor_user_id=None,
                    event_type=TimelineEventType.INCIDENT_CREATED,
                    title=_TIMELINE_TITLE,
                    created_at=now,
                    reservation_id=reservation_id,
                    # Identifiers only, for the reason the title is a constant.
                    metadata={
                        "incident_id": str(incident.id),
                        "reservation_id": str(reservation_id),
                    },
                )
            ),
        )

        await self._uow.commit()
        return incident
