"""When a guest portal token still authorises (R1.3, R1.4; design D3).

A **domain service**, in the sense `steering/backend-architecture.md` gives the term: "lógica
que no pertenece a una sola entidad". The rule spans two of them — the token supplies
`revoked_at`, the stay supplies its status and its dates — so it belongs neither on
`GuestAccessToken` nor on `PortalStay`, and the steering's Don't is explicit that it does not
belong in `application/` either: "si hay una regla (no solo un paso de orquestación),
pertenece a `domain/`".

It lived on `GuestPortalAuthenticator` until the architecture panel of section 5 raised it as
a DESIGN-CONFLICT. D4 argues at length against putting the *decision* in a FastAPI dependency
and never says anything about the layer of the *predicate*; the panel was right that the
silence was not an argument. Moved here with Jose's approval, and D3 records it.

The move buys something concrete rather than tidiness: the window arithmetic is pure and
off-by-one-sensitive — the first implementation granted a whole extra day — and here it is
testable with nothing but dates, which is where `steering/testing.md` asks for TDD.
"""

from datetime import UTC, date, datetime, time, timedelta

from app.reservations.domain.enums import ReservationStatus


def window_closes(check_out_date: date, grace_days: int) -> datetime:
    """The instant a stay's token stops authorising (R1.3).

    **D3's boundary, taken literally**: "`now <= medianoche UTC de (check_out_date +
    settings.guest_portal_token_grace_days)`". Midnight of a date is its *first* instant, so
    a check-out on the 3rd with two days of grace dies at 00:00 on the 5th — the guest keeps
    the token through all of the 3rd and the 4th.

    Worth stating because the off-by-one is inviting in both directions: reading "two days of
    grace" as "through the end of the 5th" grants a third day, and dropping the `<=` at the
    call site cuts the guest off a day early. The first implementation made the former
    mistake and the parametrised boundary test caught it.

    Derived on every request rather than stored, which is the whole of D3: a stay that moves
    takes its window with it, and a cancellation needs no sweep. That is why there is no
    `expires_at` column.

    ASSUMPTION, recorded in D3: midnight **UTC**, not `properties.timezone`. At the default
    two days of grace the worst-case skew is two hours out of forty-eight, and using the
    property's zone would mean reading it before a tenant is known.
    """
    return datetime.combine(check_out_date + timedelta(days=grace_days), time.min, tzinfo=UTC)


def token_still_authorises(
    *,
    revoked_at: datetime | None,
    reservation_status: ReservationStatus,
    check_out_date: date,
    now: datetime,
    grace_days: int,
) -> bool:
    """D3's three checks, evaluated together (R1.3, R1.4).

    One function returning one bool, rather than three that a caller composes: R2.2 requires
    the five rejection causes to be indistinguishable, and a caller that could apply two of
    the three checks — or tell which one failed — is how that stops being true. The
    authoriser gets a yes or a no and has nothing to report but the constant refusal.

    Keyword-only on purpose. Five parameters of which two are dates and one is a datetime is
    exactly the signature where a positional swap type-checks, runs, and silently shifts
    everybody's window; this backend runs no mypy (`app/core/db.py` records that), so the
    call site is the only place that mistake could be caught.

    `now` is a parameter rather than read here, so the rule stays pure and the clock stays the
    caller's — the same discipline every other dated rule in this codebase follows.
    """
    return (
        revoked_at is None
        and reservation_status is not ReservationStatus.CANCELLED
        and now <= window_closes(check_out_date, grace_days)
    )
