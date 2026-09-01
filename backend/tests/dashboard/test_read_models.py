"""The dashboard projections (`dashboard-api` R1.2, R2.1, R2.5, task 5.1).

Every test here asserts an **absence**. That is the point of the `GuestSummary`
construction the design cites: "no future serialiser can reach a field that is not here"
(`app/guests/domain/value_objects.py:24-39`). A field that is not on the type cannot be
leaked by a schema someone writes in six months, and these tests are what keep it off.
"""

import dataclasses

import pytest

from app.dashboard.domain.read_models import (
    AccessBlock,
    ApprovalBlock,
    CleaningPhotoBlock,
    FinancialBlock,
    GuestBlock,
    IncidentBlock,
    NextActionBlock,
    OpenIncidentCountsBlock,
    OperationalKpis,
    PropertyDashboardCard,
    PropertyDetail,
    ReservationBlock,
)
from app.properties.domain.enums import PropertyOperationalState

ALL_BLOCKS = [
    ReservationBlock,
    NextActionBlock,
    GuestBlock,
    AccessBlock,
    IncidentBlock,
    FinancialBlock,
    ApprovalBlock,
    CleaningPhotoBlock,
    OpenIncidentCountsBlock,
    OperationalKpis,
    PropertyDashboardCard,
    PropertyDetail,
]


def _fields(cls) -> set[str]:
    return {field.name for field in dataclasses.fields(cls)}


# --- the security guarantees (R2.5, steering/security.md rules 3-5) ---------------------


def test_the_guest_block_carries_a_name_and_nothing_else() -> None:
    """R2.5: "THE SYSTEM SHALL devolver en `guest` únicamente el nombre... nunca
    `document_number` (`steering/security.md` regla 4: jamás en listados)"."""
    assert _fields(GuestBlock) == {"name"}


def test_the_access_block_carries_a_label_and_no_code_in_any_form() -> None:
    """R2.5: "en `access` únicamente una etiqueta de estado... ni un código de acceso, ni
    siquiera enmascarado"."""
    assert _fields(AccessBlock) == {"label"}


@pytest.mark.parametrize("block", ALL_BLOCKS, ids=lambda cls: cls.__name__)
def test_no_projection_anywhere_can_carry_a_secret(block) -> None:
    """One sweep over every block, so a field added to any of them has to pass here.

    Enumerated by name rather than by pattern: a substring check for "code" would trip on
    `property_code`, which is exactly the field the cards are keyed by.
    """
    forbidden = {
        "document_number",
        "document_number_encrypted",
        "date_of_birth",
        "nationality",
        "access_code",
        "code",
        "code_masked",
        "wifi_password",
        "wifi_password_encrypted",
        "storage_key",
        "receipt_storage_key",
        "notes_free_text",
        "description",
        "reason",
        "ai_summary",
        "ai_classification",
        "reported_by_guest_token",
    }
    assert not (_fields(block) & forbidden)


def test_the_photo_block_carries_a_url_and_never_a_storage_key() -> None:
    """Rule 5 of `steering/security.md`: "Fotos por signed URL... Nunca exponer paths
    internos". The field can only ever hold a signed URL, which is why it stays empty until
    `cleaning-photos-storage` can produce one (R2.4)."""
    assert _fields(CleaningPhotoBlock) == {"id", "url", "taken_at"}
    assert "storage_key" not in _fields(CleaningPhotoBlock)


# --- the contract shapes (dto.ts) --------------------------------------------------------


def test_the_card_carries_exactly_the_contract_fields() -> None:
    """`PropertyDashboardCard` (`frontend/features/dashboard/data/dto.ts:85-96`, R1.2)."""
    assert _fields(PropertyDashboardCard) == {
        "property_id",
        "property_code",
        "operational_state",
        "current_or_next_reservation",
        "cleaning_status",
        "open_incidents_count",
        "next_action",
        "last_event_label",
        "last_event_at",
    }


def test_the_operational_kpis_carry_exactly_the_contract_fields() -> None:
    """`OperationalKpis` (`dashboard-operational-kpis` design, R1, R2, R3)."""
    assert _fields(OperationalKpis) == {
        "cleanings_today",
        "upcoming_checkins",
        "open_incidents",
    }


def test_the_open_incident_counts_block_carries_total_and_urgent_only() -> None:
    """R3.2/R3.3 and design D5 — redacted as one unit, never a third field to redact."""
    assert _fields(OpenIncidentCountsBlock) == {"total", "urgent"}


def test_the_detail_carries_exactly_the_contract_fields() -> None:
    """`PropertyDetail` (`dto.ts:161-174`, R2.1) — the sections of PRD §9.2."""
    assert _fields(PropertyDetail) == {
        "property_id",
        "property_code",
        "operational_state",
        "current_or_next_reservation",
        "guest",
        "access",
        "cleaning_status",
        "last_cleaning_photos",
        "open_incidents",
        "financial",
        "notes",
        "pending_approvals",
    }


@pytest.mark.parametrize("block", [PropertyDashboardCard, PropertyDetail], ids=lambda c: c.__name__)
def test_the_operational_state_stays_the_enum_and_never_becomes_a_string(block) -> None:
    """R5.5 and R1.3: the canonical literal travels as the exact PRD value, untranslated.

    The QA panel of section 5 found this resting on the annotation alone — and this project
    runs no typechecker, so a future edit retyping the field to `str` and feeding it from a
    new label catalogue would have passed every test here. The field-name sweeps check names,
    not types; this checks the type.
    """
    hints = {field.name: field.type for field in dataclasses.fields(block)}

    assert hints["operational_state"] is PropertyOperationalState


def test_no_label_catalogue_exists_for_the_operational_state() -> None:
    """The other half: R5.5 is violated by *rendering* the literal, so the absence of a
    catalogue that could is worth asserting rather than assuming."""
    from app.dashboard.domain import labels

    catalogues = {
        name for name in vars(labels) if name.endswith("_LABELS")
    }
    assert not any("OPERATIONAL_STATE" in name or "PROPERTY_STATE" in name for name in catalogues), (
        "a catalogue for PropertyOperationalState would mean the canonical literal is being "
        "translated somewhere; R5.5 forbids it"
    )


def test_neither_projection_carries_a_colour() -> None:
    """R1.3: "SHALL NOT calcular en la respuesta ningún color: el mapeo de color es del
    frontend (PRD §9.1)"."""
    for block in (PropertyDashboardCard, PropertyDetail):
        assert not any("colour" in name or "color" in name for name in _fields(block))


# --- immutability -----------------------------------------------------------------------


@pytest.mark.parametrize("block", ALL_BLOCKS, ids=lambda cls: cls.__name__)
def test_every_projection_is_frozen(block) -> None:
    """Frozen is what makes the guarantee structural rather than conventional."""
    assert dataclasses.is_dataclass(block)
    assert block.__dataclass_params__.frozen


def test_the_detail_holds_its_collections_as_tuples() -> None:
    """A mutable default on a shared projection is how one response ends up carrying
    another's rows."""
    hints = {field.name: field.type for field in dataclasses.fields(PropertyDetail)}
    for name in ("last_cleaning_photos", "open_incidents", "pending_approvals"):
        assert "tuple" in str(hints[name])


# --- money ------------------------------------------------------------------------------


def test_money_is_decimal_and_never_float() -> None:
    """Money that has been through a binary float has been through a rounding error."""
    for block, names in (
        (FinancialBlock, ("reservation_total", "pending_expenses")),
        (ApprovalBlock, ("amount",)),
    ):
        hints = {field.name: str(field.type) for field in dataclasses.fields(block)}
        for name in names:
            assert "Decimal" in hints[name]
            assert "float" not in hints[name]
