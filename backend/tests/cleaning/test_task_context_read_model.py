"""`CleaningTaskContext`'s field set, pinned (R1.4, R2.5, design D3).

Deliberately brittle, same as `tests/guests/test_portal_ports.py` does for `StayInfo`: this is
the only route carrying an **attribute** of `Property` or `Reservation` to a role that holds
neither `READ_PROPERTIES` nor `READ_RESERVATIONS` — `CleaningTaskResponse` already gives it the
two ids and the planned window, and nothing else. So adding a field here is a security decision,
and a test that tolerated it silently would be no mitigation at all.

It is the risk the design names as "the projection grows until it is the dump this change
rejects".
"""

import dataclasses

import pytest

from app.cleaning.domain.read_models import CleaningTaskContext


def _fields(cls: type) -> set[str]:
    return set(cls.__dataclass_fields__)


def test_context_declares_exactly_the_eleven_fields_design_d3_lists() -> None:
    assert _fields(CleaningTaskContext) == {
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


@pytest.mark.parametrize(
    "forbidden",
    [
        # R1.4, named one by one because each is a different kind of mistake.
        #
        # The three plaintext sinks of rule 11 of `steering/security.md` that are auditable but
        # not denylisted (`properties-crud` design D7): a `Property` dumped through
        # `from_attributes` would carry them, and design D9 records that this change does not
        # widen their reader set.
        "access_notes",
        "cleaning_notes",
        "emergency_notes",
        # Rule 3 grants no form at all for a WiFi password, masked or otherwise. The flag is
        # excluded too: no requirement asks for it, and the narrowest projection ages best.
        "wifi_password_encrypted",
        "has_wifi_password",
        # R2.5 — the money, the channel and the guest of a reservation. A `CLEANER` has no
        # `READ_RESERVATIONS`, so this route is the only way any of them could arrive.
        "gross_amount",
        "ota_commission",
        "net_amount",
        "payment_status",
        "channel",
        "guest_id",
        "special_requests",
        "internal_notes",
    ],
)
def test_context_cannot_carry_what_r1_4_and_r2_5_forbid(forbidden: str) -> None:
    assert forbidden not in _fields(CleaningTaskContext)


def test_context_is_frozen() -> None:
    """A projection a use case cannot edit on the way out."""
    context = CleaningTaskContext(
        property_name="Redes 11",
        property_internal_code="REDES11",
        address_line1=None,
        address_line2=None,
        city=None,
        province=None,
        postal_code=None,
        country="ES",
        timezone="Europe/Madrid",
        checkout_at=None,
        next_checkin_deadline=None,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.property_name = "otra"  # type: ignore[misc]
