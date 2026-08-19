"""R1-R4 — `GET /api/v1/cleaning-tasks/{id}/context`, end to end over ASGI.

What only this level can show, and why task 3.4 insists on it:

* **The forbidden fields are absent from the SERIALISED body.** A projection that omits them is
  an intention; a body that does not contain the string is the guarantee. The two come apart the
  moment somebody reaches for `model_validate` over `Property`, which carries `access_notes`,
  `cleaning_notes` and `emergency_notes`. The fixture below sets all three to recognisable
  values, so the assertions search bytes that would be there if the guarantee broke.
* **R1.3 is pydantic's default, not something the code states.** A `null` address must arrive
  *with its key*, and only the real body can show the key did not vanish.
* **R2.4 is a serialisation property.** The offset has to be in the string.
* **The two 404s are byte-identical.** Another cleaner's task and an id that never existed must
  be one outcome, and comparing the rendered bodies is the only way to prove it.

The per-branch rules are pinned in `test_task_context_use_case.py`; here they are checked to
survive the wiring.
"""

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import TASK_NOT_FOUND_MESSAGE
from app.core.openapi import build_openapi
from app.main import create_app
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from tests.cleaning.conftest import auth_header, insert_task

TASKS = "/api/v1/cleaning-tasks"

#: The eleven keys of `CleaningTaskContext`, as the wire must carry them (design D3).
EXPECTED_KEYS = {
    "property_name",
    "property_internal_code",
    "address_line1",
    "address_line2",
    "city",
    "province",
    "postal_code",
    "country",
    "timezone",
    "checkout_at",
    "next_checkin_deadline",
}

#: Set on the fixture property so a leak would be visible as this exact string in the body.
ACCESS_NOTES = "LLAVES-EN-EL-BUZON"
CLEANING_NOTES = "ASPIRAR-EL-SOFA"
EMERGENCY_NOTES = "PORTERO-600000000"


async def _insert_cleaner(session, tenant) -> UserModel:
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Limpiadora",
        email=f"cleaner-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x" * 60,
        role=UserRole.CLEANER,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def cleaner_a(db_session, tenant_a):
    return await _insert_cleaner(db_session, tenant_a)


@pytest_asyncio.fixture
async def other_cleaner_a(db_session, tenant_a):
    """A second cleaner **of the same tenant** — the R3.2 case, which tenant scoping alone
    would not catch."""
    return await _insert_cleaner(db_session, tenant_a)


@pytest_asyncio.fixture
async def cleaner_b(db_session, tenant_b):
    return await _insert_cleaner(db_session, tenant_b)


@pytest_asyncio.fixture
async def addressed_property_a(db_session, property_a):
    """`property_a` with a real address — and with the three notes R1.4 forbids.

    `address_line2` stays `NULL` on purpose: it is the field R1.3 is about.
    """
    property_a.address_line1 = "Calle de Redes 11"
    property_a.address_line2 = None
    property_a.city = "Madrid"
    property_a.province = "Madrid"
    property_a.postal_code = "28029"
    property_a.country = "ES"
    property_a.timezone = "Europe/Madrid"
    property_a.access_notes = ACCESS_NOTES
    property_a.cleaning_notes = CLEANING_NOTES
    property_a.emergency_notes = EMERGENCY_NOTES
    await db_session.flush()
    return property_a


@pytest_asyncio.fixture
async def outgoing_reservation_a(db_session, tenant_a, addressed_property_a):
    """The stay whose checkout the cleaning follows, with money on it (the R2.5 case)."""
    from datetime import UTC, datetime, time, timedelta
    from decimal import Decimal

    check_out = datetime.now(UTC).date() + timedelta(days=1)
    reservation = ReservationModel(
        tenant_id=tenant_a.id,
        property_id=addressed_property_a.id,
        channel=ReservationChannel.AIRBNB,
        check_in_date=check_out - timedelta(days=3),
        check_out_date=check_out,
        nights=3,
        status=ReservationStatus.CONFIRMED,
        check_out_time=time(10, 30),
        gross_amount=Decimal("450.00"),
        ota_commission=Decimal("67.50"),
        net_amount=Decimal("382.50"),
        special_requests="LATE-CHECKOUT-PLEASE",
        internal_notes="INTERNAL-DO-NOT-SHOW",
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation


@pytest_asyncio.fixture
async def next_arrival_a(db_session, tenant_a, addressed_property_a, outgoing_reservation_a):
    """A `CONFIRMED` arrival two days after the checkout — inside D10's 14-day horizon.

    Without it `next_checkin_deadline` would be `null` on every API test and R2.2 would never be
    exercised over the wire, only in the use-case fakes.
    """
    from datetime import time, timedelta

    check_in = outgoing_reservation_a.check_out_date + timedelta(days=2)
    reservation = ReservationModel(
        tenant_id=tenant_a.id,
        property_id=addressed_property_a.id,
        channel=ReservationChannel.AIRBNB,
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=2),
        nights=2,
        status=ReservationStatus.CONFIRMED,
        check_in_time=time(16, 0),
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation


@pytest_asyncio.fixture
async def task_a(db_session, tenant_a, addressed_property_a, template_a, cleaner_a,
                 outgoing_reservation_a, next_arrival_a):
    task = await insert_task(
        db_session,
        tenant_a,
        addressed_property_a,
        template_a,
        reservation=outgoing_reservation_a,
        status=CleaningTaskStatus.CREATED,
        cleaner=cleaner_a,
    )
    await db_session.flush()
    return task


@pytest_asyncio.fixture
async def task_b(db_session, tenant_b, property_b, template_b, cleaner_b):
    task = await insert_task(
        db_session, tenant_b, property_b, template_b, cleaner=cleaner_b
    )
    await db_session.flush()
    return task


async def _context(api, task_id, user):
    return await api.get(f"{TASKS}/{task_id}/context", headers=auth_header(api, user))


# --- the happy path ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_assigned_cleaner_gets_the_eleven_fields(api, task_a, cleaner_a):
    """R1.1, R1.2 — the address and the zone, over a role with neither `READ_PROPERTIES` nor
    `READ_RESERVATIONS`."""
    response = await _context(api, task_a.id, cleaner_a)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == EXPECTED_KEYS
    assert body["property_name"] == "Property REDES11"
    assert body["property_internal_code"] == "REDES11"
    assert body["address_line1"] == "Calle de Redes 11"
    assert body["city"] == "Madrid"
    assert body["province"] == "Madrid"
    assert body["postal_code"] == "28029"
    assert body["country"] == "ES"
    assert body["timezone"] == "Europe/Madrid"


@pytest.mark.asyncio
async def test_a_null_address_field_travels_as_null_with_its_key(api, task_a, cleaner_a):
    """R1.3 — inherited pydantic behaviour, so it gets its own test rather than being assumed.

    The failure this catches is an `exclude_none` appearing anywhere on the path: the value
    would not become wrong, the **key would disappear**, and a client destructuring the response
    would read `undefined` instead of "this flat has no second address line".
    """
    response = await _context(api, task_a.id, cleaner_a)

    body = response.json()
    assert "address_line2" in body
    assert body["address_line2"] is None


@pytest.mark.asyncio
async def test_both_instants_are_iso_8601_with_an_explicit_offset(api, task_a, cleaner_a):
    """R2.4 — a serialisation property, so only the rendered string can show it."""
    body = (await _context(api, task_a.id, cleaner_a)).json()

    for field in ("checkout_at", "next_checkin_deadline"):
        value = body[field]
        assert value is not None, f"{field} should be populated by the fixtures"
        assert "T" in value
        # Madrid, so CEST or CET depending on the date — but never a bare local time and never
        # a `Z` that would silently reinterpret the instant.
        assert value.endswith("+02:00") or value.endswith("+01:00"), value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forbidden",
    [
        # R1.4 — the three plaintext sinks, by their fixture values so the assertion cannot
        # pass merely because the key is spelled differently.
        ACCESS_NOTES,
        CLEANING_NOTES,
        EMERGENCY_NOTES,
        "access_notes",
        "cleaning_notes",
        "emergency_notes",
        "has_wifi_password",
        "wifi_password",
        # R2.5 — the money, the channel and the guest of the outgoing reservation.
        "450.00",
        "67.50",
        "382.50",
        "LATE-CHECKOUT-PLEASE",
        "INTERNAL-DO-NOT-SHOW",
        "gross_amount",
        "ota_commission",
        "net_amount",
        "payment_status",
        "guest_id",
        "special_requests",
        "internal_notes",
        # R2.5 names the channel too, and it was the one clause with no assertion: both the
        # key and the fixture's value, since either alone could pass for the wrong reason.
        "channel",
        "AIRBNB",
    ],
)
async def test_the_body_never_carries_what_r1_4_and_r2_5_forbid(
    api, task_a, cleaner_a, forbidden
):
    """Against the real bytes, not the field list — the guarantee, not the intention."""
    response = await _context(api, task_a.id, cleaner_a)

    assert forbidden not in response.text


@pytest.mark.asyncio
async def test_the_forbidden_search_is_not_vacuous(api, task_a, cleaner_a, db_session):
    """The test above would pass against an empty body — this proves the rows really hold it.

    **Every value the parametrised test searches for, not a sample of them.** A first version
    checked two of the three property notes and nothing at all from the reservation, which left
    six of the forbidden strings able to pass for the wrong reason: a fixture that quietly
    stopped setting `gross_amount`, or wired the reservation to another property, would make
    their absence from the body meaningless and no test would notice.
    """
    assert (await _context(api, task_a.id, cleaner_a)).status_code == 200

    from sqlalchemy import select

    from app.properties.infrastructure.models import PropertyModel

    stored = await db_session.scalar(
        select(PropertyModel).where(PropertyModel.id == task_a.property_id)
    )
    assert stored.access_notes == ACCESS_NOTES
    assert stored.cleaning_notes == CLEANING_NOTES
    assert stored.emergency_notes == EMERGENCY_NOTES

    reservation = await db_session.scalar(
        select(ReservationModel).where(ReservationModel.id == task_a.reservation_id)
    )
    # The reservation the endpoint actually reads: same property, and carrying every value
    # R2.5 forbids.
    assert reservation.property_id == task_a.property_id
    assert reservation.gross_amount == Decimal("450.00")
    assert reservation.ota_commission == Decimal("67.50")
    assert reservation.net_amount == Decimal("382.50")
    assert reservation.special_requests == "LATE-CHECKOUT-PLEASE"
    assert reservation.internal_notes == "INTERNAL-DO-NOT-SHOW"
    assert reservation.channel is ReservationChannel.AIRBNB


# --- the row-level rule --------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_cleaners_task_is_a_404_identical_to_an_unknown_id(
    api, task_a, other_cleaner_a
):
    """R3.2 — same status **and the same body**, byte for byte.

    Two 404s with distinguishable bodies would be the probe the shared message exists to close:
    a body saying "not assigned to you" confirms the task exists and belongs to someone else.
    """
    mine = await _context(api, task_a.id, other_cleaner_a)
    unknown = await _context(api, uuid.uuid4(), other_cleaner_a)

    assert mine.status_code == 404
    assert unknown.status_code == 404
    # The raw bytes, not `.json()`: comparing parsed bodies is blind to key order and
    # whitespace, so it would not prove what this test's name claims.
    assert mine.text == unknown.text


@pytest.mark.asyncio
async def test_the_404_uses_the_prd_error_envelope(api, task_a, other_cleaner_a):
    """R4.2 — PRD §23's envelope with the `NOT_FOUND` code."""
    body = (await _context(api, task_a.id, other_cleaner_a)).json()

    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == TASK_NOT_FOUND_MESSAGE


@pytest.mark.asyncio
async def test_another_tenants_task_is_a_404(api, task_b, cleaner_a):
    """R3.3 at the wire — a wiring check, **not** the test that discharges isolation.

    `cleaner_a` belongs to tenant A and asks for a task of tenant B, and the neighbour tenant is
    not optional: an isolation test with nothing to fail to reach proves nothing. But be honest
    about what this one can prove. Every authenticated request marks the session
    (`bind_session_to_tenant`, `app/auth/api/dependencies.py`), and `_scope_statement_to_tenant`
    (`app/core/db.py`) then injects the tenant predicate into every ORM select regardless of what
    the use case passes explicitly — so this assertion would still see a `404` even if
    `GetCleaningTaskContextUseCase` dropped its own `tenant_id` filter entirely. Measured: a probe
    that removed the filter from `SqlAlchemyPropertyRepository.get` left this test green.

    The test that actually discharges rule 1 of `steering/security.md` for this composition runs
    on fakes with no session in play, where no defence-in-depth net can rescue it:
    `tests/cleaning/test_task_context_use_case.py::TestTheRowLevelRule`
    `::test_a_task_pointing_at_another_tenants_property_is_not_found`.
    """
    response = await _context(api, task_b.id, cleaner_a)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_a_role_without_the_read_permission_is_403(api, task_a, users_by_role_a):
    """R3.4 — `TECHNICIAN` holds no cleaning permission at all.

    **What "antes de tocar la base de datos" does and does not mean here.** `require(...)` is a
    dependency, so FastAPI resolves it before the handler: no cleaning task, property or
    reservation row is read. It is *not* true that the request performs no query at all — the
    authentication dependency loads the caller's user row first, which is what makes the role it
    checks the persisted one.

    The code is asserted and not just the status: `PasswordChangeRequiredError` also answers
    `403` (`app/auth/api/errors.py`), so a bare status assertion would keep passing if the
    shared user fixture ever started demanding a password change — leaving the RBAC gate
    untested while the suite stayed green.
    """
    response = await _context(api, task_a.id, users_by_role_a[UserRole.TECHNICIAN])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER],
    ids=["property_manager", "tenant_owner"],
)
async def test_a_manager_or_owner_reads_a_task_that_is_not_theirs(
    api, task_a, users_by_role_a, role
):
    """R3.5 — `restrict_to_cleaner_id` is `None` for both, so the row rule does not apply."""
    response = await _context(api, task_a.id, users_by_role_a[role])

    assert response.status_code == 200, response.text
    assert response.json()["property_internal_code"] == "REDES11"


# --- what the contract has to say ----------------------------------------------------------


def test_the_published_description_states_the_three_things_r4_3_requires():
    """R4.3 — the description is a *requirement*, so it is asserted and not just written.

    Everything else in this module tests behaviour, which means the description could be dropped
    or garbled by a refactor and all 8000-odd tests would stay green: nothing else reads the
    string. The three clauses below are the ones R4.3 and design D4/D10 put in the contract rather
    than only in the design, so they are the three that must survive.

    Asserted against the generated document, not the decorator, because R4.3 is about what the
    published operation declares — that is what `cleaner-app` will read.
    """
    document = build_openapi(create_app())
    description = document["paths"][f"{TASKS}/{{task_id}}/context"]["get"]["description"]

    # R4.3: role-derived scope, not widenable by parameter.
    assert "no request parameter can widen it" in description
    # D4: the plan and the answer-as-of-now are different things.
    assert "scheduled_start" in description and "scheduled_end" in description
    # D10: what `null` means, with the horizon named.
    assert "within the 14 days following the anchor" in description
