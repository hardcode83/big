"""The provisioning port (design D1).

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
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.cleaning.domain.entities import CleaningTask
    from app.properties.domain.entities import Property
    from app.reservations.domain.entities import Reservation


class BlockingIncidentQuery(Protocol):
    async def has_unresolved_critical(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> bool:
        """Whether a `CRITICAL` incident of that property is still open (R5.2).

        A **boolean**, and a port of the cleaning domain rather than a use of the maintenance
        aggregate: `cleaning` only reads incidents for this one precondition (proposal §Out of
        scope), so importing `Incident` here would couple the two domains for a yes/no answer.

        `maintenance` has no application layer yet, so nothing creates incidents today and this
        always answers `False` in practice. The precondition is still implemented and tested
        against directly-inserted rows — the same treatment the state machine already gives its
        own incident context.
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
