"""`POST /api/v1/guest/incident/{token}` over HTTP (R5.1, R5.2, R5.3; design D15).

The fourth and last route of PRD §23, and the only one of the four that **creates a row from a
stranger's free text**. So the assertions that carry the weight are about what it refuses
before writing anything, what the answer does not contain, and what the portal offers no way
to do afterwards.

The throttle is a fake, as in `test_portal_api.py`: what these tests need from it is the order
the section 5 security panel made binding, and a fake is the only way to observe an order.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from app.audit.infrastructure.models import AuditLogModel
from app.core.db import get_db_session
from app.guests.api.portal_dependencies import get_guest_portal_throttle
from app.guests.api.portal_router import _NOT_FOUND
from app.guests.api.portal_schemas import MultiLineText, SingleLineText
from app.guests.domain.enums import LegalRegistrationStatus
from app.guests.domain.portal_token import generate_guest_token, hash_guest_token
from app.guests.infrastructure.models import GuestAccessTokenModel, GuestModel
from app.main import create_app
from app.maintenance.domain.enums import IncidentSource, IncidentStatus
from app.maintenance.infrastructure.models import IncidentModel
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from tests.auth.conftest import tenant_a, tenant_b, utc_now  # noqa: F401
from tests.route_walk import flatten_routes

#: Far enough inside the window that the grace period cannot expire it mid-suite.
CHECK_OUT = datetime.now(UTC).date() + timedelta(days=3)

REPORT = {
    "title": "The boiler makes a loud noise",
    "description": "It started last night and it wakes us up.",
}


class _AllowAll:
    """Records what it was asked, in the order it was asked."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def probe_allowed(self, client_ip: str) -> bool:
        self.calls.append("probe")
        return True

    async def request_allowed(self, token_hash: str) -> bool:
        self.calls.append("request")
        return True

    async def record_failed_authorisation(self, client_ip: str) -> None:
        self.calls.append("failure")


class _RefuseRequests(_AllowAll):
    async def request_allowed(self, token_hash: str) -> bool:
        self.calls.append("request")
        return False


@pytest.fixture
def throttle() -> _AllowAll:
    return _AllowAll()


@pytest_asyncio.fixture
async def api(db_session, throttle):
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_guest_portal_throttle] = lambda: throttle
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _stay(db_session, tenant, *, name="Casa Redes", **overrides):
    prop = PropertyModel(
        tenant_id=tenant.id,
        name=name,
        internal_code=f"C{uuid.uuid4().hex[:6]}",
        max_guests=4,
    )
    db_session.add(prop)
    await db_session.flush()

    guest = GuestModel(tenant_id=tenant.id, full_name="Ada Lovelace")
    db_session.add(guest)
    await db_session.flush()

    values = {
        "check_in_date": CHECK_OUT - timedelta(days=2),
        "check_out_date": CHECK_OUT,
        "status": ReservationStatus.CONFIRMED,
        "legal_registration_status": LegalRegistrationStatus.PENDING_GUEST_DATA,
    }
    values.update(overrides)
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        guest_id=guest.id,
        channel="DIRECT",
        nights=2,
        **values,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation, prop


async def _token(db_session, tenant, reservation) -> str:
    token = generate_guest_token()
    db_session.add(
        GuestAccessTokenModel(
            tenant_id=tenant.id,
            reservation_id=reservation.id,
            token_hash=hash_guest_token(token),
        )
    )
    await db_session.flush()
    return token


async def _incidents(db_session) -> list[IncidentModel]:
    db_session.expunge_all()
    return list((await db_session.execute(select(IncidentModel))).scalars().all())


# --- The happy path (R5.1) -------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_guest_opens_an_incident_against_their_own_stay(
    api, db_session, tenant_a
) -> None:
    reservation, prop = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(f"/api/v1/guest/incident/{token}", json=REPORT)

    assert response.status_code == 201
    body = response.json()
    stored = await _incidents(db_session)
    assert len(stored) == 1
    incident = stored[0]
    assert body["id"] == str(incident.id)
    assert incident.tenant_id == tenant_a.id
    assert incident.property_id == prop.id
    assert incident.reservation_id == reservation.id
    assert incident.source is IncidentSource.GUEST
    assert incident.status is IncidentStatus.OPEN
    assert incident.title == REPORT["title"]
    assert incident.description == REPORT["description"]


@pytest.mark.asyncio
async def test_the_acknowledgement_is_three_fields_and_nothing_else(
    api, db_session, tenant_a
) -> None:
    """R5.3: the only reading of an incident this surface offers is the acknowledgement.

    Pinned as an exact key set rather than field by field, because the failure mode is a field
    *appearing* — a later change returning the category, the property or the internal notes
    would keep every positive assertion green.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(f"/api/v1/guest/incident/{token}", json=REPORT)

    assert set(response.json()) == {"id", "status", "created_at"}
    assert response.json()["status"] == "OPEN"


@pytest.mark.asyncio
async def test_the_persisted_reporter_is_the_digest_and_never_the_token(
    api, db_session, tenant_a
) -> None:
    """R5.1 end to end: the column would hold either value, so this is what pins which."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    await api.post(f"/api/v1/guest/incident/{token}", json=REPORT)

    incident = (await _incidents(db_session))[0]
    assert incident.reported_by_guest_token == hash_guest_token(token)
    assert incident.reported_by_user_id is None
    assert token not in (incident.reported_by_guest_token or "")


@pytest.mark.asyncio
async def test_the_report_leaves_an_audit_row_and_a_timeline_entry(
    api, db_session, tenant_a
) -> None:
    """R6.1, R6.3 over the wire — and neither carries the token or the guest's words."""
    reservation, prop = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    await api.post(f"/api/v1/guest/incident/{token}", json=REPORT)

    incident = (await _incidents(db_session))[0]
    audit = list((await db_session.execute(select(AuditLogModel))).scalars().all())
    events = list((await db_session.execute(select(TimelineEventModel))).scalars().all())

    assert [row.action for row in audit] == ["INCIDENT_CREATED"]
    assert audit[0].entity_type == "INCIDENT"
    assert audit[0].entity_id == incident.id
    assert audit[0].actor_guest_token_hash == hash_guest_token(token)
    assert audit[0].actor_user_id is None
    assert REPORT["title"] not in str(audit[0].changes)
    assert REPORT["description"] not in str(audit[0].changes)

    assert [event.event_type for event in events] == [TimelineEventType.INCIDENT_CREATED]
    assert events[0].actor_type is TimelineActorType.GUEST
    assert events[0].actor_user_id is None
    assert events[0].property_id == prop.id
    assert REPORT["description"] not in str(events[0].metadata_)
    assert events[0].title != REPORT["title"]


# --- Refusals before anything is written (R5.2) ----------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"title": "Boiler"}, id="no-description"),
        pytest.param({"description": "It is broken"}, id="no-title"),
        pytest.param({"title": "Boiler", "description": "   "}, id="blank-description"),
        pytest.param({"title": "   ", "description": "It is broken"}, id="blank-title"),
        pytest.param({"title": "T" * 301, "description": "x"}, id="title-too-long"),
        pytest.param(
            {"title": "T", "description": "x" * 5001}, id="description-too-long"
        ),
        pytest.param(
            {"title": "boiler\x00", "description": "ok"}, id="nul-byte-in-title"
        ),
        pytest.param(
            {"title": "boiler", "description": "ok\x00"}, id="nul-byte-in-description"
        ),
        pytest.param(
            {"title": "boiler\nsecond line", "description": "ok"},
            id="newline-in-title",
        ),
        pytest.param(
            {"title": "T", "description": "x", "property_id": str(uuid.uuid4())},
            id="identity-in-the-body",
        ),
    ],
)
@pytest.mark.asyncio
async def test_an_invalid_body_is_refused_before_the_incident_exists(
    api, db_session, tenant_a, body
) -> None:
    """R5.2 — "rechazarlo **antes** de crear la incidencia", asserted as absence of the row.

    The identity case is R2.1 at the boundary: `extra="forbid"` rejects a body naming a
    `property_id` rather than ignoring it, so a caller cannot believe it was honoured.

    The `description-too-long` case is the section 7 security panel's second finding: the field
    was unbounded on the argument that the 1 MiB body ceiling was the bound, which bounds a
    request and not what a stay may accumulate at sixty requests a minute (D6, D13). Both
    length cases count characters **after** stripping.

    The control-character cases are the QA panel's finding, and each answered `500` before the
    fix: a `U+0000` is refused by Postgres, asyncpg raises, and nothing catches it. A newline in
    the `title` is refused too — it is one line in an operator's list — while `description`
    keeps its paragraphs, which `test_a_multi_line_description_is_accepted` pins from the other
    side.

    The lone-surrogate half of the same finding needs a raw body rather than a dict, so it lives
    in `test_a_lone_surrogate_is_refused_like_any_other_unstorable_text` below.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(f"/api/v1/guest/incident/{token}", json=body)

    assert response.status_code == 422
    assert await _incidents(db_session) == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            '{"title": "boiler\\ud800", "description": "ok"}', id="in-title"
        ),
        pytest.param(
            '{"title": "boiler", "description": "ok\\udfff"}', id="in-description"
        ),
    ],
)
@pytest.mark.asyncio
async def test_a_body_carrying_a_lone_surrogate_is_refused_before_the_field_is_reached(
    api, db_session, tenant_a, body
) -> None:
    """A `\\uD800` escape in an ASCII body: refused, and **not** by the field validator.

    What this pins is the endpoint's behaviour — `422`, no row — plus *where* the refusal comes
    from, because that turned out to be the interesting part. FastAPI parses bodies with
    pydantic-core's `jiter`, which refuses to build a string holding an unpaired surrogate, so the
    body dies as invalid JSON before any `AfterValidator` runs. The error type is
    `string_unicode`/`json_invalid`, never the `value_error` `_storable_text` raises.

    **This test was first written claiming the opposite** — that the escape reached the field and
    the guard caught it — on the strength of `json.loads` behaving that way. The QA panel of
    section 7 measured it and the claim was false for this stack. The guard's own branch is pinned
    directly by `test_the_storable_text_guard_refuses_a_surrogate_when_it_can_reach_it`, which is
    the only way to reach it.

    Sent as a raw body because these cases cannot travel through `json=`: httpx serialises with
    `ensure_ascii=False` and dies in the client before a request exists.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(
        f"/api/v1/guest/incident/{token}",
        content=body.encode("ascii"),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert await _incidents(db_session) == []


def test_the_storable_text_guard_refuses_a_surrogate_when_it_can_reach_it() -> None:
    """The branch no request body can exercise, pinned where it can be.

    Without this, deleting the `encode("utf-8")` check would leave the whole suite green — the
    `422` would keep arriving from the JSON parser one layer earlier — and the branch would be
    coverage nobody had earned. It is kept rather than deleted because it is correct and cheap,
    and because a JSON parser that ever accepts a lone surrogate would make it the only thing
    between an anonymous body and an unhandled `500` in asyncpg's parameter binding.
    """
    for annotation in (SingleLineText, MultiLineText):
        with pytest.raises(ValidationError) as refusal:
            TypeAdapter(annotation).validate_python("boiler" + chr(0xD800))

        assert "unpaired surrogate" in str(refusal.value)

    # **The message this module writes** carries no fragment of the value, which is the part
    # under this module's control and the reason it does not quote the `UnicodeEncodeError`.
    #
    # Pydantic's own `str(ValidationError)` *does* append `input_value=...`, so the guarantee
    # R3.3 needs is not "the exception is clean" — it is that nothing serialises that field into
    # a response. Measured, and pinned one test up in
    # `test_a_validation_failure_does_not_echo_what_was_rejected`. Asserting it on `str(exc)`
    # here would have been a comfortable test of a false statement.
    with pytest.raises(ValidationError) as refusal:
        TypeAdapter(SingleLineText).validate_python("12345678Z" + chr(0xD800))

    assert "12345678Z" not in refusal.value.errors()[0]["msg"]


@pytest.mark.asyncio
async def test_a_validation_failure_does_not_echo_what_was_rejected(
    api, db_session, tenant_a
) -> None:
    """R3.3 inside the `422`, which is the one refusal body that could carry the value back.

    Raised as a doubt by the security panel of section 7: Pydantic v2 puts the rejected `input`
    in every entry of `ValidationError.errors()`, and FastAPI's **default** handler serialises
    that dict wholesale — so on a stock application a `422` on `document_number` answers with the
    submitted document number. Measured here: this application does not, because it installs its
    own handler that projects each error to `loc`/`type`/`msg` and drops `input`.

    So the guarantee holds today by virtue of that handler, and nothing pinned it. This test is
    the pin. It drives `document_number` deliberately — the field R3.3 names — through the check-in
    route, because the incident fields would prove the same mechanism about text that is not PII.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    number = "12345678Z" + "X" * 200  # over the field's maximum, so it is a 422

    response = await api.post(
        f"/api/v1/guest/checkin/{token}",
        json={
            "full_name": "Ada Lovelace",
            "nationality": "GB",
            "date_of_birth": "1815-12-10",
            "document_type": "PASSPORT",
            "document_number": number,
            "document_expiry_date": "2032-01-01",
        },
    )

    assert response.status_code == 422
    assert number not in response.text
    assert "12345678Z" not in response.text
    # The refusal still says which field failed, which is what makes it usable.
    assert "document_number" in response.text


@pytest.mark.asyncio
async def test_a_multi_line_description_is_accepted(api, db_session, tenant_a) -> None:
    """The other side of the control-character guard: prose is prose.

    Without this, the cheapest way to satisfy the QA finding — refusing every control character
    in both fields — would pass every test above while making a guest press Enter and get a
    `422` for describing a problem in two paragraphs.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(
        f"/api/v1/guest/incident/{token}",
        json={
            "title": "The boiler makes a loud noise",
            "description": "It started last night.\n\nIt wakes us up at 3am.\tEvery night.",
        },
    )

    assert response.status_code == 201
    incident = (await _incidents(db_session))[0]
    assert "\n\n" in incident.description
    assert "\t" in incident.description


@pytest.mark.asyncio
async def test_a_body_that_never_parses_spends_no_throttle_budget(
    api, db_session, tenant_a, throttle
) -> None:
    """The measured half of constraint 1 (section 6 security panel).

    FastAPI validates the body while solving dependencies, so a malformed one is a `422` that
    never reaches the route — and therefore charges nothing. It costs no information: the
    answer is identical whatever the token, and the body ceiling of D7 bounds the work.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(f"/api/v1/guest/incident/{token}", json={"title": "x"})

    assert response.status_code == 422
    assert throttle.calls == []


# --- The refusal is the same refusal (R2.2, D5) ----------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_token_answers_the_one_constant_404(api, db_session, tenant_a) -> None:
    await _stay(db_session, tenant_a)

    response = await api.post(
        f"/api/v1/guest/incident/{generate_guest_token()}", json=REPORT
    )

    assert response.status_code == 404
    assert response.json() == _NOT_FOUND
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
async def test_a_revoked_token_answers_the_same_404(api, db_session, tenant_a) -> None:
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    row = (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.token_hash == hash_guest_token(token)
            )
        )
    ).scalar_one()
    row.revoked_at = datetime.now(UTC)
    await db_session.flush()

    response = await api.post(f"/api/v1/guest/incident/{token}", json=REPORT)

    assert response.status_code == 404
    assert response.json() == _NOT_FOUND
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
async def test_a_cancelled_stay_answers_the_same_404(api, db_session, tenant_a) -> None:
    reservation, _ = await _stay(db_session, tenant_a, status=ReservationStatus.CANCELLED)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(f"/api/v1/guest/incident/{token}", json=REPORT)

    assert response.status_code == 404
    assert response.json() == _NOT_FOUND
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
async def test_a_failed_authorisation_is_charged_to_the_per_ip_budget(
    api, db_session, tenant_a, throttle
) -> None:
    """Constraint 3: every rejection is counted, so the throttle cannot become the
    distinguisher D5 forbids."""
    await _stay(db_session, tenant_a)

    await api.post(f"/api/v1/guest/incident/{generate_guest_token()}", json=REPORT)

    assert throttle.calls == ["probe", "failure"]


@pytest.mark.asyncio
async def test_the_per_token_budget_is_charged_only_after_authorising(
    db_session, tenant_a
) -> None:
    """Constraint 4, and the row must not exist: a `429` means nothing was written."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    throttle = _RefuseRequests()
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_guest_portal_throttle] = lambda: throttle
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/guest/incident/{token}", json=REPORT)

    assert response.status_code == 429
    assert throttle.calls == ["probe", "request"]
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
async def test_a_token_of_another_tenant_cannot_open_an_incident_here(
    api, db_session, tenant_a, tenant_b
) -> None:
    """Rule 1 of `steering/security.md` at the HTTP boundary.

    The stay, the property and the tenant all come from the token, so "cross-tenant" cannot be
    expressed in the request at all — which is what this asserts: tenant B's token writes
    tenant B's row, and tenant A's stay is untouched.
    """
    reservation_a, _ = await _stay(db_session, tenant_a, name="Casa A")
    reservation_b, prop_b = await _stay(db_session, tenant_b, name="Casa B")
    await _token(db_session, tenant_a, reservation_a)
    token_b = await _token(db_session, tenant_b, reservation_b)

    response = await api.post(f"/api/v1/guest/incident/{token_b}", json=REPORT)

    assert response.status_code == 201
    stored = await _incidents(db_session)
    assert [row.tenant_id for row in stored] == [tenant_b.id]
    assert stored[0].property_id == prop_b.id
    assert stored[0].reservation_id == reservation_b.id


# --- R5.3, structurally ----------------------------------------------------------------


def test_the_portal_offers_no_way_to_read_or_change_an_incident() -> None:
    """R5.3 is enforced by absence, so the census is the test.

    "Ninguna ruta de portal que liste/lea/modifique incidencias" cannot be proven by calling
    an endpoint that does not exist — a `404` would be indistinguishable from the one D5
    returns for a dead token. What is checkable is the application's own route table: there is
    exactly one incident route in the whole system, and it is this `POST`.

    Through `flatten_routes` and not `app.routes`, which is the trap that module was written
    to close: an included router is a single object there, so walking it directly finds **zero**
    endpoints and the assertion passes while inspecting nothing. This test was written the
    wrong way first and caught by its own red — the third time that walk has claimed somebody.

    **Scoped to the portal's own surface, and it did not start that way.** It asserted that
    the portal's `POST` was the only incident route *in the whole application*, which was
    true while nothing else could reach an incident. `maintenance` is what makes it false:
    that change gives the module the `api/` it never had, with eleven authenticated routes.
    Widening the assertion to list them would make this test fail every time that surface
    grows, for a reason that has nothing to do with the guest portal. What R5.3 actually
    promises is about **this** surface — an anonymous bearer of a stay link cannot read or
    change an incident — so that is what is asserted: among the routes reachable without a
    session, exactly one touches an incident and it only creates one.
    """
    routes, _ = flatten_routes(create_app())

    portal_incident_routes = {
        (method, path)
        for path, route in routes
        if "incident" in path and path.startswith("/api/v1/guest/")
        for method in route.methods or set()
        if method != "HEAD"
    }

    assert portal_incident_routes == {("POST", "/api/v1/guest/incident/{token}")}
