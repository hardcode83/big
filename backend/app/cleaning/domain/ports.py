"""The ports `cleaning` declares for collaborators outside its own module.

`TaskIncidentReportingPort` (`cleaner-incident-report` D2) is the newest, and it follows the
norm `messaging/domain/ports.py` wrote down for exactly this shape: the port lives in the
**consuming** module and `maintenance` supplies the implementer, because `application/` may
depend on a port of its *own* `domain/` and never on another module's use cases. `cleaning`
already had that bridge running the other way — `BlockingIncidentQuery` below — so this module
now sits on both ends of the same rule.

The provisioning port (design D1 of `cleaning`).

`process_checkouts` has to create the `CleaningTask` **inside the transaction that writes
the transition** (R2.3): a property in `AWAITING_CLEANING` without a task is exactly the
terminal state this change exists to remove, and two transactions can leave one behind.

`AdvancePropertyStatesUseCase` owns that transaction — one commit per tenant, stated in its
own module docstring — so the composition point has to be inside it. It takes this port as
an **optional** collaborator and calls it after each accepted `CHECKOUT_TIME_REACHED`
transition, before committing. `None` leaves `check_checkin_windows` and
`mark_occupied_estimated` exactly as `celery-jobs` left them.

The import direction is the one that module already uses: `properties/application/` imports
`ReservationRepository` from `reservations/domain/` (`use_cases.py:55`).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from app.maintenance.domain.enums import IncidentStatus

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.cleaning.domain.entities import CleaningTask
    from app.properties.domain.entities import Property
    from app.reservations.domain.entities import Reservation


@dataclass(frozen=True)
class IncidentReport:
    """What the cleaner typed, and nothing else (`cleaner-incident-report` D2, D8).

    Two fields because the request schema accepts exactly two (R1.3). Everything else about
    the incident — its source, its property, the task it hangs off, who is acting — is decided
    by the system and travels as its own parameter, so there is no field here a caller could
    use to widen what it is asking for.

    The bounds on these two strings are applied by the request schema that builds this, not
    here — enforcing them needs Pydantic and `domain/` is Pydantic-free. **The values of those
    bounds are not the schema's to invent**: they are `MAX_INCIDENT_TITLE` and
    `MAX_INCIDENT_DESCRIPTION` in `app/maintenance/domain/entities.py`, which is where D7 put
    them precisely so that a second schema binding the same column cannot re-derive its own.
    The guard that makes the text storable at all is `app/core/storable_text.py`.
    """

    title: str
    description: str


@dataclass(frozen=True)
class IncidentReportedAcknowledgement:
    """The three fields the cleaner gets back (R4.4), and no more.

    A mirror of the guest portal's `IncidentReportedResponse`: the id of what was just created,
    its status and when. The cleaner does not read, list or follow incidents (proposal §Out of
    scope), so this is the whole of what this surface may ever say about one.

    `status` is typed as `IncidentStatus` rather than `str`. Importing an enum is not what
    `BlockingIncidentQuery` avoided below — that returned a boolean to keep the **aggregate**
    `Incident` out of this module for a yes/no answer. An enum is a value with no behaviour,
    and it is what makes the operation appear in `openapi.json` with the same schema the
    portal's does instead of a bare string.
    """

    id: uuid.UUID
    status: IncidentStatus
    created_at: datetime


class BlockingIncidentQuery(Protocol):
    async def has_unresolved_critical(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> bool:
        """Whether a `CRITICAL` incident of that property is still open (R5.2).

        A **boolean**, and a port of the cleaning domain rather than a use of the maintenance
        aggregate: `cleaning` only reads incidents for this one precondition (proposal §Out of
        scope), so importing `Incident` here would couple the two domains for a yes/no answer.

        **This used to say `maintenance` had no application layer, so nothing created incidents
        and the answer was always `False` in practice.** Both halves are now false, and the
        second stopped being a curiosity: `maintenance` has had its own flow since 2026-08-15,
        and since `cleaner-incident-report` the cleaner can open an incident from the very task
        whose close this clause guards. So this port now answers `True` in ordinary operation,
        and the coupling it creates is declared behaviour rather than a dormant precondition —
        R6.2 of that change spells it out: an incident is born `MEDIUM` and blocks nothing until
        the classification job raises it to `CRITICAL`.

        The scope is unchanged and deliberately so: `tenant_id` and `property_id`, never the
        task. Narrowing it to the cleaning became *possible* once `incidents.cleaning_task_id`
        existed, and is out of scope precisely because it would **relax** this invariant — a
        `CRITICAL` incident opened by a guest would stop blocking. `tests/cleaning/test_completion_clause_contract.py`
        keeps that honest.
        """
        ...


class TaskIncidentReportingPort(Protocol):
    async def report(
        self,
        *,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        cleaning_task_id: uuid.UUID,
        report: IncidentReport,
        actor_user_id: uuid.UUID,
        ip: str | None,
        now: datetime,
    ) -> IncidentReportedAcknowledgement:
        """Open an incident from the cleaning task the cleaner is working on (R3.1, R4.4).

        **There is no `source` parameter, and that absence is the contract.** R3.1 requires the
        incident to be sealed `IncidentSource.CLEANER` by the writer and never read from the
        request; a port that took the source would move that decision to this module, which is
        the consumer, and let `cleaning` ask for any source in the enum. The implementer seals
        it (D3).

        **`property_id` comes from the resolved task, never from the request** (R1.4). Passing
        it explicitly rather than letting the implementer look it up is what discharges the
        precondition `IncidentRepository.add` states: the foreign keys of `incidents` are
        global rather than composite with `tenant_id`, so the caller must have resolved both it
        and `cleaning_task_id` inside the tenant first. The use case does exactly that before
        calling here (D5).

        **The incident is not classified here** (R3.2). It is born `OPEN`, with no summary and
        no classification, and with the schema's own defaults for category and severity
        (`OTHER` and `MEDIUM` — they are `NOT NULL`, so "unclassified" is a default rather than
        an absence). The classification job fills those in on a later tick; which module owns
        those columns is recorded in the rule-11 census of `sdd/steering/security.md` and not
        restated here.

        `actor_user_id` is a human actor and is required: rule 9 of `steering/security.md`
        exempts only automatic classification from naming one, so an alta without an actor is
        refused and commits nothing (R3.6).
        """
        ...


class CleaningProvisioningPort(Protocol):
    async def provision_for_checkout(
        self,
        *,
        tenant_id: uuid.UUID,
        property: "Property",
        reservation: "Reservation",
        known_reservations: Sequence["Reservation"],
        now: datetime,
    ) -> "CleaningTask | None":
        """Create the cleaning task for a checkout that just happened, or `None`.

        **Returns `None` instead of raising** for every ordinary reason not to create one
        — `TenantConfig.auto_create_cleaning_task` off, `Reservation.cleaning_required`
        false, a live task already there, or no resolvable checklist template (R2.2,
        R2.4, R2.5). The scheduler counts those and moves on; a property whose tenant
        never configured a template must not abort the run for its neighbours, which is
        the same reasoning `AdvancePropertyStatesUseCase` applies to an unresolvable
        reservation time.

        Anything genuinely unexpected still raises, and `run_for_every_tenant` rolls that
        tenant back (`app/scheduler/runner.py:139-148`).

        **Does not commit.** The caller owns the transaction — that is the whole point.

        `known_reservations` is what the caller already loaded for this property in the
        scheduler's candidate window, passed in rather than re-queried: the next confirmed
        stay is what `scheduled_end` comes from (R2.6), and the job has it in hand. It also
        keeps this port free of a `ReservationRepository`.

        **`property` must arrive with `current_operational_state` already advanced to
        `AWAITING_CLEANING`.** The implementation may perform a second transition on it
        (`CLEANER_ASSIGNED` → `CLEANING_SCHEDULED`) when it auto-assigns, and the machine
        reads the state off the entity it is handed.
        """
        ...
