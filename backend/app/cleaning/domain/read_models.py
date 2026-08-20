"""The projection `GET /cleaning-tasks/{id}/context` serves (`cleaner-task-context` design D3).

The read side of a poor man's CQRS, same construction as `app/dashboard/domain/read_models.py`:
no entity here, no table, no writer. Pure Python — no pydantic, no sqlalchemy —
`tests/test_layering.py` enforces it, and `app/cleaning/api/schemas.py` maps it to the wire.

**Why the field list is closed, and which rules depend on it staying closed.** A `CLEANER`
holds five permissions and neither `READ_PROPERTIES` nor `READ_RESERVATIONS` is among them
(`app/auth/domain/policy.py`). What that role already reaches is `CleaningTaskResponse`
(`app/cleaning/api/schemas.py`), which carries `property_id`, `reservation_id` and the task's
`scheduled_start`/`scheduled_end` — identifiers and the planned window, no attribute of either
row. This projection is the only route that carries `Property` and `Reservation` **attributes**
to that role, which is what makes enumerating them here the mechanism that turns two
requirements **structural** instead of remembered:

* **R1.4** — `access_notes`, `cleaning_notes`, `emergency_notes`, `wifi_password_encrypted` and
  `has_wifi_password` never appear. Three of those are plaintext sinks of rule 11 of
  `steering/security.md` that are auditable but not denylisted (`properties-crud` design D7), so
  a `Property` dumped through `from_attributes` would carry them. `Property` is never serialised;
  a field that is not here has nowhere to land.
* **R2.5** — no `gross_amount`, `ota_commission`, `net_amount`, `payment_status`, `channel`,
  `guest_id`, `special_requests` or `internal_notes` of any reservation. Same mechanism.

The rule for whoever adds a field, from design D8: **a projection may narrow, never union.** A
field that a permission guards *as a whole* — a reservation's amount, a guest's name — does not
come in here; it goes through `dashboard-api` D10. `tests/cleaning/test_task_context_read_model.py`
pins the set so that adding one is a deliberate act.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CleaningTaskContext:
    """Where the cleaner has to go and the window she has to do it in (R1.1, R1.2, R2.1, R2.2).

    `checkout_at` and `next_checkin_deadline` are timezone-aware, which is what makes R2.4 (ISO
    8601 with an explicit offset) fall out of pydantic's default serialisation with no formatter
    of our own; `timezone` is what lets a client read that offset as a place.

    Both are the answer **now**, deliberately not the task's `scheduled_start`/`scheduled_end`,
    which are the plan the scheduler committed to (design D4). They can disagree, and the
    operation's description says so.
    """

    property_name: str
    property_internal_code: str
    address_line1: str | None
    address_line2: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    country: str
    timezone: str
    checkout_at: datetime | None
    next_checkin_deadline: datetime | None
