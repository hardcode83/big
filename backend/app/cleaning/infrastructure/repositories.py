"""SQLAlchemy adapters for the cleaning ports (design D2, D6).

Every statement filters `tenant_id` explicitly and every write checks it, because the
session listener of `app/core/db.py` covers neither INSERTs nor the identity map (limits 3
and 4 of its own docstring). No method commits: the use case owns the transaction.

**And for `cleaning_checklist_completions` the explicit filter is not defence in depth —
it is the only defence.** That table has no `tenant_id` column (`domain-foundation-ops`
scopes it transitively through `cleaning_task_id`), so `tenant_scoped_classes()`
(`app/core/db.py:62`), which selects mapped classes *by that column*, never hands it to
`with_loader_criteria`. Its adapter therefore resolves the parent task inside the tenant
before touching a single row, and refuses when it does not resolve. R7.5 asks for a
dedicated isolation test precisely because nothing else here would catch a regression.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cleaning.domain.entities import (
    LIVE_STATUSES,
    CleaningChecklistCompletion,
    CleaningChecklistTemplate,
    CleaningTask,
)
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import (
    CleaningTaskNotFoundError,
    DuplicateLiveCleaningTaskError,
)
from app.cleaning.domain.value_objects import CleaningTaskSummary
from app.cleaning.domain.repositories import CleaningTaskFilters, Page, TemplatePage
from app.cleaning.infrastructure.models import (
    CleaningChecklistCompletionModel,
    CleaningChecklistTemplateModel,
    CleaningTaskModel,
)
from app.core.tenancy import CrossTenantWriteError
from app.maintenance.domain.enums import IncidentSeverity, IncidentStatus
from app.maintenance.infrastructure.models import IncidentModel

LIVE_TASK_CONSTRAINT = "uq_cleaning_tasks_live_reservation"
# The unique constraint `upsert` conflicts on. Named rather than derived from the columns
# so the statement breaks loudly if `domain-foundation-ops`' constraint is ever renamed,
# instead of silently degrading to a plain insert.
CHECKLIST_COMPLETION_CONSTRAINT = (
    "uq_cleaning_checklist_completions_cleaning_task_id_item_id"
)

# Columns `save` writes back. Identity (`id`, `tenant_id`, `property_id`,
# `reservation_id`, `checklist_template_id`) is absent: a repository able to move a row to
# another tenant would defeat rule 1, and one able to re-point `reservation_id` would
# defeat the idempotency key of design D2.
#
# `notes` is absent **on purpose** (design D13): rule 11 of `steering/security.md`
# enumerates six cleartext sinks and this column is not one of them, so this change does
# not open a write path to it. Adding it here is not a detail — it is the steering
# decision D13 declines to take.
_MUTABLE_TASK_COLUMNS = (
    "assigned_cleaner_id",
    "status",
    "scheduled_start",
    "scheduled_end",
    "accepted_at",
    "started_at",
    "completed_at",
    "validation_status",
    "validated_by_user_id",
    "validated_at",
    "updated_at",
)


class SqlAlchemyCleaningTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: uuid.UUID, task_id: uuid.UUID) -> CleaningTask | None:
        result = await self._session.execute(
            select(CleaningTaskModel).where(
                CleaningTaskModel.tenant_id == tenant_id, CleaningTaskModel.id == task_id
            )
        )
        model = result.scalar_one_or_none()
        return _to_task(model) if model is not None else None

    async def add(self, tenant_id: uuid.UUID, task: CleaningTask) -> None:
        _require_same_tenant(task.tenant_id, tenant_id, "cleaning task")
        self._session.add(
            CleaningTaskModel(
                id=task.id,
                tenant_id=task.tenant_id,
                property_id=task.property_id,
                checklist_template_id=task.checklist_template_id,
                reservation_id=task.reservation_id,
                assigned_cleaner_id=task.assigned_cleaner_id,
                status=task.status,
                scheduled_start=task.scheduled_start,
                scheduled_end=task.scheduled_end,
                accepted_at=task.accepted_at,
                started_at=task.started_at,
                completed_at=task.completed_at,
                validation_status=task.validation_status,
                validated_by_user_id=task.validated_by_user_id,
                validated_at=task.validated_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            # The partial index is the authority, not a prior read: two concurrent runs of
            # `process_checkouts` both pass the lookup and only one can pass this (D2).
            if LIVE_TASK_CONSTRAINT in str(error.orig):
                raise DuplicateLiveCleaningTaskError(
                    f"Reservation {task.reservation_id} already has a live cleaning task"
                ) from error
            raise

    async def save(self, tenant_id: uuid.UUID, task: CleaningTask) -> None:
        _require_same_tenant(task.tenant_id, tenant_id, "cleaning task")
        values = {column: getattr(task, column) for column in _MUTABLE_TASK_COLUMNS}
        try:
            await self._session.execute(
                update(CleaningTaskModel)
                .where(
                    CleaningTaskModel.tenant_id == task.tenant_id,
                    CleaningTaskModel.id == task.id,
                )
                .values(**values)
            )
            await self._session.flush()
        except IntegrityError as error:
            # Reachable too: re-assigning a task back into a live status while another one
            # holds the reservation trips the same index.
            if LIVE_TASK_CONSTRAINT in str(error.orig):
                raise DuplicateLiveCleaningTaskError(
                    f"Reservation {task.reservation_id} already has a live cleaning task"
                ) from error
            raise

    async def list_live_for_reservation(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> Sequence[CleaningTask]:
        rows = await self._session.execute(
            select(CleaningTaskModel).where(
                CleaningTaskModel.tenant_id == tenant_id,
                CleaningTaskModel.reservation_id == reservation_id,
                CleaningTaskModel.status.in_(sorted(LIVE_STATUSES, key=lambda s: s.value)),
            )
        )
        return [_to_task(model) for model in rows.scalars()]

    async def list_live_for_properties(
        self, tenant_id: uuid.UUID, property_ids: Sequence[uuid.UUID]
    ) -> Sequence[CleaningTaskSummary]:
        """One statement for N properties (`dashboard-api` R1.7).

        The `IN` is what keeps the dashboard collection at a fixed query count; the caller
        groups the result by `property_id`. An empty batch short-circuits rather than
        emitting `IN ()`, which is neither valid nor meaningful.

        **Selects three columns, not the row.** `select(CleaningTaskModel)` would read
        `notes` — free text, and the hazard `api/schemas.py:8-13` already names for this
        entity — plus `assigned_cleaner_id` and `validated_by_user_id`, only for the
        projection to drop them. Naming the columns means they never leave Postgres.
        """
        if not property_ids:
            return []
        rows = await self._session.execute(
            select(
                CleaningTaskModel.id,
                CleaningTaskModel.property_id,
                CleaningTaskModel.status,
            ).where(
                CleaningTaskModel.tenant_id == tenant_id,
                CleaningTaskModel.property_id.in_(list(property_ids)),
                CleaningTaskModel.status.in_(sorted(LIVE_STATUSES, key=lambda s: s.value)),
            )
        )
        return [
            CleaningTaskSummary(id=row.id, property_id=row.property_id, status=row.status)
            for row in rows.all()
        ]

    async def list_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[CleaningTask]:
        rows = await self._session.execute(
            select(CleaningTaskModel)
            .where(
                CleaningTaskModel.tenant_id == tenant_id,
                CleaningTaskModel.property_id == property_id,
            )
            .order_by(CleaningTaskModel.created_at, CleaningTaskModel.id)
        )
        return [_to_task(model) for model in rows.scalars()]

    async def list_rejecters_for_reservation(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> Sequence[uuid.UUID]:
        rows = await self._session.execute(
            select(CleaningTaskModel.assigned_cleaner_id).where(
                CleaningTaskModel.tenant_id == tenant_id,
                CleaningTaskModel.reservation_id == reservation_id,
                CleaningTaskModel.status == CleaningTaskStatus.REJECTED,
                CleaningTaskModel.assigned_cleaner_id.is_not(None),
            )
        )
        return list(rows.scalars())

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: CleaningTaskFilters,
        *,
        page: int,
        per_page: int,
    ) -> Page:
        conditions = _task_conditions(tenant_id, filters)
        total = await self._session.scalar(
            select(func.count()).select_from(CleaningTaskModel).where(*conditions)
        )
        rows = await self._session.execute(
            _ordered_tasks(select(CleaningTaskModel).where(*conditions))
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return Page(
            items=tuple(_to_task(model) for model in rows.scalars()), total=int(total or 0)
        )


class SqlAlchemyCleaningChecklistTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, tenant_id: uuid.UUID, template_id: uuid.UUID
    ) -> CleaningChecklistTemplate | None:
        result = await self._session.execute(
            select(CleaningChecklistTemplateModel).where(
                CleaningChecklistTemplateModel.tenant_id == tenant_id,
                CleaningChecklistTemplateModel.id == template_id,
            )
        )
        model = result.scalar_one_or_none()
        return _to_template(model) if model is not None else None

    async def add(self, tenant_id: uuid.UUID, template: CleaningChecklistTemplate) -> None:
        _require_same_tenant(template.tenant_id, tenant_id, "checklist template")
        self._session.add(
            CleaningChecklistTemplateModel(
                id=template.id,
                tenant_id=template.tenant_id,
                property_id=template.property_id,
                name=template.name,
                items=template.items,
                required_photos=template.required_photos,
                active=template.active,
            )
        )
        await self._session.flush()

    async def list_candidates_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[CleaningChecklistTemplate]:
        """Both resolution levels in one query, so `resolve_template` can see ambiguity."""
        rows = await self._session.execute(
            select(CleaningChecklistTemplateModel).where(
                CleaningChecklistTemplateModel.tenant_id == tenant_id,
                CleaningChecklistTemplateModel.active.is_(True),
                (CleaningChecklistTemplateModel.property_id == property_id)
                | (CleaningChecklistTemplateModel.property_id.is_(None)),
            )
        )
        return [_to_template(model) for model in rows.scalars()]

    async def list(
        self, tenant_id: uuid.UUID, *, page: int, per_page: int
    ) -> TemplatePage:
        conditions = [CleaningChecklistTemplateModel.tenant_id == tenant_id]
        total = await self._session.scalar(
            select(func.count()).select_from(CleaningChecklistTemplateModel).where(*conditions)
        )
        rows = await self._session.execute(
            select(CleaningChecklistTemplateModel)
            .where(*conditions)
            .order_by(
                CleaningChecklistTemplateModel.created_at.desc(),
                CleaningChecklistTemplateModel.id,
            )
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return TemplatePage(
            items=tuple(_to_template(model) for model in rows.scalars()),
            total=int(total or 0),
        )


class SqlAlchemyCleaningChecklistCompletionRepository:
    """The table with no `tenant_id` and no loader-criteria net (design D6).

    Both methods start by resolving the parent task **within** `tenant_id`. That is not a
    convenience lookup: it is the isolation boundary, and skipping it would let a caller
    read or write another tenant's checklist with nothing to stop it.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_task(
        self, tenant_id: uuid.UUID, task_id: uuid.UUID
    ) -> Sequence[CleaningChecklistCompletion]:
        rows = await self._session.execute(
            select(CleaningChecklistCompletionModel)
            .join(
                CleaningTaskModel,
                CleaningTaskModel.id == CleaningChecklistCompletionModel.cleaning_task_id,
            )
            .where(
                CleaningTaskModel.tenant_id == tenant_id,
                CleaningChecklistCompletionModel.cleaning_task_id == task_id,
            )
            .order_by(CleaningChecklistCompletionModel.item_id)
        )
        return [_to_completion(model) for model in rows.scalars()]

    async def upsert(
        self, tenant_id: uuid.UUID, completion: CleaningChecklistCompletion
    ) -> None:
        """One task identifier — the entity's — resolved inside the tenant before writing.

        Raises `CleaningTaskNotFoundError` when the parent does not resolve, which is the
        same answer an unknown task gets (R7.3): from outside, "another tenant's task" and
        "no such task" must be one outcome.
        """
        owner = await self._session.scalar(
            select(CleaningTaskModel.id).where(
                CleaningTaskModel.tenant_id == tenant_id,
                CleaningTaskModel.id == completion.cleaning_task_id,
            )
        )
        if owner is None:
            raise CleaningTaskNotFoundError()

        # `ON CONFLICT DO UPDATE`, one statement, and **not** a read followed by an insert or
        # an update. The first version did exactly that check-then-act, and both the
        # architecture and the QA reviewer of `/sdd:review` reached the same conclusion: two
        # concurrent taps of the same item — a double tap on a slow connection, or a retry —
        # both read "no row" and both insert, and the loser violates
        # `uq_cleaning_checklist_completions_cleaning_task_id_item_id` with a bare
        # `IntegrityError`. That is not a `CleaningDomainError`, so `api/errors.py` never sees
        # it and R4.4's promised idempotent `204` becomes an unhandled 500.
        #
        # Catching `IntegrityError` and retrying would also work — it is what
        # `CleaningTaskRepository.add`/`save` do a few lines above — but here the window can be
        # closed outright instead of handled, and D2's own reasoning ("dejarlo solo en el `if`
        # es un check-then-insert que la primera concurrencia rompe") argues for removing it.
        # There it could not be removed: `add` inserts a whole aggregate with nothing to
        # update on conflict.
        #
        # `cleaning_task_id=owner` and not `completion.cleaning_task_id`: same value, but the
        # one that was proved to belong to the tenant.
        statement = (
            pg_insert(CleaningChecklistCompletionModel)
            .values(
                id=completion.id,
                cleaning_task_id=owner,
                item_id=completion.item_id,
                completed=completion.completed,
                completed_at=completion.completed_at,
                completed_by=completion.completed_by,
            )
            .on_conflict_do_update(
                constraint=CHECKLIST_COMPLETION_CONSTRAINT,
                set_={
                    "completed": completion.completed,
                    "completed_at": completion.completed_at,
                    "completed_by": completion.completed_by,
                },
            )
        )
        await self._session.execute(statement)
        await self._session.flush()


class SqlAlchemyBlockingIncidentQuery:
    """R5.2 — is a `CRITICAL` incident of this property still open?

    A read of another module's table from this one's adapter, deliberately: the port is a
    boolean (`cleaning/domain/ports.py`), so nothing of the `Incident` aggregate crosses into
    `cleaning`. `maintenance` owns writes and will own its own repository; when it has one,
    this can be reimplemented on top of it without touching a use case.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_unresolved_critical(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> bool:
        found = await self._session.scalar(
            select(IncidentModel.id)
            .where(
                IncidentModel.tenant_id == tenant_id,
                IncidentModel.property_id == property_id,
                IncidentModel.severity == IncidentSeverity.CRITICAL,
                IncidentModel.status.notin_(
                    [IncidentStatus.RESOLVED, IncidentStatus.CANCELLED]
                ),
            )
            .limit(1)
        )
        return found is not None


def _require_same_tenant(entity_tenant_id: uuid.UUID, tenant_id: uuid.UUID, entity: str) -> None:
    if entity_tenant_id != tenant_id:
        raise CrossTenantWriteError(
            entity=entity, entity_tenant_id=entity_tenant_id, acting_tenant_id=tenant_id
        )


def _task_conditions(tenant_id: uuid.UUID, filters: CleaningTaskFilters) -> list:
    conditions = [CleaningTaskModel.tenant_id == tenant_id]
    if filters.property_id is not None:
        conditions.append(CleaningTaskModel.property_id == filters.property_id)
    if filters.status is not None:
        conditions.append(CleaningTaskModel.status == filters.status)
    if filters.assigned_cleaner_id is not None:
        conditions.append(CleaningTaskModel.assigned_cleaner_id == filters.assigned_cleaner_id)
    return conditions


def _ordered_tasks(statement: Select) -> Select:
    """Newest first, `id` as the tie-break.

    Without the second key two tasks created in the same transaction — the rejected one and
    its replacement (design D3) share a timestamp — could swap places between pages, so a
    client paging through would see one twice and miss the other.
    """
    return statement.order_by(CleaningTaskModel.created_at.desc(), CleaningTaskModel.id)


def _to_task(model: CleaningTaskModel) -> CleaningTask:
    return CleaningTask(
        id=model.id,
        tenant_id=model.tenant_id,
        property_id=model.property_id,
        checklist_template_id=model.checklist_template_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        reservation_id=model.reservation_id,
        assigned_cleaner_id=model.assigned_cleaner_id,
        status=model.status,
        scheduled_start=model.scheduled_start,
        scheduled_end=model.scheduled_end,
        accepted_at=model.accepted_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
        notes=model.notes,
        validation_status=model.validation_status,
        validated_by_user_id=model.validated_by_user_id,
        validated_at=model.validated_at,
    )


def _to_template(model: CleaningChecklistTemplateModel) -> CleaningChecklistTemplate:
    return CleaningChecklistTemplate(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        items=model.items,
        required_photos=model.required_photos,
        created_at=model.created_at,
        updated_at=model.updated_at,
        property_id=model.property_id,
        active=model.active,
    )


def _to_completion(model: CleaningChecklistCompletionModel) -> CleaningChecklistCompletion:
    return CleaningChecklistCompletion(
        id=model.id,
        cleaning_task_id=model.cleaning_task_id,
        item_id=model.item_id,
        completed=model.completed,
        completed_at=model.completed_at,
        completed_by=model.completed_by,
        notes=model.notes,
    )
