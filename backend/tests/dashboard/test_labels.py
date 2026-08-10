"""The dashboard's label catalogues (`dashboard-api` R5.2, task 5.3).

The point of every test here is coverage: a value added to one of the four enums must break
the suite rather than reach a reader untranslated.
"""

import pytest

from app.cleaning.domain.enums import CleaningTaskStatus
from app.core.i18n import Catalog, Locale
from app.dashboard.domain.labels import (
    ACCESS_STATUS_LABELS,
    APPROVAL_LABELS,
    CLEANING_STATUS_LABELS,
    INCIDENT_TITLE_LABELS,
    NEXT_ACTION_KEYS,
    NEXT_ACTION_LABELS,
    RESPONSIBLE_LABELS,
)
from app.dashboard.domain.next_action import NEXT_ACTION_BY_STATE, Responsible
from app.maintenance.domain.enums import IncidentCategory, OwnerApprovalRelatedType
from app.reservations.domain.enums import ReservationAccessStatus


def _assert_covers(catalog: Catalog, keys: set[str], name: str) -> None:
    assert catalog.keys == keys, f"{name} does not cover exactly its vocabulary"
    for key in keys:
        assert catalog.locales_for(key) == frozenset(Locale), (
            f"{name}[{key}] is missing a locale"
        )
        for locale in Locale:
            rendered = catalog.render(key, locale)
            assert rendered, f"{name}[{key}][{locale.value}] rendered empty"
            assert "{" not in rendered, "an unsubstituted placeholder reached the reader"


def test_cleaning_status_labels_cover_the_enum_in_both_locales() -> None:
    _assert_covers(
        CLEANING_STATUS_LABELS,
        {status.value for status in CleaningTaskStatus},
        "CLEANING_STATUS_LABELS",
    )


def test_incident_title_labels_cover_the_category_enum_in_both_locales() -> None:
    _assert_covers(
        INCIDENT_TITLE_LABELS,
        {category.value for category in IncidentCategory},
        "INCIDENT_TITLE_LABELS",
    )


def test_access_status_labels_cover_the_enum_in_both_locales() -> None:
    """R2.5: `access` carries "únicamente una etiqueta de estado", so every status a
    reservation can hold must have one."""
    _assert_covers(
        ACCESS_STATUS_LABELS,
        {status.value for status in ReservationAccessStatus},
        "ACCESS_STATUS_LABELS",
    )


def test_approval_labels_cover_the_related_type_enum_in_both_locales() -> None:
    _assert_covers(
        APPROVAL_LABELS,
        {related.value for related in OwnerApprovalRelatedType},
        "APPROVAL_LABELS",
    )


def test_responsible_labels_cover_every_role_in_both_locales() -> None:
    _assert_covers(
        RESPONSIBLE_LABELS,
        {role.value for role in Responsible},
        "RESPONSIBLE_LABELS",
    )


def test_next_action_labels_cover_every_key_the_table_can_produce() -> None:
    """Derived from `NEXT_ACTION_BY_STATE`, not restated: an action added to the table with
    no label must fail here rather than render as a missing string."""
    _assert_covers(NEXT_ACTION_LABELS, set(NEXT_ACTION_KEYS), "NEXT_ACTION_LABELS")


def test_the_derived_key_set_matches_the_table() -> None:
    assert NEXT_ACTION_KEYS == {
        action.action_key for action in NEXT_ACTION_BY_STATE.values() if action is not None
    }
    assert len(NEXT_ACTION_KEYS) == 6


@pytest.mark.parametrize(
    ("catalog", "key", "spanish", "english"),
    [
        (CLEANING_STATUS_LABELS, "IN_PROGRESS", "Limpieza en curso", "Cleaning in progress"),
        (NEXT_ACTION_LABELS, "assign_cleaner", "Asignar limpiadora", "Assign a cleaner"),
        (RESPONSIBLE_LABELS, "ASSIGNED_CLEANER", "Limpiadora asignada", "Assigned cleaner"),
        (INCIDENT_TITLE_LABELS, "APPLIANCE", "Electrodoméstico averiado", "Broken appliance"),
        (APPROVAL_LABELS, "INCIDENT", "Aprobación de incidencia", "Incident approval"),
    ],
)
def test_the_two_languages_really_differ(
    catalog: Catalog, key: str, spanish: str, english: str
) -> None:
    """Coverage alone would pass a catalogue that shipped the same string twice."""
    assert catalog.render(key, Locale.ES) == spanish
    assert catalog.render(key, Locale.EN) == english
    assert spanish != english


ALL_CATALOGUES = [
    ("CLEANING_STATUS_LABELS", CLEANING_STATUS_LABELS),
    ("NEXT_ACTION_LABELS", NEXT_ACTION_LABELS),
    ("RESPONSIBLE_LABELS", RESPONSIBLE_LABELS),
    ("INCIDENT_TITLE_LABELS", INCIDENT_TITLE_LABELS),
    ("APPROVAL_LABELS", APPROVAL_LABELS),
    ("ACCESS_STATUS_LABELS", ACCESS_STATUS_LABELS),
]


@pytest.mark.parametrize(("name", "catalog"), ALL_CATALOGUES, ids=lambda value: value)
def test_no_label_anywhere_is_the_untranslated_key(name: str, catalog: Catalog) -> None:
    """R5.2, over **every** key of **every** catalogue in **both** locales.

    The QA panel of section 5 found this wired to one catalogue and, worse, that the
    coverage helper would pass a table whose English column was the raw enum literal from
    top to bottom — a copy-paste slip that reaches a reader as `NOISE` instead of "Noise
    problem", with the suite still green. A key rendering as itself is a missing
    translation, not a label.
    """
    for key in catalog.keys:
        for locale in Locale:
            rendered = catalog.render(key, locale)
            assert rendered != key, f"{name}[{key}][{locale.value}] renders as its own key"


@pytest.mark.parametrize(("name", "catalog"), ALL_CATALOGUES, ids=lambda value: value)
def test_every_key_really_has_two_different_languages(name: str, catalog: Catalog) -> None:
    """The other half of the same gap: coverage alone passes a catalogue that shipped the
    Spanish string in the English slot for every key but the one the suite sampled.

    A handful of terms are legitimately identical across the two — this asserts the
    catalogue as a whole is translated, not that every single string differs.
    """
    identical = [
        key for key in catalog.keys if catalog.render(key, Locale.ES) == catalog.render(key, Locale.EN)
    ]
    assert len(identical) <= 1, (
        f"{name} has {len(identical)} keys with the same text in both locales "
        f"({sorted(identical)}); that is a copied column, not a translation"
    )
