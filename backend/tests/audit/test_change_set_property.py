"""The `PROPERTY` audit contract (`properties-crud` R5, R7, design D7).

`properties-crud` is the first writer of a property's audit trail, so this is where its half of
rule 11 of `sdd/steering/security.md` gets pinned. The value that matters most is the WiFi
password: rule 3 names it **first** among the values that never exist in cleartext, and rule 11
is explicit that a guest needing to see it does not authorise a masked form either.

Split from `test_change_set.py`, which pins the contract itself; this file pins that the new
entity type honours it.
"""

import pytest

from app.audit.domain import actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import AUDITABLE_FIELDS, REDACTED_FIELDS, ChangeSet
from app.properties.domain.repositories import PATCHABLE_PROPERTY_FIELDS

_FREE_TEXT_NOTES = ("access_notes", "cleaning_notes", "emergency_notes")


def test_the_property_entity_type_is_part_of_the_closed_vocabulary() -> None:
    """Without this `AuditLogFactory.build` raises, and no property write could be audited."""
    assert actions.ENTITY_PROPERTY in actions.ENTITY_TYPES
    assert actions.PROPERTY_CREATED in actions.ACTIONS
    assert actions.PROPERTY_UPDATED in actions.ACTIONS


def test_a_property_change_set_can_be_constructed() -> None:
    assert ChangeSet(actions.ENTITY_PROPERTY).entity_type == "PROPERTY"


def test_the_wifi_password_cannot_be_recorded_as_a_diff() -> None:
    """The structural half of rule 3: there is no reachable form that keeps the value."""
    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_PROPERTY).diff(
            "wifi_password_encrypted", None, "gAAAA-el-secreto"
        )


def test_the_wifi_password_is_recordable_as_redacted() -> None:
    """The other half: a password changing must still leave a trace.

    This is why `wifi_password_encrypted` is on the allowlist as well as the denylist — dropping
    it from the allowlist would make `redacted()` fail too, and the change would vanish entirely.
    """
    changes = ChangeSet(actions.ENTITY_PROPERTY).redacted("wifi_password_encrypted")

    assert changes.as_dict() == {"wifi_password_encrypted": {"changed": True}}


def test_the_shorter_wifi_password_spelling_is_also_refused() -> None:
    """Both spellings are denylisted; the panel of another change caught one of them missing."""
    assert "wifi_password" in REDACTED_FIELDS
    assert "wifi_password_encrypted" in REDACTED_FIELDS


@pytest.mark.parametrize("field", _FREE_TEXT_NOTES)
def test_the_free_text_notes_are_recordable_as_redacted(field: str) -> None:
    """Design D7 records them without their value: an operator may paste a door code in one."""
    changes = ChangeSet(actions.ENTITY_PROPERTY).redacted(field)

    assert changes.as_dict() == {field: {"changed": True}}


def test_the_operational_state_is_not_an_auditable_property_field() -> None:
    """Its trail is `property_state_transitions`, which records more than a generic row could.

    Two sinks for one fact are two things that can disagree, which is the reasoning rule 9's
    named exception already records for the `SYSTEM` actor.
    """
    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_PROPERTY).diff(
            "current_operational_state", "VACANT_READY", "OUT_OF_SERVICE"
        )


def test_an_invented_field_is_refused() -> None:
    """The allowlist is what stops a caller writing an arbitrary payload under a harmless key."""
    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_PROPERTY).diff("profile_patch", None, "anything")


def test_every_patchable_column_is_auditable() -> None:
    """A field the API can change but the trail cannot record is a silent edit.

    Asserted as a relation between the two allowlists rather than as a copy of the field names:
    a copy is what drifts, and `PATCHABLE_PROPERTY_FIELDS` is the single home of the first rule.
    """
    assert PATCHABLE_PROPERTY_FIELDS <= AUDITABLE_FIELDS["PROPERTY"]


def test_the_audited_set_adds_only_the_wifi_password_to_the_patchable_ones() -> None:
    """Pins the intended difference, so a future widening is visible in the diff."""
    assert AUDITABLE_FIELDS["PROPERTY"] - PATCHABLE_PROPERTY_FIELDS == {
        "wifi_password_encrypted"
    }
