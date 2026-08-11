"""The portal's projections, checked as **shapes** (R2.1, R3.1-R3.3; design D4, D9).

These assert almost nothing about behaviour, and that is the point. R3.2 and R3.3 are
satisfied structurally — the forbidden fields do not exist on the type, so no serialiser,
present or future, can reach one. A test that only checked a response body would pass for a
type that *could* leak and happened not to today.

Pure unit tests: `portal_ports.py` is stdlib plus dataclasses, so nothing needs booting.
"""

import dataclasses
import uuid
from datetime import date, time

import pytest

from app.guests.domain.portal_ports import (
    GuestAccessToken,
    GuestPortalStayReader,
    GuestAccessTokenRepository,
    GuestSession,
    StayInfo,
)


def _fields(cls) -> set[str]:
    return {field.name for field in dataclasses.fields(cls)}


# --- `StayInfo` (D9) ------------------------------------------------------------------


def test_stay_info_declares_exactly_the_fields_design_d9_lists() -> None:
    """The allowlist, asserted as an exact set so a new field is a conscious decision.

    Deliberately brittle. Adding a column to what an anonymous endpoint returns is a
    security decision, and a test that tolerated it silently would be the "vocabulary entry
    nobody consciously chose" failure the audit module argues against.
    """
    assert _fields(StayInfo) == {
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


@pytest.mark.parametrize(
    "forbidden",
    [
        # R3.2, named one by one because each is a different kind of mistake.
        "internal_notes",
        "gross_amount",
        "ota_commission",
        "net_amount",
        "external_pms_id",
        "external_channel_id",
        # R3.3 — the one endpoint that returns a document number stays
        # `GET /api/v1/guests/{id}/document`, with its own role and audit row.
        "document_number",
        "document_number_encrypted",
        # Rule 4 of `steering/security.md` grants no masked form for a WiFi password, so
        # there is no shape in which it could legitimately appear.
        "wifi_password",
        "wifi_password_encrypted",
        # The credential itself: R1.2 keeps it out of every response.
        "token",
        "token_hash",
        # Another guest's data, and the ids that would let a caller correlate stays.
        "guest_name",
        "guest_email",
        "reservation_id",
        "tenant_id",
    ],
)
def test_stay_info_cannot_carry_what_r3_forbids(forbidden: str) -> None:
    assert forbidden not in _fields(StayInfo)


def test_stay_info_is_frozen() -> None:
    """A projection a use case cannot edit on the way out."""
    info = StayInfo(
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 3),
        check_in_time=time(15, 0),
        check_out_time=time(11, 0),
        property_name="Casa Redes",
        address_line1=None,
        address_line2=None,
        city=None,
        province=None,
        postal_code=None,
        country="ES",
        timezone="Europe/Madrid",
        wifi_name=None,
        arrival_notes=None,
        access_code_masked=None,
        support_channel=None,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        info.property_name = "Otra"  # type: ignore[misc]


# --- `GuestSession` (D4) --------------------------------------------------------------


def test_guest_session_carries_only_what_the_token_resolved() -> None:
    """R2.1: every identifier a portal use case has came out of the token's own row.

    That is what makes "NEVER SHALL leerlos de la ruta, del cuerpo, de la query ni de una
    cabecera" true by construction rather than by discipline — there is nowhere else for
    them to come from.
    """
    assert _fields(GuestSession) == {
        "tenant_id",
        "reservation_id",
        "property_id",
        "guest_id",
        "token_hash",
    }


def test_guest_session_carries_the_hash_and_never_the_token() -> None:
    """R1.2. The digest is what the throttle charges and what the audit rows name (D6, D11)."""
    assert "token" not in _fields(GuestSession)
    assert "token_hash" in _fields(GuestSession)


def test_guest_session_is_frozen() -> None:
    session = GuestSession(
        tenant_id=uuid.uuid4(),
        reservation_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        guest_id=None,
        token_hash="a" * 64,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        session.tenant_id = uuid.uuid4()  # type: ignore[misc]


def test_a_session_may_have_no_guest_yet() -> None:
    """OQ3: `reservations.guest_id` is nullable, and the check-in creates one rather than
    refusing — which would leave stays that can never complete their legal registration."""
    session = GuestSession(
        tenant_id=uuid.uuid4(),
        reservation_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        guest_id=None,
        token_hash="a" * 64,
    )

    assert session.guest_id is None


# --- `GuestAccessToken` (D2) ----------------------------------------------------------


def test_the_token_row_carries_the_hash_and_never_the_value() -> None:
    """R1.2: past the authoriser, the cleartext value does not exist anywhere."""
    fields = _fields(GuestAccessToken)

    assert "token_hash" in fields
    assert "token" not in fields
    assert "token_value" not in fields


def test_the_token_row_has_no_expiry_column() -> None:
    """D3, as an absence: the window is derived at authorisation time, never stored."""
    assert "expires_at" not in _fields(GuestAccessToken)


# --- The ports themselves -------------------------------------------------------------


def test_the_token_repository_offers_no_way_to_list_or_read_tokens() -> None:
    """Interface segregation, and a security boundary (D2, D14).

    An operator has no read to perform: the row holds only a digest, and rule 3(a)'s named
    exception returns the cleartext exactly once at issue time. A port with a listing would
    be the open door for whichever change comes next.
    """
    methods = {name for name in vars(GuestAccessTokenRepository) if not name.startswith("_")}

    assert methods == {"find_live_by_token_hash", "add", "revoke_live_for_reservation"}


def test_the_stay_reader_offers_exactly_one_read() -> None:
    """One question, about one stay. Not a repository of reservations wearing a hat."""
    methods = {name for name in vars(GuestPortalStayReader) if not name.startswith("_")}

    assert methods == {"stay_info"}
