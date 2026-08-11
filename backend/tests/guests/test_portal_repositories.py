"""The guest portal's two adapters, against real Postgres (R1.5, R2.5, R3.1-R3.3; D2, D4, D9).

Integration rather than unit, because what is under test is exactly what a fake cannot show:
that the unfiltered lookup really does resolve a tenant, that the partial unique index really
does refuse a second live token, and that the projection really does join three tables
without dragging a money column along.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access.domain.enums import AccessRecordStatus
from app.access.infrastructure.models import AccessRecordModel
from app.core.db import TENANT_ID_SESSION_KEY, bind_session_to_tenant
from app.core.tenancy import CrossTenantWriteError
from app.guests.domain.portal_ports import GuestAccessToken
from app.guests.domain.portal_token import generate_guest_token, hash_guest_token
from app.guests.infrastructure.legal import SqlAlchemyLegalRegistrationStayStore
from app.guests.infrastructure.models import GuestAccessTokenModel, GuestModel
from app.guests.infrastructure.portal_repositories import (
    SessionTenantBinder,
    SqlAlchemyGuestAccessTokenRepository,
    SqlAlchemyGuestPortalStayReader,
    SqlAlchemyPortalStayLocator,
)
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.models import TenantModel

CHECK_IN = date(2026, 9, 1)


async def _stay(db_session, name: str, **property_overrides):
    """A tenant with one property and one reservation, ready to hang a token off."""
    tenant = TenantModel(name=name, billing_email=f"{name}@example.com")
    db_session.add(tenant)
    await db_session.flush()

    defaults = {
        "name": f"Property {name}",
        "internal_code": f"CODE-{uuid.uuid4().hex[:8]}",
        "pms_external_id": f"PMS-{uuid.uuid4().hex[:8]}",
        "max_guests": 4,
    }
    defaults.update(property_overrides)
    prop = PropertyModel(tenant_id=tenant.id, **defaults)
    db_session.add(prop)
    await db_session.flush()

    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel="DIRECT",
        status="CONFIRMED",
        check_in_date=CHECK_IN,
        check_out_date=CHECK_IN + timedelta(days=2),
        nights=2,
    )
    db_session.add(reservation)
    await db_session.flush()
    return tenant, prop, reservation


def _token(tenant, reservation, token_hash: str) -> GuestAccessToken:
    return GuestAccessToken(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        reservation_id=reservation.id,
        token_hash=token_hash,
    )


# --- `SqlAlchemyGuestAccessTokenRepository` (D2, D4) ----------------------------------


@pytest.mark.asyncio
async def test_the_global_lookup_resolves_the_tenant_without_being_told_it(db_session) -> None:
    """D4 step 1, and the reason `token_hash` is globally unique.

    This is the whole premise of the anonymous surface: the caller presents a string and the
    row says which tenant they belong to. Two tenants exist here precisely so that answering
    correctly means something.
    """
    tenant_a, _, reservation_a = await _stay(db_session, "lookup-a")
    tenant_b, _, reservation_b = await _stay(db_session, "lookup-b")
    repository = SqlAlchemyGuestAccessTokenRepository(db_session)

    token_a = generate_guest_token()
    token_b = generate_guest_token()
    await repository.add(tenant_a.id, _token(tenant_a, reservation_a, hash_guest_token(token_a)))
    await repository.add(tenant_b.id, _token(tenant_b, reservation_b, hash_guest_token(token_b)))
    await db_session.flush()

    found = await repository.find_live_by_token_hash(hash_guest_token(token_b))

    assert found is not None
    assert found.tenant_id == tenant_b.id
    assert found.reservation_id == reservation_b.id


@pytest.mark.asyncio
async def test_an_unknown_token_hash_resolves_to_nothing(db_session) -> None:
    repository = SqlAlchemyGuestAccessTokenRepository(db_session)

    assert await repository.find_live_by_token_hash(hash_guest_token("never issued")) is None


@pytest.mark.asyncio
async def test_the_lookup_returns_a_revoked_row_and_lets_the_authoriser_judge(db_session) -> None:
    """The adapter deliberately does not filter `revoked_at` (D5).

    Every failure has to be indistinguishable to the client, and that is only checkable if
    one place decides all of them. An adapter that hid revoked rows would move half the
    decision here and make the other half untestable as a whole.
    """
    tenant, _, reservation = await _stay(db_session, "revoked-visible")
    repository = SqlAlchemyGuestAccessTokenRepository(db_session)
    token = generate_guest_token()
    await repository.add(tenant.id, _token(tenant, reservation, hash_guest_token(token)))
    await db_session.flush()

    await repository.revoke_live_for_reservation(
        tenant.id, reservation.id, now=datetime(2026, 8, 10, tzinfo=UTC)
    )

    found = await repository.find_live_by_token_hash(hash_guest_token(token))

    assert found is not None
    assert found.revoked_at is not None


@pytest.mark.asyncio
async def test_two_live_tokens_for_one_stay_are_refused_by_the_schema(db_session) -> None:
    """R1.5. The use case revokes first (D14); this is what makes that not merely polite."""
    tenant, _, reservation = await _stay(db_session, "two-live")
    repository = SqlAlchemyGuestAccessTokenRepository(db_session)

    await repository.add(tenant.id, _token(tenant, reservation, hash_guest_token("first")))
    await db_session.flush()
    await repository.add(tenant.id, _token(tenant, reservation, hash_guest_token("second")))

    with pytest.raises(IntegrityError, match="uq_guest_access_tokens_live_per_reservation"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_revoking_then_issuing_again_is_allowed(db_session) -> None:
    """The other half of R1.5, and the shape `IssueGuestAccessTokenUseCase` depends on."""
    tenant, _, reservation = await _stay(db_session, "reissue")
    repository = SqlAlchemyGuestAccessTokenRepository(db_session)
    await repository.add(tenant.id, _token(tenant, reservation, hash_guest_token("first")))
    await db_session.flush()

    revoked_id = await repository.revoke_live_for_reservation(
        tenant.id, reservation.id, now=datetime(2026, 8, 10, tzinfo=UTC)
    )
    await repository.add(tenant.id, _token(tenant, reservation, hash_guest_token("second")))
    await db_session.flush()

    assert revoked_id is not None
    live = (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id,
                GuestAccessTokenModel.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(live) == 1


@pytest.mark.asyncio
async def test_revoking_a_stay_with_no_live_token_reports_nothing(db_session) -> None:
    """`None`, so the caller can tell "revoked one" from "there was none" (R1.4)."""
    tenant, _, reservation = await _stay(db_session, "revoke-none")
    repository = SqlAlchemyGuestAccessTokenRepository(db_session)

    revoked_id = await repository.revoke_live_for_reservation(
        tenant.id, reservation.id, now=datetime(2026, 8, 10, tzinfo=UTC)
    )

    assert revoked_id is None


@pytest.mark.asyncio
async def test_revoking_an_already_revoked_stay_reports_nothing(db_session) -> None:
    """The third revoke case (R1.4), and the one that makes the predicate load-bearing.

    `WHERE revoked_at IS NULL` is what stops a second call overwriting the first
    revocation's timestamp — which would quietly rewrite when access was withdrawn, in a row
    that exists to answer exactly that question.
    """
    tenant, _, reservation = await _stay(db_session, "revoke-twice")
    repository = SqlAlchemyGuestAccessTokenRepository(db_session)
    await repository.add(tenant.id, _token(tenant, reservation, hash_guest_token("once")))
    await db_session.flush()
    first_revocation = datetime(2026, 8, 10, tzinfo=UTC)

    first_id = await repository.revoke_live_for_reservation(
        tenant.id, reservation.id, now=first_revocation
    )
    second = await repository.revoke_live_for_reservation(
        tenant.id, reservation.id, now=datetime(2026, 8, 11, tzinfo=UTC)
    )
    await db_session.flush()

    assert first_id is not None
    assert second is None
    stored = (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id
            )
        )
    ).scalar_one()
    assert stored.revoked_at == first_revocation


@pytest.mark.asyncio
async def test_revocation_cannot_reach_another_tenants_token(db_session) -> None:
    """R2.5. The filter is explicit, not inherited from the session marker."""
    tenant_a, _, reservation_a = await _stay(db_session, "revoke-a")
    tenant_b, _, reservation_b = await _stay(db_session, "revoke-b")
    repository = SqlAlchemyGuestAccessTokenRepository(db_session)
    await repository.add(tenant_b.id, _token(tenant_b, reservation_b, hash_guest_token("b")))
    await db_session.flush()

    revoked_id = await repository.revoke_live_for_reservation(
        tenant_a.id, reservation_b.id, now=datetime(2026, 8, 10, tzinfo=UTC)
    )

    assert revoked_id is None


@pytest.mark.asyncio
async def test_adding_a_token_of_another_tenant_is_refused(db_session) -> None:
    """`app/core/db.py`'s third limit: the session filter does not cover INSERTs."""
    tenant_a, _, _ = await _stay(db_session, "add-a")
    tenant_b, _, reservation_b = await _stay(db_session, "add-b")
    repository = SqlAlchemyGuestAccessTokenRepository(db_session)

    with pytest.raises(CrossTenantWriteError):
        await repository.add(tenant_a.id, _token(tenant_b, reservation_b, hash_guest_token("x")))


@pytest.mark.asyncio
async def test_a_marked_session_cannot_see_another_tenants_token(db_session) -> None:
    """Rule 1 of `steering/security.md`, on the table this change adds.

    The lookup above runs unmarked on purpose. This is the other half: once the authoriser
    has bound the session, the net covers this table like any other, so the rest of the
    request cannot reach across.
    """
    tenant_a, _, reservation_a = await _stay(db_session, "marked-a")
    tenant_b, _, reservation_b = await _stay(db_session, "marked-b")
    repository = SqlAlchemyGuestAccessTokenRepository(db_session)
    await repository.add(tenant_a.id, _token(tenant_a, reservation_a, hash_guest_token("a")))
    await repository.add(tenant_b.id, _token(tenant_b, reservation_b, hash_guest_token("b")))
    await db_session.flush()
    db_session.expunge_all()

    bind_session_to_tenant(db_session, tenant_a.id)

    visible = (await db_session.execute(select(GuestAccessTokenModel))).scalars().all()

    assert [row.tenant_id for row in visible] == [tenant_a.id]


# --- `SqlAlchemyGuestPortalStayReader` (D9) -------------------------------------------


@pytest.mark.asyncio
async def test_it_projects_the_stay_and_its_property(db_session) -> None:
    tenant, prop, reservation = await _stay(
        db_session,
        "info",
        wifi_name="Casa Redes",
        access_notes="La llave está en el buzón 3",
        city="Madrid",
        province="Madrid",
        postal_code="28013",
    )
    reader = SqlAlchemyGuestPortalStayReader(db_session, support_channel="+34 600 000 000")

    info = await reader.stay_info(tenant.id, reservation.id)

    assert info is not None
    assert info.check_in_date == CHECK_IN
    assert info.property_name == prop.name
    assert info.city == "Madrid"
    assert info.wifi_name == "Casa Redes"
    assert info.arrival_notes == "La llave está en el buzón 3"
    assert info.support_channel == "+34 600 000 000"


@pytest.mark.asyncio
async def test_the_times_fall_back_to_the_properties_defaults(db_session) -> None:
    """D9: the reservation's own times are nullable, and a channel import rarely sets them.

    Returning `None` would be correct and useless — the guest wants to know when they can get
    in, and the property always has an answer.
    """
    tenant, _, reservation = await _stay(
        db_session,
        "fallback",
        default_check_in_time=time(16, 0),
        default_check_out_time=time(10, 30),
    )
    reader = SqlAlchemyGuestPortalStayReader(db_session)

    info = await reader.stay_info(tenant.id, reservation.id)

    assert reservation.check_in_time is None
    assert info is not None
    assert info.check_in_time == time(16, 0)
    assert info.check_out_time == time(10, 30)


@pytest.mark.asyncio
async def test_the_reservations_own_times_win_when_it_has_them(db_session) -> None:
    """The positive half, so the fallback cannot pass by always using the default."""
    tenant, _, reservation = await _stay(db_session, "own-times")
    reservation.check_in_time = time(18, 45)
    reservation.check_out_time = time(9, 15)
    await db_session.flush()
    reader = SqlAlchemyGuestPortalStayReader(db_session)

    info = await reader.stay_info(tenant.id, reservation.id)

    assert info is not None
    assert info.check_in_time == time(18, 45)
    assert info.check_out_time == time(9, 15)


@pytest.mark.asyncio
async def test_a_stay_of_another_tenant_is_simply_not_there(db_session) -> None:
    """R2.5, and what makes the `404` of D5 identical for "absent" and "someone else's"."""
    tenant_a, _, _ = await _stay(db_session, "reader-a")
    _, _, reservation_b = await _stay(db_session, "reader-b")
    reader = SqlAlchemyGuestPortalStayReader(db_session)

    assert await reader.stay_info(tenant_a.id, reservation_b.id) is None


@pytest.mark.asyncio
async def test_it_refuses_a_stay_whose_property_belongs_to_another_tenant(db_session) -> None:
    """R3.1 and rule 1, on the shape the security panel of section 3 exploited.

    `reservations.property_id` is a plain FK with no tenant coupling, so this row is
    representable — and before the `PropertyModel.tenant_id` predicate was added, this exact
    setup returned tenant B's property name, WiFi network and arrival instructions as if they
    were tenant A's stay.

    **The session is deliberately left unmarked**, which is the whole point: the portal
    authorises before binding (D4), so on this path the global filter of `app/core/db.py` is
    off by design. A version of this test on a marked session would pass against the broken
    query, because the net would have covered for it.
    """
    tenant_a, _, reservation_a = await _stay(db_session, "join-a")
    _, property_b, _ = await _stay(db_session, "join-b", wifi_name="WIFI-B", access_notes="code 1234")
    reservation_a.property_id = property_b.id
    await db_session.flush()
    reader = SqlAlchemyGuestPortalStayReader(db_session)

    assert TENANT_ID_SESSION_KEY not in db_session.info

    assert await reader.stay_info(tenant_a.id, reservation_a.id) is None


@pytest.mark.asyncio
async def test_it_shows_the_masked_code_of_a_usable_access_record(db_session) -> None:
    tenant, prop, reservation = await _stay(db_session, "code-usable")
    db_session.add(
        AccessRecordModel(
            tenant_id=tenant.id,
            property_id=prop.id,
            reservation_id=reservation.id,
            status=AccessRecordStatus.DELIVERED,
            code_masked="****42",
        )
    )
    await db_session.flush()
    reader = SqlAlchemyGuestPortalStayReader(db_session)

    info = await reader.stay_info(tenant.id, reservation.id)

    assert info is not None
    assert info.access_code_masked == "****42"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [AccessRecordStatus.REVOKED, AccessRecordStatus.EXPIRED, AccessRecordStatus.PENDING]
)
async def test_it_hides_the_code_of_a_record_that_will_not_open_the_door(
    db_session, status: AccessRecordStatus
) -> None:
    """Showing a dead code is worse than showing none: the guest tries it and blames the flat.

    `PENDING` is in the list for a different reason — no code has been registered yet, so
    `code_masked` is whatever a test or a provider left there rather than something real.
    """
    tenant, prop, reservation = await _stay(db_session, f"code-{status.value.lower()}")
    db_session.add(
        AccessRecordModel(
            tenant_id=tenant.id,
            property_id=prop.id,
            reservation_id=reservation.id,
            status=status,
            code_masked="****99",
        )
    )
    await db_session.flush()
    reader = SqlAlchemyGuestPortalStayReader(db_session)

    info = await reader.stay_info(tenant.id, reservation.id)

    assert info is not None
    assert info.access_code_masked is None


@pytest.mark.asyncio
async def test_a_reissued_code_shows_the_newest_usable_one(db_session) -> None:
    """A stay can carry several access records over its life; the guest needs the current."""
    tenant, prop, reservation = await _stay(db_session, "code-reissued")
    old = AccessRecordModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        reservation_id=reservation.id,
        status=AccessRecordStatus.DELIVERED,
        code_masked="****11",
    )
    old.created_at = datetime(2026, 8, 1, tzinfo=UTC)
    new = AccessRecordModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        reservation_id=reservation.id,
        status=AccessRecordStatus.DELIVERED,
        code_masked="****22",
    )
    new.created_at = datetime(2026, 8, 9, tzinfo=UTC)
    db_session.add_all([old, new])
    await db_session.flush()
    reader = SqlAlchemyGuestPortalStayReader(db_session)

    info = await reader.stay_info(tenant.id, reservation.id)

    assert info is not None
    assert info.access_code_masked == "****22"


@pytest.mark.asyncio
async def test_two_codes_written_in_the_same_instant_resolve_deterministically(
    db_session,
) -> None:
    """`created_at` alone is not a total order (R3.1).

    Two access records reissued inside one transaction can share a timestamp exactly, and
    `ORDER BY created_at DESC` on its own then lets the query plan decide which code the
    guest sees. `id` breaks the tie — the same fix `SqlAlchemyGuestRepository.find_by_email`
    already carries, which the QA panel of section 3 noticed had not been carried over.

    Asserts **which** record wins, not merely that the answer is stable. With a real total
    order the winner is computable, and pinning it catches a regression that stability alone
    would not — flipping the tiebreaker to `id.asc()` keeps the query perfectly stable while
    silently showing the guest the older of two codes. Raised by the QA panel of section 3.
    """
    tenant, prop, reservation = await _stay(db_session, "code-tie")
    same_instant = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    records = {}
    for masked in ("****11", "****22"):
        record = AccessRecordModel(
            tenant_id=tenant.id,
            property_id=prop.id,
            reservation_id=reservation.id,
            status=AccessRecordStatus.DELIVERED,
            code_masked=masked,
        )
        record.created_at = same_instant
        db_session.add(record)
        records[masked] = record
    await db_session.flush()
    reader = SqlAlchemyGuestPortalStayReader(db_session)

    expected = max(records.values(), key=lambda record: record.id).code_masked
    answers = {
        (await reader.stay_info(tenant.id, reservation.id)).access_code_masked
        for _ in range(5)
    }

    assert answers == {expected}


@pytest.mark.asyncio
async def test_each_time_falls_back_independently(db_session) -> None:
    """The mixed case: a reservation with one of its two times set.

    The two extremes (neither set, both set) are covered above, and both would pass for an
    implementation that decided once and applied the same source to both fields. This is the
    case that separates them.
    """
    tenant, _, reservation = await _stay(
        db_session,
        "mixed-times",
        default_check_in_time=time(16, 0),
        default_check_out_time=time(10, 30),
    )
    reservation.check_in_time = time(19, 0)
    await db_session.flush()
    reader = SqlAlchemyGuestPortalStayReader(db_session)

    info = await reader.stay_info(tenant.id, reservation.id)

    assert reservation.check_out_time is None
    assert info is not None
    assert info.check_in_time == time(19, 0)
    assert info.check_out_time == time(10, 30)


@pytest.mark.asyncio
async def test_a_stay_with_no_access_record_reports_no_code(db_session) -> None:
    tenant, _, reservation = await _stay(db_session, "code-absent")
    reader = SqlAlchemyGuestPortalStayReader(db_session)

    info = await reader.stay_info(tenant.id, reservation.id)

    assert info is not None
    assert info.access_code_masked is None


# --- `SqlAlchemyPortalStayLocator` and `SessionTenantBinder` (R2.5, D4) ---------------
#
# Added after the section 5 panel found both adapters had **no test of any kind** — not a
# fake, not an integration test — while their siblings above had both. `steering/backend-
# architecture.md` puts `infrastructure/` on "integration tests contra Postgres/Redis
# reales", and the unit tests of the authoriser only ever see doubles, so nothing exercised
# the real query or the real bind.


@pytest.mark.asyncio
async def test_the_locator_projects_the_seven_fields_the_authoriser_needs(db_session) -> None:
    """D4 step 2. `status` is the **reservation's**, not the legal registration's."""
    tenant, prop, reservation = await _stay(db_session, "locator")
    locator = SqlAlchemyPortalStayLocator(db_session)

    stay = await locator.find(tenant.id, reservation.id)

    assert stay is not None
    assert stay.reservation_id == reservation.id
    assert stay.tenant_id == tenant.id
    assert stay.property_id == prop.id
    assert stay.guest_id is None
    assert stay.check_in_date == CHECK_IN
    assert stay.check_out_date == CHECK_IN + timedelta(days=2)
    assert stay.status is ReservationStatus.CONFIRMED


@pytest.mark.asyncio
async def test_the_locator_hides_another_tenants_stay_on_an_unmarked_session(
    db_session,
) -> None:
    """R2.5, on the session state the authoriser actually runs in.

    Deliberately unmarked — D4 step 2 happens before `bind_session_to_tenant`, so the global
    filter is off and the explicit `tenant_id` predicate is the only thing scoping this read.
    A marked-session version would pass even if the predicate were deleted.
    """
    tenant_a, _, _ = await _stay(db_session, "locator-a")
    _, _, reservation_b = await _stay(db_session, "locator-b")
    locator = SqlAlchemyPortalStayLocator(db_session)

    assert TENANT_ID_SESSION_KEY not in db_session.info
    assert await locator.find(tenant_a.id, reservation_b.id) is None


@pytest.mark.asyncio
async def test_the_locator_leaves_no_orm_instance_behind(db_session) -> None:
    """Limit 4 of `app/core/db.py`, asserted structurally rather than by refcounting.

    A row read while the session is unmarked stays reachable through the identity map
    afterwards. The locator selects **columns**, so no `ReservationModel` is ever created —
    which is a stronger guarantee than dropping a reference and trusting CPython to collect
    it, the arrangement the section 3, 4 and 5 panels each declined to accept.
    """
    tenant, _, reservation = await _stay(db_session, "locator-idmap")
    db_session.expunge_all()
    locator = SqlAlchemyPortalStayLocator(db_session)

    await locator.find(tenant.id, reservation.id)

    assert not any(
        isinstance(instance, ReservationModel) for instance in db_session.identity_map.values()
    )


@pytest.mark.asyncio
async def test_the_token_lookup_leaves_no_orm_instance_behind(db_session) -> None:
    """The same, for D4 step 1 — the read that runs before any tenant is known.

    This one selected the whole model until the section 5 security panel probed it and found
    a `GuestAccessTokenModel` reachable through `session.get()` after the bind, while the
    authoriser's docstring claimed otherwise.
    """
    tenant, _, reservation = await _stay(db_session, "token-idmap")
    repository = SqlAlchemyGuestAccessTokenRepository(db_session)
    token = generate_guest_token()
    await repository.add(tenant.id, _token(tenant, reservation, hash_guest_token(token)))
    await db_session.flush()
    db_session.expunge_all()

    found = await repository.find_live_by_token_hash(hash_guest_token(token))

    assert found is not None
    assert not any(
        isinstance(instance, GuestAccessTokenModel)
        for instance in db_session.identity_map.values()
    )


@pytest.mark.asyncio
async def test_the_binder_marks_the_session_and_the_filter_becomes_live(db_session) -> None:
    """D4 step 4, through the real adapter rather than a recording double.

    Asserts the *effect* — that the global filter starts covering the request — because
    "the binder was called" is what the unit tests already prove with a fake.
    """
    tenant_a, _, reservation_a = await _stay(db_session, "binder-a")
    _, _, _ = await _stay(db_session, "binder-b")
    db_session.expunge_all()
    binder = SessionTenantBinder(db_session)

    binder.bind(tenant_a.id)

    visible = (await db_session.execute(select(ReservationModel))).scalars().all()
    assert [row.tenant_id for row in visible] == [tenant_a.id]


@pytest.mark.asyncio
async def test_the_binder_refuses_to_rebind_to_another_tenant(db_session) -> None:
    """One-way, and the refusal comes from `app/core/db.py` rather than being re-implemented.

    Re-binding would repoint the global filter at a foreign tenant mid-request, which is
    worse than never binding at all.
    """
    tenant_a, _, _ = await _stay(db_session, "binder-once")
    binder = SessionTenantBinder(db_session)
    binder.bind(tenant_a.id)

    with pytest.raises(ValueError, match="already bound"):
        binder.bind(uuid.uuid4())


@pytest.mark.asyncio
async def test_the_binder_refuses_a_null_tenant(db_session) -> None:
    """The setter used to be its own unbind; `bind_session_to_tenant` closed that."""
    binder = SessionTenantBinder(db_session)

    with pytest.raises(ValueError, match="null tenant"):
        binder.bind(None)  # type: ignore[arg-type]


# --- `LegalRegistrationStayStore.set_guest` (R4.2, OQ3) -------------------------------


@pytest.mark.asyncio
async def test_set_guest_attaches_a_guest_to_a_stay_that_had_none(db_session) -> None:
    tenant, _, reservation = await _stay(db_session, "set-guest")
    guest = GuestModel(tenant_id=tenant.id, full_name="Ada Lovelace")
    db_session.add(guest)
    await db_session.flush()
    store = SqlAlchemyLegalRegistrationStayStore(db_session)

    assert reservation.guest_id is None

    await store.set_guest(tenant.id, reservation.id, guest.id)
    await db_session.flush()
    await db_session.refresh(reservation)

    assert reservation.guest_id == guest.id


@pytest.mark.asyncio
async def test_set_guest_writes_only_that_column(db_session) -> None:
    """The reason it is a second narrow method and not a widened port (D10).

    `LegalRegistrationStayStore` reaches one column at a time on purpose; a method that
    rewrote the booking would erase the boundary its own docstring exists to draw.
    """
    tenant, _, reservation = await _stay(db_session, "set-guest-narrow")
    guest = GuestModel(tenant_id=tenant.id, full_name="Ada Lovelace")
    db_session.add(guest)
    await db_session.flush()
    before = (reservation.check_in_date, reservation.check_out_date, reservation.status)
    store = SqlAlchemyLegalRegistrationStayStore(db_session)

    await store.set_guest(tenant.id, reservation.id, guest.id)
    await db_session.flush()
    await db_session.refresh(reservation)

    assert (reservation.check_in_date, reservation.check_out_date, reservation.status) == before
    assert reservation.legal_registration_status is not None


@pytest.mark.asyncio
async def test_set_guest_cannot_attach_a_guest_of_another_tenant(db_session) -> None:
    """R2.5 and R4.2 — the hole three reviewers of section 3 reproduced independently.

    The `WHERE` clause filters the *reservation* by tenant, which stops the write reaching
    somebody else's stay. It says nothing about the **value** being written, and
    `with_loader_criteria` never could: limit 3 of `app/core/db.py` is that the net
    constrains which rows an UPDATE touches, not what a foreign key column is set to.

    So the guarantee is the composite FK on `(tenant_id, guest_id)`, mirroring the one
    section 1 added for `guest_access_tokens`. Its sibling in this very module,
    `SqlAlchemyGuestAccessTokenRepository.add`, defends the same boundary explicitly — the
    asymmetry is what made this easy to miss.
    """
    tenant_a, _, reservation_a = await _stay(db_session, "foreign-guest-a")
    tenant_b, _, _ = await _stay(db_session, "foreign-guest-b")
    guest_b = GuestModel(tenant_id=tenant_b.id, full_name="Ada Lovelace")
    db_session.add(guest_b)
    await db_session.flush()
    store = SqlAlchemyLegalRegistrationStayStore(db_session)

    # The `UPDATE` is issued by `execute()` rather than deferred to the flush, so the
    # constraint fires inside the call — which is the better place for it: the caller learns
    # at the write, not at some later boundary it may not own.
    with pytest.raises(IntegrityError, match="fk_reservations_guest_within_tenant"):
        await store.set_guest(tenant_a.id, reservation_a.id, guest_b.id)


@pytest.mark.asyncio
async def test_set_guest_accepts_a_guest_of_the_same_tenant(db_session) -> None:
    """The positive half, so the constraint above cannot pass by rejecting everything."""
    tenant, _, reservation = await _stay(db_session, "same-tenant-guest")
    guest = GuestModel(tenant_id=tenant.id, full_name="Ada Lovelace")
    db_session.add(guest)
    await db_session.flush()
    store = SqlAlchemyLegalRegistrationStayStore(db_session)

    await store.set_guest(tenant.id, reservation.id, guest.id)
    await db_session.flush()
    await db_session.refresh(reservation)

    assert reservation.guest_id == guest.id


@pytest.mark.asyncio
async def test_a_booking_may_still_have_no_guest(db_session) -> None:
    """OQ3's premise, and why the composite FK does not break it.

    `guest_id` is nullable and PostgreSQL's default MATCH SIMPLE means a composite foreign
    key simply does not apply when any of its columns is NULL. `POST /reservations` allows a
    booking with no guest, and it has to keep working — it is the case the portal's check-in
    exists to resolve.
    """
    tenant, _, reservation = await _stay(db_session, "no-guest")

    assert reservation.guest_id is None

    await db_session.flush()  # must not raise


@pytest.mark.asyncio
async def test_a_claimed_stay_is_not_stolen_by_a_second_submission(db_session) -> None:
    """R4.5 / OQ3 against the **real** adapter: `WHERE guest_id IS NULL` is the whole fix.

    This is the test the QA panel of section 6 asked for after showing that deleting that one
    predicate left `tests/guests` at 272 passed. The use-case test that covers the same
    ground drives a fake whose `set_guest` implements the claim itself, so it verifies a
    semantics that only exists in the fake; and none of the sibling tests here calls
    `set_guest` on a stay of the **same** tenant that already has a guest, which is the only
    arrangement where the predicate does anything.

    What the unconditional write did: the loser of two concurrent submissions repointed the
    reservation at the `Guest` it had just created, orphaning the winner's row **with the
    encrypted document already inside it** — an identity document no route can reach and no
    ordinary flow can delete. Here the second caller is simply told who holds the stay.
    """
    tenant, _, reservation = await _stay(db_session, "claimed-stay")
    winner = GuestModel(tenant_id=tenant.id, full_name="Grace Hopper")
    loser = GuestModel(tenant_id=tenant.id, full_name="Ada Lovelace")
    db_session.add_all([winner, loser])
    await db_session.flush()
    reservation.guest_id = winner.id
    await db_session.flush()

    holder = await SqlAlchemyLegalRegistrationStayStore(db_session).set_guest(
        tenant.id, reservation.id, loser.id
    )
    await db_session.flush()
    await db_session.refresh(reservation)

    assert holder == winner.id
    assert reservation.guest_id == winner.id


@pytest.mark.asyncio
async def test_claiming_a_free_stay_returns_the_new_guest(db_session) -> None:
    """The winning side, so the test above cannot pass by refusing every claim."""
    tenant, _, reservation = await _stay(db_session, "free-stay")
    guest = GuestModel(tenant_id=tenant.id, full_name="Ada Lovelace")
    db_session.add(guest)
    await db_session.flush()

    holder = await SqlAlchemyLegalRegistrationStayStore(db_session).set_guest(
        tenant.id, reservation.id, guest.id
    )
    await db_session.flush()
    await db_session.refresh(reservation)

    assert holder == guest.id
    assert reservation.guest_id == guest.id


@pytest.mark.asyncio
async def test_set_guest_cannot_reach_a_stay_of_another_tenant(db_session) -> None:
    """R2.5 over **both** statements of the claim, which is why the neighbour has a guest.

    `set_guest` writes conditionally and, when the write matches nothing, reads once more to
    find out who holds the stay. Two queries, two places to forget the `tenant_id` filter —
    and the tenancy panel of section 6 mutated the second one away with the whole suite still
    green, because the previous version of this test only asserted that the neighbour's
    `guest_id` stayed `None`. A stay with no guest reads back as `None` filtered or not.

    Giving tenant B's stay a guest of its own separates the two outcomes: with the filter,
    tenant A is told nobody holds it; without, tenant A is handed the id of a guest belonging
    to somebody else. The portal never calls it with a foreign reservation — the id comes from
    the token's own row — but this is a public port method, and rule 1 of
    `steering/security.md` asks for the test rather than for the argument.
    """
    tenant_a, _, _ = await _stay(db_session, "set-guest-a")
    tenant_b, _, reservation_b = await _stay(db_session, "set-guest-b")
    guest_a = GuestModel(tenant_id=tenant_a.id, full_name="Ada Lovelace")
    guest_b = GuestModel(tenant_id=tenant_b.id, full_name="Grace Hopper")
    db_session.add_all([guest_a, guest_b])
    await db_session.flush()
    reservation_b.guest_id = guest_b.id
    await db_session.flush()
    store = SqlAlchemyLegalRegistrationStayStore(db_session)

    holder = await store.set_guest(tenant_a.id, reservation_b.id, guest_a.id)
    await db_session.flush()
    await db_session.refresh(reservation_b)

    assert holder is None
    assert reservation_b.guest_id == guest_b.id
