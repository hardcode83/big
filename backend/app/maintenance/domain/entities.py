import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, Mapping

from app.auth.domain.enums import UserRole
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentPhotoStage,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)
from app.maintenance.domain.exceptions import (
    IncidentAlreadyClosedError,
    IncidentBlockedByPendingApprovalError,
    InvalidIncidentTransitionError,
    MaintenanceValidationError,
    OwnerApprovalAlreadyAnsweredError,
)
from app.maintenance.domain.value_objects import IncidentClassification


# ASSUMPTION (`dashboard-api` R2.3): the PRD does not define which `IncidentStatus` values
# count as "open". PRD §9.1 asks the card for an open-incident count and §9.2 for the list,
# without saying where the line falls, so it is drawn here — by exclusion, which is the
# form that survives the enum growing: a status added later is open until someone decides
# otherwise, and that is the safe direction for a count an operator acts on.
#
# `RESOLVED` and `CANCELLED` are the two terminal values of `IncidentStatus`.
# `WAITING_EXTERNAL_PARTS` is deliberately open — the flat still has a broken thing in it.
#
# It lives in `domain/` beside the entity, the way `LIVE_STATUSES` does in `cleaning`, so
# the rule has one home rather than a copy in each query that needs it. The `maintenance`
# change owns it from here on; if its flow disagrees, it changes this constant, not a
# `WHERE` clause somewhere.
CLOSED_INCIDENT_STATUSES = frozenset(
    {IncidentStatus.RESOLVED, IncidentStatus.CANCELLED}
)
OPEN_INCIDENT_STATUSES = frozenset(IncidentStatus) - CLOSED_INCIDENT_STATUSES

#: The statuses in which an incident accepts a photo (`incident-photos` R2.4, design D6).
#:
#: The two in which the technician's work is actually under way. It is **not**
#: `OPEN_INCIDENT_STATUSES`: an incident that is merely `CLASSIFIED` or `ASSIGNED` has nobody
#: on site yet, and evidence filed before the work starts is evidence of nothing.
#:
#: `WAITING_EXTERNAL_PARTS` is in, for the same reason `CLOSED_INCIDENT_STATUSES` leaves it
#: out: the flat still has a broken thing in it, and a technician waiting on a part may well
#: photograph what is missing.
#:
#: Lives here beside the other two so the rule has one home rather than a literal tuple inside
#: `ensure_accepts_photo`.
PHOTO_ACCEPTING_INCIDENT_STATUSES = frozenset(
    {IncidentStatus.IN_PROGRESS, IncidentStatus.WAITING_EXTERNAL_PARTS}
)

#: What `ai_classification["adapter"]` says when the name it was given is not a closed
#: token. `incidents.ai_classification` is a rule-11 sink of `steering/security.md` under
#: the **structured form by default** (D4: "guarda sólo valores cerrados y números"), and
#: `adapter` is the one of its five keys whose value is not an enum, a number or a
#: timestamp — so without this it is a free-text column with an enum-sounding name, which
#: is exactly how `webhook_events.event_type` got into the census late. Same remedy as
#: there: a closed form, and what does not fit degrades to a constant.
UNKNOWN_CLASSIFIER_ADAPTER = "UNKNOWN_CLASSIFIER"

#: The shortest run of characters an adapter's `summary` may not share with the text it was
#: given. Eight, because that is long enough to be a document number, an IBAN fragment or a
#: password, and short enough that no ordinary Spanish or English word reaches it by
#: coincidence — the check is aimed at the **values** rule 3 of `steering/security.md`
#: enumerates, not at prose resemblance.
#:
#: **What it does not catch, measured rather than assumed** (security panel of section 6): a
#: short code echoed on its own — a four-digit door code — passes, because eight characters
#: is above it. That is the price of the length, and lowering it is worse: the guard starts
#: eating ordinary words and degrades into always-dropping, which is a guard nobody can
#: trust. The real closer is still the admission condition task 9.1 writes into the census —
#: an adapter is admitted with a closed vocabulary and its test. This is the net.
_ECHO_RUN_LENGTH = 8


#: The closed set of titles an incident derived from a guest conversation may carry (R4.6,
#: design D13).
#:
#: `incidents.title` is a rule-11 sink and *we* compose it, so it goes in closed form; the
#: guest's own words go to `description`, verbatim, where excepción 2 covers them because the
#: value is not ours.
#:
#: **It lives here, and not in the module that opens the incident.** The census in
#: `steering/security.md` is organised by writer, and it is the only place that says which
#: module that is for this column; what is local — and the reason the catalogue sits beside the
#: entity — is that a caller free to bring its own vocabulary would make the closed form
#: unenforceable from the side that has to guarantee it. `messaging` still decides
#: *which* conversation intent opens an incident and therefore which of these titles it asks
#: for — that mapping is its own, and `tests/maintenance/test_report_incident_from_conversation.py`
#: pins the two together so neither can drift.
CONVERSATION_INCIDENT_TITLES: frozenset[str] = frozenset(
    {
        "Maintenance issue reported in a guest conversation",
        "Access problem reported in a guest conversation",
    }
)


#: `incidents.title` is `VARCHAR(300)`, and a value that does not fit dies at the driver and
#: aborts the transaction. Bounded so an over-long title is a `422` instead.
#:
#: **Here, and not inside a request schema that uses it** (`cleaner-incident-report` D7): this
#: module is where the column lives — the entity below, and its DDL next door in
#: `maintenance/infrastructure/models.py` — so this is where its width can be kept true to what
#: the database will actually take. It began in `guests/api/portal_schemas.py`, back
#: when a single schema was the only thing that needed it; a constant living inside one schema
#: makes any second binder's copy one nobody keeps in step.
MAX_INCIDENT_TITLE = 300
#: `incidents.description` is unbounded `TEXT`, so nothing downstream refuses a large value —
#: this constant is the whole bound. 5000 is the house figure for a free-text field a person
#: writes (`properties.MAX_NOTES`, `reservations.MAX_TEXT`), and somebody describing a broken
#: boiler needs far less.
#:
#: **Added by the security panel of section 7 of `guest-portal-api`, and the reasoning is worth
#: keeping.** The first version left it unbounded, arguing the body ceiling was the bound. It is
#: not the right bound: the ceiling is per *request*, while that change's per-token budget is 60
#: requests a minute, so one link holder could sustain tens of MiB a minute into a column with no
#: maximum, on a write it deliberately does not deduplicate. `title` was already capped against
#: the same class of abuse; the asymmetry was the bug.
MAX_INCIDENT_DESCRIPTION = 5000
#: `incidents.materials` is `VARCHAR(2000)`, and the bound lives here for the reason the two
#: above do: this module owns the column — the entity below and its DDL next door in
#: `maintenance/infrastructure/models.py` — so this is where the width can be kept true to what
#: the database will take. `api/schemas.py` imports it rather than repeating a literal.
#:
#: 2000 and not 5000: it is the figure `incidents.assignment_note` already uses for a bounded
#: note a person types about one job, and a list of parts is shorter than a description of a
#: fault.
MAX_MATERIALS = 2000
#: `incident_messages.content` is `VARCHAR(2000)` (`staff-messaging` design D5), the mirror
#: of `cleaning`'s `MAX_CLEANING_TASK_MESSAGE_LENGTH`. This module owns the column — the
#: entity below and its DDL next door in `maintenance/infrastructure/models.py` — so this is
#: where the width lives; `api/schemas.py` imports it rather than repeating a literal.
MAX_INCIDENT_MESSAGE_LENGTH = 2000


@dataclass
class Incident:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    source: IncidentSource
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
    reservation_id: uuid.UUID | None = None
    reported_by_user_id: uuid.UUID | None = None
    #: The cleaning task during which the incident was reported, when it was reported from
    #: one (`cleaner-incident-report` R4.1). `None` for every other source — the guest
    #: portal, a conversation and the demo seed stay valid without it (R4.2).
    cleaning_task_id: uuid.UUID | None = None
    reported_by_guest_token: str | None = None
    category: IncidentCategory = IncidentCategory.OTHER
    severity: IncidentSeverity = IncidentSeverity.MEDIUM
    status: IncidentStatus = IncidentStatus.OPEN
    ai_summary: str | None = None
    ai_classification: dict[str, Any] | None = None
    assigned_technician_id: uuid.UUID | None = None
    #: What the manager wrote for the technician when handing over the job. Belongs to the
    #: **current** assignment, not to the incident: `assign` writes it every time, so a
    #: reassignment that carries no note leaves none behind (D7).
    assignment_note: str | None = None
    #: When the technician says they will arrive (R3.1). Belongs to the **current**
    #: assignment like `assignment_note`: `assign` and `reject` both clear it, so an hour
    #: promised by whoever is no longer on the job cannot outlive them (R3.5, D2).
    eta_at: datetime | None = None
    owner_approval_required: bool = False
    estimated_cost: Decimal | None = None
    approved_cost: Decimal | None = None
    final_cost: Decimal | None = None
    #: What the technician says they put in, typed on closing (R4.1). Free text this module
    #: stores verbatim — a rule-11 sink of `steering/security.md` under excepción 3 — so it is
    #: deliberately **outside** `AUDITABLE_FIELDS["INCIDENT"]` and never reaches a timeline
    #: `metadata` (R4.6). It explains `final_cost` and is never derived from it (R4.4).
    materials: str | None = None
    resolved_at: datetime | None = None

    #: The legal moves of an incident, as `operation -> (origins it accepts, destination)`
    #: (R4.1, R4.4, design D5). Single authority on the order of the flow: every method
    #: below asks it before touching a field, which is what makes R4.4 ("rechazar cualquier
    #: transición fuera del orden declarado") true once instead of once per endpoint.
    #:
    #: **Keyed by operation and not by `origin -> {destinations}`**, because two different
    #: operations legitimately share a destination and must not thereby inherit each
    #: other's origins: `AWAITING_OWNER_APPROVAL → CLASSIFIED` is `resume_after_approval`'s
    #: and `classify` must still refuse it, exactly as `ACCEPTED → IN_PROGRESS` is
    #: `en_route`'s and not `resume_work`'s. A pair-keyed table cannot express that and
    #: silently accepted eight moves the flow forbids.
    #:
    #: `resume_after_approval` appears twice because D11 derives its destination from the
    #: approval's `related_type`. Neither terminal status appears as an origin anywhere,
    #: which is what makes `RESOLVED`/`CANCELLED` terminal without a rule of their own.
    _TRANSITIONS: ClassVar[
        Mapping[str, tuple[frozenset[IncidentStatus], IncidentStatus]]
    ] = {
        "classify": (frozenset({IncidentStatus.OPEN}), IncidentStatus.CLASSIFIED),
        "require_owner_approval": (
            frozenset({IncidentStatus.CLASSIFIED, IncidentStatus.IN_PROGRESS}),
            IncidentStatus.AWAITING_OWNER_APPROVAL,
        ),
        "resume_after_approval:INCIDENT": (
            frozenset({IncidentStatus.AWAITING_OWNER_APPROVAL}),
            IncidentStatus.CLASSIFIED,
        ),
        "resume_after_approval:MAINTENANCE_COST": (
            frozenset({IncidentStatus.AWAITING_OWNER_APPROVAL}),
            IncidentStatus.IN_PROGRESS,
        ),
        # R3.5: reassigning any non-terminal incident, which is why every status the
        # technician cycle passes through is an origin here.
        "assign": (
            frozenset(
                {
                    IncidentStatus.CLASSIFIED,
                    IncidentStatus.ASSIGNED,
                    IncidentStatus.ACCEPTED,
                    IncidentStatus.IN_PROGRESS,
                    IncidentStatus.WAITING_EXTERNAL_PARTS,
                }
            ),
            IncidentStatus.ASSIGNED,
        ),
        "accept": (frozenset({IncidentStatus.ASSIGNED}), IncidentStatus.ACCEPTED),
        # R1.1: the technician says no and the incident goes back to where `assign` picks
        # things up.
        #
        # ASSUMPTION: the destination is not in the PRD. `CLASSIFIED` is chosen because it is
        # the origin `assign` already distributes from and because it is not terminal — that
        # is `cancel`, which is the manager's, and the fault is still there for somebody else
        # to fix. Recorded as the `ASSUMPTION` of R1 in the change's `proposal.md`.
        "reject": (
            frozenset({IncidentStatus.ASSIGNED, IncidentStatus.ACCEPTED}),
            IncidentStatus.CLASSIFIED,
        ),
        "en_route": (frozenset({IncidentStatus.ACCEPTED}), IncidentStatus.IN_PROGRESS),
        "wait_for_parts": (
            frozenset({IncidentStatus.IN_PROGRESS}),
            IncidentStatus.WAITING_EXTERNAL_PARTS,
        ),
        "resume_work": (
            frozenset({IncidentStatus.WAITING_EXTERNAL_PARTS}),
            IncidentStatus.IN_PROGRESS,
        ),
        "resolve": (frozenset({IncidentStatus.IN_PROGRESS}), IncidentStatus.RESOLVED),
        "cancel": (
            frozenset(set(IncidentStatus) - CLOSED_INCIDENT_STATUSES),
            IncidentStatus.CANCELLED,
        ),
    }

    def _check_transition(self, operation: str) -> IncidentStatus:
        """Validate without mutating, so a refusal leaves the entity untouched (R4.4).

        Returns the destination, so a caller that mutates other fields first can do it
        knowing the move is legal.

        Three refusals rather than one, because they mean different things to whoever gets
        the 409: a closed incident will never admit any move, one awaiting the owner is
        waiting for a specific answer, and anything else is a step taken out of order.
        """
        origins, target = self._TRANSITIONS[operation]
        if self.status in origins:
            return target

        self._refuse_if_closed_or_awaiting_owner()
        raise InvalidIncidentTransitionError(
            f"Incident cannot move from {self.status.value} to {target.value}"
        )

    def _refuse_if_closed_or_awaiting_owner(self) -> None:
        """The two refusals that mean something more specific than "out of order", in order.

        Extracted from `_check_transition` by `incident-photos` (design D6) so that the order
        has **one home**: `ensure_accepts_photo` below has to produce the same three
        distinguishable refusals, and a second copy of this sequence is the thing that would
        eventually disagree with the first.

        The order is the content. A closed incident is checked first because it will never
        admit anything, so reporting "out of order" would invite waiting for a state that is
        never coming; one awaiting the owner is second because it is blocked on a specific
        answer from a specific person, which is actionable. Whatever survives both is a step
        taken out of sequence, and that refusal belongs to the caller — it is the only one of
        the three whose message depends on where the caller was trying to go.

        Returns `None` and mutates nothing: both callers validate before touching a field.
        """
        if self.status in CLOSED_INCIDENT_STATUSES:
            raise IncidentAlreadyClosedError(
                f"Incident is already {self.status.value} and admits no further transition"
            )
        if self.status is IncidentStatus.AWAITING_OWNER_APPROVAL:
            raise IncidentBlockedByPendingApprovalError(
                "Incident is waiting for the owner to answer an approval request"
            )

    def ensure_accepts_photo(self) -> None:
        """Refuse unless this incident is in a state where the technician's work is under way.

        R2.4/R2.5/R2.6 and design D6. **Does not mutate**: uploading a photo is evidence, not
        a lifecycle step, so there is no row for it in `_TRANSITIONS` and nothing here moves
        the status. D6 rejected adding such a row outright — a table of transitions with a
        non-transition inside it lies about what it is.

        Three distinguishable refusals, sharing their order with `_check_transition` through
        `_refuse_if_closed_or_awaiting_owner`:

        1. `RESOLVED`/`CANCELLED` → `IncidentAlreadyClosedError` (R2.6);
        2. `AWAITING_OWNER_APPROVAL` → `IncidentBlockedByPendingApprovalError` (R2.5);
        3. anything that is neither `IN_PROGRESS` nor `WAITING_EXTERNAL_PARTS` →
           `InvalidIncidentTransitionError` (R2.4).

        All three are already `409 CONFLICT` with distinct messages in
        `app/maintenance/api/errors.py`, so this needs no new error class and does not touch
        the module's published error contract.

        `WAITING_EXTERNAL_PARTS` accepts photos deliberately: the flat still has a broken thing
        in it, and a technician waiting on a part may well photograph what is missing. That is
        the same reason `CLOSED_INCIDENT_STATUSES` leaves it out.
        """
        self._refuse_if_closed_or_awaiting_owner()
        if self.status not in PHOTO_ACCEPTING_INCIDENT_STATUSES:
            raise InvalidIncidentTransitionError(
                f"Cannot attach a photo to an incident in status {self.status.value}"
            )

    def _transition(self, operation: str, now: datetime) -> None:
        self.status = self._check_transition(operation)
        self.updated_at = now

    def _reject_if_closed(self) -> None:
        if self.status in CLOSED_INCIDENT_STATUSES:
            raise IncidentAlreadyClosedError(
                f"Incident is already {self.status.value} and cannot be edited"
            )

    def classify(
        self,
        classification: IncidentClassification,
        *,
        confidence_threshold: Decimal,
        adapter: str,
        now: datetime,
    ) -> None:
        """Apply what the classifier returned (R1.2, R1.3, R1.5; design D3).

        Above the threshold the incident becomes `CLASSIFIED` with the adapter's category,
        severity and summary. Below it the incident **stays `OPEN` with its default
        category and severity**, but `ai_classification` is written anyway: that is what
        tells "confidence too low, a human must triage" apart from "never looked at", and
        it is what keeps the job of D2 from retrying a verdict that will not change.

        `title` and `description` are never touched (R1.5).
        """
        self._check_transition("classify")

        # Closed values and numbers only — the structured form rule 11 of
        # `steering/security.md` requires of this column (D4). Never the incident's text.
        self.ai_classification = {
            "category": classification.category.value,
            "severity": classification.severity.value,
            "confidence": str(classification.confidence),
            "adapter": adapter if adapter.isidentifier() else UNKNOWN_CLASSIFIER_ADAPTER,
            "classified_at": now.isoformat(),
        }
        if classification.confidence < confidence_threshold:
            self.updated_at = now
            return

        self.category = classification.category
        self.severity = classification.severity
        self.ai_summary = self._non_echoing(classification.summary)
        self._transition("classify", now)

    def _non_echoing(self, summary: str) -> str | None:
        """Refuse a `summary` that repeats a long run of the reported text (D4).

        D4 closes `incidents.ai_summary` **by contract** — "el `summary` que devuelve un
        adaptador no puede ser un eco de `title` ni de `description`" — and until the
        security panel of section 6 that contract was a docstring on the port plus one
        adapter that happened to honour it. The day a real provider paraphrases, the guest's
        document number lands in a column excepción 2 does not cover, readable by everyone
        holding `READ_INCIDENTS`.

        Dropping the summary rather than raising: the classification itself — category,
        severity, confidence — is good and R1.6 says an incident must not be lost over a
        classifier's misbehaviour. What is refused is the one field that could carry the
        value, and its absence is visible to whoever looks.
        """
        haystack = f"{self.title} {self.description}".lower()
        candidate = summary.lower()
        for start in range(len(candidate) - _ECHO_RUN_LENGTH + 1):
            if candidate[start : start + _ECHO_RUN_LENGTH] in haystack:
                return None
        return summary

    def set_triage(
        self,
        *,
        now: datetime,
        category: IncidentCategory | None = None,
        severity: IncidentSeverity | None = None,
        estimated_cost: Decimal | None = None,
    ) -> None:
        """Let a human fix what the classifier got wrong (R1.4) and cost the job.

        No transition: triage annotates an incident wherever it is in the flow, and the
        only bar is that it is not closed. Whether the new `estimated_cost` opens the
        owner-approval gate is D11's decision and belongs to the use case; what this method
        guarantees is that the fields move together with `updated_at`.
        """
        self._reject_if_closed()
        if estimated_cost is not None and estimated_cost < 0:
            raise MaintenanceValidationError("Estimated cost cannot be negative")

        if category is not None:
            self.category = category
        if severity is not None:
            self.severity = severity
        if estimated_cost is not None:
            self.estimated_cost = estimated_cost
        self.updated_at = now

    def require_owner_approval(
        self,
        *,
        now: datetime,
        final_cost: Decimal | None = None,
        materials: str | None = None,
    ) -> None:
        """Park the incident until the owner answers (R2.1, R4.3; design D11).

        The same method for both gates — the budget one from `CLASSIFIED` and the real-cost
        one from `IN_PROGRESS` — because the incident lives them identically. Which one it
        was is recorded on the `OwnerApproval`'s `related_type`, and that is what
        `resume_after_approval` reads back.

        The second gate passes `final_cost`: the technician's number is written, and
        `resolved_at` is **not** (D11) — the system did not accept the close.

        It passes `materials` for the same reason and with the same shape (R4.3, D7): both are
        optional and both **preserve** rather than replace, so the repeat close after the owner
        answers cannot silently wipe the description of a spend already declared.
        """
        self._check_transition("require_owner_approval")
        if final_cost is not None and final_cost < 0:
            raise MaintenanceValidationError("Final cost cannot be negative")

        if final_cost is not None:
            self.final_cost = final_cost
        # R4.3: the second gate keeps what the technician declared. Written only when it
        # comes, so the repeat close after the owner's answer cannot erase it (D7).
        if materials is not None:
            self.materials = materials
        self.owner_approval_required = True
        self._transition("require_owner_approval", now)

    def resume_after_approval(
        self,
        *,
        related_type: OwnerApprovalRelatedType,
        approved_cost: Decimal,
        now: datetime,
    ) -> None:
        """Put an approved incident back where it was, derived from `related_type` (D11).

        `INCIDENT` was the budget gate, so the incident goes back to `CLASSIFIED` and waits
        for an assignment; `MAINTENANCE_COST` was the real-cost gate, so it goes back to
        `IN_PROGRESS` and the technician retries the close. Nothing records "where it came
        from" — the approval already does.

        **`approved_cost` must be what `OwnerApproval.answer` returned**, which is that
        approval's own `amount` (R2.4). This method cannot verify it — the approval is a
        different aggregate — so tying the two together is the caller's job in
        `application/`; what is checked here is the one thing an incident knows on its own,
        that a cost is not negative, which is the refusal `set_triage`,
        `require_owner_approval` and `resolve` already make.
        """
        operation = f"resume_after_approval:{related_type.value}"
        if operation not in self._TRANSITIONS:
            raise MaintenanceValidationError(
                f"Approval of type {related_type.value} does not resume an incident"
            )
        self._check_transition(operation)
        if approved_cost < 0:
            raise MaintenanceValidationError("Approved cost cannot be negative")

        self.approved_cost = approved_cost
        self._transition(operation, now)

    def _apply_eta(self, eta_at: datetime | None, now: datetime) -> None:
        """Validate and write the technician's promised hour (R3.3, R3.4; design D6).

        `None` means "the body did not carry one", so it returns without touching anything —
        which is what makes R3.3 ("deja el valor anterior intacto") fall out rather than need
        an absent-versus-null sentinel.

        Two refusals, both `MaintenanceValidationError` so the router answers `422`:

        * **Naïve or offsetless.** Not in R3.4's letter and load-bearing anyway: comparing an
          aware `now` with a naïve value raises `TypeError`, which leaves the endpoint as an
          undeclared `500`. `utcoffset()` is checked beside `tzinfo` because a `tzinfo`
          returning `None` from it is just as unusable.
        * **Strictly before `now`.** The boundary itself passes — a technician saying "I am
          here now" is not an error.

        The rule lives here and not in the request schema because the reference instant is the
        router's `now_utc()` and a business rule in a DTO leaves every non-HTTP caller
        (`seed_demo`, the tests) without it (D6).
        """
        if eta_at is None:
            return
        if eta_at.tzinfo is None or eta_at.utcoffset() is None:
            raise MaintenanceValidationError("ETA must carry a timezone")
        if eta_at < now:
            raise MaintenanceValidationError("ETA cannot be in the past")
        self.eta_at = eta_at

    def assign(
        self,
        *,
        technician_id: uuid.UUID,
        now: datetime,
        assignment_note: str | None = None,
    ) -> None:
        """Hand the incident to a technician, or to a different one (R3.1, R3.5).

        The assignee's role and tenant are checked by the use case against
        `UserRepository`: this entity cannot read users, and a domain object that took a
        `User` to validate one field would drag the `auth` aggregate in behind it.

        `assignment_note` is written **every time**, so an assignment that carries none
        leaves none behind (`tech-incident-context` D7). The note belongs to the assignment
        in force, not to the incident: `assign` accepts five origins, so preserving it would
        show technician B what the manager wrote for technician A, and an obsolete note
        presented as current is worse than no note. It also avoids the "absent vs. sent as
        null" sentinel `UpdatePropertyRequest._reject_explicit_nulls` had to build — this is
        a complete operation, not a patch.
        """
        self._check_transition("assign")

        self.assigned_technician_id = technician_id
        self.assignment_note = assignment_note
        # R3.5, and unconditionally for `assignment_note`'s reason: the ETA belongs to the
        # assignment in force, so technician B does not inherit the hour technician A promised.
        self.eta_at = None
        self._transition("assign", now)

    def accept(self, *, now: datetime, eta_at: datetime | None = None) -> None:
        """The technician takes the job (R4.1), optionally saying when they will arrive (R3.2).

        Cancelling the SLA deadline is R3.3's, and belongs to the use case that owns the
        notification rows.

        `_apply_eta` runs **after** `_check_transition` and **before** `_transition`: a step
        out of order is refused before any field moves (R1.8's discipline), and a bad ETA is
        refused before the status changes.
        """
        self._check_transition("accept")
        self._apply_eta(eta_at, now)
        self._transition("accept", now)

    def reject(self, *, now: datetime) -> None:
        """The technician refuses the job, and it goes back to the manager (R1.1, R1.2; D2).

        Clears **all three** fields of the assignment in force, not only the assignee R1.2
        names: `eta_at` and `assignment_note` belong to the assignment too, so an incident
        that is `CLASSIFIED` and unowned must not keep the note written for whoever said no
        nor the hour they promised. Who refused is not lost — the use case audits
        `assigned_technician_id` with its previous value, and the timeline event carries the
        identifier.

        Ordered so R1.8 holds: `_check_transition` first, so a refusal from any other status
        raises without a field having moved.
        """
        self._check_transition("reject")

        self.assigned_technician_id = None
        self.eta_at = None
        self.assignment_note = None
        self._transition("reject", now)

    def en_route(self, *, now: datetime, eta_at: datetime | None = None) -> None:
        """The technician is on their way: `ACCEPTED → IN_PROGRESS` (R2.1).

        Called `start` until `tech-cycle-completion` renamed it (D4). Origins and destination
        are untouched — PRD §12 draws this very move as "Técnico en ruta → status
        IN_PROGRESS" — and what changed is the name and the timeline event the use case
        writes, so `TECHNICIAN_EN_ROUTE` stops being a member of the vocabulary nobody
        writes. `resume_work` keeps `TECHNICIAN_STARTED`, so nothing is orphaned.

        Takes an optional `eta_at` (R3.2), applied in the same order `accept` uses: transition
        checked, ETA validated, then the status moves.
        """
        self._check_transition("en_route")
        self._apply_eta(eta_at, now)
        self._transition("en_route", now)

    def wait_for_parts(self, *, now: datetime) -> None:
        """`IN_PROGRESS → WAITING_EXTERNAL_PARTS` (R4.1).

        Deliberately open, not closed: `OPEN_INCIDENT_STATUSES` counts it, because the flat
        still has a broken thing in it.
        """
        self._transition("wait_for_parts", now)

    def resume_work(self, *, now: datetime) -> None:
        """`WAITING_EXTERNAL_PARTS → IN_PROGRESS` (R4.1)."""
        self._transition("resume_work", now)

    def resolve(
        self, *, final_cost: Decimal, now: datetime, materials: str | None = None
    ) -> None:
        """Close the incident with what it actually cost (R4.2).

        `final_cost` is mandatory — the signature is where R4.2 is enforced. Whether that
        cost needs the owner's blessing first is D11's second gate and is decided by the
        use case *before* calling this: an incident that reaches here is one that may close.
        """
        self._check_transition("resolve")
        if final_cost < 0:
            raise MaintenanceValidationError("Final cost cannot be negative")

        self.final_cost = final_cost
        if materials is not None:
            self.materials = materials
        self.resolved_at = now
        self._transition("resolve", now)

    def cancel(self, *, now: datetime) -> None:
        """Terminal, from anywhere that is not already terminal (R2.5, R4.4)."""
        self._transition("cancel", now)

    def needs_owner_approval(self, cost: Decimal | None, threshold: Decimal) -> bool:
        """Whether this cost has to go past the owner first (R2.1, R4.3; design D11).

        The threshold rule of PRD §12, and it lives here rather than in the two use cases
        that ask it. It was a bare `cost > threshold` in both of them until the
        architecture panel of section 6 pointed at the steering rule it breaks — "No lógica
        de negocio en `application/`: si hay una regla (no solo un paso de orquestación),
        pertenece a `domain/`" — and it is a rule, not a step: strictly greater, no cost at
        all is no gate, and an already-approved budget that covers the bill is no gate
        either.
        """
        if cost is None:
            return False
        return cost > threshold and not self.is_covered_by_approval(cost)

    def is_covered_by_approval(self, final_cost: Decimal) -> bool:
        """Whether an already-approved budget covers this cost (R4.3, D11).

        The literal formula of D11 — an incident with no approved cost is covered by
        nothing, and an approval for less than the bill does not stretch.
        """
        return self.approved_cost is not None and final_cost <= self.approved_cost


@dataclass
class OwnerApproval:
    """No created_at/updated_at: §7.19 declares requested_at/responded_at only.

    Strict fidelity to the PRD, decided in the design gate (OQ1). It makes this the
    only editable table in the schema without `updated_at` — an automatic expiry
    leaves no timestamp — so `maintenance` adds one if its approval flow needs it.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    related_type: OwnerApprovalRelatedType
    related_id: uuid.UUID
    amount: Decimal
    reason: str
    requested_at: datetime
    status: OwnerApprovalStatus = OwnerApprovalStatus.PENDING
    responded_at: datetime | None = None
    responded_by: uuid.UUID | None = None
    response_notes: str | None = None

    #: The only two answers a person can give. `PENDING` is the absence of an answer and
    #: `EXPIRED` is out of scope for this change (proposal §Out of scope), so neither is a
    #: value `answer` accepts — offering them would let a caller un-answer an approval.
    _ANSWERS: ClassVar[frozenset[OwnerApprovalStatus]] = frozenset(
        {OwnerApprovalStatus.APPROVED, OwnerApprovalStatus.REJECTED}
    )

    def answer(
        self,
        *,
        status: OwnerApprovalStatus,
        responded_by: uuid.UUID,
        response_notes: str | None,
        now: datetime,
    ) -> Decimal | None:
        """Record the owner's decision, once (R2.4, R2.6).

        Returns **the cost the incident may now commit to** — `amount` when approved, and
        `None` when rejected. That is what "IF la respuesta es `APPROVED`, THEN SHALL fijar
        `approved_cost`" means one aggregate over: the approval knows the number, and the
        incident is where it is applied, so the two are not written by the same object.

        The guard is on `status is PENDING` rather than on `responded_at`: the status is
        what the answer changes, and an approval carrying a response with no status would
        be the inconsistency this refuses to create.
        """
        if status not in self._ANSWERS:
            raise MaintenanceValidationError(
                f"{status.value} is not an answer an owner can give"
            )
        if self.status is not OwnerApprovalStatus.PENDING:
            raise OwnerApprovalAlreadyAnsweredError(
                f"Approval was already answered with {self.status.value}"
            )

        self.status = status
        self.responded_at = now
        self.responded_by = responded_by
        self.response_notes = response_notes
        return self.amount if status is OwnerApprovalStatus.APPROVED else None


@dataclass
class IncidentPhoto:
    """One photo of one incident, at one stage of the job (`incident-photos` R1).

    `ASSUMPTION`: **this entity is not in the PRD.** PRD §7.13 `Incident` declares no photo
    column and PRD §7 defines only `CleaningPhoto` (§7.12); what exists is PRD §6 granting the
    `TECHNICIAN` "subir fotos (antes y después)" and PRD §12 asking for them twice. So the
    entity, its table and `IncidentPhotoStage` extend the PRD's model rather than implement it
    — recorded the same way `cleaning` recorded the deviation for its checklist templates.

    **`tenant_id` is on the row, and that is a deliberate departure from `cleaning_photos`**
    (R1.3, design D2), which has none and is scoped through its parent task. Three separate
    things follow from the column, and only the first is about convenience: the *model* that
    maps this entity lands in `tenant_scoped_classes()` and therefore under the global filter
    of `app/core/db.py`; it lets the isolation test R6.3 demands exist without going through
    the incident; and paired with the composite foreign key of D2 it makes "the photo's tenant
    and its incident's tenant agree" an invariant of the schema instead of discipline in the
    repository.

    The first of those is worth stating precisely, because it is easy to credit to the wrong
    layer: `tenant_scoped_classes()` resolves from the SQLAlchemy **mapper registry**
    (`app/core/db.py`), so it is `IncidentPhotoModel` that enters the filter, not this
    dataclass. This entity is plain Python and no query ever sees it.

    **No `updated_at`, and that is the deviation from `steering/backend.md`'s "toda entidad con
    `tenant_id`, `created_at`, `updated_at`" — recorded here rather than left to be noticed**,
    the way `OwnerApproval` below records its own. A photo row is **immutable after insert**:
    `IncidentPhotoRepository` declares `add` and `list_for_incident` and no `save`, so there is
    no write path through which an `updated_at` could ever move, and a column that can only
    ever equal `created_at` invites a reader to trust it as evidence of an edit that cannot
    happen. The precedent is not new either — `cleaning_photos` carries `created_at` alone for
    the same reason. If a later change gives a photo an editable field, that change adds the
    column and this paragraph goes.

    **What is deliberately absent**: no `content_type` and no client file name (R1.5). The
    served `Content-Type` is derived from the extension inside `storage_key` and from nothing
    else, and the client's file name never touches the key — so persisting either would create
    a second, weaker source for a decision that already has one. There is also no
    `ai_validation_result`: `cleaning` left its equivalent unwritten for want of a port, and
    this change opens no write path to one.

    `storage_key` is internal and never leaves the application in a response body or header;
    `IncidentPhotoResponse` enumerates its fields explicitly for that reason (R3.3).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    incident_id: uuid.UUID
    #: The user from the verified token, never a value that travelled with the request.
    uploaded_by: uuid.UUID
    stage: IncidentPhotoStage
    storage_key: str
    #: Written by the use case rather than defaulted in the database: Postgres `now()` is the
    #: *transaction* timestamp, so several photos inserted together would share one instant and
    #: the listing's ordering would fall through to a random `uuid4`. The upload order is what
    #: R3.1 asks the listing to preserve.
    created_at: datetime


@dataclass
class IncidentMessage:
    """One staff-to-manager message on an incident's thread (`staff-messaging` R2).

    The mirror of `app.cleaning.domain.entities.CleaningTaskMessage` — see that class for
    the reasoning behind the shape (plain dataclass, no invariant of its own) and behind
    `author_role` being frozen at write time rather than joined from `users.role`.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    incident_id: uuid.UUID
    author_id: uuid.UUID
    author_role: UserRole
    content: str
    created_at: datetime
