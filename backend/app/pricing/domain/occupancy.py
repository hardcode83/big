"""Occupancy of a property over the next 30 days (R2.3, design D5).

A pure function over `Reservation` entities, and one scalar per property and execution —
not one per day of the horizon. PRD §7.17 defines occupancy relative to *today*
("los próximos 30 días"), not relative to the date being priced, so computing it per day
would be sixty queries for a signal that does not change between them.

**No PMS call**: the local `reservations` are already the projection of the PMS calendar,
and Mode 1 does not talk to the PMS at all (PRD §19).
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from app.pricing.domain.constants import OCCUPANCY_WINDOW_DAYS
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationStatus

#: Everything else counts as occupied, `PENDING` included: it is a night the PMS calendar
#: already blocks even though nobody confirmed it. A cancellation and a no-show are the only
#: two states that describe a night which ended up free. The PRD says "ocupación" without
#: defining it, so the definition is declared here.
FREE_STATUSES: frozenset[ReservationStatus] = frozenset(
    {ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW}
)


def occupancy_window(execution_date: date) -> tuple[date, date]:
    """Half-open `[start, end)` of the window, starting the day after the execution date."""
    start = execution_date + timedelta(days=1)
    return start, start + timedelta(days=OCCUPANCY_WINDOW_DAYS)


def occupancy_pct_for(
    reservations: Iterable[Reservation], *, execution_date: date
) -> Decimal:
    """Percentage of occupied nights in the window, as a `Decimal` between 0 and 100.

    A stay covers the nights `[check_in_date, check_out_date)` — the check-out day is not
    a night. Overlapping reservations count their shared nights once, which is why this
    walks a set of dates rather than summing lengths.
    """
    start, end = occupancy_window(execution_date)
    occupied: set[date] = set()
    for reservation in reservations:
        if reservation.status in FREE_STATUSES:
            continue
        night = max(reservation.check_in_date, start)
        last = min(reservation.check_out_date, end)
        while night < last:
            occupied.add(night)
            night += timedelta(days=1)
    return Decimal(len(occupied)) * Decimal(100) / Decimal(OCCUPANCY_WINDOW_DAYS)
