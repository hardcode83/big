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

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cleaning.domain.entities import CleaningTask
from app.cleaning.infrastructure.repositories import SqlAlchemyLiveCleaningTaskReader
from app.core.db import require_unmarked_session
from app.core.tenancy import CrossTenantWriteError
from app.integrations.domain.storage import ObjectLocation
from app.maintenance.domain.entities import (
    CLOSED_INCIDENT_STATUSES,
    OPEN_INCIDENT_STATUSES,
    Incident,
    IncidentPhoto,
    OwnerApproval,
)
from app.maintenance.domain.enums import IncidentStatus, OwnerApprovalStatus
from app.maintenance.domain.exceptions import MaintenanceValidationError
from app.maintenance.domain.repositories import IncidentFilters, IncidentPage
from app.maintenance.domain.value_objects import IncidentSummary, OwnerApprovalSummary
from app.maintenance.infrastructure.models import (
    IncidentModel,
    IncidentPhotoModel,
    OwnerApprovalModel,
)

# Sorted so the emitted `IN` is stable across runs, which keeps query logs and the
# statement-count test of R1.7 comparable. Same device the cleaning adapter uses.
_OPEN_STATUSES = sorted(OPEN_INCIDENT_STATUSES, key=lambda status: status.value)
_CLOSED_STATUSES = sorted(CLOSED_INCIDENT_STATUSES, key=lambda status: status.value)

#: The columns `Incident`'s own methods may change. Named rather than writing the whole row,
#: for the reason `cleaning` gives its `_MUTABLE_TASK_COLUMNS`: an UPDATE that also set
#: `tenant_id`, `property_id` or `created_at` would let a wiring mistake move a row between
#: tenants through a method whose name says it only saves.
_MUTABLE_INCIDENT_COLUMNS = (
    "category",
    "severity",
    "status",
    "ai_summary",
    "ai_classification",
    "assigned_technician_id",
    "assignment_note",
    "eta_at",
    "materials",
    "owner_approval_required",
    "estimated_cost",
    "approved_cost",
    "final_cost",
    "resolved_at",
    "updated_at",
)

#: Same device for the approval. `requested_at`, `amount`, `reason` and the polymorphic pair
#: are written once by `add` and never again — an approval whose amount could change after
#: the owner answered it would make `approved_cost` meaningless.
_MUTABLE_APPROVAL_COLUMNS = (
    "status",
    "responded_at",
    "responded_by",
    "response_notes",
)


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

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: IncidentFilters,
        *,
        page: int,
        per_page: int,
    ) -> IncidentPage:
        """`GET /incidents` (R5.1). Whole rows, unlike the two projections above.

        `filters.assigned_technician_id` is where R5.3 lands: the use case sets it from the
        actor's role, so a `TECHNICIAN` gets a `WHERE` clause rather than a router that has
        to remember to filter.
        """
        if page < 1 or per_page < 1:
            # `offset((page - 1) * per_page)` goes negative for `page = 0`, and Postgres
            # answers that with `OFFSET must not be negative` — a `DBAPIError` that reaches
            # the caller as a 500 instead of the 422 a bad query parameter deserves. The
            # route of D14 declares `ge=1` on both, so this is the second line of defence
            # and the one that holds for a caller that is not a route: the job, a command,
            # a test.
            raise MaintenanceValidationError(
                f"page and per_page must be positive, got page={page}, per_page={per_page}"
            )

        conditions = _incident_conditions(tenant_id, filters)
        total = await self._session.scalar(
            select(func.count()).select_from(IncidentModel).where(*conditions)
        )
        rows = await self._session.execute(
            select(IncidentModel)
            .where(*conditions)
            # Newest first — an operator reads this as a queue of what just broke. `id`
            # breaks a shared instant so the order is total and the pages do not overlap.
            .order_by(IncidentModel.created_at.desc(), IncidentModel.id.desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return IncidentPage(
            items=tuple(_to_incident(model) for model in rows.scalars()),
            total=int(total or 0),
        )

    async def list_pending_classification(
        self, tenant_id: uuid.UUID, *, limit: int
    ) -> Sequence[Incident]:
        """The candidate rule of D3, as one `WHERE`: `OPEN` and never looked at."""
        rows = await self._session.execute(
            select(IncidentModel)
            .where(
                IncidentModel.tenant_id == tenant_id,
                IncidentModel.status == IncidentStatus.OPEN,
                IncidentModel.ai_classification.is_(None),
            )
            .order_by(IncidentModel.created_at, IncidentModel.id)
            .limit(limit)
        )
        return [_to_incident(model) for model in rows.scalars()]

    async def list_active_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[Incident]:
        """Every non-terminal incident of the property (D7), as entities.

        Excludes by terminal status rather than selecting the open ones one by one, so a
        status added to the enum later counts as active until somebody decides otherwise —
        the same direction `OPEN_INCIDENT_STATUSES` chose, and the safe one for a machine
        that decides whether a flat can be let.
        """
        rows = await self._session.execute(
            select(IncidentModel)
            .where(
                IncidentModel.tenant_id == tenant_id,
                IncidentModel.property_id == property_id,
                IncidentModel.status.notin_(_CLOSED_STATUSES),
            )
            .order_by(IncidentModel.created_at, IncidentModel.id)
        )
        return [_to_incident(model) for model in rows.scalars()]


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
                cleaning_task_id=incident.cleaning_task_id,
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
                assignment_note=incident.assignment_note,
                eta_at=incident.eta_at,
                materials=incident.materials,
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

    async def get(self, tenant_id: uuid.UUID, incident_id: uuid.UUID) -> Incident | None:
        result = await self._session.execute(
            select(IncidentModel).where(
                IncidentModel.tenant_id == tenant_id, IncidentModel.id == incident_id
            )
        )
        model = result.scalar_one_or_none()
        return _to_incident(model) if model is not None else None

    async def save(self, tenant_id: uuid.UUID, incident: Incident) -> None:
        _require_same_tenant(incident.tenant_id, tenant_id, "incident")
        await self._session.execute(
            update(IncidentModel)
            .where(
                IncidentModel.tenant_id == incident.tenant_id,
                IncidentModel.id == incident.id,
            )
            .values(
                **{
                    column: getattr(incident, column)
                    for column in _MUTABLE_INCIDENT_COLUMNS
                }
            )
        )
        await self._session.flush()


class SqlAlchemyOwnerApprovalRepository:
    """`OwnerApprovalRepository` — the adapter behind the owner-approval port.

    `owner_approvals.reason` and `response_notes` are rule 11 cleartext sinks; who writes them
    is declared in that rule's table (`sdd/steering/security.md`) and nowhere else.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, tenant_id: uuid.UUID, approval_id: uuid.UUID
    ) -> OwnerApproval | None:
        result = await self._session.execute(
            select(OwnerApprovalModel).where(
                OwnerApprovalModel.tenant_id == tenant_id,
                OwnerApprovalModel.id == approval_id,
            )
        )
        model = result.scalar_one_or_none()
        return _to_approval(model) if model is not None else None

    async def add(self, tenant_id: uuid.UUID, approval: OwnerApproval) -> None:
        _require_same_tenant(approval.tenant_id, tenant_id, "owner approval")
        self._session.add(
            OwnerApprovalModel(
                id=approval.id,
                tenant_id=approval.tenant_id,
                property_id=approval.property_id,
                related_type=approval.related_type,
                related_id=approval.related_id,
                amount=approval.amount,
                reason=approval.reason,
                status=approval.status,
                requested_at=approval.requested_at,
                responded_at=approval.responded_at,
                responded_by=approval.responded_by,
                response_notes=approval.response_notes,
            )
        )
        await self._session.flush()

    async def save(self, tenant_id: uuid.UUID, approval: OwnerApproval) -> None:
        _require_same_tenant(approval.tenant_id, tenant_id, "owner approval")
        await self._session.execute(
            update(OwnerApprovalModel)
            .where(
                OwnerApprovalModel.tenant_id == approval.tenant_id,
                OwnerApprovalModel.id == approval.id,
            )
            .values(
                **{
                    column: getattr(approval, column)
                    for column in _MUTABLE_APPROVAL_COLUMNS
                }
            )
        )
        await self._session.flush()

    async def find_approved_for_incident(
        self, tenant_id: uuid.UUID, incident_id: uuid.UUID
    ) -> Sequence[OwnerApproval]:
        """Both gates of D11 point at the incident through the polymorphic pair, so
        `related_id` is the whole filter and `related_type` is not — the budget gate writes
        `INCIDENT` and the real-cost gate `MAINTENANCE_COST`, and the caller wants either."""
        rows = await self._session.execute(
            select(OwnerApprovalModel)
            .where(
                OwnerApprovalModel.tenant_id == tenant_id,
                OwnerApprovalModel.related_id == incident_id,
                OwnerApprovalModel.status == OwnerApprovalStatus.APPROVED,
            )
            # `NULLS LAST` explicitly: Postgres puts nulls **first** under `DESC`, so an
            # `APPROVED` row with no `responded_at` would sort ahead of every real answer.
            # `OwnerApproval.answer` always writes the two together, so such a row is not
            # reachable through the domain — but a backfill could make one, and the caller
            # of this port is deciding whether a cost was authorised.
            .order_by(
                OwnerApprovalModel.responded_at.desc().nullslast(),
                OwnerApprovalModel.id.desc(),
            )
        )
        return [_to_approval(model) for model in rows.scalars()]


class SqlAlchemyLiveCleaningTaskQuery:
    """`LiveCleaningTaskQuery` — the third collection `PropertyStateMachine` needs (D7).

    **Composes `cleaning`'s one-method reader, not its repository.** The mirror image —
    `cleaning`'s `SqlAlchemyBlockingIncidentQuery` reads `incidents` directly — is not
    available to us as-is: that one returns a boolean, so nothing of the `Incident`
    aggregate crosses, while this must return `CleaningTask` entities, and mapping them here
    would be a second copy of something that belongs to `cleaning`.

    The first version of this class composed `SqlAlchemyCleaningTaskRepository` whole, which
    is the alternative D7 rejected — "repositorio de otro agregado raíz, y `maintenance`
    sólo necesita un método de lectura" — reached by composition rather than by import, and
    it also filtered `is_live` in Python after loading every task of the property. Both were
    raised by the architecture panel of section 5. `SqlAlchemyLiveCleaningTaskReader` is the
    narrow, read-only, SQL-filtered surface that rejection asks for.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._tasks = SqlAlchemyLiveCleaningTaskReader(session)

    async def list_live_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[CleaningTask]:
        return await self._tasks.list_live_for_property(tenant_id, property_id)


def _require_same_tenant(
    entity_tenant_id: uuid.UUID, tenant_id: uuid.UUID, entity: str
) -> None:
    if entity_tenant_id != tenant_id:
        raise CrossTenantWriteError(
            entity=entity, entity_tenant_id=entity_tenant_id, acting_tenant_id=tenant_id
        )


def _incident_conditions(tenant_id: uuid.UUID, filters: IncidentFilters) -> list:
    conditions = [IncidentModel.tenant_id == tenant_id]
    if filters.property_id is not None:
        conditions.append(IncidentModel.property_id == filters.property_id)
    if filters.status is not None:
        conditions.append(IncidentModel.status == filters.status)
    if filters.severity is not None:
        conditions.append(IncidentModel.severity == filters.severity)
    if filters.assigned_technician_id is not None:
        conditions.append(
            IncidentModel.assigned_technician_id == filters.assigned_technician_id
        )
    return conditions


def _to_incident(model: IncidentModel) -> Incident:
    """Hydrate the entity **without `reported_by_guest_token`**, deliberately.

    Nothing in this module's flow reads it: R1-R4 classify, price, assign and resolve, and
    none of those asks who reported the fault. Carrying it anyway would hand every read path
    — and therefore every serialiser downstream of one — a stable unsalted digest that
    correlates one guest's stay across properties and reservations, which is precisely the
    field `IncidentSummary`'s docstring names when it explains why the dashboard got a
    projection instead of the entity.

    Dropping it here is safe rather than lossy: `_MUTABLE_INCIDENT_COLUMNS` does not include
    the column, so a hydrated-then-saved incident cannot erase what the guest portal wrote.
    Raised by the security panel of section 5.
    """
    return Incident(
        id=model.id,
        tenant_id=model.tenant_id,
        property_id=model.property_id,
        source=model.source,
        title=model.title,
        description=model.description,
        created_at=model.created_at,
        updated_at=model.updated_at,
        reservation_id=model.reservation_id,
        reported_by_user_id=model.reported_by_user_id,
        cleaning_task_id=model.cleaning_task_id,
        category=model.category,
        severity=model.severity,
        status=model.status,
        ai_summary=model.ai_summary,
        ai_classification=model.ai_classification,
        assigned_technician_id=model.assigned_technician_id,
        assignment_note=model.assignment_note,
        eta_at=model.eta_at,
        materials=model.materials,
        owner_approval_required=model.owner_approval_required,
        estimated_cost=model.estimated_cost,
        approved_cost=model.approved_cost,
        final_cost=model.final_cost,
        resolved_at=model.resolved_at,
    )


def _to_approval(model: OwnerApprovalModel) -> OwnerApproval:
    return OwnerApproval(
        id=model.id,
        tenant_id=model.tenant_id,
        property_id=model.property_id,
        related_type=model.related_type,
        related_id=model.related_id,
        amount=model.amount,
        reason=model.reason,
        requested_at=model.requested_at,
        status=model.status,
        responded_at=model.responded_at,
        responded_by=model.responded_by,
        response_notes=model.response_notes,
    )


def _to_incident_photo(model: IncidentPhotoModel) -> IncidentPhoto:
    return IncidentPhoto(
        id=model.id,
        tenant_id=model.tenant_id,
        incident_id=model.incident_id,
        uploaded_by=model.uploaded_by,
        stage=model.stage,
        storage_key=model.storage_key,
        created_at=model.created_at,
    )


class SqlAlchemyIncidentPhotoRepository:
    """`IncidentPhotoRepository` — the writer and reader of `incident_photos` (R1, R3).

    **Unlike `SqlAlchemyCleaningPhotoRepository`, this one needs no join to be scoped.**
    `incident_photos` carries its own `tenant_id` (design D2), so every statement here filters
    the column directly. Its cleaning counterpart has to resolve the parent task first — or join
    `cleaning_tasks` to read — because its table names no owner of its own; that difference is
    the whole practical payoff of D2.

    Never commits: the use case owns the transaction, so the object, the row and the audit entry
    land together or not at all (design D7).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: uuid.UUID, photo: IncidentPhoto) -> None:
        """Insert one photo, refusing a row that belongs to another tenant.

        The explicit check is the mechanism, not belt-and-braces: limit 3 of `app/core/db.py`
        says the session's global filter does **not** cover INSERTs, so for a write this is the
        only thing between a wiring mistake and a row of another tenant. Same guard, same
        reason, as `SqlAlchemyIncidentRepository.add` above.

        The composite foreign key of D2 is the second line of defence and catches a different
        error: this check compares the photo's tenant against the *acting* tenant, while the
        constraint compares it against the tenant of the *incident*. A row could pass this and
        still be refused by Postgres — which is exactly the case
        `test_a_photo_cannot_be_attached_to_an_incident_of_another_tenant` drives.
        """
        if photo.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="incident_photo",
                entity_tenant_id=photo.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            IncidentPhotoModel(
                id=photo.id,
                tenant_id=photo.tenant_id,
                incident_id=photo.incident_id,
                uploaded_by=photo.uploaded_by,
                stage=photo.stage,
                storage_key=photo.storage_key,
                # Written, never left to a default — the column has none, deliberately. See
                # `IncidentPhotoModel`: Postgres `now()` is the transaction timestamp, so a
                # burst of photos would share one instant and the ordering below would fall
                # through to a random `uuid4`.
                created_at=photo.created_at,
            )
        )
        await self._session.flush()

    async def list_for_incident(
        self, tenant_id: uuid.UUID, incident_id: uuid.UUID
    ) -> Sequence[IncidentPhoto]:
        """That incident's photos, oldest first (R3.1).

        `created_at` then `id`: the timestamp is what the requirement asks for, and `id` breaks
        a tie deterministically so two photos sharing an instant do not swap places between
        reads. `cleaning` orders the same way for the same reason.
        """
        rows = await self._session.execute(
            select(IncidentPhotoModel)
            .where(
                IncidentPhotoModel.tenant_id == tenant_id,
                IncidentPhotoModel.incident_id == incident_id,
            )
            .order_by(IncidentPhotoModel.created_at, IncidentPhotoModel.id)
        )
        return [_to_incident_photo(model) for model in rows.scalars()]


class SqlAlchemyUnscopedIncidentPhotoLocationQuery:
    """Implements `UnscopedObjectLocationQuery` for `incident_photos` — design D13.

    **The one read in this module that does not take a tenant**, and a class of its own rather
    than a method on the repository above, which is the mechanism: the repository every
    authenticated use case holds cannot express this query, so none of them can reach for it
    instead of a scoped read. Its only wiring is the anonymous serving route's builder.

    **No `JOIN`, unlike its cleaning twin.** `incident_photos.tenant_id` is on the row (design
    D2), so both facts the caller needs come from one table. The cleaning version has to join
    `cleaning_tasks` because that is where its tenant lives.

    **Contract of the session it is given: never marked with a tenant.** Nothing in the
    anonymous route's dependency chain binds one — the route carries no `require(...)`, because
    an `<img src>` sends no `Authorization` header. That is not something the route's shape
    guarantees, though: limit 2 of `_scope_statement_to_tenant` (`app/core/db.py`) is explicit
    that being anonymous is no guarantee of being unmarked, and names the cases. What keeps the
    contract true is `require_unmarked_session` below, which fails the read instead of letting
    it scope silently to one tenant and refuse every photo of any other — a wiring mistake that
    would otherwise surface as a broken signature.

    Declared in the census of `tests/test_unscoped_reads.py`, which is where R6.4 requires the
    exception to be visible.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def locate_without_tenant_scoping(
        self, object_id: uuid.UUID
    ) -> ObjectLocation | None:
        """Two columns, no entity: the key to rebuild the signature over, and its owner.

        Returning `ObjectLocation` rather than `IncidentPhoto` keeps `uploaded_by`, `stage` and
        `created_at` — data about a tenant nobody has authenticated against — out of a request
        that returns bytes.
        """
        require_unmarked_session(self._session, read="locate_without_tenant_scoping")
        row = (
            await self._session.execute(
                select(IncidentPhotoModel.storage_key, IncidentPhotoModel.tenant_id).where(
                    IncidentPhotoModel.id == object_id
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return ObjectLocation(storage_key=row.storage_key, tenant_id=row.tenant_id)
