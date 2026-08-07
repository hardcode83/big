"""R1.2 — the two JSONB columns of a template stop being free text.

`domain-foundation-ops` persists `items`/`required_photos` without validating their
structure (`specs/domain-foundation-ops.md` §Esquema DB). From this change on the
`item_id` is the key a checklist is completed by and the key of
`uq_cleaning_checklist_completions_cleaning_task_id_item_id`, so it has to be a
non-empty, unique string.
"""

import pytest

from app.cleaning.domain.exceptions import CleaningValidationError
from app.cleaning.domain.value_objects import (
    MAX_ITEMS,
    MAX_KEY_LENGTH,
    MAX_REQUIRED_PHOTOS,
    parse_template_content,
)

VALID_ITEMS = [
    {"item_id": "kitchen", "label": "Cocina", "required": True},
    {"item_id": "bathroom", "label": "Baño", "required": False},
]
VALID_PHOTOS = [{"photo_type": "kitchen", "label": "Cocina", "required": True}]


def test_parses_items_and_photos():
    spec = parse_template_content(VALID_ITEMS, VALID_PHOTOS)

    assert spec.item_ids() == {"kitchen", "bathroom"}
    assert spec.required_item_ids() == {"kitchen"}
    assert spec.required_photos[0].photo_type == "kitchen"


def test_required_defaults_to_false_when_absent():
    spec = parse_template_content([{"item_id": "a", "label": "A"}], [])

    assert spec.required_item_ids() == frozenset()


def test_rejects_empty_item_list():
    with pytest.raises(CleaningValidationError, match="non-empty list"):
        parse_template_content([], [])


def test_rejects_duplicated_item_id():
    items = [
        {"item_id": "kitchen", "label": "Cocina", "required": True},
        {"item_id": "kitchen", "label": "Cocina otra vez", "required": False},
    ]

    with pytest.raises(CleaningValidationError, match="duplicated item_id"):
        parse_template_content(items, [])


def test_rejects_blank_item_id():
    with pytest.raises(CleaningValidationError, match="item_id"):
        parse_template_content([{"item_id": "   ", "label": "A"}], [])


def test_rejects_non_boolean_required():
    """`isinstance(True, int)` is True, so `required: 1` needs an explicit type check."""
    with pytest.raises(CleaningValidationError, match="'required' must be a boolean"):
        parse_template_content([{"item_id": "a", "label": "A", "required": 1}], [])


def test_rejects_item_that_is_not_an_object():
    with pytest.raises(CleaningValidationError, match="must be an object"):
        parse_template_content(["kitchen"], [])


def test_rejects_duplicated_photo_type():
    photos = [
        {"photo_type": "kitchen", "label": "A", "required": True},
        {"photo_type": "kitchen", "label": "B", "required": True},
    ]

    with pytest.raises(CleaningValidationError, match="duplicated photo_type"):
        parse_template_content(VALID_ITEMS, photos)


def test_rejects_required_photos_that_is_not_a_list():
    with pytest.raises(CleaningValidationError, match="'required_photos' must be a list"):
        parse_template_content(VALID_ITEMS, {"photo_type": "kitchen"})


# --- bounds and charset -----------------------------------------------------------
#
# Found by the QA and security panels of section 1. `item_id` and `photo_type` land in
# `String(100)` columns and `item_id` also travels as a URL path segment, so a template
# that validates here and fails later is a 500 where R1.2 promises a 422 "sin escribir
# nada".


def test_rejects_an_item_id_longer_than_the_column():
    long_id = "x" * (MAX_KEY_LENGTH + 1)

    with pytest.raises(CleaningValidationError, match="longer than 100"):
        parse_template_content([{"item_id": long_id, "label": "A"}], [])


def test_accepts_an_item_id_exactly_at_the_limit():
    spec = parse_template_content([{"item_id": "x" * MAX_KEY_LENGTH, "label": "A"}], [])

    assert spec.item_ids() == {"x" * MAX_KEY_LENGTH}


def test_rejects_a_photo_type_longer_than_the_column():
    with pytest.raises(CleaningValidationError, match="longer than 100"):
        parse_template_content(
            VALID_ITEMS, [{"photo_type": "x" * 101, "label": "A", "required": True}]
        )


def test_rejects_a_label_longer_than_its_bound():
    with pytest.raises(CleaningValidationError, match="longer than 200"):
        parse_template_content([{"item_id": "a", "label": "L" * 201}], [])


@pytest.mark.parametrize(
    "bad",
    [
        "kitchen/sink",
        "kitchen sink",
        "kitchen%20",
        "cocina/../x",
        # `$` in a Python regex also matches before a trailing newline, so these two were
        # accepted by the first version of the charset gate — and `"kitchen"` vs
        # `"kitchen\n"` render identically while the duplicate check sees two items.
        "kitchen\n",
        "kitchen\r",
        "kitchen\r\n",
    ],
)
def test_rejects_an_item_id_that_would_break_the_url_path_segment(bad):
    """`POST /cleaning-tasks/{id}/checklist/{item_id}/complete` — a `/` makes the item
    creatable and permanently uncompletable."""
    with pytest.raises(CleaningValidationError, match="may only contain"):
        parse_template_content([{"item_id": bad, "label": "A"}], [])


@pytest.mark.parametrize("bad", ["kitchen\n", "a\tb", "x\x00y"])
def test_rejects_a_photo_type_with_a_control_character(bad):
    with pytest.raises(CleaningValidationError, match="may only contain"):
        parse_template_content(VALID_ITEMS, [{"photo_type": bad, "label": "A"}])


@pytest.mark.parametrize("good", ["kitchen", "kitchen-sink", "kitchen_sink", "v1.2", "AB9"])
def test_accepts_url_safe_item_ids(good):
    assert parse_template_content([{"item_id": good, "label": "A"}], []).item_ids() == {good}


def test_rejects_a_photo_type_that_is_not_url_safe():
    with pytest.raises(CleaningValidationError, match="may only contain"):
        parse_template_content(VALID_ITEMS, [{"photo_type": "a/b", "label": "A"}])


def test_rejects_more_items_than_the_cap():
    items = [{"item_id": f"i{n}", "label": "A"} for n in range(MAX_ITEMS + 1)]

    with pytest.raises(CleaningValidationError, match="more than 200 entries"):
        parse_template_content(items, [])


def test_rejects_more_required_photos_than_the_cap():
    photos = [{"photo_type": f"p{n}", "label": "A"} for n in range(MAX_REQUIRED_PHOTOS + 1)]

    with pytest.raises(CleaningValidationError, match="more than 50 entries"):
        parse_template_content(VALID_ITEMS, photos)
