"""The next-action table (`dashboard-api` R1.2, design D6, task 5.2).

Written before the implementation: `steering/testing.md` requires TDD "en `domain/` con
invariante real", and the invariant here is exhaustiveness — every operational state must
have a decided answer, so that a state added later breaks the suite instead of silently
answering `null` on the one card that most needed it.
"""

import pytest

from app.dashboard.domain.next_action import (
    NEXT_ACTION_BY_STATE,
    NextAction,
    Responsible,
    next_action_for,
)
from app.properties.domain.enums import PropertyOperationalState

STATE = PropertyOperationalState


# --- exhaustiveness: the invariant this module exists to hold ---------------------------


def test_the_table_covers_every_operational_state() -> None:
    """Design D6: "Los once estados están cubiertos: la función es exhaustiva sobre el enum
    y un test lo verifica, de modo que un estado nuevo rompa la suite en vez de devolver
    `null` en silencio"."""
    assert set(NEXT_ACTION_BY_STATE) == set(PropertyOperationalState)


def test_the_enum_still_has_the_eleven_states_the_table_was_agreed_for() -> None:
    """If this fails, the enum grew: decide the new state's action deliberately rather than
    letting it inherit whatever the table's default happens to be."""
    assert len(PropertyOperationalState) == 11


@pytest.mark.parametrize("state", list(PropertyOperationalState), ids=lambda s: s.value)
def test_every_state_resolves_without_raising(state: PropertyOperationalState) -> None:
    result = next_action_for(state)

    assert result is None or isinstance(result, NextAction)


# --- the table agreed in the design gate (D6) -------------------------------------------
#
# Stated here as literals rather than derived from `NEXT_ACTION_BY_STATE`: a table computed
# from the implementation would agree with any mistake in it. Same device
# `tests/properties/test_api.py` records for the role matrix.


@pytest.mark.parametrize(
    ("state", "action_key", "responsible"),
    [
        (STATE.AWAITING_CLEANING, "assign_cleaner", Responsible.MANAGER),
        (STATE.CLEANING_SCHEDULED, "pending_acceptance", Responsible.ASSIGNED_CLEANER),
        (STATE.CLEANING_IN_PROGRESS, "cleaning_in_progress", Responsible.ASSIGNED_CLEANER),
        (STATE.AWAITING_CHECKIN, "deliver_access", Responsible.MANAGER),
        (STATE.MAINTENANCE_REQUIRED, "review_incident", None),
        (STATE.CRITICAL_INCIDENT, "attend_incident", None),
    ],
    ids=lambda value: getattr(value, "value", value),
)
def test_the_states_with_an_action_return_the_agreed_one(
    state: PropertyOperationalState, action_key: str, responsible: Responsible | None
) -> None:
    result = next_action_for(state)

    assert result is not None
    assert result.action_key == action_key
    assert result.responsible is responsible


@pytest.mark.parametrize(
    "state",
    [
        STATE.OCCUPIED_ESTIMATED,
        STATE.READY_FOR_NEXT_GUEST,
        STATE.VACANT_READY,
        STATE.BLOCKED_BY_OWNER,
        STATE.OUT_OF_SERVICE,
    ],
    ids=lambda s: s.value,
)
def test_the_states_that_need_nothing_return_none(state: PropertyOperationalState) -> None:
    """`nextAction: null` is a decision here, not an absence: nobody owes an action on a
    flat that is ready, occupied, blocked by its owner or out of service."""
    assert next_action_for(state) is None


# --- the shape, and what it deliberately is not -----------------------------------------


def test_the_responsible_is_a_role_and_never_a_person() -> None:
    """Design D6: "**El responsable es un rol, no una persona.** Se descartó resolver el
    nombre real («María G.») porque cuesta una consulta más y, sobre todo, porque «el
    manager» no está definido cuando un tenant tiene varios"."""
    assert set(Responsible) == {Responsible.MANAGER, Responsible.ASSIGNED_CLEANER}
    for member in Responsible:
        assert isinstance(member.value, str)


def test_a_next_action_is_immutable() -> None:
    import dataclasses

    action = next_action_for(STATE.AWAITING_CLEANING)
    assert action is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        action.action_key = "something else"  # type: ignore[misc]


def test_the_action_key_is_a_catalogue_key_and_not_a_rendered_label() -> None:
    """The label is `app/dashboard/domain/labels.py`'s job (D4): this table decides *what*
    happens next, not how to say it in two languages."""
    for state in PropertyOperationalState:
        action = next_action_for(state)
        if action is None:
            continue
        assert action.action_key.islower()
        assert " " not in action.action_key


def test_next_action_for_rejects_something_that_is_not_a_state() -> None:
    with pytest.raises(ValueError):
        next_action_for("AWAITING_CLEANING")  # type: ignore[arg-type]
