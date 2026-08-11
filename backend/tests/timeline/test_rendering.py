"""Readable timeline entries in the reader's language (`dashboard-api` R5, task 2.1)."""

import dataclasses
import uuid
from datetime import UTC, datetime

import pytest

from app.core.i18n import Catalog, Locale
from app.timeline.domain import rendering
from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.rendering import (
    MAX_SUBSTITUTED_LENGTH,
    SUBSTITUTABLE_METADATA_KEYS,
    TIMELINE_TITLE_TEMPLATES,
    RenderedEntry,
    render,
)

# Metadata that satisfies every placeholder any template uses. Kept in one place so a
# template that starts needing a new key fails the per-type test loudly.
FULL_METADATA = {
    "to_state": "AWAITING_CLEANING",
    "from_state": "OCCUPIED_ESTIMATED",
    "trigger": "CHECKOUT_TIME_REACHED",
    "source": "Booking.com",
}


def _event(
    event_type: TimelineEventType,
    *,
    metadata: dict | None = None,
    title: str = "Stored English title",
    description: str | None = "Stored description",
) -> TimelineEvent:
    return TimelineEvent(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        actor_type=TimelineActorType.SYSTEM,
        event_type=event_type,
        title=title,
        created_at=datetime(2026, 8, 9, 10, 30, tzinfo=UTC),
        severity=TimelineSeverity.INFO,
        description=description,
        metadata=FULL_METADATA if metadata is None else metadata,
    )


# --- coverage: the catalogue must keep pace with the enum (R5.4) -----------------------


def test_every_event_type_has_a_template_in_both_locales() -> None:
    """R5.4: "un test SHALL demostrar que los 45 valores de `TimelineEventType` tienen
    entrada en ambos idiomas" — so a type added later breaks the suite instead of
    reaching production speaking English."""
    missing = {
        event_type.value: sorted(
            locale.value for locale in Locale if locale not in TIMELINE_TITLE_TEMPLATES.get(event_type, {})
        )
        for event_type in TimelineEventType
        if set(Locale) - set(TIMELINE_TITLE_TEMPLATES.get(event_type, {}))
    }
    assert not missing, f"event types without a template in every locale: {missing}"


def test_the_catalogue_covers_the_whole_enum_and_nothing_else() -> None:
    assert set(TIMELINE_TITLE_TEMPLATES) == set(TimelineEventType)
    # 45 when `dashboard-api` wrote R5.4; the 46th is `GUEST_CHECKIN_COMPLETED`, added by
    # `guest-portal-api` D12 because R6.3 needs a milestone for the guest filling in their own
    # legal data and none of the 45 said it — `CHECKIN_WINDOW_OPENED` is the clock, and reusing
    # `LEGAL_REGISTRATION_SUBMITTED` would have asserted for ever that a police submission
    # happened when it had not. Updated deliberately, which is what this assertion asks for: a
    # new value with no template is a timeline entry that silently degrades to a stored title.
    assert len(TimelineEventType) == 46, "counts every value; update it deliberately"


# --- one case per type, in both languages ---------------------------------------------


@pytest.mark.parametrize("event_type", list(TimelineEventType), ids=lambda t: t.value)
@pytest.mark.parametrize("locale", list(Locale), ids=lambda locale: locale.value)
def test_every_type_renders_in_every_locale(
    event_type: TimelineEventType, locale: Locale
) -> None:
    entry = render(_event(event_type), locale)

    assert entry.title, "a rendered title is never empty"
    assert entry.title != "Stored English title", (
        f"{event_type.value} degraded to the stored title instead of rendering; "
        "its template probably needs a metadata key FULL_METADATA does not carry"
    )
    assert "{" not in entry.title, "an unsubstituted placeholder reached the reader"


def test_the_two_locales_differ_where_the_language_differs() -> None:
    spanish = render(_event(TimelineEventType.CLEANING_COMPLETED), Locale.ES)
    english = render(_event(TimelineEventType.CLEANING_COMPLETED), Locale.EN)

    assert spanish.title == "Limpieza completada"
    assert english.title == "Cleaning completed"


def test_the_canonical_state_literal_is_not_translated() -> None:
    """R5.5: `PropertyOperationalState` travels as the exact PRD value."""
    for locale in Locale:
        entry = render(_event(TimelineEventType.PROPERTY_STATE_CHANGED), locale)
        assert "AWAITING_CLEANING" in entry.title


# --- degradation (R5.4) ----------------------------------------------------------------


def test_an_event_type_absent_from_the_catalogue_degrades_to_the_stored_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The path R5.4 reserves for a `TimelineEventType` a future change adds."""
    monkeypatch.setattr(rendering, "TIMELINE_TITLES", Catalog({}))

    entry = render(_event(TimelineEventType.CLEANING_COMPLETED), Locale.ES)

    assert entry.title == "Stored English title"


def test_a_template_whose_metadata_key_is_absent_degrades_to_the_stored_title() -> None:
    """Design D5: "Un tipo cuya plantilla pida un dato que su factoría nunca guardó cae a
    la degradación — correcto, no silencioso"."""
    entry = render(_event(TimelineEventType.PROPERTY_STATE_CHANGED, metadata={}), Locale.ES)

    assert entry.title == "Stored English title"


@pytest.mark.parametrize(
    "value",
    [
        {"nested": "object"},
        ["a", "list"],
        None,
        True,
        "x" * (MAX_SUBSTITUTED_LENGTH + 1),
    ],
    ids=["dict", "list", "null", "bool", "oversized-string"],
)
def test_a_metadata_value_that_is_not_a_bounded_scalar_degrades(value) -> None:
    """A `dict` repr or a multi-kilobyte string has no business in a one-line title."""
    entry = render(
        _event(TimelineEventType.PROPERTY_STATE_CHANGED, metadata={"to_state": value}),
        Locale.EN,
    )

    assert entry.title == "Stored English title"


def test_a_bounded_string_at_the_limit_still_substitutes() -> None:
    value = "y" * MAX_SUBSTITUTED_LENGTH

    entry = render(
        _event(TimelineEventType.PROPERTY_STATE_CHANGED, metadata={"to_state": value}),
        Locale.EN,
    )

    assert entry.title == f"Property state changed to {value}"


# --- the metadata allow-list (security panel, section 2) --------------------------------


def test_only_the_types_with_a_placeholder_may_interpolate_anything() -> None:
    """A template with no placeholder must not be offered any metadata at all, so a key a
    future writer adds cannot start appearing in a title by accident."""
    import string

    formatter = string.Formatter()
    for event_type, templates in TIMELINE_TITLE_TEMPLATES.items():
        placeholders = {
            field
            for template in templates.values()
            for _, field, _, _ in formatter.parse(template)
            if field
        }
        allowed = SUBSTITUTABLE_METADATA_KEYS.get(event_type, frozenset())
        assert placeholders == allowed, (
            f"{event_type.value}: templates use {sorted(placeholders)} but the allow-list "
            f"grants {sorted(allowed)}"
        )


def test_a_metadata_key_outside_the_allow_list_is_never_interpolated() -> None:
    """The failure the panel described: a generic writer putting caller-influenced text
    under a key that happens to match another event type's placeholder."""
    entry = render(
        _event(
            TimelineEventType.CLEANING_COMPLETED,
            metadata={"to_state": "<injected>", "source": "<injected>"},
        ),
        Locale.EN,
    )

    assert entry.title == "Cleaning completed"
    assert "<injected>" not in entry.title


def test_a_type_may_not_borrow_another_types_placeholder_key() -> None:
    entry = render(
        _event(TimelineEventType.RESERVATION_IMPORTED, metadata={"source": "Booking.com"}),
        Locale.EN,
    )
    assert entry.title == "Reservation imported from Booking.com"

    # `to_state` is not on `RESERVATION_IMPORTED`'s allow-list, and its template does not
    # ask for one — so a stray key changes nothing.
    borrowed = render(
        _event(
            TimelineEventType.RESERVATION_IMPORTED,
            metadata={"source": "Booking.com", "to_state": "<injected>"},
        ),
        Locale.EN,
    )
    assert borrowed.title == "Reservation imported from Booking.com"


# --- the shape the entry exposes -------------------------------------------------------


def test_the_rendered_entry_carries_the_fields_of_the_frontend_contract() -> None:
    """`TimelineEntry` (`frontend/features/dashboard/data/dto.ts:99-108`)."""
    assert {field.name for field in dataclasses.fields(RenderedEntry)} == {
        "id",
        "occurred_at",
        "actor_type",
        "event_type",
        "severity",
        "title",
        "description",
    }


def test_the_rendered_entry_has_no_metadata_field() -> None:
    """R4.3: `metadata` is free JSON and not part of the read contract, so the projection
    structurally lacks it — no future serialiser can reach a field that is not here."""
    assert not hasattr(RenderedEntry, "metadata")
    assert "metadata" not in {field.name for field in dataclasses.fields(RenderedEntry)}


def test_the_entry_carries_the_stored_columns_it_does_not_compose() -> None:
    event = _event(TimelineEventType.CLEANING_STARTED)

    entry = render(event, Locale.ES)

    assert entry.id == event.id
    assert entry.occurred_at == event.created_at
    assert entry.actor_type is event.actor_type
    assert entry.event_type is event.event_type
    assert entry.severity is event.severity


def test_the_description_is_passed_through_not_composed() -> None:
    """Descriptions are human text (`PropertyStateTransition.reason`); translating what a
    person wrote is not this module's job."""
    event = _event(TimelineEventType.PROPERTY_STATE_CHANGED, description="Se rompió la caldera")

    assert render(event, Locale.EN).description == "Se rompió la caldera"
    assert render(_event(TimelineEventType.CLEANING_STARTED, description=None), Locale.ES).description is None


def test_rendering_never_modifies_the_stored_title() -> None:
    """R5.3: the stored `title` stays the English audit copy."""
    event = _event(TimelineEventType.CLEANING_COMPLETED)

    render(event, Locale.ES)

    assert event.title == "Stored English title"
