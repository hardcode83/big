"""`GET /api/v1/blocked-transitions` over the real app (R2).

The two that matter most: a `CLEANER` cannot read it, and a neighbour tenant's stall is invisible
rather than merely unlisted. The third is R2.4 — the entry disappears on its own once the stall is
resolved, with nothing written to make that happen.
"""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import func, select

from app.auth.domain.enums import UserRole
from app.auth.domain.policy import ROLE_PERMISSIONS, Permission
from app.properties.domain.enums import PropertyOperationalState
from app.properties.infrastructure.models import PropertyModel, PropertyStateTransitionModel
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.models import TenantConfigModel
from tests.properties.conftest import auth_header

ENDPOINT = "/api/v1/blocked-transitions"

# The route takes its instant from `now_utc`, i.e. the real clock, so every stay here is anchored
# to today rather than written as a literal. A fixed date would have made these tests pass on the
# day they were written and drift afterwards — the first version asserted `CHECKIN_TIME_REACHED`
# and got `CHECKOUT_TIME_REACHED`, because the hardcoded stay had already ended.
def _today():
    return datetime.now(UTC).date()

# Literals, never derived from `ROLE_PERMISSIONS`: a table computed from the catalogue would
# agree with any mistake in it. Same reasoning `test_api.py` records for its own sets.
READERS = {UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER}
ALL_ROLES = list(UserRole)


async def _stalled_property(db_session, tenant, *, internal_code="REDES11"):
    """A flat in `CLEANING_IN_PROGRESS` with a stay that started before now: REDES11's shape.

    Seeded directly rather than through the API for the reason `conftest.property_b` records —
    and because `current_operational_state` is deliberately not writable through the API at all.
    """
    prop = PropertyModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Redes 11",
        internal_code=internal_code,
        timezone="Europe/Madrid",
        current_operational_state=PropertyOperationalState.CLEANING_IN_PROGRESS,
        default_check_in_time=time(15, 0),
        default_check_out_time=time(11, 0),
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


async def _stay(db_session, prop, *, started_days_ago=3, ends_in_days=2,
                status=ReservationStatus.CONFIRMED):
    """A stay that is running *right now*, so `CHECKIN_TIME_REACHED` is the due trigger.

    Mid-stay at any hour of the day: the check-in was days ago and the checkout is days away, so
    neither `CHECKIN_WINDOW_OPENED` (which needs the check-in date to be today) nor
    `CHECKOUT_TIME_REACHED` (which needs the checkout passed) can also fire. That keeps the
    expected entry a single one without depending on what time the suite runs.
    """
    check_in = _today() - timedelta(days=started_days_ago)
    check_out = _today() + timedelta(days=ends_in_days)
    reservation = ReservationModel(
        id=uuid.uuid4(),
        tenant_id=prop.tenant_id,
        property_id=prop.id,
        channel=ReservationChannel.MANUAL,
        check_in_date=check_in,
        check_out_date=check_out,
        nights=(check_out - check_in).days,
        status=status,
        adults=2,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation


def _at(api, user):
    return auth_header(api, user)


# --- R2.1, R2.2: the collection and its reason ---


@pytest.mark.asyncio
async def test_a_stalled_flat_is_listed_with_its_reason(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R2.2: "el trigger que no pudo aplicarse y el estado que lo impide"."""
    prop = await _stalled_property(db_session, tenant_a)
    stay = await _stay(db_session, prop)

    response = await api.get(
        ENDPOINT, headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["total_pages"] == 1
    [entry] = body["data"]
    assert entry["property_id"] == str(prop.id)
    assert entry["property_code"] == "REDES11"
    assert entry["reservation_id"] == str(stay.id)
    assert entry["trigger"] == "CHECKIN_TIME_REACHED"
    assert entry["blocking_state"] == "CLEANING_IN_PROGRESS"
    assert entry["due_since"].startswith(f"{stay.check_in_date.isoformat()}T15:00:00")


@pytest.mark.asyncio
async def test_a_healthy_portfolio_lists_nothing(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """The flat did check in, and the recorded transition is what says so (R1.1 as amended).

    Without this the collection would list every occupied flat in the tenant, which is what the
    section-3 panel caught.
    """
    prop = await _stalled_property(db_session, tenant_a)
    prop.current_operational_state = PropertyOperationalState.OCCUPIED_ESTIMATED
    stay = await _stay(db_session, prop)
    db_session.add(
        PropertyStateTransitionModel(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            property_id=prop.id,
            from_state=PropertyOperationalState.AWAITING_CHECKIN,
            to_state=PropertyOperationalState.OCCUPIED_ESTIMATED,
            triggered_by="SYSTEM",
            metadata_={
                "trigger": "CHECKIN_TIME_REACHED",
                "reservation_id": str(stay.id),
            },
        )
    )
    await db_session.flush()

    response = await api.get(
        ENDPOINT, headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0


# --- R2.3: permissions and tenant isolation ---


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ALL_ROLES, ids=lambda role: role.value)
async def test_only_readers_of_properties_may_list(
    api, db_session, tenant_a, users_by_role_a, role
) -> None:
    """D6 widened this to `READ_PROPERTIES`, so the owner sees it and a cleaner does not."""
    await _stalled_property(db_session, tenant_a)

    response = await api.get(ENDPOINT, headers=_at(api, users_by_role_a[role]))

    assert response.status_code == (200 if role in READERS else 403), response.text


def test_every_reader_of_this_collection_may_already_read_reservations() -> None:
    """What D6's justification actually rests on, asserted instead of assumed.

    D6 widened the permission to `READ_PROPERTIES` on the grounds that the collection "no expone
    nada que la propietaria no vea ya en su card del dashboard", which R2.3 then depends on. But
    the body carries `reservation_id` and `due_since` unconditionally, while `app/dashboard`
    re-checks `READ_RESERVATIONS` before including its reservation block. So the claim is true
    only while every role holding `READ_PROPERTIES` also holds `READ_RESERVATIONS` — a coincidence
    in `ROLE_PERMISSIONS`, not a guarantee.

    The section-4 security panel proposed gating the fields the way the dashboard does. This pins
    the coincidence instead, because gating would make the response shape depend on the role for a
    role that does not exist yet, and D6 explicitly chose not to touch `ROLE_PERMISSIONS`. If an
    auditor-style role ever gains `READ_PROPERTIES` without `READ_RESERVATIONS`, this fails and
    names D6 — which is the moment somebody has to decide, rather than the moment it leaks.
    """
    readers = {
        role
        for role, permissions in ROLE_PERMISSIONS.items()
        if Permission.READ_PROPERTIES in permissions
    }
    assert readers, "READ_PROPERTIES is held by nobody — D6's premise is gone"
    without_reservations = {
        role for role in readers if Permission.READ_RESERVATIONS not in ROLE_PERMISSIONS[role]
    }
    assert without_reservations == set(), (
        "these roles can read GET /api/v1/blocked-transitions but not reservations, so its "
        "`reservation_id`/`due_since` would be new exposure and design D6's justification for "
        f"widening to READ_PROPERTIES no longer holds: {without_reservations}"
    )


@pytest.mark.asyncio
async def test_it_is_not_anonymous(api) -> None:
    assert (await api.get(ENDPOINT)).status_code == 401


@pytest.mark.asyncio
async def test_a_neighbours_stall_is_invisible(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    """Rule 1 of `steering/security.md`, DoD §28.18.

    Tenant B's flat is stalled and tenant A's portfolio is clean, so an unscoped query would
    show A exactly one entry — the failure is unmistakable rather than a subtle count.
    """
    theirs = await _stalled_property(db_session, tenant_b, internal_code="THEIRS")
    await _stay(db_session, theirs)

    response = await api.get(
        ENDPOINT, headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "data": [],
        "total": 0,
        "page": 1,
        "per_page": 20,
        "total_pages": 0,
    }


@pytest.mark.asyncio
async def test_a_neighbours_recorded_transition_cannot_clear_our_stall(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    """The evidence read is tenant-scoped too, and this is the shape of getting it wrong.

    `applied_clock_triggers` filters by a caller-supplied reservation id. If it did not also
    filter by tenant, a neighbour's transition row carrying the same reservation id would mark
    our stall as already applied and hide it.
    """
    prop = await _stalled_property(db_session, tenant_a)
    stay = await _stay(db_session, prop)
    theirs = await _stalled_property(db_session, tenant_b, internal_code="THEIRS")
    db_session.add(
        PropertyStateTransitionModel(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            property_id=theirs.id,
            from_state=PropertyOperationalState.AWAITING_CHECKIN,
            to_state=PropertyOperationalState.OCCUPIED_ESTIMATED,
            triggered_by="SYSTEM",
            metadata_={
                "trigger": "CHECKIN_TIME_REACHED",
                "reservation_id": str(stay.id),
            },
        )
    )
    await db_session.flush()

    response = await api.get(
        ENDPOINT, headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )

    assert response.json()["total"] == 1


# --- R2.4: it goes away on its own, and nothing is written ---


@pytest.mark.asyncio
async def test_resolving_the_stall_removes_the_entry_without_any_write(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R2.4, and design D5's reason for persisting nothing: there is no row to forget to close.

    The resolution is simulated the way the machine performs one — the state **and** its
    `property_state_transitions` row, in the same flush. That is not incidental to the test: rule
    9 of `steering/security.md` requires that "todo escritor de `current_operational_state`
    persiste su fila … en la misma transacción", and an earlier version of this test moved only
    the column. The entry correctly stayed listed, because a state moved without a transition row
    is precisely the bypass this change's proposal complains about — the collection is right to
    keep reporting it.
    """
    prop = await _stalled_property(db_session, tenant_a)
    stay = await _stay(db_session, prop)
    headers = _at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    before = await api.get(ENDPOINT, headers=headers)
    assert before.json()["total"] == 1

    prop.current_operational_state = PropertyOperationalState.OCCUPIED_ESTIMATED
    db_session.add(
        PropertyStateTransitionModel(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            property_id=prop.id,
            from_state=PropertyOperationalState.CLEANING_IN_PROGRESS,
            to_state=PropertyOperationalState.OCCUPIED_ESTIMATED,
            triggered_by="SYSTEM",
            metadata_={
                "trigger": "CHECKIN_TIME_REACHED",
                "reservation_id": str(stay.id),
            },
        )
    )
    await db_session.flush()

    after = await api.get(ENDPOINT, headers=headers)

    assert after.json()["total"] == 0


@pytest.mark.asyncio
async def test_reading_the_collection_writes_nothing_at_all(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    prop = await _stalled_property(db_session, tenant_a)
    await _stay(db_session, prop)
    # `TenantConfigModel` is in this list because it was the one that could actually break the
    # claim: the use case reads the check-in window, and the obvious accessor (`get_or_create`)
    # inserts a default row when the tenant has none. Both the architect and the security reviewer
    # found that in the section-4 panel, and without this model the test's own name was untrue.
    counts_before = {
        model: (
            await db_session.execute(select(func.count()).select_from(model))
        ).scalar_one()
        for model in (
            PropertyStateTransitionModel,
            ReservationModel,
            PropertyModel,
            TenantConfigModel,
        )
    }

    await api.get(ENDPOINT, headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER]))

    for model, before in counts_before.items():
        after = (
            await db_session.execute(select(func.count()).select_from(model))
        ).scalar_one()
        assert after == before, model.__name__


# --- pagination is of the result, not of the source (D5) ---


@pytest.mark.asyncio
async def test_a_stall_beyond_the_first_page_of_the_portfolio_still_appears(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """The original bug, reproduced deliberately and refused.

    Twenty-five healthy flats are created before the stalled one. Paginating the *source* would
    put the stall past the first page of properties and hide it again; paginating the result
    cannot.
    """
    for index in range(25):
        healthy = PropertyModel(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            name=f"Healthy {index}",
            internal_code=f"OK{index:03d}",
            timezone="Europe/Madrid",
            current_operational_state=PropertyOperationalState.VACANT_READY,
        )
        db_session.add(healthy)
    prop = await _stalled_property(db_session, tenant_a, internal_code="ZZZ-LAST")
    await _stay(db_session, prop)

    response = await api.get(
        ENDPOINT, headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )

    body = response.json()
    assert body["total"] == 1
    assert [entry["property_code"] for entry in body["data"]] == ["ZZZ-LAST"]


@pytest.mark.asyncio
async def test_the_envelope_pages_the_stalls_and_orders_oldest_first(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    first = await _stalled_property(db_session, tenant_a, internal_code="OLDEST")
    await _stay(db_session, first, started_days_ago=5)
    second = await _stalled_property(db_session, tenant_a, internal_code="NEWEST")
    await _stay(db_session, second, started_days_ago=2)
    headers = _at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    page_one = (await api.get(f"{ENDPOINT}?per_page=1", headers=headers)).json()
    page_two = (await api.get(f"{ENDPOINT}?per_page=1&page=2", headers=headers)).json()

    assert page_one["total"] == 2
    assert page_one["total_pages"] == 2
    assert [entry["property_code"] for entry in page_one["data"]] == ["OLDEST"]
    assert [entry["property_code"] for entry in page_two["data"]] == ["NEWEST"]


@pytest.mark.asyncio
async def test_per_page_is_bounded(api, users_by_role_a) -> None:
    response = await api.get(
        f"{ENDPOINT}?per_page=101", headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )

    assert response.status_code == 422
