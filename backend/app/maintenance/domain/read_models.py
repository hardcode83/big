"""What `GET /incidents/{incident_id}/context` serves (`tech-incident-context` design D4).

The read side of a poor man's CQRS, the same construction as
`app/cleaning/domain/read_models.py` and `app/dashboard/domain/read_models.py`: no entity here,
no table, no writer. Pure Python — no pydantic, no sqlalchemy — `tests/test_layering.py`
enforces it, and `app/maintenance/api/schemas.py` maps it to the wire.

**Why the field list is closed, and which rules depend on it staying closed.** A `TECHNICIAN`
holds five permissions and neither `READ_PROPERTIES` nor `READ_RESERVATIONS` is among them
(`app/auth/domain/policy.py`). What that role already reaches is `IncidentResponse`
(`app/maintenance/api/schemas.py`), which carries `property_id` and `reservation_id` as bare
identifiers and no attribute of either row. This projection is the only route that carries
`Property` **attributes** to that role, which is what makes enumerating them here the mechanism
that turns three requirements **structural** instead of remembered:

* **R2.5 / R5.2** — `wifi_password_encrypted` is not a field of `Property` at all
  (`properties-crud` D2), and `has_wifi_password`, `cleaning_notes` and `emergency_notes` are
  not fields of this projection. Rule 3 of `steering/security.md` grants no form for a WiFi
  password, masked or otherwise, and the flag is excluded too: no requirement asks for it, and
  the narrowest projection ages best. `Property` is never serialised; a field that is not here
  has nowhere to land.
* **R5.3** — no attribute of any reservation: no `gross_amount`, `ota_commission`, `net_amount`,
  `payment_status`, `channel`, `guest_id`, `special_requests` or `internal_notes`. PRD §12 does
  not ask for the booking on this screen, and the use case reads no reservation repository, so
  there is not even a statement that could produce one.
* **R5.4** — no `reported_by_guest_token`, `reported_by_user_id` or `ai_classification`. The
  first never leaves the port (`IncidentRepository.get` drops it); the other two are excluded
  the same way as everything else, by not being here.

The rule for whoever adds a field, inherited verbatim from `cleaner-task-context` design D8: **a
projection may narrow, never union.** A field that a permission guards *as a whole* — a
reservation's amount, a guest's name — does not come in here; it goes through `dashboard-api`
D10. `tests/maintenance/test_incident_context_read_model.py` pins the set so that adding one is
a deliberate act.

This capability **diverges** from "aggregating cannot grant" with the same bounded scope
`cleaner-task-context` claimed: its subject is an incident the caller may already read in full,
and what it adds are ten attributes of one property over a row set **narrower** than
`READ_PROPERTIES` would give.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class IncidentContext:
    """Where the technician has to go, how to get in, and what the manager said (R1, R2, R3).

    Ten of the eleven fields come from the property, which is why a property that does not
    resolve inside the tenant is a `404` and never a partial answer (R1.5, design D9). The
    eleventh, `assignment_note`, belongs to the **assignment in force** and is replaced on every
    reassignment (design D7).

    The fields are named after their columns rather than aliased by audience. The guest portal
    renames `access_notes` to `arrival_notes`, which is right there — its reader never sees a
    column name — but a third name for a column that has to be auditable across the tree makes
    it ungreppable, and a technician's screen is a surface of operation, not of hospitality.
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
    access_notes: str | None
    assignment_note: str | None
