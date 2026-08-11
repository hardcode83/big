"""`GuestPortalAuthenticator` — the five rejections and the one success (R1.3, R1.4, R2.1,
R2.2, R2.5; design D3, D4, D5).

Unit tests with fakes, per `steering/backend-architecture.md` for `application/`. That is not
only convention here: the whole point of D4's ports is that the authoriser can be exercised
without a database, and a test that needed one would be evidence the layering had slipped.

**What these tests are really about is indistinguishability.** R2.2 requires that
"inexistente, mal formado, revocado, fuera de ventana o de una reserva cancelada" all look
the same, so most of this file is one parametrised case asserting the five causes produce a
single exception type carrying nothing that separates them.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pytest

from app.guests.application.portal import GuestPortalAuthenticator
from app.guests.domain.exceptions import GuestPortalUnauthorised
from app.guests.domain.portal_ports import GuestAccessToken, PortalStay
from app.guests.domain.portal_token import generate_guest_token, hash_guest_token
from app.reservations.domain.enums import ReservationStatus

TENANT = uuid.uuid4()
RESERVATION = uuid.uuid4()
PROPERTY = uuid.uuid4()
GUEST = uuid.uuid4()
CHECK_OUT = date(2026, 9, 3)
GRACE_DAYS = 2

#: D3: the window closes at midnight UTC of check-out + grace, i.e. the *first* instant of
#: 2026-09-05. So the guest keeps access through all of the 3rd and the 4th.
WITHIN = datetime(2026, 9, 4, 23, 59, tzinfo=UTC)
BEYOND = datetime(2026, 9, 5, 0, 0, 1, tzinfo=UTC)


@dataclass
class FakeTokens:
    rows: dict[str, GuestAccessToken] = field(default_factory=dict)
    lookups: list[str] = field(default_factory=list)

    async def find_live_by_token_hash(self, token_hash):
        self.lookups.append(token_hash)
        return self.rows.get(token_hash)

    async def add(self, tenant_id, token) -> None:  # pragma: no cover
        raise AssertionError("the authoriser never mints")

    async def revoke_live_for_reservation(self, tenant_id, reservation_id, *, now):  # pragma: no cover
        raise AssertionError("the authoriser never revokes")


@dataclass
class FakeStays:
    stays: dict[tuple[uuid.UUID, uuid.UUID], PortalStay] = field(default_factory=dict)
    lookups: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)

    async def find(self, tenant_id, reservation_id):
        self.lookups.append((tenant_id, reservation_id))
        return self.stays.get((tenant_id, reservation_id))


@dataclass
class RecordingBinder:
    bound: list[uuid.UUID] = field(default_factory=list)

    def bind(self, tenant_id: uuid.UUID) -> None:
        self.bound.append(tenant_id)


def _stay(**overrides) -> PortalStay:
    defaults = {
        "reservation_id": RESERVATION,
        "tenant_id": TENANT,
        "property_id": PROPERTY,
        "guest_id": GUEST,
        "check_in_date": date(2026, 9, 1),
        "check_out_date": CHECK_OUT,
        "status": ReservationStatus.CONFIRMED,
    }
    defaults.update(overrides)
    return PortalStay(**defaults)


def _build(*, token: str, revoked_at=None, stay: PortalStay | None = _stay()):
    tokens = FakeTokens()
    tokens.rows[hash_guest_token(token)] = GuestAccessToken(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        reservation_id=RESERVATION,
        token_hash=hash_guest_token(token),
        revoked_at=revoked_at,
    )
    stays = FakeStays()
    if stay is not None:
        stays.stays[(TENANT, RESERVATION)] = stay
    binder = RecordingBinder()
    authenticator = GuestPortalAuthenticator(
        tokens=tokens, stays=stays, binder=binder, grace_days=GRACE_DAYS
    )
    return authenticator, tokens, stays, binder


# --- The success path (R2.1, D4) ------------------------------------------------------


@pytest.mark.asyncio
async def test_it_returns_a_session_built_only_from_the_token_row_and_its_stay() -> None:
    """R2.1 literally: nothing here could have come from the request.

    The authoriser is handed one string and a clock. Every identifier on the returned session
    was read out of the token's own row or the reservation it names — so "NEVER SHALL leerlos
    de la ruta, del cuerpo, de la query ni de una cabecera" is true by construction, not by
    the router being careful.
    """
    token = generate_guest_token()
    authenticator, _, _, _ = _build(token=token)

    session = await authenticator.authorize(token, WITHIN)

    assert session.tenant_id == TENANT
    assert session.reservation_id == RESERVATION
    assert session.property_id == PROPERTY
    assert session.guest_id == GUEST
    assert session.token_hash == hash_guest_token(token)


@pytest.mark.asyncio
async def test_it_binds_the_session_to_the_tenant_the_token_resolved() -> None:
    """D4 step 4. Before this, the request has no tenant; after it, the global filter does."""
    token = generate_guest_token()
    authenticator, _, _, binder = _build(token=token)

    await authenticator.authorize(token, WITHIN)

    assert binder.bound == [TENANT]


@pytest.mark.asyncio
async def test_it_looks_the_row_up_by_digest_and_never_by_the_token() -> None:
    """R1.2: the cleartext value is not a key anywhere, not even transiently."""
    token = generate_guest_token()
    authenticator, tokens, _, _ = _build(token=token)

    await authenticator.authorize(token, WITHIN)

    assert tokens.lookups == [hash_guest_token(token)]
    assert token not in tokens.lookups


@pytest.mark.asyncio
async def test_a_stay_with_no_guest_yet_still_authorises() -> None:
    """OQ3: `reservations.guest_id` is nullable, and the check-in is what fills it.

    Refusing here would make the portal unusable for exactly the bookings it exists to
    complete.
    """
    token = generate_guest_token()
    authenticator, _, _, _ = _build(token=token, stay=_stay(guest_id=None))

    session = await authenticator.authorize(token, WITHIN)

    assert session.guest_id is None


# --- The five rejections, and their indistinguishability (R2.2, D5) -------------------


@pytest.mark.asyncio
async def test_an_unknown_token_is_refused() -> None:
    authenticator, _, _, binder = _build(token=generate_guest_token())

    with pytest.raises(GuestPortalUnauthorised):
        await authenticator.authorize(generate_guest_token(), WITHIN)

    assert binder.bound == []


@pytest.mark.asyncio
async def test_a_malformed_token_is_refused_by_the_same_path() -> None:
    """Not a special case — it hashes to a digest no row carries.

    Worth its own test because the obvious alternative is a format check that answers before
    the lookup, which would make "malformed" measurably cheaper than "unknown".
    """
    authenticator, tokens, _, binder = _build(token=generate_guest_token())

    with pytest.raises(GuestPortalUnauthorised):
        await authenticator.authorize("not a token at all", WITHIN)

    assert len(tokens.lookups) == 1
    assert binder.bound == []


@pytest.mark.asyncio
async def test_a_revoked_token_is_refused() -> None:
    token = generate_guest_token()
    authenticator, _, _, binder = _build(
        token=token, revoked_at=datetime(2026, 8, 10, tzinfo=UTC)
    )

    with pytest.raises(GuestPortalUnauthorised):
        await authenticator.authorize(token, WITHIN)

    assert binder.bound == []


@pytest.mark.asyncio
async def test_a_token_past_its_window_is_refused() -> None:
    token = generate_guest_token()
    authenticator, _, _, binder = _build(token=token)

    with pytest.raises(GuestPortalUnauthorised):
        await authenticator.authorize(token, BEYOND)

    assert binder.bound == []


@pytest.mark.asyncio
async def test_a_cancelled_stay_stops_authorising_with_no_manual_action() -> None:
    """R1.4's second half, and the reason D3 derives the window instead of storing it.

    A cancellation takes effect on the next request, not on the next sweep — there is no
    sweep.
    """
    token = generate_guest_token()
    authenticator, _, _, binder = _build(
        token=token, stay=_stay(status=ReservationStatus.CANCELLED)
    )

    with pytest.raises(GuestPortalUnauthorised):
        await authenticator.authorize(token, WITHIN)

    assert binder.bound == []


@pytest.mark.asyncio
async def test_a_token_whose_stay_vanished_is_refused() -> None:
    """The composite FK makes this unreachable today; the check is the fail-closed direction."""
    token = generate_guest_token()
    authenticator, _, _, binder = _build(token=token, stay=None)

    with pytest.raises(GuestPortalUnauthorised):
        await authenticator.authorize(token, WITHIN)

    assert binder.bound == []


@pytest.mark.asyncio
async def test_the_five_rejections_are_indistinguishable() -> None:
    """R2.2 and D5, asserted as the property rather than case by case.

    One exception type, one message, and **no `__cause__`** — a chained cause would put the
    real reason in a traceback and, sooner or later, in a response or a log line. The five
    cases are built here the same way the individual tests build them; what this adds is the
    comparison between them, which is the thing that has to stay true.
    """
    token = generate_guest_token()
    cases = []

    for kwargs, presented, now in (
        ({}, generate_guest_token(), WITHIN),
        ({}, "malformed", WITHIN),
        ({"revoked_at": datetime(2026, 8, 10, tzinfo=UTC)}, token, WITHIN),
        ({}, token, BEYOND),
        ({"stay": _stay(status=ReservationStatus.CANCELLED)}, token, WITHIN),
    ):
        authenticator, _, _, _ = _build(token=token, **kwargs)
        with pytest.raises(GuestPortalUnauthorised) as caught:
            await authenticator.authorize(presented, now)
        cases.append(caught.value)

    assert len({type(error) for error in cases}) == 1
    assert len({str(error) for error in cases}) == 1
    assert all(error.__cause__ is None for error in cases)


@pytest.mark.asyncio
async def test_every_rejection_costs_the_same_two_lookups() -> None:
    """The timing constraint the section 3 security panel left binding on this task.

    "Unknown" costing one query and "known but dead" costing two is observable even when the
    response is identical. So **both** lookups run on every path, including the one where no
    token row was found at all — that miss is issued against ids that cannot resolve.

    The earlier version of this test asserted the weaker "unconditionally *once a row is
    found*", which the implementation did satisfy while the class docstring claimed the
    stronger property. The section 5 panel caught the gap between the two; this asserts the
    claim that is actually made.
    """
    token = generate_guest_token()
    counts = []

    # All **five** causes, not four. An earlier version left "past window" out on the
    # grounds that it must cost the same by construction — which is exactly the reasoning
    # that let the original bug hide behind a docstring.
    for kwargs, presented, now in (
        ({}, generate_guest_token(), WITHIN),                                  # unknown
        ({}, "malformed", WITHIN),                                             # malformed
        ({"revoked_at": datetime(2026, 8, 10, tzinfo=UTC)}, token, WITHIN),    # revoked
        ({}, token, BEYOND),                                                   # past window
        ({"stay": _stay(status=ReservationStatus.CANCELLED)}, token, WITHIN),  # cancelled
    ):
        authenticator, tokens, stays, _ = _build(token=token, **kwargs)
        with pytest.raises(GuestPortalUnauthorised):
            await authenticator.authorize(presented, now)
        counts.append((len(tokens.lookups), len(stays.lookups)))

    assert counts == [(1, 1)] * 5


@pytest.mark.asyncio
async def test_a_naive_clock_is_refused_before_either_lookup() -> None:
    """R2.2, and a trap the section 5 security panel spotted before §6 could fall into it.

    **The hazard**: the window comparison is against an aware datetime, so a naive `now`
    would raise `TypeError` deep inside the rule — but only on the branch that *resolving*
    tokens reach. Wired to the wrong clock, that answers `500` for every real token and the
    constant `404` for everything else: a clean existence oracle, and an outage on the
    authorising path.

    **What the code does instead**: refuses up front with `ValueError`, before either lookup,
    so the failure is uniform and loud rather than shaped like the data. A wiring bug is not
    a rejection cause, so it must not be laundered into `GuestPortalUnauthorised` either.
    """
    token = generate_guest_token()
    authenticator, tokens, stays, _ = _build(token=token)

    with pytest.raises(ValueError, match="timezone-aware"):
        await authenticator.authorize(token, datetime(2026, 9, 4, 12, 0))  # noqa: DTZ001

    assert tokens.lookups == []
    assert stays.lookups == []


# --- The window (R1.3, D3) ------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("moment", "authorised"),
    [
        (datetime(2026, 9, 4, 23, 59, 59, tzinfo=UTC), True),
        (datetime(2026, 9, 5, 0, 0, 1, tzinfo=UTC), False),
    ],
)
async def test_the_window_is_wired_through_to_the_domain_rule(
    moment: datetime, authorised: bool
) -> None:
    """Two points, because this layer proves the **wiring**, not the arithmetic.

    `authorize` now does nothing with the window but forward `check_out_date`, `grace_days`
    and `now` into `token_still_authorises` and branch on the bool it returns. So the
    boundary itself — the instant, the microsecond either side, `grace_days=0` — is proven
    once and at finer precision in `test_portal_authorisation.py`, where it is pure.

    What is left to prove here is that the right values reach the rule and the answer is
    respected, and one point on each side of the boundary shows that. The QA panel of section
    5 flagged the full five-point sweep this replaced as duplicating the domain test.
    """
    token = generate_guest_token()
    authenticator, _, _, _ = _build(token=token)

    if authorised:
        assert await authenticator.authorize(token, moment) is not None
    else:
        with pytest.raises(GuestPortalUnauthorised):
            await authenticator.authorize(token, moment)


@pytest.mark.asyncio
async def test_moving_the_stay_moves_the_window() -> None:
    """D3's whole argument for deriving rather than storing: no `expires_at` to go stale."""
    token = generate_guest_token()
    authenticator, _, _, _ = _build(
        token=token, stay=_stay(check_out_date=CHECK_OUT + timedelta(days=10))
    )

    session = await authenticator.authorize(token, BEYOND)

    assert session.reservation_id == RESERVATION
