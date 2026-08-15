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

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from app.audit.domain import actions as audit_actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.ports import UserRepository
from app.auth.domain.repositories import UserFilters
from app.core.unit_of_work import UnitOfWork
from app.maintenance.domain.entities import Incident, OwnerApproval
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)
from app.maintenance.domain.exceptions import (
    IncidentNotFoundError,
    InvalidTechnicianError,
    MaintenanceValidationError,
    OwnerApprovalNotFoundError,
)
from app.maintenance.domain.notifications import (
    RELATED_TYPE_INCIDENT,
    owner_approval_notification,
    sla_minutes_for,
    technician_assignment_notification,
)
from app.maintenance.domain.ports import IncidentClassifier, LiveCleaningTaskQuery
from app.maintenance.domain.repositories import (
    IncidentFilters,
    IncidentPage,
    IncidentQuery,
    IncidentRepository,
    OwnerApprovalRepository,
)
from app.notifications.domain.enums import NotificationType
from app.notifications.domain.repositories import NotificationLogRepository
from app.properties.domain.clock_triggers import candidate_window
from app.properties.domain.enums import StateTransitionTriggeredBy
from app.properties.domain.exceptions import (
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
from app.reservations.domain.repositories import ReservationRepository
from app.tenants.domain.repositories import TenantConfigRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.domain.repositories import TimelineEventRepository
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData

logger = logging.getLogger(__name__)

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


# --- The incident flow of `maintenance` itself (R1-R6, design D5-D13) -------------------


#: What the timeline says at each milestone. Constants, and `metadata` carries identifiers
#: only — the discipline `ReportGuestIncidentUseCase` established above and D10 repeats:
#: `timeline_events` is append-only, so free text an anonymous caller typed could never be
#: redacted afterwards.
_TIMELINE_TITLES: dict[TimelineEventType, str] = {
    TimelineEventType.INCIDENT_CLASSIFIED: "Incident classified",
    TimelineEventType.OWNER_APPROVAL_REQUIRED: "Owner approval requested",
    TimelineEventType.OWNER_APPROVED_EXPENSE: "Owner approved the expense",
    TimelineEventType.OWNER_REJECTED_EXPENSE: "Owner rejected the expense",
    TimelineEventType.TECHNICIAN_ASSIGNED: "Technician assigned",
    TimelineEventType.TECHNICIAN_ACCEPTED: "Technician accepted the incident",
    TimelineEventType.TECHNICIAN_STARTED: "Technician started work",
    TimelineEventType.INCIDENT_RESOLVED: "Incident resolved",
    TimelineEventType.INCIDENT_CANCELLED: "Incident cancelled",
}


@dataclass(frozen=True)
class IncidentActor:
    """Who is acting, and from where — the two things `audit_logs` records that
    `property_state_transitions` cannot (rule 9 of `steering/security.md`)."""

    user_id: uuid.UUID
    role: UserRole
    ip: str | None = None

    @property
    def restrict_to_technician_id(self) -> uuid.UUID | None:
        """R5.3 — derived from the role **here**, never accepted from the request.

        A `TECHNICIAN` sees and acts on their own incidents only; every other role holding
        an incident permission sees the tenant's. Returning the id rather than a boolean
        means the caller cannot forget to apply it: it goes straight into the repository
        filter. Calqued from `CleaningActor.restrict_to_cleaner_id`.

        This is also why `EXECUTE_INCIDENTS` can belong to two roles (D13): `require()`
        takes a single permission, so the assignee restriction has to ride the role.
        """
        return self.user_id if self.role is UserRole.TECHNICIAN else None


class _AuditWriter:
    """Builds and appends an audit entry, so no use case constructs one by hand.

    Same shape as `cleaning`'s. Every operation of this flow writes one (R6.1), and rule 9
    of `steering/security.md` names `Incident` and `OwnerApproval` in its enumeration, so
    there is no argument to make beyond the citation.
    """

    #: The only action of this module whose row may go without an actor: the classification
    #: the job of D2 performs, where there is no user to name. Everything else in the flow is
    #: done by a person, and R6.4 says "SHALL nombrar como actor al usuario que ejecuta la
    #: transición" — so the absence of an actor is refused here rather than trusted.
    #:
    #: **Enforced in this writer and not in `AuditLogFactory`**, which is the wider fix the
    #: security panel of section 4 asked for. The factory is the chokepoint every module
    #: writes through, and five other modules already write actor-less rows on purpose
    #: (`ACCESS_RECORD_CREATED`, `ACCESS_REVOKED`, `USER_PASSWORD_RESET` and
    #: `PMS_CREDENTIAL_ROTATED` from the command line, `PMS_CREDENTIAL_READ` from a sync);
    #: declaring which of those are permitted is re-deciding four other changes' exemptions,
    #: and this one has no standing to. What it can do — and does — is make its own actions
    #: impossible to write anonymously by accident. The factory-level version is a candidate
    #: for a change of its own.
    _ACTOR_OPTIONAL_ACTIONS = frozenset({audit_actions.INCIDENT_CLASSIFIED})

    def __init__(self, audit: AuditLogRepository) -> None:
        self._audit = audit

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        actor: IncidentActor | None,
        changes: ChangeSet,
        now: datetime,
    ) -> None:
        """`actor=None` is the classification job and nothing else (D6, R6.4).

        Its row goes with `actor_user_id` and `actor_ip` at `NULL` because the clock fires
        the job: there is no person, and no request for `actor_ip` to come from. That is
        rule 9's **fourth named exception** in `steering/security.md`, and this guard is what
        keeps it from widening by accident — the exception covers one action and one caller.
        """
        if actor is None and action not in self._ACTOR_OPTIONAL_ACTIONS:
            raise MaintenanceValidationError(
                f"{action} must name the user who performed it (R6.4); only "
                f"{sorted(self._ACTOR_OPTIONAL_ACTIONS)} may be written without an actor."
            )
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_user_id=actor.user_id if actor is not None else None,
                actor_ip=actor.ip if actor is not None else None,
                changes=changes,
                now=now,
            ),
        )


class _IncidentTransitionMixin:
    """The shared middle of every operation that may move the property's state.

    Load the incident within the tenant (and within the acting technician's own rows),
    mutate the entity, put it in the machine's context **already mutated**, persist
    transition + timeline + property. Written once because `steering/architecture.md` makes
    `PropertyStateMachine` the only place a transition happens, and ten copies of this would
    be ten chances to bypass it.
    """

    _incidents: IncidentRepository
    _reader: IncidentQuery
    _properties: PropertyRepository
    _transitions: PropertyStateTransitionRepository
    _timeline: TimelineEventRepository
    _reservations: ReservationRepository
    _cleaning_tasks: LiveCleaningTaskQuery
    _audit: "_AuditWriter"

    async def _load_incident(
        self, tenant_id: uuid.UUID, incident_id: uuid.UUID, actor: IncidentActor
    ) -> Incident:
        incident = await self._incidents.get(tenant_id, incident_id)
        if incident is None:
            raise IncidentNotFoundError()
        restrict = actor.restrict_to_technician_id
        if restrict is not None and incident.assigned_technician_id != restrict:
            # R5.3/R5.4: for this technician the incident does not exist. Same error, same
            # message — a distinguishable 404 would confirm that it exists and is somebody
            # else's.
            raise IncidentNotFoundError()
        return incident

    async def _record_timeline(
        self,
        *,
        tenant_id: uuid.UUID,
        incident: Incident,
        event_type: TimelineEventType,
        actor: IncidentActor | None,
        now: datetime,
        extra: dict[str, str] | None = None,
    ) -> None:
        """One milestone, with a constant title and identifiers only (D10, R6.3).

        Actor `AI` when there is no user, which is the classification job: `TimelineEventFactory`
        only accepts `actor_user_id` alongside `USER`, so the row cannot claim a person who
        was not there — literally what R6.4 forbids.
        """
        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                TimelineEventData(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    property_id=incident.property_id,
                    actor_type=(
                        TimelineActorType.USER if actor is not None else TimelineActorType.AI
                    ),
                    actor_user_id=actor.user_id if actor is not None else None,
                    event_type=event_type,
                    title=_TIMELINE_TITLES[event_type],
                    created_at=now,
                    reservation_id=incident.reservation_id,
                    metadata={"incident_id": str(incident.id), **(extra or {})},
                )
            ),
        )

    async def _fire_trigger(
        self,
        *,
        tenant_id: uuid.UUID,
        incident: Incident,
        trigger: PropertyStateTrigger,
        actor: IncidentActor | None,
        now: datetime,
    ) -> None:
        """Ask `PropertyStateMachine` to recompute the property's state (R4.6, D7, D8).

        **The context carries all three collections D7 names**, and that is the part which is
        not obvious: `ContextualStateResolver.after_incident_resolution` falls through to
        `_contextual_reservation_cleaning`, which reads `context.cleaning_tasks` **and**
        `context.reservations`. Without the cleaning tasks a property with a pending cleaning
        would leave `MAINTENANCE_REQUIRED` for `VACANT_READY` instead of `AWAITING_CLEANING`
        — a plausible, wrong destination that fails nothing.

        The incident being changed is included through `list_active_for_property`, which
        reads it back already saved; callers therefore persist the entity **before** calling
        this.
        """
        property = await self._properties.get(tenant_id, incident.property_id)
        if property is None:
            # The incident's own FK guarantees the row exists, so this is our wiring being
            # wrong rather than a caller's mistake — and D8's tolerance is about the
            # machine refusing a trigger, not about a missing aggregate.
            raise MaintenanceValidationError("Incident points at an unknown property")

        # The incident being changed has to be in the context **even when it is terminal**:
        # `PropertyStateMachine._source_incident` resolves `source_entity_id` against this
        # collection, so a `RESOLVED` or `CANCELLED` one — which `list_active_for_property`
        # correctly excludes — would make the machine refuse the very trigger it is being
        # asked for, and D8's tolerance would swallow the refusal as a warning. The property
        # would then quietly stay in `MAINTENANCE_REQUIRED` for ever.
        #
        # Adding it back is safe: `after_incident_resolution` filters actives with
        # `status not in (RESOLVED, CANCELLED)` itself, so a terminal one in the context
        # informs the source lookup and never the destination.
        active = await self._reader.list_active_for_property(tenant_id, property.id)
        incidents = tuple(active) + (
            () if any(other.id == incident.id for other in active) else (incident,)
        )

        date_from, date_to = candidate_window(now)
        request = PropertyStateChangeRequest(
            property=property,
            trigger=trigger,
            context=PropertyTransitionContext(
                incidents=incidents,
                reservations=tuple(
                    await self._reservations.list_for_properties(
                        tenant_id, [property.id], date_from, date_to
                    )
                ),
                cleaning_tasks=tuple(
                    await self._cleaning_tasks.list_live_for_property(tenant_id, property.id)
                ),
            ),
            actor=(
                TransitionActor(
                    triggered_by=StateTransitionTriggeredBy.USER, user_id=actor.user_id
                )
                if actor is not None
                else TransitionActor(triggered_by=StateTransitionTriggeredBy.SYSTEM)
            ),
            reference_instant=now,
            evidence_ids=TransitionEvidenceIds(
                transition_id=uuid.uuid4(), timeline_event_id=uuid.uuid4()
            ),
            source_entity_id=incident.id,
            correlation_id=str(uuid.uuid4()),
        )
        try:
            result = PropertyStateMachine.evaluate(request)
        except (NoOperationalStateChangeError, InvalidStateTransitionError):
            # D8: the incident exists and is in the status it should be; only the property's
            # state did not move. The matrix has real gaps — `BLOCKED_BY_OWNER` and
            # `OUT_OF_SERVICE` stop everything by a human decision, and a no-op is a no-op —
            # so failing the operation here would refuse a classification because of a state
            # nobody asked about. The incident is the record; the operational state is a
            # projection. Same reasoning `_fire_cleaner_assigned` established in `cleaning`.
            #
            # **`IncompatibleTransitionContextError` is deliberately NOT caught**, although
            # D8 lists it. Every way the machine raises it for an incident trigger is a
            # disagreement between *our* code and itself — a severity that does not match
            # the trigger we derived from it, an incident that is terminal when we said it
            # was active, a `source_entity_id` absent from the context we built. None of
            # those is a gap in the matrix, and swallowing them is not tolerance but a
            # blind spot: it is exactly what hid the missing-source bug this mixin had
            # until its own tests found it. `cleaning`'s equivalent draws the same line for
            # the same reason ("this is our bug and must surface as a 500"). Raised as a
            # DESIGN-CONFLICT by the architecture panel of section 6 and recorded in D8.
            logger.warning(
                "maintenance.transition_refused",
                extra={
                    "tenant_id": str(tenant_id),
                    "property_id": str(property.id),
                    "incident_id": str(incident.id),
                    "trigger": trigger.value,
                },
            )
            return

        # **No `AuditLog` row for the property itself, and it is an open question rather
        # than a decision.** Rule 9 of `steering/security.md` exempts a property state
        # transition only for actor `SYSTEM` and says of the rest that "una transición con
        # cualquier otro actor —`USER`, `WEBHOOK` o `SCHEDULER`— NO está exenta"; every
        # transition this mixin fires with an actor is a `USER` one. The security panel of
        # section 6 raised it. It is not fixed here because `properties` decided the
        # opposite for *all* actors, in code and in a test that says so by name
        # (`tests/audit/test_change_set_property.py::test_the_operational_state_is_not_an_auditable_property_field`),
        # and `cleaning`'s mixin has the identical gap — so closing it in this one module
        # would make the trail inconsistent without making it complete. Recorded as a
        # roadmap candidate in the change's `proposal.md` (§Out of scope).
        await self._transitions.add(tenant_id, result.transition)
        await self._timeline.add(tenant_id, result.timeline_event)
        property.current_operational_state = result.transition.to_state
        await self._properties.save(tenant_id, property)

    def _severity_trigger(self, incident: Incident) -> PropertyStateTrigger | None:
        """Which trigger a newly classified incident fires, if any (R4.6).

        `MEDIUM` and `LOW` fire nothing: PRD §12 escalates the property for a serious fault,
        and the state machine has no trigger for the others.
        """
        return {
            IncidentSeverity.HIGH: PropertyStateTrigger.INCIDENT_HIGH,
            IncidentSeverity.CRITICAL: PropertyStateTrigger.INCIDENT_CRITICAL,
        }.get(incident.severity)


class _IncidentFlowBase(_IncidentTransitionMixin):
    """Constructor shared by every operation of the incident lifecycle."""

    def __init__(
        self,
        *,
        incidents: IncidentRepository,
        reader: IncidentQuery,
        properties: PropertyRepository,
        transitions: PropertyStateTransitionRepository,
        timeline: TimelineEventRepository,
        reservations: ReservationRepository,
        cleaning_tasks: LiveCleaningTaskQuery,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._incidents = incidents
        self._reader = reader
        self._properties = properties
        self._transitions = transitions
        self._timeline = timeline
        self._reservations = reservations
        self._cleaning_tasks = cleaning_tasks
        self._audit = _AuditWriter(audit)
        self._uow = uow


class ClassifyIncidentUseCase(_IncidentFlowBase):
    """R1.2, R1.3, R1.6 — put an `OPEN` incident through the classifier.

    Driven by the job of D2 (with `actor=None`) and by `POST /incidents/{id}/classify` (with
    the manager who forced it). One use case for both, because the difference is who asked,
    not what happens.
    """

    def __init__(self, *, classifier: IncidentClassifier, configs: TenantConfigRepository, **kwargs) -> None:
        super().__init__(**kwargs)
        self._classifier = classifier
        self._configs = configs

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        incident_id: uuid.UUID,
        actor: IncidentActor | None,
        now: datetime,
    ) -> Incident:
        incident = (
            await self._load_incident(tenant_id, incident_id, actor)
            if actor is not None
            else await self._incidents.get(tenant_id, incident_id)
        )
        if incident is None:
            raise IncidentNotFoundError()

        config = await self._configs.get_or_create(tenant_id, now)
        try:
            classification = await self._classifier.classify(
                title=incident.title, description=incident.description
            )
        except Exception as error:
            # R1.6: leave it `OPEN` with `ai_classification` unwritten, so the next tick of
            # the job picks it up again (D3). Nothing is committed, so nothing is half done —
            # which is the other half of "NEVER SHALL perderla ni dejarla en un estado
            # intermedio". Deliberately broad: a port's failure modes belong to whatever
            # implements it, and a real provider will raise things this module cannot name.
            # The **type** and the ids, never `exc_info`: the port was handed
            # `incident.title` and `incident.description`, and an adapter that embeds its
            # input in the message — which `httpx.HTTPStatusError` and
            # `pydantic.ValidationError` both do by default — would have that message
            # rendered into the traceback. Log readers are a wider set than
            # `READ_INCIDENTS`, and excepción 2 of rule 11 says the guest's prose "no se
            # propaga". Raised by the security panel of section 6; the same shape
            # `notification_logs.last_error` already uses.
            logger.warning(
                "maintenance.classification_failed",
                extra={
                    "tenant_id": str(tenant_id),
                    "incident_id": str(incident.id),
                    "error_type": type(error).__name__,
                },
            )
            return incident

        previous = (incident.category, incident.severity, incident.status)
        incident.classify(
            classification,
            confidence_threshold=config.ai_confidence_threshold,
            adapter=type(self._classifier).__name__,
            now=now,
        )
        await self._incidents.save(tenant_id, incident)

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.INCIDENT_CLASSIFIED,
            entity_type=audit_actions.ENTITY_INCIDENT,
            entity_id=incident.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_INCIDENT)
            .diff("category", previous[0], incident.category)
            .diff("severity", previous[1], incident.severity)
            .diff("status", previous[2], incident.status),
            now=now,
        )
        await self._record_timeline(
            tenant_id=tenant_id,
            incident=incident,
            event_type=TimelineEventType.INCIDENT_CLASSIFIED,
            actor=actor,
            now=now,
        )

        if incident.status is IncidentStatus.CLASSIFIED:
            trigger = self._severity_trigger(incident)
            if trigger is not None:
                await self._fire_trigger(
                    tenant_id=tenant_id,
                    incident=incident,
                    trigger=trigger,
                    actor=actor,
                    now=now,
                )

        await self._uow.commit()
        return incident


class _ApprovalGateMixin:
    """Opening an owner approval — the half D11's two gates have in common.

    Both gates create the same row, audit it the same way, put the same milestone on the
    timeline and notify the same person; what differs is `related_type`, which is precisely
    what `Incident.resume_after_approval` reads back to decide where the incident returns
    to. Written once, in a mixin rather than in a base class, because only two of the ten
    use cases open a gate.
    """

    _approvals: OwnerApprovalRepository
    _users: UserRepository
    _notifications: NotificationLogRepository
    _audit: _AuditWriter
    _record_timeline: Callable[..., Awaitable[None]]

    async def _open_approval(
        self,
        *,
        tenant_id: uuid.UUID,
        incident: Incident,
        amount: Decimal,
        related_type: OwnerApprovalRelatedType,
        actor: IncidentActor,
        now: datetime,
    ) -> OwnerApproval:
        """Create the approval, audit it and tell the owner (R2.1, R2.3, R4.3, D11).

        `reason` is a constant plus identifiers, never the incident's own text: it is one of
        the four columns D4 puts in the rule-11 census, and our code is what writes it.
        """
        approval = OwnerApproval(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=incident.property_id,
            related_type=related_type,
            related_id=incident.id,
            amount=amount,
            reason=f"Maintenance expense above the tenant threshold. Incident {incident.id}.",
            requested_at=now,
        )
        await self._approvals.add(tenant_id, approval)
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.OWNER_APPROVAL_REQUESTED,
            entity_type=audit_actions.ENTITY_OWNER_APPROVAL,
            entity_id=approval.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_OWNER_APPROVAL)
            .diff("status", None, approval.status)
            .diff("amount", None, approval.amount)
            .diff("related_type", None, approval.related_type),
            now=now,
        )
        await self._record_timeline(
            tenant_id=tenant_id,
            incident=incident,
            event_type=TimelineEventType.OWNER_APPROVAL_REQUIRED,
            actor=actor,
            now=now,
            extra={"owner_approval_id": str(approval.id)},
        )
        await self._notify_owner(
            tenant_id=tenant_id, incident=incident, approval=approval, now=now
        )
        return approval

    async def _notify_owner(
        self,
        *,
        tenant_id: uuid.UUID,
        incident: Incident,
        approval: OwnerApproval,
        now: datetime,
    ) -> None:
        """R2.3 — a `NotificationLog` for the owner, through the existing adapter.

        If the tenant has no active owner account there is nobody to address, and the run is
        not failed over it: the approval row is the record, and `app/cli/bootstrap.py`
        creates the owner in every environment that has one. Logged rather than swallowed,
        because a tenant in that state has a pending approval nobody will ever see.
        """
        owners = await self._users.list(
            tenant_id,
            UserFilters(role=UserRole.TENANT_OWNER, status=UserStatus.ACTIVE),
            page=1,
            per_page=1,
        )
        if not owners.items:
            logger.warning(
                "maintenance.owner_approval_without_recipient",
                extra={
                    "tenant_id": str(tenant_id),
                    "owner_approval_id": str(approval.id),
                },
            )
            return

        owner = owners.items[0]
        await self._notifications.add(
            tenant_id,
            owner_approval_notification(
                tenant_id=tenant_id,
                incident_id=incident.id,
                property_id=incident.property_id,
                approval_id=approval.id,
                owner_id=owner.id,
                recipient_contact=owner.email,
                now=now,
            ),
        )


@dataclass
class IncidentClassificationReport:
    """What one tenant's tick of `classify_incidents` did (design D2).

    Counted rather than listed: the report goes into the Celery result and then into a log,
    and an incident id there would be an identifier of a fault in a place nobody scopes by
    tenant. `considered` and the three outcomes add up, which is what makes a run readable.
    """

    tenant_id: str
    considered: int = 0
    classified: int = 0
    low_confidence: int = 0
    failed: int = 0


class ClassifyPendingIncidentsUseCase:
    """The job of D2: everything in `OPEN` that nobody has looked at yet (R1.2).

    **One transaction per incident, not one per tick.** `ClassifyIncidentUseCase` commits
    its own work, so a tenant with fifty pending incidents and a classifier that dies on the
    thirty-first keeps thirty — and the other twenty come back on the next tick because
    their `ai_classification` is still `NULL` (D3). A single transaction around the loop
    would trade that for an all-or-nothing run of unbounded length.

    Bounded by `batch_size` for the same reason the notification jobs are: a tick has to
    end.
    """

    def __init__(
        self,
        *,
        reader: IncidentQuery,
        classify: "ClassifyIncidentUseCase",
        batch_size: int,
    ) -> None:
        self._reader = reader
        self._classify = classify
        self._batch_size = batch_size

    async def execute(
        self, *, tenant_id: uuid.UUID, now: datetime
    ) -> IncidentClassificationReport:
        report = IncidentClassificationReport(tenant_id=str(tenant_id))
        pending = await self._reader.list_pending_classification(
            tenant_id, limit=self._batch_size
        )

        for incident in pending:
            report.considered += 1
            result = await self._classify.execute(
                tenant_id=tenant_id,
                incident_id=incident.id,
                # D6: no user asked for this, so the audit row goes without an actor.
                actor=None,
                now=now,
            )
            if result.status is IncidentStatus.CLASSIFIED:
                report.classified += 1
            elif result.ai_classification is not None:
                report.low_confidence += 1
            else:
                report.failed += 1

        return report


class TriageIncidentUseCase(_ApprovalGateMixin, _IncidentFlowBase):
    """R1.4, R2.1 — a human fixes the classification, and may put a price on the job.

    This is where D11's **first** gate lives: an `estimated_cost` above
    `TenantConfig.owner_approval_threshold_eur` parks the incident until the owner answers.
    """

    def __init__(
        self,
        *,
        approvals: OwnerApprovalRepository,
        users: UserRepository,
        notifications: NotificationLogRepository,
        configs: TenantConfigRepository,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._approvals = approvals
        self._users = users
        self._notifications = notifications
        self._configs = configs

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        incident_id: uuid.UUID,
        actor: IncidentActor,
        now: datetime,
        category: IncidentCategory | None = None,
        severity: IncidentSeverity | None = None,
        estimated_cost: Decimal | None = None,
    ) -> Incident:
        incident = await self._load_incident(tenant_id, incident_id, actor)
        previous = (incident.category, incident.severity, incident.estimated_cost)

        incident.set_triage(
            category=category, severity=severity, estimated_cost=estimated_cost, now=now
        )

        config = await self._configs.get_or_create(tenant_id, now)
        gate_opened = incident.needs_owner_approval(
            estimated_cost, config.owner_approval_threshold_eur
        )
        if gate_opened:
            incident.require_owner_approval(now=now)

        await self._incidents.save(tenant_id, incident)
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.INCIDENT_TRIAGED,
            entity_type=audit_actions.ENTITY_INCIDENT,
            entity_id=incident.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_INCIDENT)
            .diff("category", previous[0], incident.category)
            .diff("severity", previous[1], incident.severity)
            .diff("estimated_cost", previous[2], incident.estimated_cost)
            .diff("owner_approval_required", False, incident.owner_approval_required),
            now=now,
        )

        if gate_opened:
            await self._open_approval(
                tenant_id=tenant_id,
                incident=incident,
                amount=incident.estimated_cost or Decimal(0),
                related_type=OwnerApprovalRelatedType.INCIDENT,
                actor=actor,
                now=now,
            )

        await self._uow.commit()
        return incident


class RespondOwnerApprovalUseCase(_IncidentFlowBase):
    """R2.4, R2.5, R2.6 — the owner answers, once, and the incident moves accordingly.

    Where the incident goes back to is **derived from the approval's `related_type`** (D11),
    so nothing has to remember where it came from: `INCIDENT` was the budget gate and
    resumes at `CLASSIFIED`; `MAINTENANCE_COST` was the real-cost gate and resumes at
    `IN_PROGRESS`. A rejection cancels the incident and fires `INCIDENT_RESOLVED`, which is
    what brings the property back out of `CRITICAL_INCIDENT` — possible because D9 widened
    that trigger's precondition to accept a cancelled incident.
    """

    def __init__(self, *, approvals: OwnerApprovalRepository, **kwargs) -> None:
        super().__init__(**kwargs)
        self._approvals = approvals

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        approval_id: uuid.UUID,
        status: OwnerApprovalStatus,
        response_notes: str | None,
        actor: IncidentActor,
        now: datetime,
    ) -> Incident:
        if actor.role is not UserRole.TENANT_OWNER:
            # R2.6. The permission already says this (`RESPOND_OWNER_APPROVALS` is the
            # owner's alone), and it is repeated here because the use case is reachable from
            # anything that constructs it — a job, a command, a future route — and only one
            # of those goes through `require()`.
            raise MaintenanceValidationError("Only the tenant owner may answer an approval")

        approval = await self._approvals.get(tenant_id, approval_id)
        if approval is None:
            raise OwnerApprovalNotFoundError()

        incident = await self._incidents.get(tenant_id, approval.related_id)
        if incident is None:
            raise IncidentNotFoundError()

        previous_status = approval.status
        # Raises if it was already answered (R2.6) — before anything else is written.
        approved_cost = approval.answer(
            status=status,
            responded_by=actor.user_id,
            response_notes=response_notes,
            now=now,
        )
        await self._approvals.save(tenant_id, approval)

        if approved_cost is not None:
            incident.resume_after_approval(
                related_type=approval.related_type,
                approved_cost=approved_cost,
                now=now,
            )
        else:
            incident.cancel(now=now)
        await self._incidents.save(tenant_id, incident)

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.OWNER_APPROVAL_ANSWERED,
            entity_type=audit_actions.ENTITY_OWNER_APPROVAL,
            entity_id=approval.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_OWNER_APPROVAL)
            .diff("status", previous_status, approval.status)
            .diff("responded_by", None, approval.responded_by)
            .diff("responded_at", None, approval.responded_at),
            now=now,
        )
        await self._audit.record(
            tenant_id=tenant_id,
            action=(
                audit_actions.INCIDENT_CANCELLED
                if approved_cost is None
                else audit_actions.INCIDENT_RESUMED
            ),
            entity_type=audit_actions.ENTITY_INCIDENT,
            entity_id=incident.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_INCIDENT)
            .diff("status", IncidentStatus.AWAITING_OWNER_APPROVAL, incident.status)
            .diff("approved_cost", None, incident.approved_cost),
            now=now,
        )
        await self._record_timeline(
            tenant_id=tenant_id,
            incident=incident,
            event_type=(
                TimelineEventType.OWNER_APPROVED_EXPENSE
                if approved_cost is not None
                else TimelineEventType.OWNER_REJECTED_EXPENSE
            ),
            actor=actor,
            now=now,
            extra={"owner_approval_id": str(approval.id)},
        )

        if approved_cost is None:
            # R2.5 + D9: the incident is cancelled, so the property has to be recomposed
            # from whatever is left — otherwise a rejected budget strands it in
            # `CRITICAL_INCIDENT` with no trigger able to reach it.
            await self._fire_trigger(
                tenant_id=tenant_id,
                incident=incident,
                trigger=PropertyStateTrigger.INCIDENT_RESOLVED,
                actor=actor,
                now=now,
            )

        await self._uow.commit()
        return incident


class AssignIncidentUseCase(_IncidentFlowBase):
    """R3.1, R3.4, R3.5 — hand the incident to a technician and open their SLA deadline."""

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
        incident_id: uuid.UUID,
        technician_id: uuid.UUID,
        actor: IncidentActor,
        now: datetime,
    ) -> Incident:
        incident = await self._load_incident(tenant_id, incident_id, actor)

        # R3.4: resolved **inside the tenant**, so a neighbour's user id is a 422 and not a
        # row pointing across tenants — `incidents.assigned_technician_id` is a plain FK and
        # the database would accept it.
        candidate = await self._users.get(tenant_id, technician_id)
        if (
            candidate is None
            or candidate.role is not UserRole.TECHNICIAN
            # `ACTIVE` too, which R3.4 does not name: assigning to a deactivated account
            # writes a notification to an address the tenant has stopped using and leaves
            # work nobody will do. The same stricter-but-not-conflicting reading
            # `AssignCleaningTaskUseCase` settled on.
            or candidate.status is not UserStatus.ACTIVE
        ):
            raise InvalidTechnicianError(technician_id)

        previous_technician = incident.assigned_technician_id
        previous_status = incident.status
        incident.assign(technician_id=technician_id, now=now)
        await self._incidents.save(tenant_id, incident)

        if previous_technician is not None:
            # R3.5: the previous assignee's deadline stops being theirs the moment the work
            # is somebody else's. `cancel_sla_deadline` answers "zero rows is normal", so a
            # first assignment costs nothing and this stays a plain unconditional pair.
            await self._notifications.cancel_sla_deadline(
                tenant_id,
                related_type=RELATED_TYPE_INCIDENT,
                related_id=incident.id,
                notification_type=NotificationType.TECHNICIAN_ASSIGNED.value,
            )

        config = await self._configs.get_or_create(tenant_id, now)
        await self._notifications.add(
            tenant_id,
            technician_assignment_notification(
                tenant_id=tenant_id,
                incident_id=incident.id,
                property_id=incident.property_id,
                technician_id=technician_id,
                recipient_contact=candidate.email,
                sla_minutes=sla_minutes_for(incident.severity, config),
                now=now,
            ),
        )

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.INCIDENT_ASSIGNED,
            entity_type=audit_actions.ENTITY_INCIDENT,
            entity_id=incident.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_INCIDENT)
            .diff("assigned_technician_id", previous_technician, technician_id)
            .diff("status", previous_status, incident.status),
            now=now,
        )
        await self._record_timeline(
            tenant_id=tenant_id,
            incident=incident,
            event_type=TimelineEventType.TECHNICIAN_ASSIGNED,
            actor=actor,
            now=now,
            extra={"technician_id": str(technician_id)},
        )

        await self._uow.commit()
        return incident


class _TechnicianStepUseCase(_IncidentFlowBase):
    """The four steps of R4.1 the technician drives, which differ only in three values.

    Who may drive them is `_load_incident`'s job: a `TECHNICIAN` who is not the assignee
    gets the same 404 as for an incident that does not exist (R4.5, R5.3), and a
    `PROPERTY_MANAGER` is unrestricted because R4.5 says so — "un `PROPERTY_MANAGER` sí
    puede, para desatascar".

    None of them moves the property: PRD §12 escalates it when the fault is *classified* and
    recomposes it when the fault is *gone*, and a technician being on their way changes
    neither.
    """

    #: The entity method to call, the audit action, and the timeline event — or `None`.
    _STEP: tuple[str, str, TimelineEventType | None]

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        incident_id: uuid.UUID,
        actor: IncidentActor,
        now: datetime,
    ) -> Incident:
        method, action, event_type = self._STEP
        incident = await self._load_incident(tenant_id, incident_id, actor)

        previous_status = incident.status
        getattr(incident, method)(now=now)
        await self._incidents.save(tenant_id, incident)

        await self._audit.record(
            tenant_id=tenant_id,
            action=action,
            entity_type=audit_actions.ENTITY_INCIDENT,
            entity_id=incident.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_INCIDENT).diff(
                "status", previous_status, incident.status
            ),
            now=now,
        )
        if event_type is not None:
            await self._record_timeline(
                tenant_id=tenant_id,
                incident=incident,
                event_type=event_type,
                actor=actor,
                now=now,
            )

        await self._after_step(tenant_id=tenant_id, incident=incident, now=now)
        await self._uow.commit()
        return incident

    async def _after_step(
        self, *, tenant_id: uuid.UUID, incident: Incident, now: datetime
    ) -> None:
        """Nothing, for three of the four steps."""


class AcceptIncidentUseCase(_TechnicianStepUseCase):
    """R4.1 and R3.3 — taking the job closes the deadline it opened."""

    _STEP = ("accept", audit_actions.INCIDENT_ACCEPTED, TimelineEventType.TECHNICIAN_ACCEPTED)

    def __init__(self, *, notifications: NotificationLogRepository, **kwargs) -> None:
        super().__init__(**kwargs)
        self._notifications = notifications

    async def _after_step(
        self, *, tenant_id: uuid.UUID, incident: Incident, now: datetime
    ) -> None:
        """R3.3: "WHEN el técnico acepta la incidencia, THE SYSTEM SHALL cancelar el plazo
        pendiente" — otherwise `check_sla_breaches` escalates work already accepted."""
        await self._notifications.cancel_sla_deadline(
            tenant_id,
            related_type=RELATED_TYPE_INCIDENT,
            related_id=incident.id,
            notification_type=NotificationType.TECHNICIAN_ASSIGNED.value,
        )


class StartIncidentUseCase(_TechnicianStepUseCase):
    """`ACCEPTED → IN_PROGRESS` (R4.1)."""

    _STEP = ("start", audit_actions.INCIDENT_STARTED, TimelineEventType.TECHNICIAN_STARTED)


class WaitForPartsUseCase(_TechnicianStepUseCase):
    """`IN_PROGRESS → WAITING_EXTERNAL_PARTS` (R4.1).

    **No timeline event, and that is decided rather than missing** (D10): the vocabulary of
    `TimelineEventType` is PRD §10's, none of its members describes waiting for a part, and
    the milestone is already described by the incident's own `status`. Inventing one would
    put an assertion in an append-only table that nothing else in the system makes.
    """

    _STEP = ("wait_for_parts", audit_actions.INCIDENT_WAITING_PARTS, None)


class ResumeWorkUseCase(_TechnicianStepUseCase):
    """`WAITING_EXTERNAL_PARTS → IN_PROGRESS` (R4.1).

    Its audit action is `INCIDENT_STARTED` and its timeline event `TECHNICIAN_STARTED`: work
    resuming is work starting, and a separate verb would split "when did somebody actually
    work on this" across two names.
    """

    _STEP = ("resume_work", audit_actions.INCIDENT_STARTED, TimelineEventType.TECHNICIAN_STARTED)


class ResolveIncidentUseCase(_ApprovalGateMixin, _IncidentFlowBase):
    """R4.2, R4.3 — the technician closes with the real cost, unless it needs approval first.

    This is D11's **second** gate, and the reason it exists is in the proposal's own
    `ASSUMPTION`: the PRD sets the threshold on the *estimated* cost, so without this,
    estimating 90 EUR and spending 500 walks straight past the approval rule.
    """

    def __init__(
        self,
        *,
        approvals: OwnerApprovalRepository,
        users: UserRepository,
        notifications: NotificationLogRepository,
        configs: TenantConfigRepository,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._approvals = approvals
        self._users = users
        self._notifications = notifications
        self._configs = configs

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        incident_id: uuid.UUID,
        final_cost: Decimal,
        actor: IncidentActor,
        now: datetime,
    ) -> Incident:
        incident = await self._load_incident(tenant_id, incident_id, actor)
        config = await self._configs.get_or_create(tenant_id, now)
        previous_status = incident.status

        needs_approval = incident.needs_owner_approval(
            final_cost, config.owner_approval_threshold_eur
        )
        if needs_approval:
            # D11: the cost is written and the incident parks **without `resolved_at`** —
            # the technician said what it cost and the system did not accept the close.
            incident.require_owner_approval(final_cost=final_cost, now=now)
            await self._incidents.save(tenant_id, incident)
            await self._audit.record(
                tenant_id=tenant_id,
                action=audit_actions.INCIDENT_AWAITING_APPROVAL,
                entity_type=audit_actions.ENTITY_INCIDENT,
                entity_id=incident.id,
                actor=actor,
                changes=ChangeSet(audit_actions.ENTITY_INCIDENT)
                .diff("status", previous_status, incident.status)
                .diff("final_cost", None, incident.final_cost)
                .diff("owner_approval_required", False, True),
                now=now,
            )
            await self._open_approval(
                tenant_id=tenant_id,
                incident=incident,
                amount=final_cost,
                related_type=OwnerApprovalRelatedType.MAINTENANCE_COST,
                actor=actor,
                now=now,
            )
            await self._uow.commit()
            return incident

        incident.resolve(final_cost=final_cost, now=now)
        await self._incidents.save(tenant_id, incident)
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.INCIDENT_RESOLVED,
            entity_type=audit_actions.ENTITY_INCIDENT,
            entity_id=incident.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_INCIDENT)
            .diff("status", previous_status, incident.status)
            .diff("final_cost", None, incident.final_cost)
            .diff("resolved_at", None, incident.resolved_at),
            now=now,
        )
        await self._record_timeline(
            tenant_id=tenant_id,
            incident=incident,
            event_type=TimelineEventType.INCIDENT_RESOLVED,
            actor=actor,
            now=now,
        )
        await self._fire_trigger(
            tenant_id=tenant_id,
            incident=incident,
            trigger=PropertyStateTrigger.INCIDENT_RESOLVED,
            actor=actor,
            now=now,
        )

        await self._uow.commit()
        return incident


class CancelIncidentUseCase(_IncidentFlowBase):
    """Terminal from anywhere non-terminal (R4.4), and the property recomposes (D9)."""

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        incident_id: uuid.UUID,
        actor: IncidentActor,
        now: datetime,
    ) -> Incident:
        incident = await self._load_incident(tenant_id, incident_id, actor)
        previous_status = incident.status

        incident.cancel(now=now)
        await self._incidents.save(tenant_id, incident)

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.INCIDENT_CANCELLED,
            entity_type=audit_actions.ENTITY_INCIDENT,
            entity_id=incident.id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_INCIDENT).diff(
                "status", previous_status, incident.status
            ),
            now=now,
        )
        await self._record_timeline(
            tenant_id=tenant_id,
            incident=incident,
            event_type=TimelineEventType.INCIDENT_CANCELLED,
            actor=actor,
            now=now,
        )
        await self._fire_trigger(
            tenant_id=tenant_id,
            incident=incident,
            trigger=PropertyStateTrigger.INCIDENT_RESOLVED,
            actor=actor,
            now=now,
        )

        await self._uow.commit()
        return incident


class ListIncidentsUseCase:
    """`GET /incidents` (R5.1, R5.3).

    **The technician restriction is applied here, into the repository filter**, and never in
    a router: `IncidentActor.restrict_to_technician_id` returns an id for a `TECHNICIAN` and
    `None` for everyone else, and a filter the caller supplied cannot widen it — the use
    case overwrites that field rather than defaulting it.
    """

    def __init__(self, reader: IncidentQuery) -> None:
        self._reader = reader

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor: IncidentActor,
        filters: IncidentFilters,
        page: int,
        per_page: int,
    ) -> IncidentPage:
        restrict = actor.restrict_to_technician_id
        if restrict is not None:
            filters = replace(filters, assigned_technician_id=restrict)
        return await self._reader.list(tenant_id, filters, page=page, per_page=per_page)


class GetIncidentUseCase:
    """`GET /incidents/{id}` (R5.1, R5.3, R5.4).

    A technician who is not the assignee gets `IncidentNotFoundError` — the same error, with
    the same message, as an id that does not exist. Answering 403 there would turn the
    endpoint into a probe for which incidents exist.
    """

    def __init__(self, incidents: IncidentRepository) -> None:
        self._incidents = incidents

    async def execute(
        self, *, tenant_id: uuid.UUID, incident_id: uuid.UUID, actor: IncidentActor
    ) -> Incident:
        incident = await self._incidents.get(tenant_id, incident_id)
        if incident is None:
            raise IncidentNotFoundError()
        restrict = actor.restrict_to_technician_id
        if restrict is not None and incident.assigned_technician_id != restrict:
            raise IncidentNotFoundError()
        return incident
