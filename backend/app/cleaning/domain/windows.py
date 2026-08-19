"""The two ends of a cleaning's window, as pure policy (`cleaner-task-context` design D5).

Two callers, which is what moved these here: `ProvisionCleaningTaskUseCase` writes them into a
task's `scheduled_start`/`scheduled_end`, and `GetCleaningTaskContextUseCase` reports them live.
A second caller is the classic trigger for the extraction, and `steering/backend-architecture.md`
§Don'ts puts a rule in `domain/` rather than in `application/` — the same move the architecture
reviewer of `cleaning` §4 made for `resolve_auto_assignee`.

**Neither function reimplements the arithmetic.** Both delegate to
`app.properties.domain.clock_triggers.effective_bounds`, whose module docstring says its DST
policy — reject the spring gap, demand an explicit `fold` in the autumn one — "must never be
reimplemented". This module only decides *which* bounds to ask for and what to do when they
cannot be materialised.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from app.properties.domain.clock_triggers import effective_bounds
from app.properties.domain.entities import Property
from app.properties.domain.exceptions import IncompatibleTransitionContextError
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationStatus

#: ASSUMPTION (R2.2, R2.3): how far past the anchor `GetCleaningTaskContextUseCase` looks for a
#: next arrival. Design D10 chose it — "el horizonte de la próxima llegada, como ASSUMPTION
#: declarada" — over 7, 30 and the dashboard's 90 days, the same class of choice
#: `dashboard/application/use_cases.py` marks for its own "current or next reservation".
#:
#: **Applied by that use case, not by `next_arrival_after` below** — it bounds the window handed
#: to `ReservationRepository.list_for_properties` and then the result itself (D5, third piece).
#: The function must not apply it, and the reason is its other caller: `process_checkouts`
#: anchors on the stay's checkout, which for a backlog run is up to `CANDIDATE_LOOKBEHIND`
#: (30 days) behind `now`, so a 14-day cap inside the function would discard arrivals that job
#: is required to keep. It lives here because this is the module the rule belongs to, and the
#: constant is what the two callers disagree about.
#:
#: **Deliberately not `candidate_window`'s `CANDIDATE_LOOKAHEAD` of two days.** That one is the
#: scheduler's fetch window, and reusing it here would reproduce the very defect the live
#: projection exists to fix: an arrival five days out leaves the stored `scheduled_end` unset for
#: good. Fourteen days because the deadline exists so a cleaner can order her day — an arrival a
#: fortnight away imposes nothing on today's cleaning — and because a shorter horizon than the
#: dashboard's 90 days keeps a wide range out of a per-task read.
#:
#: Consequence for the contract: in the projection `None` means "no `CONFIRMED` arrival within 14
#: days of the anchor", which is why the operation's description and `docs/cleaning.md` have to
#: say it in those words rather than "there is no next arrival" (tasks 3.3 and 4.2).
NEXT_ARRIVAL_HORIZON = timedelta(days=14)


def resolve_checkout(property: Property, reservation: Reservation) -> datetime | None:
    """When the outgoing guest is out, as a real instant in the property's zone (R2.1, R2.4).

    `Reservation.check_out_time` with a fallback to `Property.default_check_out_time` — which is
    `effective_bounds` verbatim, not a copy of it.

    **`None`, never `now`, when the bounds cannot be materialised** (design D5). Its sibling
    `_effective_checkout` degrades to `now` and is right to: a scheduling hint is better
    approximate than absent. This value is shown to a person, and an invented departure time on
    a cleaner's screen is worse than an empty one.
    """
    try:
        _, end = effective_bounds(property, reservation)
    except IncompatibleTransitionContextError:
        return None
    return end


def next_arrival_after(
    property: Property,
    candidates: Sequence[Reservation],
    anchor: datetime,
    *,
    exclude_id: uuid.UUID | None = None,
) -> datetime | None:
    """The next guest's arrival at or after `anchor`, or `None` when there is none (R2.2, R2.3).

    `_next_checkin` moved, with `current: Reservation` replaced by an optional id: the projection
    has no "current reservation" when `task.reservation_id` is `None` (design D6), and an id is
    all the rule ever used the reservation for. `exclude_id=None` skips nothing.

    **No upper bound, on purpose**: how far ahead an arrival still counts is the caller's, because
    the two callers need different answers. `NEXT_ARRIVAL_HORIZON` above says why. The caller is
    therefore also what keeps `candidates` to the right property and tenant — this function reads
    the sequence it is handed, exactly as `_next_checkin` did.

    **`anchor` is the checkout, not `now`.** The reason is `celery-jobs`': `process_checkouts` is
    built to recover a backlog — `CANDIDATE_LOOKBEHIND` is 30 days — so filtering on `now` made a
    same-day turnover processed late lose a deadline that was sitting in the candidates. A
    cleaning's window is `[checkout, next arrival]`; neither end is a function of when anyone
    asked.

    Only `CONFIRMED` arrivals, inherited from `_next_checkin` rather than diverged from. Said out
    loud because it is visible in the response: a `PENDING` arrival imposes no deadline and the
    field comes back `None`. Two eligibility policies in one repository would be worse than one
    debatable policy.

    Guards its own precondition on `anchor`, in the spirit of `opens_checkin_window` in the
    neighbouring `clock_triggers` module: `effective_bounds` returns aware instants, so a caller
    that forgot `tzinfo` would otherwise get a bare `TypeError` out of a datetime comparison, at a
    line that does not name the mistake. No production caller can reach it — `process_checkouts`
    passes `scheduled_start or now` and the projection anchors on a checkout or on `now`, all aware
    — so this pins a programming error, not a live one.

    **`ValueError`, not a domain error of either module.** Not `InvalidTransitionInputError`, which
    `opens_checkin_window` raises: that belongs to `properties`' tree, and FastAPI dispatches
    exception handlers by type across the whole app, so raising it from `cleaning` would have it
    answered by `properties/api/errors.py`'s catch-all as "Unexpected property error" and never
    reach `cleaning/api/errors.py` — the cross-module leak that `PropertyNotFoundError`'s docstring
    in `cleaning/domain/exceptions.py` exists to prevent. And not a `CleaningDomainError` either:
    that module's errors "name a business outcome the callers have to tell apart (404 / 409 / 422)",
    and a naive datetime is none of those — it is a bug, and dressing it as a 422 would tell a
    client to fix something it did not send. `Reservation.__post_init__` raises a bare `ValueError`
    for its own invariant, which is the precedent this follows.
    """
    if anchor.tzinfo is None or anchor.utcoffset() is None:
        raise ValueError("anchor must be timezone-aware")
    starts: list[datetime] = []
    for candidate in candidates:
        if exclude_id is not None and candidate.id == exclude_id:
            continue
        if candidate.status is not ReservationStatus.CONFIRMED:
            continue
        try:
            start, _ = effective_bounds(property, candidate)
        except IncompatibleTransitionContextError:
            continue
        if start >= anchor:
            starts.append(start)
    return min(starts) if starts else None


def next_arrival_within_horizon(
    property: Property,
    candidates: Sequence[Reservation],
    anchor: datetime,
    *,
    exclude_id: uuid.UUID | None = None,
) -> datetime | None:
    """`next_arrival_after` bounded by `NEXT_ARRIVAL_HORIZON` — the projection's rule (D10).

    This is what `GetCleaningTaskContextUseCase` calls, and it exists so the bound is a rule in
    `domain/` rather than a comparison written inline in `application/`
    (`steering/backend-architecture.md` §Don'ts: "No lógica de negocio en `application/` — si hay
    una regla (no solo un paso de orquestación), pertenece a `domain/`").

    **Applying the bound here is not redundant with bounding the fetch, and this is the reason.**
    The caller's window goes to `ReservationRepository.list_for_properties`, which takes `date`s,
    so `(anchor + NEXT_ARRIVAL_HORIZON).date()` admits an arrival later *on that date* than the
    horizon instant — up to a day beyond the bound. Clamping the value is what makes `None` mean
    exactly "no `CONFIRMED` arrival within 14 days of the anchor" rather than "within 14 days,
    give or take how the window rounded".

    `next_arrival_after` stays unbounded because `process_checkouts` needs it that way; see
    `NEXT_ARRIVAL_HORIZON`.
    """
    arrival = next_arrival_after(property, candidates, anchor, exclude_id=exclude_id)
    if arrival is None or arrival > anchor + NEXT_ARRIVAL_HORIZON:
        return None
    return arrival
