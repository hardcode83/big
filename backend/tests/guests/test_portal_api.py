"""The anonymous guest portal over HTTP (R2.1-R2.3, R3.1-R3.3, R4.1-R4.5, R6.1, R6.4).

**This surface is reachable from the open internet with no account**, so the assertions that
carry the weight are about what the three routes refuse and what they never say: that the five
rejection causes are one indistinguishable answer, that a valid JWT buys nothing, and that no
response carries a document number — not even back to the guest who just supplied it.

The throttle is a fake here, as in `tests/integrations/test_webhook_receiver_api.py`. Its own
behaviour is pinned in `test_portal_throttle.py`; what these tests need from it is the
**order** the section 5 security panel made binding (task 6.1, constraints 1-4), and a fake is
the only way to observe that order rather than infer it from a counter.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.audit.infrastructure.models import AuditLogModel
from app.auth.api.dependencies import get_client_ip, get_password_hasher, get_token_codec
from app.auth.domain.enums import UserRole
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.config import settings
from app.core.db import TENANT_ID_SESSION_KEY, get_db_session
from app.core.errors import error_envelope
from app.guests.api.errors import http_error_for
from app.guests.api.portal_dependencies import (
    get_guest_portal_throttle,
    get_stay_info_use_case,
)
from app.guests.api.portal_router import _NOT_FOUND
from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus
from app.guests.domain.exceptions import GuestPortalUnauthorised
from app.guests.domain.portal_token import generate_guest_token, hash_guest_token
from app.guests.infrastructure.models import GuestAccessTokenModel, GuestModel
from app.main import create_app
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.timeline.infrastructure.models import TimelineEventModel
from tests.auth.conftest import (  # noqa: F401
    TEST_BCRYPT_ROUNDS,
    tenant_a,
    tenant_b,
    users_by_role_a,
    utc_now,
)

SECRET = "f" * 64
NUMBER = "12345678Z"

#: Far enough inside the window that the grace period cannot expire it mid-suite.
CHECK_OUT = datetime.now(UTC).date() + timedelta(days=3)

CHECKIN = {
    "full_name": "Ada Lovelace",
    "nationality": "GB",
    "date_of_birth": "1815-12-10",
    "document_type": "PASSPORT",
    "document_number": NUMBER,
    "document_expiry_date": "2032-01-01",
}


class _AllowAll:
    """Records what it was asked, in the order it was asked."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures: list[str] = []

    async def probe_allowed(self, client_ip: str) -> bool:
        self.calls.append("probe")
        return True

    async def request_allowed(self, token_hash: str) -> bool:
        self.calls.append("request")
        return True

    async def record_failed_authorisation(self, client_ip: str) -> None:
        self.calls.append("failure")
        self.failures.append(client_ip)


class _RefuseProbes(_AllowAll):
    async def probe_allowed(self, client_ip: str) -> bool:
        self.calls.append("probe")
        return False


class _RefuseRequests(_AllowAll):
    async def request_allowed(self, token_hash: str) -> bool:
        self.calls.append("request")
        return False


@pytest.fixture
def throttle() -> _AllowAll:
    return _AllowAll()


def _build_app(db_session, throttle):
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_guest_portal_throttle] = lambda: throttle
    return app


@pytest_asyncio.fixture
async def api(db_session, throttle):
    app = _build_app(db_session, throttle)
    codec = JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        yield client


async def _stay(db_session, tenant, *, name="Casa Redes", with_guest=True, **overrides):
    prop = PropertyModel(
        tenant_id=tenant.id,
        name=name,
        internal_code=f"C{uuid.uuid4().hex[:6]}",
        pms_external_id=f"PMS-{uuid.uuid4().hex[:6]}",
        max_guests=4,
        wifi_name=f"{name} 5G",
        access_notes="El portal es el 3, timbre B",
        city="Madrid",
    )
    db_session.add(prop)
    await db_session.flush()

    guest = None
    if with_guest:
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
        guest_id=guest.id if guest else None,
        channel="DIRECT",
        nights=2,
        **values,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation, guest


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


# --- `GET /guest/info/{token}` (R3.1, R3.2, R3.3; D9) ---------------------------------


@pytest.mark.asyncio
async def test_the_guest_sees_their_stay(api, db_session, tenant_a) -> None:
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.get(f"/api/v1/guest/info/{token}")

    assert response.status_code == 200
    body = response.json()
    assert body["property_name"] == "Casa Redes"
    assert body["city"] == "Madrid"
    assert body["wifi_name"] == "Casa Redes 5G"
    assert body["arrival_notes"] == "El portal es el 3, timbre B"
    assert body["check_out_date"] == CHECK_OUT.isoformat()


@pytest.mark.asyncio
async def test_the_info_response_has_the_fields_of_d9_and_no_others(
    api, db_session, tenant_a
) -> None:
    """R3.2 over the wire, on top of the structural guarantee.

    `StayInfo` cannot hold a forbidden field, so this is belt to that braces — but
    `StayInfoResponse` is a second type and could grow one of its own without the projection
    noticing. Asserting on the serialised body is what would catch that.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    reservation.internal_notes = "Cliente VIP, no cobrar la limpieza"
    await db_session.flush()
    token = await _token(db_session, tenant_a, reservation)

    response = await api.get(f"/api/v1/guest/info/{token}")

    assert set(response.json()) == {
        "check_in_date",
        "check_out_date",
        "check_in_time",
        "check_out_time",
        "property_name",
        "address_line1",
        "address_line2",
        "city",
        "province",
        "postal_code",
        "country",
        "timezone",
        "wifi_name",
        "arrival_notes",
        "access_code_masked",
        "support_channel",
    }
    assert "VIP" not in response.text


@pytest.mark.asyncio
async def test_each_token_answers_for_its_own_stay(api, db_session, tenant_a) -> None:
    """R3.1: the token is what selects the stay, so two tokens of one tenant do not blur."""
    first, _ = await _stay(db_session, tenant_a, name="Casa Redes")
    second, _ = await _stay(db_session, tenant_a, name="Piso Riazor")
    first_token = await _token(db_session, tenant_a, first)
    second_token = await _token(db_session, tenant_a, second)

    first_body = (await api.get(f"/api/v1/guest/info/{first_token}")).json()
    second_body = (await api.get(f"/api/v1/guest/info/{second_token}")).json()

    assert first_body["property_name"] == "Casa Redes"
    assert second_body["property_name"] == "Piso Riazor"


# --- The five rejections, over HTTP (R2.2, D5) ----------------------------------------


@pytest.mark.asyncio
async def test_every_rejection_is_the_same_404(api, db_session, tenant_a, throttle) -> None:
    """R2.2 end to end: five causes, one status **and one body**.

    The unit tests prove the authoriser raises one exception type; this proves the wire
    format does not reintroduce a difference — a `404` that varies by a word or by a
    `Retry-After` is still an oracle (task 6.1, constraint 4). Hence the comparison is over
    the whole response, and the body is a module constant in the router rather than something
    each route builds for itself.
    """
    revoked_reservation, _ = await _stay(db_session, tenant_a)
    revoked = await _token(db_session, tenant_a, revoked_reservation)
    (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == revoked_reservation.id
            )
        )
    ).scalar_one().revoked_at = datetime.now(UTC)

    expired_reservation, _ = await _stay(
        db_session,
        tenant_a,
        check_in_date=date(2020, 1, 1),
        check_out_date=date(2020, 1, 3),
    )
    expired = await _token(db_session, tenant_a, expired_reservation)

    cancelled_reservation, _ = await _stay(
        db_session, tenant_a, status=ReservationStatus.CANCELLED
    )
    cancelled = await _token(db_session, tenant_a, cancelled_reservation)
    await db_session.flush()

    answers = set()
    for token in (generate_guest_token(), "not-a-token", revoked, expired, cancelled):
        response = await api.get(f"/api/v1/guest/info/{token}")
        answers.add((response.status_code, response.text))
        assert "retry-after" not in {header.lower() for header in response.headers}

    assert len(answers) == 1
    assert answers.pop()[0] == 404
    # Every one of the five was charged to the per-IP budget (task 6.1, constraint 2):
    # counting only some causes would make the throttle itself the distinguisher.
    assert len(throttle.failures) == 5

    # And a live token still works, so the uniformity above is not "everything fails".
    live_reservation, _ = await _stay(db_session, tenant_a)
    live = await _token(db_session, tenant_a, live_reservation)
    assert (await api.get(f"/api/v1/guest/info/{live}")).status_code == 200


@pytest.mark.asyncio
async def test_a_valid_jwt_buys_nothing(api, db_session, tenant_a, users_by_role_a) -> None:
    """R2.3, satisfied by absence rather than by a check.

    No route in `portal_router.py` declares `bearer_scheme`, `AuthenticatedDep` or
    `require(...)`, so nothing reads `Authorization`. A caller holding a perfectly good
    manager token and an invalid path token gets byte-for-byte what a stranger gets.
    """
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    header = {
        "Authorization": "Bearer "
        + api.codec.issue_access(  # type: ignore[attr-defined]
            user_id=manager.id,
            tenant_id=manager.tenant_id,
            role=manager.role,
            family_id=uuid.uuid4(),
            now=utc_now(),
        )
    }
    token = generate_guest_token()

    anonymous = await api.get(f"/api/v1/guest/info/{token}")
    authenticated = await api.get(f"/api/v1/guest/info/{token}", headers=header)

    assert authenticated.status_code == anonymous.status_code == 404
    assert authenticated.text == anonymous.text


# --- The order the section 5 panel made binding (task 6.1, constraints 1-4) -----------


@pytest.mark.asyncio
async def test_the_probe_limit_bites_before_any_lookup(db_session, tenant_a) -> None:
    """Constraint 1: nothing touches the database before `probe_allowed`.

    Observed rather than asserted about the code — the fake refuses the probe, and the fact
    that `authorize` never ran is what proves a guess costs the guesser more than it costs us.
    """
    throttle = _RefuseProbes()
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    async with AsyncClient(
        transport=ASGITransport(app=_build_app(db_session, throttle)), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/v1/guest/info/{token}")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert throttle.calls == ["probe"]


@pytest.mark.asyncio
async def test_an_invalid_body_never_reaches_the_throttle_at_all(
    db_session, tenant_a
) -> None:
    """The measured exception to constraint 1, pinned so the docstrings stay honest.

    FastAPI parses and validates the body while solving dependencies, so on the `POST` a
    malformed one is a `422` decided before the route function — and therefore before
    `probe_allowed`. The security panel of section 6 measured this against docstrings that
    claimed "before **any** work"; the claim is now "before any lookup", and this is what
    makes the distinction a fact rather than a caveat somebody wrote down.

    It costs no information: the `422` is identical whatever the token, as the two calls
    below show. What it costs is parsing, bounded by `MaxBodySizeMiddleware` (D7).
    """
    throttle = _AllowAll()
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    async with AsyncClient(
        transport=ASGITransport(app=_build_app(db_session, throttle)), base_url="http://test"
    ) as client:
        with_live_token = await client.post(
            f"/api/v1/guest/checkin/{token}", json={"nonsense": True}
        )
        with_junk_token = await client.post(
            f"/api/v1/guest/checkin/{generate_guest_token()}", json={"nonsense": True}
        )

    assert with_live_token.status_code == with_junk_token.status_code == 422
    assert with_live_token.json() == with_junk_token.json()
    assert throttle.calls == []


@pytest.mark.asyncio
async def test_the_per_stay_limit_is_only_reached_by_a_token_that_resolves(
    db_session, tenant_a
) -> None:
    """Constraint 4: the `429` of `request_allowed` is not an oracle, because reaching it
    already requires holding the token. What has to hold is the order — authorise first,
    charge the stay's budget after, and never charge it on the rejection path.
    """
    throttle = _RefuseRequests()
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    async with AsyncClient(
        transport=ASGITransport(app=_build_app(db_session, throttle)), base_url="http://test"
    ) as client:
        good = await client.get(f"/api/v1/guest/info/{token}")
        bad = await client.get(f"/api/v1/guest/info/{generate_guest_token()}")

    assert good.status_code == 429
    assert bad.status_code == 404
    assert throttle.calls == ["probe", "request", "probe", "failure"]


# --- `GET /guest/checkin/{token}` (R4.1, R3.3) ----------------------------------------


@pytest.mark.asyncio
async def test_it_names_what_is_missing_and_not_what_was_given(
    api, db_session, tenant_a
) -> None:
    """R4.1: names of the absent fields of PRD §17, and no values at all."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    body = (await api.get(f"/api/v1/guest/checkin/{token}")).json()

    assert body["document_status"] == "NOT_PROVIDED"
    # `full_name` is on the guest already and the two dates are the reservation's, so the
    # form has five boxes and not eight.
    assert body["missing_fields"] == [
        "nationality",
        "date_of_birth",
        "document_type",
        "document_number",
        "document_expiry_date",
    ]
    assert set(body) == {"missing_fields", "document_status", "legal_registration_status"}


@pytest.mark.asyncio
async def test_a_stay_with_no_guest_asks_for_the_name_too(api, db_session, tenant_a) -> None:
    """OQ3: the booking may carry no guest at all, and then the form needs the name."""
    reservation, _ = await _stay(db_session, tenant_a, with_guest=False)
    token = await _token(db_session, tenant_a, reservation)

    body = (await api.get(f"/api/v1/guest/checkin/{token}")).json()

    assert "full_name" in body["missing_fields"]
    assert "check_in_date" not in body["missing_fields"]


@pytest.mark.asyncio
async def test_once_the_document_is_on_file_nothing_is_missing_and_nothing_is_echoed(
    api, db_session, tenant_a
) -> None:
    """R4.1 and R3.3 together — the second is why this is not just `missing_fields == []`."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    assert (await api.post(f"/api/v1/guest/checkin/{token}", json=CHECKIN)).status_code == 200

    response = await api.get(f"/api/v1/guest/checkin/{token}")

    assert response.json()["missing_fields"] == []
    assert response.json()["document_status"] == "PROVIDED"
    assert NUMBER not in response.text
    assert "Lovelace" not in response.text


# --- `POST /guest/checkin/{token}` (R4.2-R4.5, R2.1, R6.1, R6.4) ----------------------


@pytest.mark.asyncio
async def test_the_document_is_stored_encrypted_and_never_echoed(
    api, db_session, tenant_a
) -> None:
    """R4.2 and R3.3 together, because either one alone would mislead."""
    reservation, guest = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(f"/api/v1/guest/checkin/{token}", json=CHECKIN)

    assert response.status_code == 200
    assert response.json() == {
        "document_status": "PROVIDED",
        "legal_registration_status": "READY_TO_SUBMIT",
    }
    assert NUMBER not in response.text
    await db_session.refresh(guest)
    assert guest.document_number_encrypted is not None
    assert NUMBER not in guest.document_number_encrypted
    assert guest.document_status is GuestDocumentStatus.PROVIDED


@pytest.mark.asyncio
async def test_the_check_in_moves_the_legal_registration(api, db_session, tenant_a) -> None:
    """R4.3, and it is the existing rule doing the work — this change only triggers it."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    await api.post(f"/api/v1/guest/checkin/{token}", json=CHECKIN)

    await db_session.refresh(reservation)
    assert reservation.legal_registration_status is LegalRegistrationStatus.READY_TO_SUBMIT


@pytest.mark.asyncio
async def test_it_creates_and_links_a_guest_when_the_booking_had_none(
    api, db_session, tenant_a
) -> None:
    """OQ3, end to end: one row per stay, named from what the guest typed."""
    reservation, _ = await _stay(db_session, tenant_a, with_guest=False)
    token = await _token(db_session, tenant_a, reservation)

    assert (await api.post(f"/api/v1/guest/checkin/{token}", json=CHECKIN)).status_code == 200

    await db_session.refresh(reservation)
    assert reservation.guest_id is not None
    guest = (
        await db_session.execute(
            select(GuestModel).where(GuestModel.id == reservation.guest_id)
        )
    ).scalar_one()
    assert guest.full_name == "Ada Lovelace"
    assert guest.tenant_id == tenant_a.id


@pytest.mark.asyncio
async def test_the_audit_row_names_the_bearer_and_no_user(api, db_session, tenant_a) -> None:
    """R6.1 and R6.4: the actor is the token's digest, and the personal data is not in it."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    await api.post(f"/api/v1/guest/checkin/{token}", json=CHECKIN)

    entry = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == "GUEST_DOCUMENT_UPDATED")
        )
    ).scalar_one()
    assert entry.actor_guest_token_hash == hash_guest_token(token)
    assert entry.actor_user_id is None
    assert NUMBER not in str(entry.changes)
    assert "Lovelace" not in str(entry.changes)


@pytest.mark.asyncio
async def test_resending_the_form_adds_an_audit_row_but_not_a_second_milestone(
    api, db_session, tenant_a
) -> None:
    """R4.5 and D13, which treat the two side effects differently on purpose.

    The timeline is append-only, so a resend must not claim a second check-in. The audit
    trail is the opposite: suppressing the second row would hide a second submission of a
    document, possibly from another address, which is exactly what a review looks for.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    first = await api.post(f"/api/v1/guest/checkin/{token}", json=CHECKIN)
    second = await api.post(f"/api/v1/guest/checkin/{token}", json=CHECKIN)

    assert first.json() == second.json()
    events = (
        (
            await db_session.execute(
                select(TimelineEventModel).where(
                    TimelineEventModel.event_type == "GUEST_CHECKIN_COMPLETED"
                )
            )
        )
        .scalars()
        .all()
    )
    audits = (
        (
            await db_session.execute(
                select(AuditLogModel).where(AuditLogModel.action == "GUEST_DOCUMENT_UPDATED")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert len(audits) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {**CHECKIN, "document_number": ""},
        {key: value for key, value in CHECKIN.items() if key != "document_number"},
        {**CHECKIN, "nationality": "ESP"},
        {**CHECKIN, "document_expiry_date": "not-a-date"},
        {**CHECKIN, "document_type": "PARCHMENT"},
    ],
)
async def test_an_invalid_body_is_rejected_and_persists_nothing(
    api, db_session, tenant_a, body: dict
) -> None:
    """R4.4: no partial write, verified by reading the row back.

    The last three cases are not padding. `document_type` and `document_expiry_date` are
    among the four `GUEST` fields still recorded as real diffs in `audit_logs.changes` after
    section 2 denylisted the rest, so the schema refusing free text is what keeps a
    stranger's typing out of a rule 11 cleartext sink (task 6.6's carry-forward).
    """
    reservation, guest = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(f"/api/v1/guest/checkin/{token}", json=body)

    assert response.status_code == 422
    await db_session.refresh(guest)
    assert guest.document_number_encrypted is None
    assert guest.document_status is GuestDocumentStatus.NOT_PROVIDED
    assert guest.nationality is None
    assert (await db_session.execute(select(AuditLogModel))).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("smuggled", ["tenant_id", "reservation_id", "guest_id"])
async def test_an_identity_field_in_the_body_is_refused(
    api, db_session, tenant_a, smuggled: str
) -> None:
    """R2.1 at the boundary: those come from the token, and `extra="forbid"` says so loudly.

    Refusing rather than ignoring is the point — silently dropping the field would leave the
    caller believing it had been accepted.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(
        f"/api/v1/guest/checkin/{token}", json={**CHECKIN, smuggled: str(uuid.uuid4())}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
async def test_a_blank_name_is_a_422_and_changes_nothing(
    api, db_session, tenant_a, blank: str
) -> None:
    """R4.4, and the worst defect this change produced (QA panel, section 6).

    `min_length=1` counts characters, so `"   "` used to pass validation — and then the two
    branches diverged in different bad ways. With a guest already on the stay the write
    landed and replaced the legal name with whitespace; `missing_fields` *does* normalise, so
    the stay fell back to `PENDING_GUEST_DATA` and could never leave it again, with no error
    anywhere for the operator to see. With no guest, the same body came back as the `404`
    reserved for "your link does not work". `str_strip_whitespace=True` collapses both into
    the one answer R4.4 asks for.
    """
    reservation, guest = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(
        f"/api/v1/guest/checkin/{token}", json={**CHECKIN, "full_name": blank}
    )

    assert response.status_code == 422
    await db_session.refresh(guest)
    assert guest.full_name == "Ada Lovelace"
    assert guest.document_number_encrypted is None
    await db_session.refresh(reservation)
    assert reservation.legal_registration_status is LegalRegistrationStatus.PENDING_GUEST_DATA


@pytest.mark.asyncio
async def test_a_blank_name_on_a_stay_with_no_guest_is_the_same_422(
    api, db_session, tenant_a
) -> None:
    """The branch that used to answer `404` instead — same body, same status, no `Guest`."""
    reservation, _ = await _stay(db_session, tenant_a, with_guest=False)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(
        f"/api/v1/guest/checkin/{token}", json={**CHECKIN, "full_name": "   "}
    )

    assert response.status_code == 422
    await db_session.refresh(reservation)
    assert reservation.guest_id is None


@pytest.mark.asyncio
async def test_the_name_is_stored_trimmed(api, db_session, tenant_a) -> None:
    """The other half of stripping: a name with stray spaces is accepted and normalised,
    not rejected. A guest typing `" Ada Lovelace "` has made no mistake."""
    reservation, guest = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    response = await api.post(
        f"/api/v1/guest/checkin/{token}", json={**CHECKIN, "full_name": "  Ada Lovelace  "}
    )

    assert response.status_code == 200
    await db_session.refresh(guest)
    assert guest.full_name == "Ada Lovelace"


@pytest.mark.asyncio
async def test_a_revoked_token_cannot_submit(api, db_session, tenant_a) -> None:
    """R1.4 on the write path, which is the one that matters."""
    reservation, guest = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id
            )
        )
    ).scalar_one().revoked_at = datetime.now(UTC)
    await db_session.flush()

    response = await api.post(f"/api/v1/guest/checkin/{token}", json=CHECKIN)

    assert response.status_code == 404
    await db_session.refresh(guest)
    assert guest.document_number_encrypted is None


# --- Tenant isolation on the one surface whose session is born unmarked ----------------
#
# Rule 1 of `steering/security.md`: "Tests automáticos que demuestran que un tenant no accede
# a datos de otro — obligatorios en cada módulo nuevo." The tenancy panel of section 6 found
# this file with no such test at all: every row it created belonged to `tenant_a`, so a
# regression in the wiring — the layer that decides which repository runs on which session
# with which `tenant_id` — had nothing here that could fail.
#
# One constraint shapes how these are written. `bind_session_to_tenant` is one-way and the
# test client shares a single session with the fixtures, so **one test cannot authorise for
# two tenants**: the second `bind` raises rather than repointing the filter, which is exactly
# the protection it exists to give. Each test therefore drives one tenant and inspects the
# other's rows directly.


@pytest.mark.asyncio
async def test_a_token_only_ever_answers_for_its_own_tenant(
    api, db_session, tenant_a, tenant_b
) -> None:
    """R2.1 and R2.5: the tenant comes from the token's row, never from anything the caller
    sends, and a neighbour's stay is not reachable by holding a token at all."""
    theirs, _ = await _stay(db_session, tenant_a, name="Casa Redes")
    await _token(db_session, tenant_a, theirs)
    ours, _ = await _stay(db_session, tenant_b, name="Piso Riazor")
    our_token = await _token(db_session, tenant_b, ours)

    body = (await api.get(f"/api/v1/guest/info/{our_token}")).json()

    assert body["property_name"] == "Piso Riazor"
    assert "Casa Redes" not in str(body)
    # And the session ended up marked with the token's tenant, not the other one.
    assert db_session.info[TENANT_ID_SESSION_KEY] == tenant_b.id


@pytest.mark.asyncio
async def test_a_stay_pointing_at_a_neighbours_property_reveals_nothing(
    api, db_session, tenant_a, tenant_b
) -> None:
    """The leak the security and tenancy panels of section 3 reproduced, seen from outside.

    `reservations.property_id` is still a plain foreign key with no tenant coupling — the
    roadmap candidate recorded in `proposal.md` — so this row is representable today.

    **What this test pins is the end-to-end consequence with both defences in place, and it
    is deliberately not the falsifiable one.** The tenancy panel of section 6 mutated the
    reader to remove its explicit `properties.tenant_id` filter and this test still passed:
    by the time the reader runs, D4 step 4 has marked the session, so the global filter's
    `with_loader_criteria` re-adds the same predicate inside the join. Over HTTP the explicit
    filter cannot be pinned at all, because on this path the session is marked by
    construction. The test that can fail is
    `test_portal_repositories.py::test_it_refuses_a_stay_whose_property_belongs_to_another_tenant`,
    which runs on a session deliberately left **unmarked** — the arrangement the net does not
    cover, and the one a future reader in Core or literal SQL would face. Both are kept: that
    one guards the filter, this one guards the answer.
    """
    neighbour = PropertyModel(
        tenant_id=tenant_b.id,
        name="Ático del vecino",
        internal_code=f"C{uuid.uuid4().hex[:6]}",
        pms_external_id=f"PMS-{uuid.uuid4().hex[:6]}",
        max_guests=2,
        wifi_name="Ático 5G",
        city="A Coruña",
    )
    db_session.add(neighbour)
    await db_session.flush()

    reservation, _ = await _stay(db_session, tenant_a)
    reservation.property_id = neighbour.id
    await db_session.flush()
    token = await _token(db_session, tenant_a, reservation)

    response = await api.get(f"/api/v1/guest/info/{token}")

    assert response.status_code == 404
    assert "Ático" not in response.text


@pytest.mark.asyncio
async def test_the_check_in_writes_only_inside_the_tokens_tenant(
    api, db_session, tenant_a, tenant_b
) -> None:
    """R2.5 on the write path. A neighbour's guest is left exactly as it was."""
    neighbour_guest = GuestModel(tenant_id=tenant_b.id, full_name="Grace Hopper")
    db_session.add(neighbour_guest)
    reservation, guest = await _stay(db_session, tenant_a)
    await db_session.flush()
    token = await _token(db_session, tenant_a, reservation)

    assert (await api.post(f"/api/v1/guest/checkin/{token}", json=CHECKIN)).status_code == 200

    await db_session.refresh(guest)
    await db_session.refresh(neighbour_guest)
    assert guest.document_number_encrypted is not None
    assert neighbour_guest.document_number_encrypted is None
    assert neighbour_guest.full_name == "Grace Hopper"


@pytest.mark.asyncio
async def test_a_token_that_resolves_but_does_not_authorise_never_marks_the_session(
    api, db_session, tenant_a
) -> None:
    """D4 step 4: the bind happens **after** the three checks of D3, never before them.

    A session marked on the way to a refusal would leave the global filter pointing at a
    tenant the caller failed to prove anything about — for the rest of the request, and for
    everything a later handler on the same session did.

    **The token has to be a revoked one, not an unknown one**, and that is the whole design
    of this test. The tenancy panel of section 6 moved the `bind` above the three checks and
    the first version passed anyway: it presented a token that resolves to nothing, so there
    was no tenant to bind under either ordering and the mutation could not show. A revoked
    token resolves a row, a stay and a tenant, and then fails check one — which is exactly
    the arrangement where binding too early is both possible and wrong.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id
            )
        )
    ).scalar_one().revoked_at = datetime.now(UTC)
    await db_session.flush()

    assert (await api.get(f"/api/v1/guest/info/{token}")).status_code == 404

    assert TENANT_ID_SESSION_KEY not in db_session.info


# --- What the router does with the refusals that arrive late (task 6.1, constraint 2) --


class _RefusingStayInfo:
    """A use case that authorises fine and then finds nothing — the shape of a stay that
    stops resolving mid-request, or of a `Guest` row that is gone."""

    async def execute(self, session) -> None:
        raise GuestPortalUnauthorised()


@pytest.mark.asyncio
async def test_a_late_refusal_is_the_same_body_and_is_charged_too(
    db_session, tenant_a
) -> None:
    """Constraint 2 of task 6.1, which the architecture and documentation panels found
    unmet: `record_failed_authorisation` on **every** rejection, while three routes answered
    their post-authorisation refusals without charging anything.

    Both halves matter. The body has to be the module constant — a second `404` wording is
    the drift D5 exists to prevent — and the charge has to happen, because a branch that
    costs nothing is a branch a caller can tell apart by watching its own budget.
    """
    throttle = _AllowAll()
    app = _build_app(db_session, throttle)
    app.dependency_overrides[get_stay_info_use_case] = _RefusingStayInfo
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        late = await client.get(f"/api/v1/guest/info/{token}")
        early = await client.get(f"/api/v1/guest/info/{generate_guest_token()}")

    assert late.status_code == early.status_code == 404
    assert late.text == early.text
    assert len(throttle.failures) == 2


def test_the_error_handler_is_a_net_that_matches_the_constant() -> None:
    """`_MAPPING` in `api/errors.py` declares itself exhaustive over `GuestDomainError`.

    `GuestPortalUnauthorised` is one, and had no row: an escape would have become
    `500 "Unexpected guest error"` — the one thing D5 spends the whole design preventing,
    reachable through the handler rather than through a route. Unreachable today, because
    every route that can raise it catches it — `POST /guest/incident/{token}` is the one that
    does not, and does not need to: its use case has no refusal path (section 7). What the row
    cannot do is charge the per-IP budget, which is why it is the net and `_unauthorised` stays
    the mechanism (architecture panel, section 6, round 2).
    """
    http_status, code = http_error_for(GuestPortalUnauthorised())

    assert http_status == 404
    assert error_envelope(code, str(GuestPortalUnauthorised())) == _NOT_FOUND


# --- The real throttle, through the real router (QA panel, section 6) ------------------


@pytest.mark.asyncio
async def test_the_router_drives_the_real_throttle(db_session, tenant_a) -> None:
    """Every other test in this file replaces the throttle with a hand-written double.

    Nothing forces those doubles to match `RedisGuestPortalThrottle`, so renaming one of its
    methods would leave the whole file green while every request to the deployed portal
    raised `AttributeError`. This one runs the router against the real adapter and the real
    Redis of the compose stack, which is what turns the doubles into a convenience instead of
    a blind spot. The sibling surface has had it since section 2 of `reservations-webhooks`;
    this surface did not, and the QA panel of section 6 said so. Verified by that panel:
    renaming any of the three throttle methods kills this test and nothing else.

    It is also the test that made the Redis client's module global worth fixing rather than
    noting — see `_close_the_redis_client_between_tests` in the root `conftest.py`. Its first
    version carried its own teardown, which protected every test that ran *after* it and left
    it at the mercy of anything that ran before: `pytest tests/integrations tests/guests` was
    red while the reverse order was green.
    """
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    # A unique address per run, for the reason the webhook version of this test records:
    # `ASGITransport` reports every request as `127.0.0.1`, and the refusal below charges a
    # real, shared key that outlives the test inside its 60-second window. What is being
    # checked here is that the throttle's *methods* are real, not which address they key on.
    app.dependency_overrides[get_client_ip] = (
        lambda: f"198.51.100.{uuid.uuid4().int % 200}-{uuid.uuid4().hex[:8]}"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        allowed = await client.get(f"/api/v1/guest/info/{token}")
        refused = await client.get(f"/api/v1/guest/info/{generate_guest_token()}")

    assert allowed.status_code == 200
    assert refused.status_code == 404


# --- The support channel (R3.1, D9) ---------------------------------------------------


@pytest.mark.asyncio
async def test_the_support_channel_comes_from_configuration(
    api, db_session, tenant_a, monkeypatch
) -> None:
    """D9: "constante de configuración, no un dato de otro huésped".

    The first wiring passed `None` in hard and no setting existed, so the field was in the
    contract as `required` and no guest could ever receive a value — R3.1 asks for the
    support channel, and the architecture and documentation panels of section 6 both caught
    it. The default stays `None`, which is the honest answer for an installation that has not
    chosen one; what this pins is that configuring it reaches the response.
    """
    monkeypatch.setattr(settings, "guest_portal_support_channel", "+34 600 000 000")
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    body = (await api.get(f"/api/v1/guest/info/{token}")).json()

    assert body["support_channel"] == "+34 600 000 000"
