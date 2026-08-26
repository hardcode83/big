"""`IncidentContext`'s field set, pinned (R1.4, R5.1, R5.2, design D4).

Deliberately brittle, the same way `tests/cleaning/test_task_context_read_model.py` and
`tests/guests/test_portal_ports.py` are: this is the only route carrying an **attribute** of
`Property` to a role that holds no `READ_PROPERTIES` — `IncidentResponse` already gives it
`property_id` and nothing else about the row. So adding a field here is a security decision, and
a test that tolerated it silently would be no mitigation at all.

It is the risk the design names as the projection growing until it is the dump this change
rejects.
"""

import dataclasses

import pytest

from app.maintenance.domain.read_models import IncidentContext


def _fields(cls: type) -> set[str]:
    return set(cls.__dataclass_fields__)


def test_context_declares_exactly_the_eleven_fields_design_d4_lists() -> None:
    assert _fields(IncidentContext) == {
        "property_name",
        "property_internal_code",
        "address_line1",
        "address_line2",
        "city",
        "province",
        "postal_code",
        "country",
        "timezone",
        "access_notes",
        "assignment_note",
    }


@pytest.mark.parametrize(
    "forbidden",
    [
        # R2.5, R5.2 — rule 3 of `steering/security.md` grants no form at all for a WiFi
        # password, masked or otherwise. The flag goes too: no requirement asks for it, and the
        # narrowest projection ages best.
        "wifi_password_encrypted",
        "has_wifi_password",
        "wifi_name",
        # R5.2 — the two other free-text notes of `properties`. This change reads neither, which
        # is precisely why neither gains a reader here (design D12), and a `Property` dumped
        # through `from_attributes` would have carried both.
        "cleaning_notes",
        "emergency_notes",
        # R5.3 — the money, the channel and the guest of a reservation. A `TECHNICIAN` has no
        # `READ_RESERVATIONS`, and PRD §12 does not ask for the booking on this screen, so this
        # route must not be the way any of them arrives.
        "gross_amount",
        "ota_commission",
        "net_amount",
        "payment_status",
        "channel",
        "guest_id",
        "special_requests",
        "internal_notes",
        # R5.4 — what `maintenance` R8 already keeps out of the incident contract. The first
        # never leaves the port; the other two are excluded here by the same mechanism as
        # everything else on this list.
        "reported_by_guest_token",
        "reported_by_user_id",
        "ai_classification",
    ],
)
def test_context_cannot_carry_what_r2_5_r5_2_r5_3_and_r5_4_forbid(forbidden: str) -> None:
    assert forbidden not in _fields(IncidentContext)


def test_context_is_frozen() -> None:
    """A projection a use case cannot edit on the way out (R5.1)."""
    context = IncidentContext(
        property_name="Redes 11",
        property_internal_code="REDES11",
        address_line1=None,
        address_line2=None,
        city=None,
        province=None,
        postal_code=None,
        country="ES",
        timezone="Europe/Madrid",
        access_notes=None,
        assignment_note=None,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.property_name = "otra"  # type: ignore[misc]


def test_the_projection_is_pure_python() -> None:
    """`tests/test_layering.py` enforces this by glob over `domain/`; asserted here too because
    the *reason* is local: a pydantic model here could grow a `from_attributes` and a
    SQLAlchemy import could grow a relationship, and either would reopen what D4 closes."""
    import app.maintenance.domain.read_models as module

    source = module.__file__
    assert source is not None
    text = open(source, encoding="utf-8").read()
    for forbidden in ("import sqlalchemy", "from sqlalchemy", "import pydantic", "from pydantic"):
        assert forbidden not in text
