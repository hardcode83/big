"""What happens next on a property, and who owes it (`dashboard-api` R1.2, design D6).

Principle 2 of `steering/product.md` asks the dashboard to answer "¿qué pasa y quién tiene
la próxima acción?" in under ten seconds. This module is the second half of that question.

**ASSUMPTION.** PRD §9.1 asks for "próxima acción requerida y responsable" and gives one
example (`Limpiadora: María — pendiente de aceptar`) but **does not define the table**. The
mapping below was agreed with the user at the design gate of 2026-08-09 (design D6) and is
marked as an assumption because it is ours, not the PRD's. `sdd/project.md` requires that
marking; nothing here should be read as a citation.

Two shapes this module deliberately does NOT have:

* **No label.** It returns a catalogue *key*, and `app/dashboard/domain/labels.py` renders
  it in `es`/`en` (design D4, R5.2). A function that returned Spanish would have to be
  called again to produce English.
* **No person.** `responsible` is a role. Design D6: "Se descartó resolver el nombre real
  («María G.») porque cuesta una consulta más y, sobre todo, porque «el manager» no está
  definido cuando un tenant tiene varios — una decisión que el PRD no toma y que este
  change no debe inventar."

Pure Python: no pydantic, no sqlalchemy, no I/O. `tests/test_layering.py` enforces it.
"""

import enum
from dataclasses import dataclass

from app.properties.domain.enums import PropertyOperationalState


class Responsible(enum.Enum):
    """Who owes the next action — a **role**, never a person.

    Two members and not five: these are the only two roles any action in the table below
    actually falls to. Adding `TECHNICIAN` would be speculative, and the two states that
    would want it (`MAINTENANCE_REQUIRED`, `CRITICAL_INCIDENT`) answer `None` on purpose
    until `maintenance` exists to assign one.
    """

    MANAGER = "MANAGER"
    ASSIGNED_CLEANER = "ASSIGNED_CLEANER"


@dataclass(frozen=True)
class NextAction:
    """A catalogue key plus the role that owes it.

    `responsible` is `None` where the action is real but nobody is assignable yet — which
    is different from having no action at all, and the reason this type exists rather than
    a bare `tuple`.
    """

    action_key: str
    responsible: Responsible | None


#: The table agreed at the design gate (D6). `None` means "nobody owes anything right now",
#: which is a decision and not an omission: a flat that is ready, occupied, blocked by its
#: owner or out of service is in a resting state.
#:
#: **Exhaustive over `PropertyOperationalState` by construction**, and a test asserts it, so
#: a state added later breaks the suite instead of silently answering `null` on the card
#: that most needed an answer.
NEXT_ACTION_BY_STATE: dict[PropertyOperationalState, NextAction | None] = {
    PropertyOperationalState.AWAITING_CLEANING: NextAction(
        "assign_cleaner", Responsible.MANAGER
    ),
    PropertyOperationalState.CLEANING_SCHEDULED: NextAction(
        "pending_acceptance", Responsible.ASSIGNED_CLEANER
    ),
    PropertyOperationalState.CLEANING_IN_PROGRESS: NextAction(
        "cleaning_in_progress", Responsible.ASSIGNED_CLEANER
    ),
    PropertyOperationalState.AWAITING_CHECKIN: NextAction(
        "deliver_access", Responsible.MANAGER
    ),
    # `None` responsible, not `MANAGER`: who attends an incident is `maintenance`'s
    # decision (it assigns a technician), and guessing here would put a second copy of that
    # policy in a read model.
    PropertyOperationalState.MAINTENANCE_REQUIRED: NextAction("review_incident", None),
    PropertyOperationalState.CRITICAL_INCIDENT: NextAction("attend_incident", None),
    PropertyOperationalState.OCCUPIED_ESTIMATED: None,
    PropertyOperationalState.READY_FOR_NEXT_GUEST: None,
    PropertyOperationalState.VACANT_READY: None,
    PropertyOperationalState.BLOCKED_BY_OWNER: None,
    PropertyOperationalState.OUT_OF_SERVICE: None,
}


def next_action_for(state: PropertyOperationalState) -> NextAction | None:
    """The next action for `state`, or `None` when nobody owes one.

    Raises `ValueError` for anything that is not a `PropertyOperationalState` rather than
    returning `None`: "not a state" and "a state with nothing pending" are different
    answers, and collapsing them would let a typo look like a resting property.
    """
    if not isinstance(state, PropertyOperationalState):
        raise ValueError(f"{state!r} is not a PropertyOperationalState")
    return NEXT_ACTION_BY_STATE[state]
