"""The projections the dashboard serves (`dashboard-api` R1.2, R2.1, R2.5, design D1).

The read side of a poor man's CQRS: no entity here, no table, no writer. Each type mirrors
one shape of `frontend/features/dashboard/data/dto.ts`, which the change treats as a binding
contract — that file says so itself at `:9-12`.

**All frozen, and all enumerated field by field.** That is the `GuestSummary` construction
(`app/guests/domain/value_objects.py:24-39`): "a frozen projection rather than the `Guest`
entity so the guarantee is structural: no future serialiser can reach a field that is not
here". Two rules of `steering/security.md` depend on it holding:

* **Rule 4** — "número de documento jamás en listados". `GuestBlock` has a name and nothing
  else. It is not a narrowing of `GuestSummary`; it is narrower still, because a dashboard
  needs less than a reservation does.
* **Rules 3 and 4 on access codes** — `AccessBlock` carries a status label and no code, in
  any form. Design D9 records that there is nothing to mask in the first place: the
  plaintext code has no column (`app/access/domain/masking.py`), so this projection is
  agreeing with the schema rather than compensating for it.

The localised strings (`cleaning_status`, `next_action.label`, incident titles, approval
labels) arrive already rendered by `app/dashboard/domain/labels.py` — `dto.ts:28-34` calls
them `LocalizedText`, "already localized by the backend".

Pure Python: no pydantic, no sqlalchemy. `tests/test_layering.py` enforces it, and
`app/dashboard/api/schemas.py` maps these to the wire.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.maintenance.domain.enums import IncidentSeverity
from app.properties.domain.enums import PropertyOperationalState


@dataclass(frozen=True)
class ReservationBlock:
    """The current or next stay (`dto.ts:69-76`).

    `guest_name` and nothing else of the guest: `reference` is the channel plus the external
    id, which is what an operator recognises.

    **`check_in`/`check_out` are `date`, though `dto.ts` types them `IsoDateTime`, and this
    is a deliberate deviation** (`ASSUMPTION`). `reservations` stores `check_in_date` as a
    `date` and `check_in_time` as a separate `time`; turning the pair into an instant means
    resolving the property's timezone, and a wrong answer there is an off-by-hours arrival
    on an operator's screen. No requirement asks for the time — PRD §9.1 wants "reserva
    actual/próxima" — so the honest value is the day, and `dashboard-web` renders a date.
    Whoever needs the hour adds it with the timezone handling it deserves.
    """

    id: uuid.UUID
    reference: str | None
    guest_name: str | None
    check_in: date
    check_out: date


@dataclass(frozen=True)
class NextActionBlock:
    """What happens next and who owes it (`dto.ts:79-82`).

    `label` and `responsible` are both already localised. `responsible` is a **role**
    rendered as text, never a person's name (design D6).
    """

    label: str
    responsible: str | None


@dataclass(frozen=True)
class GuestBlock:
    """The guest, as a dashboard is allowed to know them (`dto.ts:120-122`, R2.5).

    A name. Structurally no `document_number`, no `date_of_birth`, no `nationality`, no
    `document_status` — rule 4 of `steering/security.md` permits `document_status` in a
    listing, but a dashboard has no use for it, and the narrowest projection that serves
    the screen is the one that ages best.
    """

    name: str | None


@dataclass(frozen=True)
class AccessBlock:
    """How the guest gets in, as a label (`dto.ts:125-127`, R2.5).

    A localised status and **no code, not even masked**. Design D9: the plaintext never had
    a column to live in, so there is nothing here to redact.
    """

    label: str | None


@dataclass(frozen=True)
class IncidentBlock:
    """One open incident (`dto.ts:138-143`).

    `title` is rendered from `IncidentCategory`, never from `incidents.title` — see
    `app/maintenance/domain/value_objects.py` for why the stored text cannot serve a
    `LocalizedText` contract and should not leave the database anyway.
    """

    id: uuid.UUID
    title: str
    severity: IncidentSeverity
    opened_at: datetime


@dataclass(frozen=True)
class FinancialBlock:
    """The money on the property detail (`dto.ts:146-150`).

    `Decimal` here, not `float`: money that has been through a binary float has been through
    a rounding error. The `api/` layer decides how to put it on the wire.
    """

    currency: str
    reservation_total: Decimal | None
    pending_expenses: Decimal | None


@dataclass(frozen=True)
class ApprovalBlock:
    """One pending owner approval (`dto.ts:153-158`).

    `label` is rendered from `OwnerApprovalRelatedType`, never from `owner_approvals.reason`.
    """

    id: uuid.UUID
    label: str
    amount: Decimal | None
    currency: str | None


@dataclass(frozen=True)
class CleaningPhotoBlock:
    """A photo of the last cleaning (`dto.ts:130-135`).

    Declared and **always empty today** (R2.4, `EXTERNAL_DEPENDENCY`). `cleaning_photos`
    stores a `storage_key`, and turning one into a URL is `StorageAdapter.get_signed_url`,
    which `cleaning-photos-storage` delivers. Rule 5 of `steering/security.md` forbids
    exposing the internal path, so `url` can only ever hold a signed URL — which is why the
    field exists but nothing fills it yet.
    """

    id: uuid.UUID
    url: str
    taken_at: datetime


@dataclass(frozen=True)
class PropertyDashboardCard:
    """One card on `/dashboard` (`dto.ts:85-96`, R1.2).

    `operational_state` is the canonical literal, untranslated (R1.3, R5.5). No colour: PRD
    §9.1 makes that the frontend's decision, and `sdd/specs/dashboard-web-frontend.md` says
    so in as many words.

    The optional blocks are `None` when the caller's role lacks the permission that guards
    their source (design D10) — indistinguishable, deliberately, from "there is none",
    because telling the two apart would itself disclose what the role may not see.
    """

    property_id: uuid.UUID
    property_code: str
    operational_state: PropertyOperationalState
    current_or_next_reservation: ReservationBlock | None
    cleaning_status: str | None
    open_incidents_count: int
    next_action: NextActionBlock | None
    last_event_label: str | None
    last_event_at: datetime | None


@dataclass(frozen=True)
class PropertyDetail:
    """The aggregate of PRD §9.2 (`dto.ts:161-174`, R2.1).

    Same block-omission rule as the card, over more sources (`READ_RESERVATIONS`,
    `READ_CLEANING_TASKS`, `READ_ACCESS_RECORDS`).
    """

    property_id: uuid.UUID
    property_code: str
    operational_state: PropertyOperationalState
    current_or_next_reservation: ReservationBlock | None
    guest: GuestBlock | None
    access: AccessBlock | None
    cleaning_status: str | None
    last_cleaning_photos: tuple[CleaningPhotoBlock, ...]
    open_incidents: tuple[IncidentBlock, ...]
    financial: FinancialBlock | None
    # **Always `None`, and that is a decision** (`ASSUMPTION`, design D12).
    #
    # PRD §9.2 lists "notas" among the detail's sections and `dto.ts:172` types it
    # `LocalizedText`, but no column owns it. The only candidates are `properties`'
    # `access_notes`, `cleaning_notes` and `emergency_notes` — and
    # `app/properties/application/property_admin.py:53-58` already names all three as
    # rule-11 plaintext sinks: "an operator can paste a door code or a wifi key into
    # 'access notes'". Piping one into a response read by every `READ_PROPERTIES` holder
    # would publish exactly what rules 3 and 4 encrypt and mask everywhere else.
    #
    # The security panel of section 5 asked for this to be decided rather than left for
    # whoever wired the use case to guess. It is: the field stays in the contract so
    # `dashboard-web` does not change shape later, and it is filled by the change that
    # gives operator notes a column of their own — not by draining a sink into a screen.
    notes: str | None
    pending_approvals: tuple[ApprovalBlock, ...]
