"""R1.3, R1.4 — precedence property → tenant, and ambiguity is refused, not broken.

Pure domain: no database, no fixtures beyond building entities.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.cleaning.domain.entities import CleaningChecklistTemplate
from app.cleaning.domain.exceptions import (
    AmbiguousChecklistTemplateError,
    ChecklistTemplateNotFoundError,
)
from app.cleaning.domain.templates import resolve_template

TENANT = uuid.uuid4()
PROPERTY = uuid.uuid4()
OTHER_PROPERTY = uuid.uuid4()
NOW = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)


def _template(*, property_id=None, active=True, name="t"):
    return CleaningChecklistTemplate(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name=name,
        items=[{"item_id": "a", "label": "A", "required": True}],
        required_photos=[],
        created_at=NOW,
        updated_at=NOW,
        property_id=property_id,
        active=active,
    )


def test_property_template_wins_over_tenant_default():
    own = _template(property_id=PROPERTY, name="own")
    default = _template(property_id=None, name="default")

    assert resolve_template([default, own], PROPERTY) is own


def test_falls_back_to_the_tenant_default():
    default = _template(property_id=None, name="default")
    other = _template(property_id=OTHER_PROPERTY, name="other")

    assert resolve_template([other, default], PROPERTY) is default


def test_inactive_templates_are_ignored():
    inactive = _template(property_id=PROPERTY, active=False)
    default = _template(property_id=None)

    assert resolve_template([inactive, default], PROPERTY) is default


def test_two_active_property_templates_are_ambiguous():
    with pytest.raises(AmbiguousChecklistTemplateError):
        resolve_template(
            [_template(property_id=PROPERTY), _template(property_id=PROPERTY)], PROPERTY
        )


def test_two_active_tenant_defaults_are_ambiguous():
    with pytest.raises(AmbiguousChecklistTemplateError):
        resolve_template([_template(), _template()], PROPERTY)


def test_ambiguity_at_the_tenant_level_does_not_fire_when_the_property_resolves():
    """Precedence is checked level by level: a clean property level ends the search."""
    own = _template(property_id=PROPERTY)

    assert resolve_template([own, _template(), _template()], PROPERTY) is own


def test_nothing_active_raises_not_found():
    with pytest.raises(ChecklistTemplateNotFoundError):
        resolve_template([_template(property_id=PROPERTY, active=False)], PROPERTY)


def test_empty_candidate_list_raises_not_found():
    with pytest.raises(ChecklistTemplateNotFoundError):
        resolve_template([], PROPERTY)
