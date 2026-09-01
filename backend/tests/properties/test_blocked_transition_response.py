"""Schema-shape tests for `BlockedTransitionResponse`.

Pure Pydantic: no DB, no fixtures, no app. The shape is the contract the frontend derives
types from (`frontend/lib/api/generated/openapi.d.ts`), and the two new optional fields —
`cleaning_task_id`, `incident_id` — must round-trip as `null` in JSON when unset, and as a UUID
string when set. That is what the dashboard's mutation hooks rely on (R1.2, R1.3).

These tests predate the population logic (§2-§3): at this stage the schema carries the
fields and `from_row` does not yet read them, so `None`/`None` is the only legal construction
in tests. §3 of `tasks.md` replaces that with the integration tests that exercise a populated
row end-to-end.
"""

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.properties.api.schemas import BlockedTransitionResponse


def _row_dict(
    *,
    property_id: uuid.UUID | None = None,
    reservation_id: uuid.UUID | None = None,
    cleaning_task_id: uuid.UUID | None = None,
    incident_id: uuid.UUID | None = None,
) -> dict:
    """The minimum dict a hand-built instance can be made from.

    Six fields are always required (R1.1); the two action ids are optional and default to None.
    """
    return {
        "property_id": property_id or uuid.uuid4(),
        "property_code": "REDES11",
        "reservation_id": reservation_id or uuid.uuid4(),
        "trigger": "CHECKIN_TIME_REACHED",
        "blocking_state": "CLEANING_IN_PROGRESS",
        "due_since": datetime(2026, 8, 19, 15, 0, tzinfo=UTC),
        "cleaning_task_id": cleaning_task_id,
        "incident_id": incident_id,
    }


# --- R1.2, R1.3: the schema accepts both ids as optional and serialises them as JSON null ---


def test_both_action_ids_default_to_none_and_serialise_as_json_null() -> None:
    """R1.3, named in the proposal because the alternatives are all wrong on the wire."""
    instance = BlockedTransitionResponse(**_row_dict())
    assert instance.cleaning_task_id is None
    assert instance.incident_id is None

    payload = json.loads(instance.model_dump_json())

    assert payload["cleaning_task_id"] is None
    assert payload["incident_id"] is None
    # Belt-and-braces: forbid the two known wrong serialisations by name, in case a future
    # Pydantic config flipped `exclude_none=True` or someone aliased the field to "".
    assert payload["cleaning_task_id"] is not ""
    assert payload["cleaning_task_id"] != "null"
    assert payload["incident_id"] != "null"


def test_only_cleaning_task_id_populated_serialises_cleaning_and_null_incident() -> None:
    """R2.1 shape: blocking_state of cleaning family ⇒ cleaning_task_id, incident_id null."""
    cleaning_id = uuid.uuid4()
    instance = BlockedTransitionResponse(**_row_dict(cleaning_task_id=cleaning_id))

    payload = json.loads(instance.model_dump_json())

    assert payload["cleaning_task_id"] == str(cleaning_id)
    assert payload["incident_id"] is None


def test_only_incident_id_populated_serialises_incident_and_null_cleaning() -> None:
    """R2.2 shape: blocking_state NOT of cleaning family ⇒ incident_id, cleaning_task_id null."""
    incident_id = uuid.uuid4()
    instance = BlockedTransitionResponse(**_row_dict(incident_id=incident_id))

    payload = json.loads(instance.model_dump_json())

    assert payload["incident_id"] == str(incident_id)
    assert payload["cleaning_task_id"] is None


def test_both_ids_populated_serialises_both_as_uuid_strings() -> None:
    """§Out of scope of R2 forbids this in production, but the schema permits it as a shape."""
    cleaning_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    instance = BlockedTransitionResponse(
        **_row_dict(cleaning_task_id=cleaning_id, incident_id=incident_id)
    )

    payload = json.loads(instance.model_dump_json())

    assert payload["cleaning_task_id"] == str(cleaning_id)
    assert payload["incident_id"] == str(incident_id)


# --- R1.1, R1.4: backwards compatibility of the six original fields ---


@pytest.mark.parametrize(
    "missing_field",
    ["property_id", "property_code", "reservation_id", "trigger", "blocking_state", "due_since"],
)
def test_each_of_the_six_original_fields_is_required(missing_field: str) -> None:
    """R1.2: existing clients keep getting the same six fields; the two new are additive.

    Dropping any of the originals must still raise — they are not "made optional" by this change.
    Parametrising on a closed list of six literals (testing.md forbids random values inside
    parametrize, but a fixed literal list is fine) makes the test name honest about what it
    exercises: each of the six, not just one.
    """
    base = _row_dict()
    del base[missing_field]
    with pytest.raises(Exception):
        BlockedTransitionResponse(**base)


def test_the_six_original_fields_round_trip_with_their_types() -> None:
    """R1.4: existing consumers see no change in shape or types."""
    pid = uuid.uuid4()
    rid = uuid.uuid4()
    instance = BlockedTransitionResponse(
        **_row_dict(property_id=pid, reservation_id=rid)
    )

    payload = json.loads(instance.model_dump_json())

    assert payload["property_id"] == str(pid)
    assert payload["property_code"] == "REDES11"
    assert payload["reservation_id"] == str(rid)
    assert payload["trigger"] == "CHECKIN_TIME_REACHED"
    assert payload["blocking_state"] == "CLEANING_IN_PROGRESS"
    assert payload["due_since"].startswith("2026-08-19T15:00:00")


def test_extra_fields_on_input_are_silently_dropped_by_response_model() -> None:
    """The schema does not declare `model_config = ConfigDict(extra="forbid")`, so Pydantic
    ignores extras silently today. The proposal does NOT require this change to enforce
    forbid on the response model (forbid is on the **request** schemas of the properties
    router, R3.3). This test pins the current behaviour so a future change that flips it
    fails loudly and reads the assertion's name. The test name matches what it asserts —
    "silently dropped", not "rejected" — so a grep for either finds the right intent.
    """
    extras = _row_dict()
    extras["not_a_real_field"] = "anything"

    # Should not raise: extras are dropped silently.
    instance = BlockedTransitionResponse(**extras)
    assert not hasattr(instance, "not_a_real_field")
