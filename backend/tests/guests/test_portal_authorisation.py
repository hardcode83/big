"""The token's liveness rule, as pure domain (R1.3, R1.4; design D3).

No fakes, no ports, no clock — dates in, a bool out. That is the point of the rule living in
`domain/` rather than on the authoriser: `steering/testing.md` asks for TDD "en `domain/` con
invariante real … es barato porque `domain/` es Python puro sin infra que montar", and the
window arithmetic is exactly that kind of invariant. It is also the part that has already
been wrong once — the first implementation granted a whole extra day.

The authoriser's own tests still cover the five rejections end to end; what these add is the
boundary behaviour, at a granularity that would be tedious to reach through a use case.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.guests.domain.portal_authorisation import token_still_authorises, window_closes
from app.reservations.domain.enums import ReservationStatus

CHECK_OUT = date(2026, 9, 3)
GRACE = 2

#: D3: midnight UTC of check-out + grace, i.e. the first instant of 2026-09-05.
CLOSES = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)


def _authorises(**overrides) -> bool:
    values = {
        "revoked_at": None,
        "reservation_status": ReservationStatus.CONFIRMED,
        "check_out_date": CHECK_OUT,
        "now": datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        "grace_days": GRACE,
    }
    values.update(overrides)
    return token_still_authorises(**values)


# --- The window (R1.3, D3) ------------------------------------------------------------


def test_the_window_closes_at_midnight_utc_of_check_out_plus_the_grace() -> None:
    """D3's wording taken literally, and the arithmetic stated once so nothing re-derives it."""
    assert window_closes(CHECK_OUT, GRACE) == CLOSES


def test_midnight_means_the_first_instant_of_that_date_not_the_last() -> None:
    """The off-by-one that already happened, pinned as the property rather than as a case.

    Reading "two days of grace" as "through the end of the 5th" grants a third day. The
    boundary is the *start* of the 5th, so the guest keeps the token through all of the 4th.
    """
    assert window_closes(CHECK_OUT, GRACE).time() == datetime.min.time()
    assert window_closes(CHECK_OUT, GRACE).date() == CHECK_OUT + timedelta(days=GRACE)


@pytest.mark.parametrize(
    ("moment", "authorised"),
    [
        (datetime(2026, 9, 3, 0, 0, tzinfo=UTC), True),        # check-out day, first instant
        (datetime(2026, 9, 4, 23, 59, 59, tzinfo=UTC), True),  # last full day granted
        (CLOSES, True),                                        # the boundary itself: `<=`
        (CLOSES + timedelta(microseconds=1), False),           # the finest step past it
        (datetime(2026, 9, 6, 0, 0, tzinfo=UTC), False),
    ],
)
def test_the_boundary_is_inclusive_to_the_microsecond(moment: datetime, authorised: bool) -> None:
    """`now <= window_closes(...)`, checked at the smallest resolution that can distinguish.

    Both neighbours of the boundary matter: granting one instant too few cuts a guest off a
    day early in practice, and one too many is the kind of thing nobody notices until a
    revocation does not take effect when it should.
    """
    assert _authorises(now=moment) is authorised


def test_a_stay_that_moves_takes_its_window_with_it() -> None:
    """D3's whole argument for deriving rather than storing — no `expires_at` to go stale."""
    later = CHECK_OUT + timedelta(days=10)

    assert _authorises(now=datetime(2026, 9, 10, tzinfo=UTC), check_out_date=later) is True


def test_no_grace_still_grants_the_day_of_check_out() -> None:
    """`grace_days=0` closes at midnight of check-out itself, so the guest keeps that instant
    and nothing after it. Worth pinning because zero is the configuration most likely to be
    tried in anger, and an implementation that subtracted a day would look fine at the
    default."""
    assert _authorises(now=datetime(2026, 9, 3, 0, 0, tzinfo=UTC), grace_days=0) is True
    assert _authorises(now=datetime(2026, 9, 3, 0, 0, 1, tzinfo=UTC), grace_days=0) is False


def test_a_stay_that_ended_long_ago_does_not_authorise() -> None:
    assert _authorises(now=datetime(2027, 1, 1, tzinfo=UTC)) is False


# --- The other two checks (R1.4, D3) --------------------------------------------------


def test_a_revoked_token_never_authorises_however_fresh_the_stay() -> None:
    """Revocation beats the window: an operator withdrawing access must take effect now."""
    assert _authorises(revoked_at=datetime(2026, 8, 1, tzinfo=UTC)) is False
    assert _authorises(
        revoked_at=datetime(2026, 8, 1, tzinfo=UTC),
        now=datetime(2026, 9, 3, tzinfo=UTC),
    ) is False


def test_a_cancelled_stay_stops_authorising_with_no_manual_action() -> None:
    """R1.4's second half. No sweep, no `expires_at` to update — the next request just fails."""
    assert _authorises(reservation_status=ReservationStatus.CANCELLED) is False


@pytest.mark.parametrize(
    "status",
    [status for status in ReservationStatus if status is not ReservationStatus.CANCELLED],
)
def test_every_other_reservation_status_still_authorises(status: ReservationStatus) -> None:
    """Only `CANCELLED` stops it, and that is checked against the enum rather than a list.

    A stay that is `COMPLETED` or `NO_SHOW` keeps its token until the window closes — the
    guest may still need the check-in form or a way to report something they left behind. If
    a future status should also revoke, this test is what forces that to be a decision.
    """
    assert _authorises(reservation_status=status) is True


def test_the_three_checks_are_independent() -> None:
    """Each one alone is enough to refuse, so no pair can mask a third that stopped working."""
    assert _authorises() is True
    assert _authorises(revoked_at=datetime(2026, 8, 1, tzinfo=UTC)) is False
    assert _authorises(reservation_status=ReservationStatus.CANCELLED) is False
    assert _authorises(now=datetime(2027, 1, 1, tzinfo=UTC)) is False
