"""The pin test of the derived identity fields (`reservation-property-identity` R5.4, D6).

`ReservationResponse` and `ReservationDetailResponse` declare EXACTLY three derived
fields on top of the column-backed ones — `property_name`, `property_internal_code`,
`guest_full_name` — and the four "every reservation has a property_id / guest_id"
fields already on the DTO stay put (R1.3, R3.1).

The set of names this test enumerates is the structural guarantee. Adding
`property.address_line1` or `guest_summary.email` to the response is a deliberate
act — a change to this test signals that the wire shape grew on purpose, not as a
side-effect of `from_attributes=True`. Same shape as
`backend/tests/cleaning/test_task_context_read_model.py` — the cleaning side of the
projection analogy this change mirrors.
"""

import dataclasses

import pytest

from app.guests.domain.value_objects import GuestSummary
from app.properties.domain.entities import Property
from app.properties.infrastructure.models import PropertyModel
from app.reservations.api.schemas import ReservationDetailResponse, ReservationResponse
from app.reservations.domain.entities import Reservation


# Names of columns that exist on `properties` (the SQLAlchemy model) and that MUST
# NOT appear on the reservation response. Listed exhaustively, so a future widening
# cannot quietly slip in. Model columns are the source of truth (Property is the
# entity, deliberately carries `has_wifi_password` instead of the encrypted secret;
# both belong in the forbidden list against the wire shape).
PROPERTY_FIELDS_FORBIDDEN_ON_RESPONSE = frozenset(
    {
        "address_line1",
        "address_line2",
        "city",
        "province",
        "postal_code",
        "country",
        "timezone",
        "wifi_name",
        "has_wifi_password",
        "wifi_password_encrypted",
        "access_notes",
        "cleaning_notes",
        "emergency_notes",
        "max_guests",
        "bedrooms",
        "bathrooms",
        "default_check_in_time",
        "default_check_out_time",
        "pms_provider",
        "pms_external_id",
        "current_operational_state",
        # `name` and `internal_code` are the SOURCE of the two derived fields; the
        # response carries them under `property_name` / `property_internal_code`
        # (R2 + D5).
        "name",
        "internal_code",
        # `tenant_id` carries the tenancy scope and must not appear on a list view.
        "tenant_id",
    }
)


# Names of `GuestSummary` that MUST NOT appear on the reservation response. Excludes
# `id` (the response uses it under `guest_id`) and `full_name` (exposed as
# `guest_full_name`, R3.1 + R4.1).
GUEST_SUMMARY_FIELDS_FORBIDDEN_ON_RESPONSE = frozenset(
    {
        "email",
        "phone",
        "preferred_language",
        "document_status",
        # `legal_registration_status` shares its name with a column on `Reservation`
        # (a different domain's enum, deliberately the same name); the response DTO
        # carries its value from `Reservation`, not `GuestSummary`. The forbidden set
        # skips it because the same name on two projections is what the test would
        # otherwise have to spell out — and the test's job is to pin what may grow,
        # not to relitigate a name existing on the entity from before this change.
    }
)


# The three derived fields the response DOES declare today. Listed here so a change
# that wants to add a new one touches this file along with the use case.
RESERVATION_RESPONSE_IDENTITY_FIELDS = frozenset(
    {"property_name", "property_internal_code", "guest_full_name"}
)


def _reservation_response_field_names() -> set[str]:
    """The fields declared on the response DTO — the wire shape, not the entity."""
    return set(ReservationResponse.model_fields)


def _reservation_entity_field_names() -> set[str]:
    return {f.name for f in dataclasses.fields(Reservation)}


def _property_model_column_names() -> set[str]:
    """The columns of `properties` — the source of `Property` and what future
    widenings would most naturally reach for.
    """
    return {column.key for column in PropertyModel.__table__.columns}


def _property_entity_field_names() -> set[str]:
    return {f.name for f in dataclasses.fields(Property)}


def _property_source_names() -> set[str]:
    """The full set a `Property` field could come from: every column the model
    exposes AND every entity-only field (`has_wifi_password`, a synthetic bool).
    Either source landing on the response is the same disclosure.
    """
    return _property_model_column_names() | _property_entity_field_names()


def _guest_summary_field_names() -> set[str]:
    return {f.name for f in dataclasses.fields(GuestSummary)}


@pytest.mark.parametrize(
    "forbidden_name", sorted(PROPERTY_FIELDS_FORBIDDEN_ON_RESPONSE)
)
def test_a_property_column_does_not_appear_in_the_response(
    forbidden_name: str
) -> None:
    """A `properties` column that is not one of the three derived fields MUST not
    have a place on `ReservationResponse`.

    Parametrising the assertion one row per forbidden name means an accidental
    widening shows up as a single named failure, not as "the assertion expected N
    fields and got N+1" with no idea which one slipped in.

    The model is the source: some columns live only on the model (`wifi_password_encrypted`,
    which `Property` deliberately omits so it cannot leak through `from_attributes`)
    and some live only on the entity. Either appearing on the response is the same
    disclosure, and both live in this list.
    """
    assert forbidden_name in _property_source_names()
    assert forbidden_name not in _reservation_response_field_names()


@pytest.mark.parametrize(
    "forbidden_name", sorted(GUEST_SUMMARY_FIELDS_FORBIDDEN_ON_RESPONSE)
)
def test_a_guest_summary_field_does_not_appear_in_the_response(
    forbidden_name: str
) -> None:
    assert forbidden_name in _guest_summary_field_names()
    assert forbidden_name not in _reservation_response_field_names()


def test_no_full_guest_documents_leak_into_the_response() -> None:
    """Belt-and-braces: even those who confuse `Guest` with `GuestSummary` cannot
    sneak document fields through. `Guest` carries `document_number_encrypted`,
    `date_of_birth`, `nationality`, `document_expiry_date`, `document_type`, and the
    response MUST not include any of them by ANY route (rule 3 + 4 of
    `steering/security.md`, and D17 — `GuestSummary` is a separate projection that
    excludes these fields BY CONSTRUCTION).
    """
    forbidden = {
        "document_number_encrypted",
        "date_of_birth",
        "nationality",
        "document_expiry_date",
        "document_type",
    }
    assert not (forbidden & _reservation_response_field_names())


def test_reservation_response_declares_exactly_the_three_derived_fields() -> None:
    """R5.4 / D6 pin: `ReservationResponse` carries exactly the three identity fields
    and no other field from `Property` or `GuestSummary`.

    A change that wanted to ship `property.address_line1` on the response would have
    to edit this test, and editing it shows up in code review as "the response grew
    a PII-bearing column". That is the whole point of the pin.
    """
    response_fields = _reservation_response_field_names()

    # The three derived fields ARE on the response.
    assert RESERVATION_RESPONSE_IDENTITY_FIELDS <= response_fields

    # Everything else that lives on `Property` or `GuestSummary` (apart from `name`
    # and `internal_code`, the sources of the two derived fields, and `id`/`full_name`,
    # the sources of `property_id` and `guest_full_name`) MUST be absent from the
    # response. The two identifiers `property_id` and `guest_id` are kept explicitly
    # on the response side as the legitimate mapping; the rest is the pin.
    #
    # `Reservation` owns a few Property-named fields by its own right
    # (`created_at`, `updated_at`, `status`, `legal_registration_status` — different
    # domain enums the entity reuses the names for, deliberately); these come from the
    # reservation row, not a Property JOIN, so they are NOT considered leaks.
    reservation_owned = _reservation_entity_field_names()
    forbidden_extras = (
        _property_source_names() | _guest_summary_field_names()
    ) - {"name", "internal_code"} - {"id", "full_name"} - reservation_owned
    response_minus_allowed = response_fields - RESERVATION_RESPONSE_IDENTITY_FIELDS - {
        "id",
        "property_id",
        "guest_id",
    }
    leaks = forbidden_extras & response_minus_allowed
    assert not leaks, (
        f"ReservationResponse leaks {sorted(leaks)} from Property/GuestSummary. The "
        "pin test lists the row's source columns and the response is supposed to "
        "declare exactly the three identity fields; check the rows this change "
        "actually intends to widen and update this assertion if it is the intent."
    )


def test_reservation_detail_response_inherits_the_pin() -> None:
    """`ReservationDetailResponse(ReservationResponse)` inherits the three fields; the
    pin does not need to repeat itself in the subclass. pydantic inheritance brings
    the declaration, and `ReservationDetail` read model carries the same three
    values populated by the use case (`test_use_cases`), so a derived response that
    dropped a field would already be broken in the API test. This test makes the
    inheritance explicit at the type level.
    """
    detail_field_names = set(ReservationDetailResponse.model_fields)
    assert (
        RESERVATION_RESPONSE_IDENTITY_FIELDS <= detail_field_names
    ), "ReservationDetailResponse must inherit the three identity fields from its base"


def test_reservation_response_keeps_the_two_reservation_owned_ids() -> None:
    """R1.3 + R3.1: adding the three derived fields must NOT replace the existing
    `property_id` and `guest_id` — the listing model and the FE both still depend
    on the FK being there (`frontend/features/reservations/data/dto.ts:76`).
    """
    response_fields = _reservation_response_field_names()
    assert {"property_id", "guest_id"} <= response_fields


def test_reservation_response_does_not_drop_a_pre_existing_field() -> None:
    """Belt-and-braces: the existing 27-column shape survives. The new fields are
    ADDED, not substituted, per R1.3 / R3.1.
    """
    pre_existing = {
        "id",
        "property_id",
        "guest_id",
        "external_pms_id",
        "external_channel_id",
        "channel",
        "status",
        "check_in_date",
        "check_out_date",
        "check_in_time",
        "check_out_time",
        "nights",
        "adults",
        "children",
        "total_guests",
        "gross_amount",
        "ota_commission",
        "net_amount",
        "currency",
        "payment_status",
        "access_status",
        "legal_registration_status",
        "cleaning_required",
        "special_requests",
        "internal_notes",
        "created_at",
        "updated_at",
    }
    assert pre_existing <= _reservation_response_field_names(), (
        "A reservation column was lost when the identity fields were added — "
        "intended as additive, never subtractive."
    )


def test_reservation_entity_carries_the_three_derived_fields() -> None:
    """The entity holds the three derived fields populated by the use case, so
    `from_domain` does not need extra kwargs per call. If a future change moved them
    off the entity, the build of `ReservationResponse.from_domain` would change
    too, and this test makes the convention explicit.
    """
    assert RESERVATION_RESPONSE_IDENTITY_FIELDS <= _reservation_entity_field_names()
