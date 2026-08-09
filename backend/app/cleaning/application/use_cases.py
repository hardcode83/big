"""Cleaning use cases — orchestration only; the rules live in `domain/`.

One use case is one transaction: each `execute` ends with `uow.commit()`, the same boundary
`reservations` established (its design D4) and the one `AdvancePropertyStatesUseCase` owns
for the scheduler. The provisioning use case is the deliberate exception — it is called
*inside* somebody else's transaction and says so.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.audit.domain import actions as audit_actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.ports import UserRepository
from app.auth.domain.repositories import UserFilters
from app.cleaning.domain.assignment import resolve_auto_assignee
from app.cleaning.domain.entities import (
    CleaningChecklistCompletion,
    CleaningChecklistTemplate,
    CleaningPhoto,
    CleaningTask,
)
from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus
from app.cleaning.domain.notifications import (
    assignment_notification,
    no_cleaner_available_notification,
)
from app.cleaning.domain.exceptions import (
    AmbiguousChecklistTemplateError,
    ChecklistItemNotFoundError,
    ChecklistTemplateNotFoundError,
    CleaningTaskNotFoundError,
    CleaningValidationError,
    DuplicateLiveCleaningTaskError,
    InvalidCleaningTransitionError,
    PhotoStorageUnavailableError,
    PhotoTooLargeError,
    PhotoTypeNotFoundError,
    PropertyNotFoundError,
    PropertyStateBlocksCleaningError,
    ReservationNotFoundError,
    UnsupportedPhotoFormatError,
)
from app.cleaning.domain.ports import BlockingIncidentQuery
from app.cleaning.domain.repositories import (
    CleaningChecklistCompletionRepository,
    CleaningChecklistTemplateRepository,
    CleaningPhotoRepository,
    CleaningTaskFilters,
    CleaningTaskRepository,
    Page,
    TemplatePage,
    UnscopedCleaningPhotoLocationQuery,
)
from app.cleaning.domain.templates import resolve_template
from app.cleaning.domain.value_objects import (
    CleaningCompletionEvidence,
    parse_template_content,
)
from app.core.unit_of_work import UnitOfWork
from app.integrations.domain.storage import (
    MAGIC_BYTES_LENGTH,
    FileStorageFactory,
    FileStoragePort,
    InvalidSignatureError,
    StorageWriteError,
    content_type_for_extension,
    detect_image_type,
    storage_key_for_photo,
    verify_signed_key,
)
from app.notifications.domain.repositories import NotificationLogRepository
from app.properties.domain.clock_triggers import candidate_window
from app.properties.domain.entities import Property
from app.properties.domain.enums import StateTransitionTriggeredBy
from app.properties.domain.exceptions import (
    IncompatibleTransitionContextError,
    InvalidStateTransitionError,
    NoOperationalStateChangeError,
)
from app.properties.domain.repositories import (
    PropertyRepository,
    PropertyStateTransitionRepository,
)
from app.properties.domain.state_machine import PropertyStateMachine
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.domain.value_objects import (
    PropertyStateChangeRequest,
    PropertyTransitionContext,
    TransitionActor,
    TransitionEvidenceIds,
)
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationStatus
from app.reservations.domain.repositories import ReservationRepository
from app.tenants.domain.repositories import TenantConfigRepository
from app.timeline.domain.repositories import TimelineEventRepository

logger = logging.getLogger(__name__)

# How many active cleaners are fetched when deciding whether there is exactly one. Two is
# enough to answer "exactly one?" — a third would not change the verdict — but the page's
# `total` is what the decision reads, so truncation cannot make "many" look like "one".
_CLEANER_PROBE_PAGE = 2

# How many managers get the "nobody to assign" alert. Same bound and same reasoning as
# `_MAX_RECIPIENTS` in `app/notifications/application/use_cases.py`: a tenant's roster of
# managers is small, and an unbounded fan-out would be a write amplification per checkout.
_MAX_MANAGER_RECIPIENTS = 20


@dataclass(frozen=True)
class CreateChecklistTemplateCommand:
    """What the caller may decide. No `tenant_id`: that comes from the verified token."""

    name: str
    items: list
    required_photos: list
    property_id: uuid.UUID | None = None


class CreateChecklistTemplateUseCase:
    def __init__(
        self,
        *,
        templates: CleaningChecklistTemplateRepository,
        properties: PropertyRepository,
        uow: UnitOfWork,
    ) -> None:
        self._templates = templates
        self._properties = properties
        self._uow = uow

    async def execute(
        self, *, tenant_id: uuid.UUID, command: CreateChecklistTemplateCommand, now: datetime
    ) -> CleaningChecklistTemplate:
        # Validates before anything is written (R1.2): `parse_template_content` raises
        # `CleaningValidationError`, which `api/errors.py` maps to 422.
        spec = parse_template_content(command.items, command.required_photos)

        if command.property_id is not None:
            # R7.3: a property of another tenant must be indistinguishable from one that
            # does not exist, so this resolves inside the token's tenant and 404s either way.
            # Without it, `cleaning_checklist_templates.property_id` is a plain FK and the
            # database would happily accept a neighbour's id.
            if await self._properties.get(tenant_id, command.property_id) is None:
                raise PropertyNotFoundError()

        template = CleaningChecklistTemplate(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=command.name,
            # The parsed spec, not `command.items`: the column can then only ever hold the
            # three keys the parser validated. See `ChecklistTemplateSpec.items_as_json`.
            items=spec.items_as_json(),
            required_photos=spec.required_photos_as_json(),
            created_at=now,
            updated_at=now,
            property_id=command.property_id,
            active=True,
        )
        await self._templates.add(tenant_id, template)
        await self._uow.commit()
        return template


class ListChecklistTemplatesUseCase:
    def __init__(self, *, templates: CleaningChecklistTemplateRepository) -> None:
        self._templates = templates

    async def execute(
        self, *, tenant_id: uuid.UUID, page: int, per_page: int
    ) -> TemplatePage:
        return await self._templates.list(tenant_id, page=page, per_page=per_page)


class ProvisionCleaningTaskUseCase:
    """Creates the cleaning task a closed checkout implies (R2, R3.1, R3.2, design D1).

    Implements `CleaningProvisioningPort`, so it is called **inside**
    `AdvancePropertyStatesUseCase`'s transaction and **never commits**: that is what makes
    R2.3 hold — a property in `AWAITING_CLEANING` without its task is the terminal state
    this whole change exists to remove, and two transactions can leave one behind.

    It returns `None` for every ordinary reason not to create one and lets the caller count
    it (R2.4). A tenant that never configured a checklist template must not abort the run
    for its neighbours, which is the same treatment the caller already gives a reservation
    whose local time cannot be materialised.
    """

    def __init__(
        self,
        *,
        tasks: CleaningTaskRepository,
        templates: CleaningChecklistTemplateRepository,
        configs: TenantConfigRepository,
        users: UserRepository,
        transitions: PropertyStateTransitionRepository,
        timeline: TimelineEventRepository,
        properties: PropertyRepository,
        notifications: NotificationLogRepository,
    ) -> None:
        self._tasks = tasks
        self._templates = templates
        self._configs = configs
        self._users = users
        self._transitions = transitions
        self._timeline = timeline
        self._properties = properties
        self._notifications = notifications

    async def provision_for_checkout(
        self,
        *,
        tenant_id: uuid.UUID,
        property: Property,
        reservation: Reservation,
        known_reservations: Sequence[Reservation],
        now: datetime,
    ) -> CleaningTask | None:
        config = await self._configs.get_or_create(tenant_id, now)
        if not config.auto_create_cleaning_task:
            return None
        if not reservation.cleaning_required:
            return None

        # R2.5's fast path. The authority is still `uq_cleaning_tasks_live_reservation`
        # (design D2), which `add` translates below — this only turns the ordinary case into
        # a `None` the report can count instead of an exception it would have to catch.
        if await self._tasks.list_live_for_reservation(tenant_id, reservation.id):
            return None

        try:
            template = resolve_template(
                await self._templates.list_candidates_for_property(tenant_id, property.id),
                property.id,
            )
        except (ChecklistTemplateNotFoundError, AmbiguousChecklistTemplateError) as exc:
            # R2.4: not an error of the run. A tenant with no template — or with two active
            # ones competing — needs a person, not a failed job, and the log is what tells
            # them which property.
            logger.warning(
                "cleaning.provisioning_without_template",
                extra={
                    "tenant_id": str(tenant_id),
                    "property_id": str(property.id),
                    "reason": type(exc).__name__,
                },
            )
            return None

        # The window is anchored to the stay, not to the moment the job noticed (R2.6).
        scheduled_start = _effective_checkout(property, reservation, now)
        task = CleaningTask(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=property.id,
            checklist_template_id=template.id,
            created_at=now,
            updated_at=now,
            reservation_id=reservation.id,
            scheduled_start=scheduled_start,
            scheduled_end=_next_checkin(
                property, known_reservations, reservation, scheduled_start or now
            ),
        )
        try:
            await self._tasks.add(tenant_id, task)
        except DuplicateLiveCleaningTaskError:
            # Lost the race against a concurrent run; the other one created it (R2.5).
            return None

        await self._auto_assign(
            tenant_id=tenant_id, property=property, task=task, reservation=reservation, now=now
        )
        return task

    async def _auto_assign(
        self,
        *,
        tenant_id: uuid.UUID,
        property: Property,
        task: CleaningTask,
        reservation: Reservation,
        now: datetime,
    ) -> None:
        """Fetches the inputs of PRD §11's rule and applies it (R3.1, R3.2).

        The **rule** is `resolve_auto_assignee` in `cleaning/domain/assignment.py`; what is
        left here is orchestration. It used to be an `if` in the middle of these two queries,
        and the architecture reviewer of section 4 was right that
        `steering/backend-architecture.md` §Don'ts puts a rule in `domain/`.
        """
        page = await self._users.list(
            tenant_id,
            UserFilters(role=UserRole.CLEANER, status=UserStatus.ACTIVE),
            page=1,
            per_page=_CLEANER_PROBE_PAGE,
        )
        by_id = {user.id: user for user in page.items}
        assignee = resolve_auto_assignee(
            active_cleaner_ids=list(by_id),
            total_active=page.total,
            rejecter_ids=set(
                await self._tasks.list_rejecters_for_reservation(tenant_id, reservation.id)
            ),
        )
        if assignee is None:
            # R6.3, PRD §11: "si no hay limpiadora disponible: alertar a manager
            # inmediatamente". Also covers "more than one", where the manager has to choose.
            await self._notify_manager_unassigned(
                tenant_id=tenant_id, task=task, property=property, now=now
            )
            return

        task.assign(assignee, now)
        await self._tasks.save(tenant_id, task)
        await self._fire_cleaner_assigned(
            tenant_id=tenant_id, property=property, task=task, now=now
        )
        config = await self._configs.get_or_create(tenant_id, now)
        await self._notifications.add(
            tenant_id,
            assignment_notification(
                tenant_id=tenant_id,
                task_id=task.id,
                property_id=property.id,
                cleaner_id=assignee,
                recipient_contact=by_id[assignee].email,
                sla_minutes=config.sla_medium_minutes,
                now=now,
            ),
        )

    async def _notify_manager_unassigned(
        self, *, tenant_id: uuid.UUID, task: CleaningTask, property: Property, now: datetime
    ) -> None:
        """One row per active manager, falling back to the owner — the arrangement
        `EscalateBreachedSlasUseCase` already established for "who holds this role"."""
        for role in (UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER):
            page = await self._users.list(
                tenant_id,
                UserFilters(role=role, status=UserStatus.ACTIVE),
                page=1,
                per_page=_MAX_MANAGER_RECIPIENTS,
            )
            if not page.items:
                continue
            for manager in page.items:
                await self._notifications.add(
                    tenant_id,
                    no_cleaner_available_notification(
                        tenant_id=tenant_id,
                        task_id=task.id,
                        property_id=property.id,
                        manager_id=manager.id,
                        recipient_contact=manager.email,
                        now=now,
                    ),
                )
            return

    async def _fire_cleaner_assigned(
        self, *, tenant_id: uuid.UUID, property: Property, task: CleaningTask, now: datetime
    ) -> None:
        """`AWAITING_CLEANING` → `CLEANING_SCHEDULED`, through the machine and only there.

        The second transition of the same run, on a property the caller has already advanced
        in memory. The task goes into the context **already `ASSIGNED`**, because
        `_validate_trigger_preconditions` reads the status off the entity it is handed
        (`app/properties/domain/state_machine.py:228-238`).

        Actor `SYSTEM`: nobody asked for this, the clock did. That is also what exempts it
        from `AuditLog` under the named exception of rule 9 in `steering/security.md`.
        """
        request = PropertyStateChangeRequest(
            property=property,
            trigger=PropertyStateTrigger.CLEANER_ASSIGNED,
            context=PropertyTransitionContext(cleaning_tasks=(task,)),
            actor=TransitionActor(triggered_by=StateTransitionTriggeredBy.SYSTEM),
            reference_instant=now,
            evidence_ids=TransitionEvidenceIds(
                transition_id=uuid.uuid4(), timeline_event_id=uuid.uuid4()
            ),
            source_entity_id=task.id,
            correlation_id=str(uuid.uuid4()),
        )
        try:
            result = PropertyStateMachine.evaluate(request)
        except (NoOperationalStateChangeError, IncompatibleTransitionContextError):
            # The task exists and is assigned; only the property's state did not move. Not a
            # reason to undo the assignment, and not a reason to fail the tenant.
            logger.warning(
                "cleaning.assignment_without_transition",
                extra={
                    "tenant_id": str(tenant_id),
                    "property_id": str(property.id),
                    "cleaning_task_id": str(task.id),
                },
            )
            return

        await self._transitions.add(tenant_id, result.transition)
        await self._timeline.add(tenant_id, result.timeline_event)
        property.current_operational_state = result.transition.to_state
        await self._properties.save(tenant_id, property)


class _AuditWriter:
    """Builds and appends an audit entry, so no use case constructs one by hand.

    Same shape as `app/auth/application/user_admin.py:58`. Rule 9 of
    `steering/security.md` exempts a property state transition from `AuditLog` **only** with
    actor `SYSTEM`; every operation below is done by a person, so every one of them writes.
    """

    def __init__(self, audit: AuditLogRepository) -> None:
        self._audit = audit

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        task_id: uuid.UUID,
        actor: "CleaningActor",
        changes: ChangeSet,
        now: datetime,
    ) -> None:
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=action,
                entity_type=audit_actions.ENTITY_CLEANING_TASK,
                entity_id=task_id,
                actor_user_id=actor.user_id,
                actor_ip=actor.ip,
                changes=changes,
                now=now,
            ),
        )

    async def record_photo_upload(
        self,
        *,
        tenant_id: uuid.UUID,
        photo: CleaningPhoto,
        actor: "CleaningActor",
        now: datetime,
    ) -> None:
        """R2.7 — the upload's own row, against the photo and not against the task.

        A second method rather than an `entity_type=` parameter on `record` above: the two
        differ in the entity they point at, in the action vocabulary they may use and in the
        fields `ChangeSet` will accept, so one signature covering both would take three
        arguments whose only legal combinations are these two.

        **`storage_key` is not in the diff, and its absence is the design.** R3.2 keeps the
        internal key out of every API response, and `audit_logs.changes` is a rule-11 sink —
        the one column whose contract is that nothing arrives through it unannounced. What the
        row records is who uploaded which kind of evidence against which cleaning.
        """
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=audit_actions.CLEANING_PHOTO_UPLOADED,
                entity_type=audit_actions.ENTITY_CLEANING_PHOTO,
                entity_id=photo.id,
                actor_user_id=actor.user_id,
                # Rule 9: `actor_ip` is one of the two things `audit_logs` records that
                # `property_state_transitions` cannot, and an upload is a person's action.
                actor_ip=actor.ip,
                changes=ChangeSet(audit_actions.ENTITY_CLEANING_PHOTO)
                .diff("photo_type", None, photo.photo_type)
                .diff("cleaning_task_id", None, photo.cleaning_task_id)
                .diff("uploaded_by", None, photo.uploaded_by),
                now=now,
            ),
        )


@dataclass(frozen=True)
class CleaningActor:
    """Who is acting, and from where — the two things `audit_logs` records that
    `property_state_transitions` cannot (rule 9)."""

    user_id: uuid.UUID
    role: UserRole
    ip: str | None = None

    @property
    def restrict_to_cleaner_id(self) -> uuid.UUID | None:
        """R7.2 — derived from the role **here**, never accepted from the request.

        A `CLEANER` sees and acts on their own tasks only; every other role that holds a
        cleaning permission sees the tenant's. Returning the id rather than a boolean means
        the caller cannot forget to apply it: it goes straight into the repository filter.
        """
        return self.user_id if self.role is UserRole.CLEANER else None


class _TaskTransitionMixin:
    """The shared middle of every task operation that moves the property's state.

    Load the task within the tenant (and within the acting cleaner's own rows), mutate the
    entity, put it in the machine's context **already mutated**, persist transition +
    timeline + property. Written once because `steering/architecture.md` makes
    `PropertyStateMachine` the only place a transition happens, and six copies of this would
    be six chances to bypass it.
    """

    _tasks: CleaningTaskRepository
    _properties: PropertyRepository
    _transitions: PropertyStateTransitionRepository
    _timeline: TimelineEventRepository
    _reservations: ReservationRepository

    async def _load_task(
        self, tenant_id: uuid.UUID, task_id: uuid.UUID, actor: CleaningActor
    ) -> CleaningTask:
        task = await self._tasks.get(tenant_id, task_id)
        if task is None:
            raise CleaningTaskNotFoundError()
        restrict = actor.restrict_to_cleaner_id
        if restrict is not None and task.assigned_cleaner_id != restrict:
            # R7.2/R7.3: for this cleaner the task does not exist. Same error, same message.
            raise CleaningTaskNotFoundError()
        return task

    async def _transition(
        self,
        *,
        tenant_id: uuid.UUID,
        task: CleaningTask,
        trigger: PropertyStateTrigger,
        actor: CleaningActor,
        now: datetime,
        with_reservations: bool = False,
    ) -> None:
        property = await self._properties.get(tenant_id, task.property_id)
        if property is None:
            raise PropertyNotFoundError()

        reservations: tuple[Reservation, ...] = ()
        if with_reservations:
            # `after_cleaning_completion` decides the destination from the property's stays
            # (`state_resolution.py:126-139`), so the context has to carry them.
            date_from, date_to = candidate_window(now)
            reservations = tuple(
                await self._reservations.list_for_properties(
                    tenant_id, [property.id], date_from, date_to
                )
            )

        request = PropertyStateChangeRequest(
            property=property,
            trigger=trigger,
            context=PropertyTransitionContext(
                cleaning_tasks=(task,), reservations=reservations
            ),
            actor=TransitionActor(
                triggered_by=StateTransitionTriggeredBy.USER, user_id=actor.user_id
            ),
            reference_instant=now,
            evidence_ids=TransitionEvidenceIds(
                transition_id=uuid.uuid4(), timeline_event_id=uuid.uuid4()
            ),
            source_entity_id=task.id,
            correlation_id=str(uuid.uuid4()),
        )
        try:
            result = PropertyStateMachine.evaluate(request)
        except (IncompatibleTransitionContextError, InvalidStateTransitionError) as exc:
            # These come from the **properties** domain, which has no `api/` layer and no
            # error handler, so letting one escape a cleaning endpoint is an unhandled 500.
            # Translating here keeps D11's single mapping honest — the design already promised
            # a 409 for the realistic case (a guest already checked in when the cleaning is
            # closed) and could not deliver it while the error was of the wrong hierarchy.
            #
            # `InvalidTransitionInputError` and `TransitionEvidenceError` are deliberately NOT
            # caught: they mean this use case built the request wrong, which is our bug and
            # must surface as a 500, exactly as `AdvancePropertyStatesUseCase` decided (R3.3).
            raise PropertyStateBlocksCleaningError(str(exc)) from exc
        await self._transitions.add(tenant_id, result.transition)
        await self._timeline.add(tenant_id, result.timeline_event)
        property.current_operational_state = result.transition.to_state
        await self._properties.save(tenant_id, property)


class _TaskLifecycleBase(_TaskTransitionMixin):
    """Constructor shared by the six operations of the task lifecycle."""

    def __init__(
        self,
        *,
        tasks: CleaningTaskRepository,
        properties: PropertyRepository,
        transitions: PropertyStateTransitionRepository,
        timeline: TimelineEventRepository,
        reservations: ReservationRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._tasks = tasks
        self._properties = properties
        self._transitions = transitions
        self._timeline = timeline
        self._reservations = reservations
        self._audit = _AuditWriter(audit)
        self._uow = uow


class AcceptCleaningTaskUseCase(_TaskLifecycleBase):
    """R3.4 — the assigned cleaner takes the task."""

    async def execute(
        self, *, tenant_id: uuid.UUID, task_id: uuid.UUID, actor: CleaningActor, now: datetime
    ) -> CleaningTask:
        task = await self._load_task(tenant_id, task_id, actor)
        previous = task.status
        task.accept(actor.user_id, now)
        await self._tasks.save(tenant_id, task)
        # No property transition: `CLEANING_SCHEDULED` covers both ASSIGNED and ACCEPTED, and
        # `PropertyStateMachine._POLICY` declares no trigger for acceptance. The task's own
        # status is the record, and the audit row is what says who answered.
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.CLEANING_TASK_ACCEPTED,
            task_id=task.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_CLEANING_TASK)
            .diff("status", previous.value, task.status.value)
            .diff("accepted_at", None, now.isoformat()),
            now=now,
        )
        await self._uow.commit()
        return task


class RejectCleaningTaskUseCase(_TaskLifecycleBase):
    """R3.5 and design D3 — terminal, plus a replacement so the property is never left with
    no live task."""

    async def execute(
        self, *, tenant_id: uuid.UUID, task_id: uuid.UUID, actor: CleaningActor, now: datetime
    ) -> CleaningTask:
        task = await self._load_task(tenant_id, task_id, actor)
        previous = task.status
        task.reject(actor.user_id, now)
        await self._tasks.save(tenant_id, task)
        await self._transition(
            tenant_id=tenant_id,
            task=task,
            trigger=PropertyStateTrigger.CLEANER_REJECTED,
            actor=actor,
            now=now,
        )

        # Design D3: the rejected row keeps its `assigned_cleaner_id` as the record of who
        # declined; the replacement is what frees the slot. Unassigned on purpose — automatic
        # reassignment is out of scope, and `resolve_auto_assignee` would hand it straight back.
        replacement = CleaningTask(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=task.property_id,
            checklist_template_id=task.checklist_template_id,
            created_at=now,
            updated_at=now,
            reservation_id=task.reservation_id,
            scheduled_start=task.scheduled_start,
            scheduled_end=task.scheduled_end,
        )
        await self._tasks.add(tenant_id, replacement)

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.CLEANING_TASK_REJECTED,
            task_id=task.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_CLEANING_TASK).diff(
                "status", previous.value, task.status.value
            ),
            now=now,
        )
        await self._uow.commit()
        return replacement


class StartCleaningTaskUseCase(_TaskLifecycleBase):
    """R3.6 — the cleaner begins, and the property enters `CLEANING_IN_PROGRESS`."""

    async def execute(
        self, *, tenant_id: uuid.UUID, task_id: uuid.UUID, actor: CleaningActor, now: datetime
    ) -> CleaningTask:
        task = await self._load_task(tenant_id, task_id, actor)
        previous = task.status
        task.start(actor.user_id, now)
        await self._tasks.save(tenant_id, task)
        await self._transition(
            tenant_id=tenant_id,
            task=task,
            trigger=PropertyStateTrigger.CLEANING_STARTED,
            actor=actor,
            now=now,
        )
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.CLEANING_TASK_STARTED,
            task_id=task.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_CLEANING_TASK)
            .diff("status", previous.value, task.status.value)
            .diff("started_at", None, now.isoformat()),
            now=now,
        )
        await self._uow.commit()
        return task


class AssignCleaningTaskUseCase(_TaskLifecycleBase):
    """R3.3 — the manager hands a task to a cleaner (or moves it to another one)."""

    def __init__(
        self,
        *,
        users: UserRepository,
        notifications: NotificationLogRepository,
        configs: TenantConfigRepository,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._users = users
        self._notifications = notifications
        self._configs = configs

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        cleaner_id: uuid.UUID,
        actor: CleaningActor,
        now: datetime,
    ) -> CleaningTask:
        task = await self._load_task(tenant_id, task_id, actor)

        # R3.3: resolved **inside the tenant**, so a neighbour's user id is a 422 and not a
        # row pointing across tenants — `cleaning_tasks.assigned_cleaner_id` is a plain FK and
        # the database would accept it (the derived obligation of design D6).
        candidate = await self._users.get(tenant_id, cleaner_id)
        if (
            candidate is None
            or candidate.role is not UserRole.CLEANER
            # `ACTIVE` too, which R3.3 does not name but the automatic path already required
            # (`resolve_auto_assignee` reads a roster filtered by status). The security
            # reviewer of `/sdd:review` raised the asymmetry: without this a manager can hand
            # a task to a deactivated person, which writes a notification to an address the
            # tenant has stopped using and leaves work nobody will do. Stricter than R3.3, not
            # in conflict with it.
            or candidate.status is not UserStatus.ACTIVE
        ):
            raise CleaningValidationError(
                "assigned_cleaner_id must be an active CLEANER of this tenant"
            )

        previous_status = task.status
        previous_cleaner = task.assigned_cleaner_id
        task.assign(cleaner_id, now)
        await self._tasks.save(tenant_id, task)

        if previous_status is CleaningTaskStatus.CREATED:
            # Only the first assignment moves the property; re-pointing an already `ASSIGNED`
            # task leaves it in `CLEANING_SCHEDULED`, and the machine has no trigger for that.
            await self._transition(
                tenant_id=tenant_id,
                task=task,
                trigger=PropertyStateTrigger.CLEANER_ASSIGNED,
                actor=actor,
                now=now,
            )

        # R6.1 — the same row the automatic path writes, with the same SLA deadline: a manual
        # assignment that nobody answers has to escalate exactly like an automatic one.
        config = await self._configs.get_or_create(tenant_id, now)
        await self._notifications.add(
            tenant_id,
            assignment_notification(
                tenant_id=tenant_id,
                task_id=task.id,
                property_id=task.property_id,
                cleaner_id=cleaner_id,
                recipient_contact=candidate.email,
                sla_minutes=config.sla_medium_minutes,
                now=now,
            ),
        )

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.CLEANING_TASK_ASSIGNED,
            task_id=task.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_CLEANING_TASK)
            .diff("status", previous_status.value, task.status.value)
            .diff(
                "assigned_cleaner_id",
                str(previous_cleaner) if previous_cleaner else None,
                str(cleaner_id),
            ),
            now=now,
        )
        await self._uow.commit()
        return task


class CompleteCleaningTaskUseCase(_TaskLifecycleBase):
    """R5.1-R5.4, and R4 of `cleaning-photos-storage` — the close.

    **Gathers the evidence; does not judge it.** All three clauses of PRD §11 are applied by
    `CleaningTask.complete()` and nowhere else (R4.3, design D4/D8), so what this class owns is
    four reads — the template, the checklist completions, the uploaded photo types and the
    blocking-incident flag — and the assembly of one `CleaningCompletionEvidence` from them.
    Moving any of the four comparisons up here would split an invariant `cleaning` spent a
    whole change concentrating in one method.
    """

    def __init__(
        self,
        *,
        completions: CleaningChecklistCompletionRepository,
        templates: CleaningChecklistTemplateRepository,
        photos: CleaningPhotoRepository,
        incidents: BlockingIncidentQuery,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._completions = completions
        self._templates = templates
        self._photos = photos
        self._incidents = incidents

    async def execute(
        self, *, tenant_id: uuid.UUID, task_id: uuid.UUID, actor: CleaningActor, now: datetime
    ) -> CleaningTask:
        task = await self._load_task(tenant_id, task_id, actor)
        template = await self._templates.get(tenant_id, task.checklist_template_id)
        if template is None:
            raise ChecklistTemplateNotFoundError(
                "The task's checklist template no longer exists"
            )
        spec = parse_template_content(
            template.items, template.required_photos, template_id=template.id
        )
        completions = await self._completions.list_for_task(tenant_id, task.id)

        evidence = CleaningCompletionEvidence(
            required_item_ids=spec.required_item_ids(),
            completed_item_ids=frozenset(
                completion.item_id for completion in completions if completion.completed
            ),
            # PRD §11's third clause (R4.1). `required_photo_types()` filters on
            # `required: true` and `photo_types()` — the one the upload path uses — does not;
            # reading the wrong one here would make every declared type mandatory and break
            # R4.5, which is why the two accessors are named for the questions they answer.
            required_photo_types=spec.required_photo_types(),
            # Distinct types, straight from the repository. Scoped by `tenant_id` like every
            # other read here, and its contract answers with an empty set for a task that is
            # not this tenant's — which blocks a close rather than granting one (design D12).
            uploaded_photo_types=await self._photos.uploaded_photo_types(tenant_id, task.id),
            has_unresolved_critical_incident=await self._incidents.has_unresolved_critical(
                tenant_id, task.property_id
            ),
        )

        previous = task.status
        # The rule lives in the entity (design D4); this only gathers what it needs.
        task.complete(actor.user_id, evidence, now)
        await self._tasks.save(tenant_id, task)
        await self._transition(
            tenant_id=tenant_id,
            task=task,
            trigger=PropertyStateTrigger.CLEANING_COMPLETED,
            actor=actor,
            now=now,
            # `after_cleaning_completion` decides between AWAITING_CHECKIN,
            # READY_FOR_NEXT_GUEST and VACANT_READY from the property's stays (R5.4).
            with_reservations=True,
        )
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.CLEANING_TASK_COMPLETED,
            task_id=task.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_CLEANING_TASK)
            .diff("status", previous.value, task.status.value)
            .diff("completed_at", None, now.isoformat())
            .diff("validation_status", None, task.validation_status.value),
            now=now,
        )
        await self._uow.commit()
        return task


class ValidateCleaningTaskUseCase(_TaskLifecycleBase):
    """R5.5 — the manager's verdict on a finished cleaning."""

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        status: CleaningValidationStatus,
        actor: CleaningActor,
        now: datetime,
    ) -> CleaningTask:
        task = await self._load_task(tenant_id, task_id, actor)
        previous = task.validation_status
        task.record_manual_validation(
            validator_user_id=actor.user_id, status=status, now=now
        )
        await self._tasks.save(tenant_id, task)
        # No property transition: validating does not move the property, which already left
        # `CLEANING_IN_PROGRESS` when the task was completed.
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.CLEANING_TASK_VALIDATED,
            task_id=task.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_CLEANING_TASK)
            .diff("validation_status", previous.value, status.value)
            .diff("validated_by_user_id", None, str(actor.user_id))
            .diff("validated_at", None, now.isoformat()),
            now=now,
        )
        await self._uow.commit()
        return task


@dataclass(frozen=True)
class CreateCleaningTaskCommand:
    """No `tenant_id`: it comes from the verified token."""

    property_id: uuid.UUID
    reservation_id: uuid.UUID | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None


class CreateCleaningTaskUseCase(_TaskLifecycleBase):
    """`POST /cleaning-tasks` — the manager creating a cleaning by hand (PRD §23).

    **Resolves every referenced id inside the tenant before building the task.** That is the
    derived obligation of design D6, and it is not defence in depth: `session.add` emits no
    statement the global listener can rewrite (`app/core/db.py:99-101`), so these three
    lookups are the only thing standing between a client-supplied id and a row that anchors
    every downstream `JOIN`.
    """

    def __init__(
        self, *, templates: CleaningChecklistTemplateRepository, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self._templates = templates

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        command: CreateCleaningTaskCommand,
        actor: CleaningActor,
        now: datetime,
    ) -> CleaningTask:
        property = await self._properties.get(tenant_id, command.property_id)
        if property is None:
            raise PropertyNotFoundError()

        reservation_id: uuid.UUID | None = None
        if command.reservation_id is not None:
            reservation = await self._reservations.get(tenant_id, command.reservation_id)
            if reservation is None:
                # R7.3: a reservation of another tenant is indistinguishable from one that
                # does not exist, and the message is a constant like every other 404 here.
                raise ReservationNotFoundError()
            if reservation.property_id != property.id:
                raise CleaningValidationError(
                    "The reservation does not belong to that property"
                )
            reservation_id = reservation.id

        template = resolve_template(
            await self._templates.list_candidates_for_property(tenant_id, property.id),
            property.id,
        )

        task = CleaningTask(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=property.id,
            checklist_template_id=template.id,
            created_at=now,
            updated_at=now,
            reservation_id=reservation_id,
            scheduled_start=command.scheduled_start,
            scheduled_end=command.scheduled_end,
        )
        await self._tasks.add(tenant_id, task)
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.CLEANING_TASK_CREATED,
            task_id=task.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_CLEANING_TASK).diff(
                "status", None, task.status.value
            ),
            now=now,
        )
        await self._uow.commit()
        return task


class GetCleaningTaskUseCase:
    def __init__(self, *, tasks: CleaningTaskRepository) -> None:
        self._tasks = tasks

    async def execute(
        self, *, tenant_id: uuid.UUID, task_id: uuid.UUID, actor: CleaningActor
    ) -> CleaningTask:
        task = await self._tasks.get(tenant_id, task_id)
        if task is None:
            raise CleaningTaskNotFoundError()
        restrict = actor.restrict_to_cleaner_id
        if restrict is not None and task.assigned_cleaner_id != restrict:
            raise CleaningTaskNotFoundError()
        return task


class ListCleaningTasksUseCase:
    def __init__(self, *, tasks: CleaningTaskRepository) -> None:
        self._tasks = tasks

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor: CleaningActor,
        property_id: uuid.UUID | None,
        status: CleaningTaskStatus | None,
        page: int,
        per_page: int,
    ) -> Page:
        """R7.1, R7.2 — the cleaner's restriction is derived here, not accepted from the query.

        `CleaningTaskFilters.assigned_cleaner_id` is set from `actor.restrict_to_cleaner_id`
        and there is no request parameter that can reach it, so the row-level rule cannot be
        dropped by omitting a filter.
        """
        return await self._tasks.list(
            tenant_id,
            CleaningTaskFilters(
                property_id=property_id,
                status=status,
                assigned_cleaner_id=actor.restrict_to_cleaner_id,
            ),
            page=page,
            per_page=per_page,
        )


@dataclass(frozen=True)
class ChecklistItemView:
    """One row of `GET /cleaning-tasks/{id}/checklist` (R4.1)."""

    item_id: str
    label: str
    required: bool
    completed: bool
    completed_at: datetime | None
    completed_by: uuid.UUID | None


class GetChecklistUseCase:
    """R4.1 — the template's items with their completion state."""

    def __init__(
        self,
        *,
        tasks: CleaningTaskRepository,
        templates: CleaningChecklistTemplateRepository,
        completions: CleaningChecklistCompletionRepository,
    ) -> None:
        self._tasks = tasks
        self._templates = templates
        self._completions = completions

    async def execute(
        self, *, tenant_id: uuid.UUID, task_id: uuid.UUID, actor: CleaningActor
    ) -> list[ChecklistItemView]:
        task = await self._tasks.get(tenant_id, task_id)
        if task is None:
            raise CleaningTaskNotFoundError()
        restrict = actor.restrict_to_cleaner_id
        if restrict is not None and task.assigned_cleaner_id != restrict:
            raise CleaningTaskNotFoundError()

        template = await self._templates.get(tenant_id, task.checklist_template_id)
        if template is None:
            raise ChecklistTemplateNotFoundError(
                "The task's checklist template no longer exists"
            )
        spec = parse_template_content(
            template.items, template.required_photos, template_id=template.id
        )
        done = {
            completion.item_id: completion
            for completion in await self._completions.list_for_task(tenant_id, task.id)
        }
        return [
            ChecklistItemView(
                item_id=item.item_id,
                label=item.label,
                required=item.required,
                completed=bool(done.get(item.item_id) and done[item.item_id].completed),
                completed_at=done[item.item_id].completed_at if item.item_id in done else None,
                completed_by=done[item.item_id].completed_by if item.item_id in done else None,
            )
            # Driven by the **template**, not by the completions table: an item nobody has
            # touched still has to appear, and a stale completion for an item the template no
            # longer declares must not.
            for item in spec.items
        ]


class CompleteChecklistItemUseCase(_TaskLifecycleBase):
    """R4.2-R4.5 — ticking one item, idempotently."""

    def __init__(
        self,
        *,
        templates: CleaningChecklistTemplateRepository,
        completions: CleaningChecklistCompletionRepository,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._templates = templates
        self._completions = completions

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        item_id: str,
        actor: CleaningActor,
        now: datetime,
    ) -> None:
        task = await self._load_task(tenant_id, task_id, actor)
        if task.status is not CleaningTaskStatus.IN_PROGRESS:
            # R4.5. The checklist belongs to the execution of the cleaning, so it cannot be
            # filled before starting or after finishing.
            raise InvalidCleaningTransitionError(
                f"Cannot record checklist progress on a task in status {task.status.value}"
            )

        template = await self._templates.get(tenant_id, task.checklist_template_id)
        if template is None:
            raise ChecklistTemplateNotFoundError(
                "The task's checklist template no longer exists"
            )
        spec = parse_template_content(
            template.items, template.required_photos, template_id=template.id
        )
        if item_id not in spec.item_ids():
            raise ChecklistItemNotFoundError(f"Unknown checklist item {item_id!r}")

        # Idempotent by R4.4: the adapter updates in place when the row is already there, so a
        # double tap cannot violate `uq_cleaning_checklist_completions_cleaning_task_id_item_id`.
        await self._completions.upsert(
            tenant_id,
            CleaningChecklistCompletion(
                id=uuid.uuid4(),
                cleaning_task_id=task.id,
                item_id=item_id,
                completed=True,
                completed_at=now,
                completed_by=actor.user_id,
            ),
        )
        # No audit row and no property transition: rule 9's enumeration does not cover
        # checklist progress, and the property does not move until the task is completed.
        await self._uow.commit()


#: How much of the upload is consumed per iteration. Big enough that a 10 MB photo is ~160
#: reads and small enough that the counter below reacts long before the ceiling: at most one
#: chunk beyond the limit is ever held, which is what makes "abort on exceeding" mean
#: something rather than "abort after buffering everything".
_UPLOAD_CHUNK_BYTES = 64 * 1024


class ChunkedUpload(Protocol):
    """What `UploadCleaningPhotoUseCase` needs from an uploaded file: bytes, on demand.

    Declared here rather than typed as Starlette's `UploadFile` because
    `tests/test_layering.py` forbids `application/` from importing `fastapi` — and the reason
    behind that rule bites here in particular: the use case must be able to consume a
    **stream** it did not buffer, so what it depends on is the read contract, not the web
    framework's object. `UploadFile` satisfies this Protocol as it is, and so does a test fake
    of four lines.
    """

    async def read(self, size: int = -1) -> bytes:
        """Up to `size` bytes, or `b""` once the file is exhausted."""
        ...


@dataclass(frozen=True)
class UploadedCleaningPhoto:
    """The stored photo and the signed URL that reads it back (design D7).

    Two fields rather than one entity because the URL is not a property of the row: it is
    minted per request, expires in 3600 s, and depends on the tenant's storage backend. The
    entity carries `storage_key`, which R3.2 forbids in any response — enumerating the
    response fields at the schema, never dumping this, is what keeps that true.
    """

    photo: CleaningPhoto
    url: str


class UploadCleaningPhotoUseCase(_TaskTransitionMixin):
    """R2 — the assigned cleaner uploads one photo of the cleaning.

    Inherits `_TaskTransitionMixin` for `_load_task` alone, and moves no property state: an
    upload is evidence, not a lifecycle step. What `_load_task` brings is the pair of rules
    that must not be re-derived per use case — the task is resolved **inside the tenant**, and
    a `CLEANER` only reaches the tasks assigned to them (R6.3, R6.4), both answered with the
    single `CleaningTaskNotFoundError` constant so another tenant's task is byte-identical to
    an id that never existed.

    **Two guarantees live here and nowhere else**, both inherited from the review panels of
    sections 1 and 2:

    * Every `storage_key` is built by `storage_key_for_photo` from the **session's**
      `tenant_id`. No key, fragment or file name from the client reaches it, and none is ever
      returned. The port's methods take an arbitrary `key` on purpose — they are shared with
      `maintenance` and `revenue` — so the port cannot enforce this and this is the only place
      that can.
    * `uploaded_by` is `actor.user_id`, from the verified token, never from the body.
      `cleaning_photos.uploaded_by` is a plain FK to `users.id` with no tenant restriction and
      the repository writes it verbatim — deliberately, exactly as `completed_by` is treated —
      so an id taken from a request would record a neighbour's user as the author.

    Order of operations is design D4 and it is not interchangeable: **object first, row
    second**, and a failed commit deletes the object. R1.5 forbids a row pointing at an object
    that is not there — that is a broken `GET` for ever — while the opposite failure leaves an
    orphaned object, which is recoverable rubbish.
    """

    def __init__(
        self,
        *,
        tasks: CleaningTaskRepository,
        templates: CleaningChecklistTemplateRepository,
        photos: CleaningPhotoRepository,
        configs: TenantConfigRepository,
        storage: FileStorageFactory,
        audit: AuditLogRepository,
        uow: UnitOfWork,
        max_bytes: int,
    ) -> None:
        self._tasks = tasks
        self._templates = templates
        self._photos = photos
        self._configs = configs
        self._storage = storage
        self._audit = _AuditWriter(audit)
        self._uow = uow
        # Passed in rather than read from `app.core.config` here: `application/` receives its
        # configuration the same way it receives its ports, which is what lets a test drive the
        # 413 path with a two-byte ceiling instead of a 10 MB fixture.
        self._max_bytes = max_bytes

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        photo_type: str,
        upload: ChunkedUpload,
        actor: CleaningActor,
        now: datetime,
    ) -> UploadedCleaningPhoto:
        task = await self._load_task(tenant_id, task_id, actor)
        if task.status is not CleaningTaskStatus.IN_PROGRESS:
            # R2.3, and the same boundary `CompleteChecklistItemUseCase` draws: evidence
            # belongs to the execution of the cleaning, so it cannot be filed before starting
            # or after finishing. Refused **before** anything is read or written.
            raise InvalidCleaningTransitionError(
                f"Cannot upload a cleaning photo to a task in status {task.status.value}"
            )

        template = await self._templates.get(tenant_id, task.checklist_template_id)
        if template is None:
            raise ChecklistTemplateNotFoundError(
                "The task's checklist template no longer exists"
            )
        spec = parse_template_content(
            template.items, template.required_photos, template_id=template.id
        )
        if photo_type not in spec.photo_types():
            # R2.2 — the same 404 the checklist gives an unknown `item_id`.
            raise PhotoTypeNotFoundError(f"Unknown photo type {photo_type!r}")

        content = await self._read_within_limit(upload)
        # D5/R2.4: the format comes from the BYTES. Whatever `Content-Type` the client
        # declared is not consulted anywhere in this module.
        image = detect_image_type(content[:MAGIC_BYTES_LENGTH])
        if image is None:
            raise UnsupportedPhotoFormatError(
                "The uploaded file is not a JPEG, PNG or WebP image"
            )

        photo_id = uuid.uuid4()
        storage_key = storage_key_for_photo(
            # The tenant of the verified token, never a value that travelled with the
            # request. This call is the only producer of keys in the cleaning module.
            tenant_id=tenant_id,
            task_id=task.id,
            photo_id=photo_id,
            # From the detected MIME, so the client's file name never reaches the key (D3).
            extension=image.extension,
        )

        config = await self._configs.get_or_create(tenant_id, now)
        # R1.2 — which backend this is stays unknown here; the factory answers from the
        # tenant's stored `storage_type`.
        storage = self._storage.storage_for(config.storage_type)
        try:
            await storage.put(storage_key, content, content_type=image.mime)
        except StorageWriteError as exc:
            # Nothing has been inserted yet, so there is nothing to compensate: this is why
            # the object goes first (D4).
            raise PhotoStorageUnavailableError(
                "The photo could not be stored; please try again"
            ) from exc

        photo = CleaningPhoto(
            id=photo_id,
            cleaning_task_id=task.id,
            uploaded_by=actor.user_id,
            photo_type=photo_type,
            storage_key=storage_key,
            created_at=now,
        )
        try:
            await self._photos.add(tenant_id, photo)
            await self._audit.record_photo_upload(
                tenant_id=tenant_id, photo=photo, actor=actor, now=now
            )
            await self._uow.commit()
        except Exception:
            # The compensating delete of design D4, and the reason `FileStoragePort.delete`
            # has a caller at all. Best effort by contract: it must not replace the real
            # failure with one of its own on the way out.
            await self._delete_quietly(storage, storage_key)
            raise

        return UploadedCleaningPhoto(photo=photo, url=storage.signed_url(storage_key))

    async def _read_within_limit(self, upload: ChunkedUpload) -> bytes:
        """Consume the upload in chunks, counting, and abort the moment it is too big (D11).

        **What this does NOT do, despite an earlier comment here saying it did: it does not
        protect against a lying `Content-Length` or a chunked upload.** It cannot, and the
        reason is mechanical. `app/core/http_limits.py` documents it: FastAPI calls
        `await request.form()` inside its route wrapper *before* it solves dependencies, and
        Starlette's multipart parser spools the file part to a `SpooledTemporaryFile` that has
        no size ceiling of its own. So by the time this loop asks for its first chunk, the file
        has already been received in full and written to the container's disk. Counting it
        afterwards cannot un-receive it.

        The check that genuinely stops an oversized or dishonest body is
        `MaxBodySizeMiddleware`, and specifically its **accumulating counter**
        (`http_limits.py:116-129`), which tallies bytes as they arrive and cuts the stream the
        moment the total passes the ceiling — that is the half covering a client that
        understates `Content-Length` or sends `Transfer-Encoding: chunked` with none at all.
        The `Content-Length` refusal before it is only the cheap fast path.

        **So do not "simplify" the middleware branch on the grounds that the use case already
        counts.** Deleting the middleware's counter would leave an anonymous caller able to
        make the backend spool an arbitrary volume to disk before authentication ever runs —
        the exact hole that module exists to close, measured twice by two different changes.

        What this loop does buy, and why it stays:

        * It bounds the **in-process copy**. `content` ends up in memory, and the ceiling plus
          one chunk is the peak this holds regardless of how large the spooled file is.
        * It is the ceiling for any wiring that has no middleware in front — a direct call from
          a test, a worker, or a future non-HTTP caller of this use case. The use case cannot
          assume an ASGI stack it does not own.

        R2.5 ("reject before reading the whole body") is satisfied by the middleware; this is
        defence in depth behind it, not a second enforcement of the same guarantee.
        """
        chunks: list[bytes] = []
        received = 0
        while True:
            chunk = await upload.read(_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            received += len(chunk)
            if received > self._max_bytes:
                # Raised before the chunk is kept, so the peak held is the ceiling plus one
                # chunk — not the size of whatever the client decided to send.
                raise PhotoTooLargeError(
                    f"The photo exceeds the {self._max_bytes} byte limit"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    async def _delete_quietly(storage: FileStoragePort, storage_key: str) -> None:
        """Delete, and swallow whatever that costs — the caller is already failing.

        The key IS logged, and that is deliberate rather than an oversight of R3.2: that rule
        governs API responses, and an orphaned object is only recoverable by someone who can
        find it. This log line is the whole recovery procedure for design D4's accepted
        failure mode.
        """
        try:
            await storage.delete(storage_key)
        except Exception:
            logger.warning(
                "cleaning.orphaned_photo_object",
                extra={"storage_key": storage_key},
            )


class ListCleaningPhotosUseCase(_TaskTransitionMixin):
    """R3.1 — the photos of one task, each with a freshly minted signed URL.

    Inherits `_TaskTransitionMixin` for `_load_task` alone, exactly as the upload does and for
    exactly the same two rules: the task is resolved **inside the tenant**, and a `CLEANER`
    only reaches the tasks assigned to them (R6.3, R6.4). A manager or owner sees every photo
    of every task of their tenant, and neither role can name a cleaner through any request
    field — `CleaningActor.restrict_to_cleaner_id` derives it from the persisted role.

    Resolving the task first is also what makes the listing's 404 the shared, byte-identical
    `CleaningTaskNotFoundError`: another tenant's task and an id that never existed are one
    outcome. Reading `list_for_task` on its own would answer an empty list for both, which
    leaks nothing but says "this task exists and has no photos" to a caller who owns neither.

    **`storage_key` leaves this use case inside `UploadedCleaningPhoto.photo` and stops at the
    schema.** It has to: `signed_url` is what turns it into the one thing a client may see, and
    the port takes the key. R3.2 is enforced by `CleaningPhotoResponse` enumerating its fields
    (never `model_validate`/`from_attributes` over the entity), and `tests/cleaning/
    test_photo_listing_api.py` asserts it against the **serialised body**, not the field list.
    """

    def __init__(
        self,
        *,
        tasks: CleaningTaskRepository,
        photos: CleaningPhotoRepository,
        configs: TenantConfigRepository,
        storage: FileStorageFactory,
    ) -> None:
        self._tasks = tasks
        self._photos = photos
        self._configs = configs
        self._storage = storage

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        actor: CleaningActor,
        now: datetime,
    ) -> tuple[UploadedCleaningPhoto, ...]:
        task = await self._load_task(tenant_id, task_id, actor)
        photos = await self._photos.list_for_task(tenant_id, task.id)
        config = await self._configs.get_or_create(tenant_id, now)
        # R1.2 again: which backend answers stays unknown here. `LOCAL` mints a URL of this
        # API's own serving route, `S3` a presigned one straight at the provider — the caller
        # gets a URL either way and cannot tell from this code which it is.
        storage = self._storage.storage_for(config.storage_type)
        return tuple(
            UploadedCleaningPhoto(photo=photo, url=storage.signed_url(photo.storage_key))
            for photo in photos
        )


@dataclass(frozen=True)
class ServedPhoto:
    """The bytes to answer with, and the `Content-Type` to answer them with.

    `content_type` comes from `content_type_for_extension` and from nowhere else (design D7,
    task 4.3c). It is carried here rather than left to the route to work out, so the route has
    nothing to derive and nothing to guess.
    """

    content: bytes
    content_type: str


class ServeLocalCleaningPhotoUseCase:
    """The anonymous signed serving route's use case (design D7, D7b) — R3.3.

    **The order of the three steps is the security property, not an implementation detail**:

    1. **Resolve** `photo_id → (storage_key, tenant_id)` with the unscoped query of D7b. There
       is no session tenant here — the route is anonymous because an `<img src>` sends no
       `Authorization` header — so this is the only way to learn either fact.
    2. **Verify** the signature against the key that came out of step 1, never against
       anything the client sent. The signature covers the whole key, which begins with
       `tenants/{tenant_id}/` (D3), so a signature that verifies **proves** the caller was
       handed a URL minted for this photo of this tenant. That is the entire authorisation of
       this endpoint.
    3. **Serve**, and only now: resolve the tenant's backend and read the bytes.

    Inverting 1 and 2 is impossible (there is nothing to verify against yet). Inverting 2 and 3
    is the failure this ordering exists to prevent, and it has its own test.

    Every refusal in steps 1 and 2 raises the **same** `InvalidSignatureError`, which the route
    turns into one constant `403` body — task 4.3b. "No such photo", "wrong signature",
    "expired" and "over the TTL ceiling" must be indistinguishable from outside, or this
    endpoint becomes an existence oracle over the photo keyspace for a caller with no
    credentials at all, on a route `api-ingress-routing` left reachable from the internet.

    Step 3 answers differently on purpose, and it is not a leak: `LocalFileReadUnsupportedError`
    (an `S3` tenant, no local serving) becomes a `404` and a `StorageWriteError` a `502`, but
    both are only reachable **after** a valid signature, i.e. by someone already holding proof
    that the photo exists.

    `now` is passed in like every other use case here, and converted to POSIX seconds for
    `verify_signed_key`, which is pure and takes the clock as an argument (task 1.3). One
    reading, converted, rather than two parameters that could disagree about *when* this
    request happened.
    """

    def __init__(
        self,
        *,
        locations: UnscopedCleaningPhotoLocationQuery,
        configs: TenantConfigRepository,
        storage: FileStorageFactory,
        signing_key: bytes,
    ) -> None:
        self._locations = locations
        self._configs = configs
        self._storage = storage
        self._signing_key = signing_key

    async def execute(
        self,
        *,
        photo_id: uuid.UUID,
        expiry: int,
        signature: str,
        now: datetime,
    ) -> ServedPhoto:
        location = await self._locations.locate_without_tenant_scoping(photo_id)
        if location is None:
            # Step 1 failed. Raised as the SAME error a bad signature raises so the route has
            # one thing to catch and one body to answer with (4.3b). The message is for the
            # log; it does not reach the response.
            #
            # Known and accepted residue: this path skips the HMAC of step 2, so it is
            # marginally faster than a signature that fails to verify. Distinguishing a UUID
            # that exists from one that does not through that difference means measuring
            # microseconds across the internet over a 122-bit keyspace, per candidate id. The
            # body is identical, which is what R3.4 asks for.
            raise InvalidSignatureError(f"no photo resolves for id {photo_id}")

        # Against the key from the DATABASE. Nothing the client sent contributes to it — the
        # URL carries only the photo id, its expiry and the signature (R3.2 keeps the key out
        # of every response, so it could not carry the key even if we wanted it to).
        verify_signed_key(
            signing_key=self._signing_key,
            key=location.storage_key,
            expiry=expiry,
            signature=signature,
            now=int(now.timestamp()),
        )

        # Everything below happens only after a valid signature. `get_or_create` can in
        # principle insert, which would be a write on an anonymous request — in practice never,
        # because the upload that created this photo already created the row, and in any case
        # this route never commits, so the flush dies with the request's transaction.
        config = await self._configs.get_or_create(location.tenant_id, now)
        # Raises `LocalFileReadUnsupportedError` for an `S3` tenant, before instantiating
        # anything — design D1's refusal point. There is no local serving for that backend
        # because the browser fetches the object straight from the provider.
        reader = self._storage.read_for(config.storage_type)
        content = await reader.read(location.storage_key)
        return ServedPhoto(
            content=content,
            # Task 4.3c: the ONLY admitted source. The MIME detected at upload is not
            # persisted; with `LOCAL` it survives solely inside the key's extension (D3).
            # Deriving it from anything else — or omitting it and letting Starlette sniff —
            # turns a polyglot that starts with `FF D8 FF` and carries HTML into stored XSS on
            # the API's own origin. `_extension_of` refuses a key it cannot read rather than
            # falling back to a default, for the same reason.
            content_type=content_type_for_extension(_extension_of(location.storage_key)),
        )


def _extension_of(storage_key: str) -> str:
    """The extension inside a storage key, with no default and no guess.

    Returns `""` for a key with no extension, which `content_type_for_extension` then refuses
    with a `ValueError` — a 500, correctly, because such a key can only come from a bug of
    ours: every key is built by `storage_key_for_photo`, which validates the extension against
    the image allowlist before assembling it. Substituting `application/octet-stream` here
    would be exactly the fallback task 4.3c exists to forbid.
    """
    _, separator, extension = storage_key.rpartition(".")
    return extension if separator else ""


def _effective_checkout(
    property: Property, reservation: Reservation, now: datetime
) -> datetime | None:
    """R2.6 — the cleaning can start when the guest is out, not when the job noticed."""
    from app.properties.domain.clock_triggers import effective_bounds

    try:
        _, end = effective_bounds(property, reservation)
    except IncompatibleTransitionContextError:
        # Unreachable in practice: the caller only gets here after the machine accepted this
        # reservation, which materialises the same bounds. Degrading to `now` rather than
        # raising keeps a scheduling hint from breaking the creation of the task.
        return now
    return end


def _next_checkin(
    property: Property,
    known_reservations: Sequence[Reservation],
    current: Reservation,
    after: datetime,
) -> datetime | None:
    """R2.6 — the deadline is the next guest's arrival, when there is one.

    Reads the reservations the job already loaded (design D1) instead of querying: the
    scheduler's window is `candidate_window(now)`, so a stay further out simply leaves
    `scheduled_end` unset rather than being guessed at.

    **`after` is the effective checkout, not `now`.** A first version filtered on `now` and
    the QA panel of section 4 reproduced what that costs: `process_checkouts` is explicitly
    built to recover a backlog — `CANDIDATE_LOOKBEHIND` is 30 days
    (`properties/domain/clock_triggers.py:41-51`) — so a same-day turnover processed late had
    its next check-in already in the past relative to `now` and `scheduled_end` came back
    `None`, silently dropping a deadline that was sitting in `known_reservations`. The
    cleaning's window is `[checkout, next arrival]`; neither end of it is a function of when
    the job happened to run.
    """
    from app.properties.domain.clock_triggers import effective_bounds

    starts: list[datetime] = []
    for candidate in known_reservations:
        if candidate.id == current.id:
            continue
        if candidate.status is not ReservationStatus.CONFIRMED:
            continue
        try:
            start, _ = effective_bounds(property, candidate)
        except IncompatibleTransitionContextError:
            continue
        if start >= after:
            starts.append(start)
    return min(starts) if starts else None
