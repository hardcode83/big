"""Cleaning aggregates (PRD §7.9-7.12, §11).

`CleaningTask` is the entity `steering/backend-architecture.md` uses **literally** as its
example of "entidad con invariante real", and this change is where that stops being an
illustration: PRD §11's validation rule ("no completar con checklist a medias") lives in
`complete()` and nowhere else, so no router and no use case can bypass it.

Born in `domain-foundation-ops` as plain dataclasses with no behaviour, which was correct
while nothing wrote these tables. The fields keep their names and types — `PropertyStateMachine`
and `ContextualStateResolver` read `.status`, `.tenant_id` and `.property_id` and are not
touched by this change.
"""

import uuid
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus
from app.cleaning.domain.exceptions import (
    BlockingIncidentError,
    ChecklistIncompleteError,
    CleaningTaskNotFoundError,
    InvalidCleaningTransitionError,
    PhotosIncompleteError,
)
from app.cleaning.domain.value_objects import CleaningCompletionEvidence

# A task that still counts as "this reservation is being taken care of".
#
# **Exactly** the statuses `ContextualStateResolver` treats as pending cleaning
# (`app/properties/domain/state_resolution.py:143-147`), and exactly the set the partial
# index `uq_cleaning_tasks_live_reservation` is built on (design D2).
#
# `PENDING_REVIEW` is deliberately **out**, and an earlier draft had it in. The resolver
# does not count it, so including it here would mean a task that blocks the creation of a
# new one while the property reports "no pending cleaning" — the same class of split-brain
# that made `AWAITING_CLEANING` terminal. Nothing in this change produces `PENDING_REVIEW`
# (`complete()` goes straight to `COMPLETED`); whoever gives it a writer updates both
# places, and `tests/cleaning/test_live_task_index.py` fails until they do.
#
# The correspondence with the index is a real cross-check, not a claim: that test parses
# the predicate out of the model and compares it to this set.
LIVE_STATUSES = frozenset(
    {
        CleaningTaskStatus.CREATED,
        CleaningTaskStatus.ASSIGNED,
        CleaningTaskStatus.ACCEPTED,
        CleaningTaskStatus.IN_PROGRESS,
    }
)

# The statuses from which a cleaner may open an incident (`cleaner-incident-report` R2.5,
# design D6). PRD §12 says "durante checklist", and these are the three in which the task is
# hers and the work is not over.
#
# **By inclusion, and deliberately not as `set(CleaningTaskStatus) - {the three terminal
# ones}`** — the opposite of how `OPEN_INCIDENT_STATUSES` is built in `maintenance`. This is a
# *write* surface belonging to the least privileged role, so a status added tomorrow must not
# become reportable because nobody remembered to exclude it. The asymmetry with that constant
# is the point: there, a status left out of the count is the safe direction; here it is not.
#
# The three that are neither here nor terminal, and why each is out:
#
# * `CREATED` — nobody has been handed the task, so there is no "durante" to speak of; and for
#   the only role holding `EXECUTE_CLEANING_TASKS` it is a 404 before it is a 409 anyway,
#   because `assigned_cleaner_id` is still NULL.
# * `PENDING_REVIEW` and `FAILED` — members of the enum with **no writer** anywhere in the
#   flow (`complete()` goes straight to `COMPLETED` with `validation_status = PASSED`), so
#   they are out by construction rather than by judgement.
#
# Wider than the photo upload, which is `IN_PROGRESS` only, and that is deliberate: a photo is
# evidence of the checklist and exists only while the work is happening, whereas a broken
# boiler is a fact about the flat that the cleaner meets on opening the door.
INCIDENT_REPORTABLE_STATUSES = frozenset(
    {
        CleaningTaskStatus.ASSIGNED,
        CleaningTaskStatus.ACCEPTED,
        CleaningTaskStatus.IN_PROGRESS,
    }
)


@dataclass
class CleaningTask:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    checklist_template_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    reservation_id: uuid.UUID | None = None
    assigned_cleaner_id: uuid.UUID | None = None
    status: CleaningTaskStatus = CleaningTaskStatus.CREATED
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str | None = None
    validation_status: CleaningValidationStatus = CleaningValidationStatus.PENDING
    validated_by_user_id: uuid.UUID | None = None
    validated_at: datetime | None = None

    @property
    def is_live(self) -> bool:
        return self.status in LIVE_STATUSES

    def assign(self, cleaner_id: uuid.UUID, now: datetime) -> None:
        """Hand the task to a cleaner (R3.1, R3.3).

        Legal from `CREATED` and from `ASSIGNED` — a manager reassigning a task the
        cleaner has not answered yet is the ordinary case. NOT legal from `ACCEPTED`:
        someone has already committed to it, and moving it under them silently is a
        different operation than the one this method names.
        """
        self._require_status(
            {CleaningTaskStatus.CREATED, CleaningTaskStatus.ASSIGNED}, "assign"
        )
        self.assigned_cleaner_id = cleaner_id
        self.status = CleaningTaskStatus.ASSIGNED
        self.accepted_at = None
        self.updated_at = now

    def accept(self, cleaner_id: uuid.UUID, now: datetime) -> None:
        """The assigned cleaner takes it (R3.4)."""
        self._require_assignee(cleaner_id)
        self._require_status({CleaningTaskStatus.ASSIGNED}, "accept")
        self.status = CleaningTaskStatus.ACCEPTED
        self.accepted_at = now
        self.updated_at = now

    def reject(self, cleaner_id: uuid.UUID, now: datetime) -> None:
        """The assigned cleaner declines it (R3.5, design D3).

        **Terminal, and `assigned_cleaner_id` stays put**: that column is the record of
        *who* rejected, which is half the value of a rejection. The freeing of the slot
        happens in the replacement task the use case creates — born in `CREATED` with no
        assignee — not by erasing the evidence here.

        The status must be `REJECTED` at the moment `PropertyStateMachine.evaluate` runs
        (`app/properties/domain/state_machine.py:232`), which is why this cannot instead
        return the task to `CREATED`.
        """
        self._require_assignee(cleaner_id)
        self._require_status(
            {CleaningTaskStatus.ASSIGNED, CleaningTaskStatus.ACCEPTED}, "reject"
        )
        self.status = CleaningTaskStatus.REJECTED
        self.updated_at = now

    def start(self, cleaner_id: uuid.UUID, now: datetime) -> None:
        """The cleaner begins (R3.6). Only after accepting — PRD §11's flow is explicit."""
        self._require_assignee(cleaner_id)
        self._require_status({CleaningTaskStatus.ACCEPTED}, "start")
        self.status = CleaningTaskStatus.IN_PROGRESS
        self.started_at = now
        self.updated_at = now

    def complete(
        self, cleaner_id: uuid.UUID, evidence: CleaningCompletionEvidence, now: datetime
    ) -> None:
        """PRD §11's validation rule, and the only place it exists (R5.1, R5.2, R4, design D4).

        **All three of its clauses, since `cleaning-photos-storage`.** They are checked in the
        order the work happens in: the checklist items the cleaner ticks off, then the photos
        that document what was done, then the blocking incident that is a fact about the
        property rather than about the cleaning. Whichever comes first is the one reported, and
        `test_task_lifecycle.py` asserts the order at both of its boundaries — an ordering
        nothing asserts is one the next refactor is free to invert.

        The photo clause used to be absent, and this docstring used to say so and point at the
        proposal's §Out of scope for the gap. That gap is closed: `CleaningCompletionEvidence`
        now carries `required_photo_types` and `uploaded_photo_types` and a task with a
        required photo missing cannot be closed (R4.1). What did **not** change is where the
        rule lives — R4.3 keeps it here, one place, so no router and no use case can bypass it;
        the use case's job is still only to gather the evidence.

        Note what the third clause is *not*: "at least one photo". A template that declares no
        `required: true` photo closes with none at all (R4.5), because `missing_required_...`
        is a set difference and an empty requirement is met by anything, including nothing.

        **Takes `cleaner_id` like the other three.** It did not, and the security reviewer of
        `/sdd:review` was right that it was the only lifecycle method missing the guard: the
        second layer this module documents for itself at `_require_assignee` existed for
        `accept`, `reject` and `start` and not for the one operation that actually closes the
        work. Not reachable today — the route is `CLEANER`-only and the use case filters — but
        "not reachable today" is exactly the premise a defence in depth is not allowed to rest
        on.
        """
        self._require_assignee(cleaner_id)
        self._require_status({CleaningTaskStatus.IN_PROGRESS}, "complete")
        missing = evidence.missing_required_item_ids()
        if missing:
            raise ChecklistIncompleteError(missing)
        missing_photos = evidence.missing_required_photo_types()
        if missing_photos:
            raise PhotosIncompleteError(missing_photos)
        if evidence.has_unresolved_critical_incident:
            raise BlockingIncidentError(
                "An unresolved CRITICAL incident blocks completing this cleaning"
            )
        self.status = CleaningTaskStatus.COMPLETED
        self.completed_at = now
        self.validation_status = CleaningValidationStatus.PASSED
        self.updated_at = now

    def cancel(self, now: datetime, reason: str) -> None:
        """Retire a cleaning that is not going to be completed (R3.1, R3.4, design D9).

        The exit the cycle did not have. REDES11 sat in `CLEANING_IN_PROGRESS` from 16 August
        because the three ways out of that state were `complete()` — which
        `after_cleaning_completion` refuses while a guest is in the flat — or inventing a HIGH
        incident to unfreeze it with false data. Neither `reject` nor any other method applied:
        `reject` is the cleaner's own act and demands `ASSIGNED`/`ACCEPTED`, and this task was
        `IN_PROGRESS`.

        **Allowed from exactly `LIVE_STATUSES`.** `PENDING_REVIEW` is refused although it is not
        terminal, and that is a declared divergence from R3.4's word "terminal" rather than an
        omission: nothing writes it (`complete()` goes straight to `COMPLETED`) and a task that
        reached it has already resolved the property's state, so there is nothing to unstick.

        **No assignee guard, unlike `accept`/`reject`/`start`/`complete`.** Those are things the
        cleaner does; this is a manager retiring someone else's task, so there is no `cleaner_id`
        to match. The authorisation is `MANAGE_CLEANING_TASKS` at the route.

        **`reason` is required even though the machine does not ask for one** —
        `CLEANING_CANCELLED` is not in `PropertyStateMachine`'s `manual` set. Taking away work
        another person was doing is exactly what an `AuditLog` has to be able to explain six
        months later.

        The evidence already gathered is **not** touched: no checklist item and no photo is
        deleted. Three reasons in D9, and the load-bearing one is that photos are objects in a
        store no transaction rolls back, so a partial delete leaves orphans on one side or the
        other depending on where it failed.
        """
        self._require_status(set(LIVE_STATUSES), "cancel")
        if not reason or not reason.strip():
            raise InvalidCleaningTransitionError("Cancelling a cleaning task requires a reason")
        self.status = CleaningTaskStatus.CANCELLED
        self.updated_at = now

    def assert_incident_reportable(self, cleaner_id: uuid.UUID) -> None:
        """May this cleaner open an incident from this task right now? (R2.5, design D6.)

        A **query that raises** rather than a mutation: reporting an incident changes nothing
        about the cleaning, so there is no state to move here. It lives in the entity all the
        same, because which statuses admit the operation is a business rule and
        `steering/backend-architecture.md` puts rules in `domain/` — the use case's job is to
        ask, not to decide.

        **`_require_assignee` first, `_require_status` second, and the order is the security
        property.** A `409` reading "cannot report on a cleaning task in status COMPLETED"
        tells a cleaner the task exists and what it is doing, which is exactly the probe the
        `404` closes; checking the status first would leak that even when the assignee check
        was going to refuse. `_require_assignee`'s own docstring makes the same argument for
        `accept`, `reject` and `start`, and this is the fourth caller of it.
        """
        self._require_assignee(cleaner_id)
        self._require_status(INCIDENT_REPORTABLE_STATUSES, "report an incident on")

    def record_manual_validation(
        self, *, validator_user_id: uuid.UUID, status: CleaningValidationStatus, now: datetime
    ) -> None:
        """A manager's verdict on a finished cleaning (R5.5).

        `PENDING` is not a verdict, so it cannot be recorded as one; `PASSED`, `FAILED`
        and `WAIVED` are.
        """
        self._require_status({CleaningTaskStatus.COMPLETED}, "validate")
        if status is CleaningValidationStatus.PENDING:
            raise InvalidCleaningTransitionError("PENDING is not a validation verdict")
        self.validation_status = status
        self.validated_by_user_id = validator_user_id
        self.validated_at = now
        self.updated_at = now

    def _require_status(
        self, allowed: AbstractSet[CleaningTaskStatus], operation: str
    ) -> None:
        if self.status not in allowed:
            raise InvalidCleaningTransitionError(
                f"Cannot {operation} a cleaning task in status {self.status.value}"
            )

    def _require_assignee(self, cleaner_id: uuid.UUID) -> None:
        """Not yours → it does not exist (R7.2, R7.3).

        **Raises `CleaningTaskNotFoundError`, not a transition error, and runs before
        `_require_status`.** Both halves matter and the security panel of section 1 found
        them: a 409 saying "cannot accept a task in status ACCEPTED" tells an unrelated
        cleaner that the task exists *and* what it is doing, which is precisely the probe
        R7.3 closes by answering 404 instead of 403. Checking the status first leaked it
        even when the assignee check would have refused.

        The use case resolves tasks with `restrict_to_cleaner_id` (design D7), so in
        practice this fires only if that filter is ever dropped — which is exactly why it
        must fail the same way the filter does, and not more loudly.
        """
        if self.assigned_cleaner_id != cleaner_id:
            # No argument: the message is the same constant an unknown id produces. A body
            # saying "not assigned to you" would confirm the task exists and belongs to
            # someone else — the probe R7.3 closes, one layer below the status code.
            raise CleaningTaskNotFoundError()


@dataclass
class CleaningChecklistTemplate:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    items: list[dict[str, Any]]
    required_photos: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    property_id: uuid.UUID | None = None
    active: bool = True


@dataclass
class CleaningChecklistCompletion:
    id: uuid.UUID
    cleaning_task_id: uuid.UUID
    item_id: str
    completed: bool = False
    completed_at: datetime | None = None
    completed_by: uuid.UUID | None = None
    notes: str | None = None


@dataclass
class CleaningPhoto:
    id: uuid.UUID
    cleaning_task_id: uuid.UUID
    uploaded_by: uuid.UUID
    photo_type: str
    storage_key: str
    created_at: datetime
    ai_validation_result: dict[str, Any] | None = None
