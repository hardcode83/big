"""The D8 redaction of `special_requests` (`app/integrations/infrastructure/free_text.py`).

D8 is the frontier `pms-beds24-adapter` deferred with an expiry date: its P.8 left
`special_requests` outside rule 13 *"until an unauthenticated write from the internet exists
over that same column"*, which is what this change brings. The chosen form is redacting long
digit runs on **external** sources only, with no Luhn check.

Both halves live here on purpose: the external path redacts and the manual API path does not.
Split across two files, the second half is the one that quietly stops being asserted.
"""

import pytest

from app.integrations.infrastructure.free_text import (
    LONG_DIGIT_RUN_REDACTED,
    MIN_REDACTED_DIGITS,
    redact_long_digit_runs,
)
from app.integrations.infrastructure.beds24.mapping import (
    to_reservation_dto as beds24_to_dto,
)
from app.integrations.infrastructure.channex.mapping import (
    to_reservation_dto as channex_to_dto,
)
from app.auth.domain.enums import UserRole
from app.reservations.infrastructure.models import ReservationModel
from sqlalchemy import select

from tests.integrations.conftest import beds24_fixture, channex_booking
from tests.reservations.conftest import (  # noqa: F401
    api,
    auth_header,
    create_payload,
    property_a,
    property_b,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)

# A test PAN, not a real one: the prefix is Visa's and the number is the one every payment
# SDK ships as its example. It is what a guest pasting their card into a booking note looks
# like.
PAN = "4111111111111111"

BOOKING_COM = "Booking.com"


def beds24_booking() -> dict:
    """The real captured booking element, same accessor `test_beds24_mapping.py` uses."""
    return beds24_fixture("bookings")["payload"]["data"][0]


# --- The primitive (task 3.1) ---


def test_a_pan_written_as_one_run_disappears():
    """The reason D8 exists: a PAN persisted in clear in a column the API returns."""
    assert PAN not in redact_long_digit_runs(f"pay with {PAN} please")


@pytest.mark.parametrize(
    "written",
    [
        PAN,
        "4111 1111 1111 1111",
        "4111-1111-1111-1111",
        "4111 1111-1111 1111",
        "4111  1111  1111  1111",
    ],
    ids=["bare", "spaces", "hyphens", "mixed", "double-spaces"],
)
def test_separators_do_not_save_it(written):
    """D8's "ignoring spaces and hyphens" is the whole difficulty of the rule.

    A human copying a card copies it the way it is printed, in groups of four. A run-of-digits
    check that stops at the first space sees `4111` four times and redacts nothing — which is
    the shape a card is *most* likely to arrive in, not the exceptional one.

    Repeated separators count too. A double space is a typo, and a rule that a typo defeats is
    not a rule; the cost is bounded by the same threshold everything else here rests on.
    """
    redacted = redact_long_digit_runs(f"note: {written}")

    assert LONG_DIGIT_RUN_REDACTED in redacted
    assert not any(character.isdigit() for character in redacted)


def test_the_surrounding_text_survives():
    """A redaction that ate the note would cost more than the PAN it removed.

    The note is what the cleaning staff reads. Replacing the run and keeping everything else is
    also what distinguishes "the guest did not write this" from "we removed it" — the same
    distinction `card_data.CARD_DATA_REMOVED` is built around.
    """
    redacted = redact_long_digit_runs(f"late arrival, card {PAN}, thanks")

    assert redacted == f"late arrival, card {LONG_DIGIT_RUN_REDACTED}, thanks"


def test_every_run_in_the_note_goes():
    redacted = redact_long_digit_runs(f"{PAN} and also 4222222222222")

    assert redacted == f"{LONG_DIGIT_RUN_REDACTED} and also {LONG_DIGIT_RUN_REDACTED}"


# --- What must survive: the operational data D8 was ratified on ---


@pytest.mark.parametrize(
    "note",
    [
        "portal code 4512",
        "portal code 45129",
        "door code 12345678",
        "call me on 600123456",
        "call me on +34600123456",
        "ref 1234567890",
    ],
    ids=["portal-4", "portal-5", "door-8", "mobile-es", "mobile-intl", "ota-ref-10"],
)
def test_the_operational_data_that_closed_the_ratification_survives(note):
    """D8 was ratified on a measurement, not on a preference.

    A Spanish portal code is 4-8 digits, a Spanish mobile 9, an international one with prefix
    11-12 — none reaches 13. That is the argument that made the false positive acceptable, so
    it is the argument that has to hold as a test: if a threshold change ever eats a phone
    number, the ratification is void and this fails.
    """
    assert redact_long_digit_runs(note) == note


def test_twelve_digits_stay_and_thirteen_go():
    """The boundary itself, pinned from both sides.

    Off by one here is not cosmetic: 12 is the longest international phone number and 13 is the
    shortest PAN, so the whole decision is this single comparison.
    """
    assert redact_long_digit_runs("1" * 12) == "1" * 12
    assert redact_long_digit_runs("1" * MIN_REDACTED_DIGITS) == LONG_DIGIT_RUN_REDACTED


def test_no_luhn_check_is_applied():
    """D8 rejected Luhn, so a run that fails it is redacted just the same.

    Worth pinning because adding Luhn is the obvious "improvement" — it is what `pms-beds24-
    adapter`'s D9 already rejected, on false positives over an operational field, and nothing
    new justifies revisiting it. A checksum would also make the rule silently weaker: a PAN
    with one mistyped digit would start surviving.
    """
    fails_luhn = "1234567890123"

    assert redact_long_digit_runs(fails_luhn) == LONG_DIGIT_RUN_REDACTED


def test_the_accepted_false_positive_is_documented_by_a_case():
    """D8 accepted this and named it, so it belongs in the suite as a fact, not as a bug.

    Two mobile numbers written back to back are 18 digits with a separator between them, and a
    rule that ignores separators cannot tell that pair from a card. What makes it acceptable is
    what is lost: a phone number in a note, when the reservation carries `guest_phone` as a
    column of its own. Reverting is a one-line change in `free_text.py` if it turns out to
    annoy in practice, which is the mitigation the design records.
    """
    both_phones = "600123456 600654321"

    assert redact_long_digit_runs(both_phones) == LONG_DIGIT_RUN_REDACTED


def test_a_run_longer_than_a_pan_goes_too():
    """**Adjustment while implementing D8, and it is the security-relevant one.**

    D8 says "runs of 13-19 digits", which read literally means a maximal run of 20+ is left
    alone — and that is not conservative, it is a hole with a trivial trigger: a PAN followed by
    any other number merges into one longer run and survives whole. `4111111111111111 1225`
    (card then expiry) is 20 digits and would persist the card in clear.

    So the operative threshold is "at least 13", with 13-19 kept as the PAN band the decision
    was reasoned on. This only ever redacts MORE than the ratified form, and on inputs the
    ratification's own argument covers a fortiori: if nothing operational reaches 13 digits,
    nothing operational reaches 20 either.
    """
    card_then_expiry = f"{PAN} 1225"

    assert redact_long_digit_runs(card_then_expiry) == LONG_DIGIT_RUN_REDACTED
    assert redact_long_digit_runs("9" * 25) == LONG_DIGIT_RUN_REDACTED


# --- Shape ---


def test_none_and_empty_survive_unchanged():
    """`special_requests` is `str | None` all the way down, so `None` is the common case."""
    assert redact_long_digit_runs(None) is None
    assert redact_long_digit_runs("") == ""


def test_a_note_without_digits_is_returned_untouched():
    note = "please leave the keys with the neighbour"

    assert redact_long_digit_runs(note) == note


# --- The external sources (task 3.2) ---


def test_the_beds24_mapping_redacts_the_guest_note():
    """Beds24 puts the guest's own note in `comments`, which becomes `special_requests`."""
    element = beds24_booking() | {"comments": f"door is broken, card {PAN}"}

    dto = beds24_to_dto(element)

    assert dto.special_requests == f"door is broken, card {LONG_DIGIT_RUN_REDACTED}"


def test_the_channex_mapping_redacts_the_guest_note():
    """Channex uses `attributes.notes` for the same thing."""
    element = channex_booking(ota_name=BOOKING_COM)
    element["attributes"] = element["attributes"] | {"notes": f"late check-in, card {PAN}"}

    dto = channex_to_dto(element)

    assert dto.special_requests == f"late check-in, card {LONG_DIGIT_RUN_REDACTED}"


def test_an_absent_beds24_note_stays_absent():
    """Redaction must not turn `None` into `""`: the column is nullable and "no note" is not
    the same fact as "an empty note"."""
    element = beds24_booking() | {"comments": None}

    assert beds24_to_dto(element).special_requests is None


def test_an_absent_channex_note_stays_absent():
    element = channex_booking(ota_name=BOOKING_COM)
    element["attributes"] = element["attributes"] | {"notes": None}

    assert channex_to_dto(element).special_requests is None


# --- The manual path, which D8 deliberately leaves alone ---


@pytest.mark.asyncio
async def test_the_api_does_not_redact_what_a_person_writes(
    api, users_by_role_a, create_payload, db_session
):
    """D8's scope is "external source", and P.8's trigger was "unauthenticated write from the
    internet". A manager typing a note through the authenticated API is neither.

    This is the half that decays silently: widening the redaction to every writer would look
    like an improvement, pass every test above, and start eating operational text an identified
    person typed on purpose. Asserted end to end over the real endpoint rather than against the
    use case, because the redaction would most plausibly be added in a schema validator or a
    router, not in the domain.
    """
    written_by_a_person = "guest gave door code 1234 and reference 9876543210123"
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]

    response = await api.post(
        "/api/v1/reservations",
        json=create_payload(special_requests=written_by_a_person),
        headers=auth_header(api, manager),
    )

    assert response.status_code == 201
    assert response.json()["special_requests"] == written_by_a_person
    stored = (
        await db_session.execute(
            select(ReservationModel).where(ReservationModel.id == response.json()["id"])
        )
    ).scalar_one()
    assert stored.special_requests == written_by_a_person
