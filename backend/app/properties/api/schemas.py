"""Request/response DTOs of the property endpoints (PRD §23, R1, R2, R3, R5).

Three rules this module exists to enforce:

* **No request schema has a `tenant_id`** — the effective tenant comes only from the verified
  token (R2.2), so one sent in a body is rejected by `extra="forbid"` and never reaches a use
  case. The same applies to the **query surface**: `BlockedTransitionListQuery` (R3.3 of
  `blocked-transition-response-ids`) carries `extra="forbid"` so `?tenant_id=…` is rejected with
  `422` rather than silently dropped.
* **No response schema has the wifi password, in any form.** `PropertyResponse` structurally
  lacks the field; what it carries is the derived `has_wifi_password` boolean (R5.2). Rule 3 of
  `steering/security.md` names `wifi_password` first among the values that are never plaintext,
  and rule 11 is explicit that a guest needing to see it does not buy a masked form either — so
  there is no masked variant to offer.
* **`current_operational_state` is not writable here.** It is absent from both request schemas:
  `steering/backend.md` forbids bypassing `PropertyStateMachine` and `PATCHABLE_PROPERTY_FIELDS`
  excludes it, so `extra="forbid"` turns an attempt into a `422` that names the field.
"""

import uuid
from datetime import datetime, time
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.integrations.domain.enums import PMSProvider
from app.properties.application.property_admin import PropertyState
from app.properties.application.use_cases import BlockedTransitionRow
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState, PropertyStatus
from app.properties.domain.repositories import PATCHABLE_PROPERTY_FIELDS

MAX_PER_PAGE = 100
# `page` needs a ceiling too, not just `per_page`: the value becomes a SQL OFFSET, and a
# 20-digit page number overflows int8 and comes back as an unhandled driver error instead of a
# `422` in the PRD §23 envelope. Same bound and same reason as `reservations`.
MAX_PAGE = 100_000

# Column widths of `properties` (`app/properties/infrastructure/models.py`), so an oversized
# value is a `422` in the envelope rather than a driver error mid-transaction.
MAX_NAME = 200
MAX_INTERNAL_CODE = 50
MAX_PMS_EXTERNAL_ID = 200
MAX_ADDRESS = 200
MAX_CITY = 100
MAX_PROVINCE = 100
MAX_POSTAL_CODE = 20
MAX_WIFI_NAME = 200

# Four columns are `String()` with NO length in the DDL (migration `4a5faad7796b`), so unlike
# every bound above there is no database width to inherit one from — they are declared here on
# purpose (R2.4). Without a bound, a multi-megabyte note is a successful write.
MAX_NOTES = 5000
MAX_WIFI_PASSWORD = 200

# Guest counts and room counts: bounded so an absurd value is a client error and not a row.
MAX_GUESTS = 50
MAX_ROOMS = 50

# `pms_provider` is accepted on write even though PRD §7.4 does not list it: ADR 0006 decision 7
# added the column, and `pms-provider-resolution.md` specifies it as nullable, meaning "the
# bootstrap default". Without it here, wiring a property to a provider would need SQL by hand.
#
# The provider CREDENTIAL is emphatically not here and never will be: rule 3(a) of
# `steering/security.md` forbids serialising one in any API response even masked, and
# `app/integrations/cli/pms_credentials.py` stays the only way to store one (R5.1).

# Columns a caller may legitimately clear by sending `null`. Everything absent from this set is
# NOT NULL in the schema, so `null` for it is a `422` rather than a write — see
# `_reject_explicit_nulls`.
#
# Scoped to what `UpdatePropertyRequest` actually declares: the rejection message enumerates this
# set verbatim, so a name here that the schema does not carry would promise a caller they can
# clear a field that does not exist. `pms_provider` was in this list while it was a patchable
# field and left with it.
NULLABLE_FIELDS = frozenset(
    {
        "pms_external_id",
        "address_line1",
        "address_line2",
        "city",
        "province",
        "postal_code",
        "wifi_name",
        "wifi_password",
        "access_notes",
        "cleaning_notes",
        "emergency_notes",
    }
)


class CreatePropertyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
    internal_code: Annotated[str, Field(min_length=1, max_length=MAX_INTERNAL_CODE)]
    pms_external_id: Annotated[str | None, Field(default=None, max_length=MAX_PMS_EXTERNAL_ID)] = None
    pms_provider: PMSProvider | None = None
    address_line1: Annotated[str | None, Field(default=None, max_length=MAX_ADDRESS)] = None
    address_line2: Annotated[str | None, Field(default=None, max_length=MAX_ADDRESS)] = None
    city: Annotated[str | None, Field(default=None, max_length=MAX_CITY)] = None
    province: Annotated[str | None, Field(default=None, max_length=MAX_PROVINCE)] = None
    postal_code: Annotated[str | None, Field(default=None, max_length=MAX_POSTAL_CODE)] = None
    country: Annotated[str, Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")] = "ES"
    timezone: Annotated[str, Field(min_length=1, max_length=50)] = "Europe/Madrid"
    max_guests: Annotated[int, Field(ge=1, le=MAX_GUESTS)] = 2
    bedrooms: Annotated[int, Field(ge=0, le=MAX_ROOMS)] = 1
    bathrooms: Annotated[int, Field(ge=0, le=MAX_ROOMS)] = 1
    default_check_in_time: time = time(15, 0)
    default_check_out_time: time = time(11, 0)
    wifi_name: Annotated[str | None, Field(default=None, max_length=MAX_WIFI_NAME)] = None
    wifi_password: Annotated[str | None, Field(default=None, max_length=MAX_WIFI_PASSWORD)] = None
    access_notes: Annotated[str | None, Field(default=None, max_length=MAX_NOTES)] = None
    cleaning_notes: Annotated[str | None, Field(default=None, max_length=MAX_NOTES)] = None
    emergency_notes: Annotated[str | None, Field(default=None, max_length=MAX_NOTES)] = None
    status: PropertyStatus = PropertyStatus.ACTIVE


class UpdatePropertyRequest(BaseModel):
    """Every field optional; only those present are applied (R3.1).

    `model_fields_set` is what distinguishes "not sent" from "sent as null", so a caller can
    clear `city` by sending `null` without every other unsent field being treated as a clear.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(default=None, min_length=1, max_length=MAX_NAME)] = None
    internal_code: Annotated[
        str | None, Field(default=None, min_length=1, max_length=MAX_INTERNAL_CODE)
    ] = None
    pms_external_id: Annotated[str | None, Field(default=None, max_length=MAX_PMS_EXTERNAL_ID)] = None
    # `pms_provider` is NOT patchable, and its absence here is load-bearing rather than an
    # oversight. It was declared once, accepted, and then dropped by `changes()` because the
    # allowlist never contained it — a `200` for a write that never happened, which is exactly
    # the class of silent discard the adapter refuses for every other key. Removing the field
    # makes `extra="forbid"` answer `422` instead, so a caller learns the truth.
    #
    # Changing a property's provider is also not a plain column write: the partial unique index
    # keys on `coalesce(pms_provider, 'MOCK')`, so moving a row between providers can collide
    # with a sibling that legitimately shares its external id. That needs its own operation with
    # its own conflict handling, which no requirement asks for yet — so the provider is chosen at
    # creation (design D5) and stays chosen.
    address_line1: Annotated[str | None, Field(default=None, max_length=MAX_ADDRESS)] = None
    address_line2: Annotated[str | None, Field(default=None, max_length=MAX_ADDRESS)] = None
    city: Annotated[str | None, Field(default=None, max_length=MAX_CITY)] = None
    province: Annotated[str | None, Field(default=None, max_length=MAX_PROVINCE)] = None
    postal_code: Annotated[str | None, Field(default=None, max_length=MAX_POSTAL_CODE)] = None
    country: Annotated[
        str | None, Field(default=None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    ] = None
    timezone: Annotated[str | None, Field(default=None, min_length=1, max_length=50)] = None
    max_guests: Annotated[int | None, Field(default=None, ge=1, le=MAX_GUESTS)] = None
    bedrooms: Annotated[int | None, Field(default=None, ge=0, le=MAX_ROOMS)] = None
    bathrooms: Annotated[int | None, Field(default=None, ge=0, le=MAX_ROOMS)] = None
    default_check_in_time: time | None = None
    default_check_out_time: time | None = None
    wifi_name: Annotated[str | None, Field(default=None, max_length=MAX_WIFI_NAME)] = None
    wifi_password: Annotated[str | None, Field(default=None, max_length=MAX_WIFI_PASSWORD)] = None
    access_notes: Annotated[str | None, Field(default=None, max_length=MAX_NOTES)] = None
    cleaning_notes: Annotated[str | None, Field(default=None, max_length=MAX_NOTES)] = None
    emergency_notes: Annotated[str | None, Field(default=None, max_length=MAX_NOTES)] = None
    status: PropertyStatus | None = None

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "UpdatePropertyRequest":
        """`null` is only a legal value for the columns that are actually nullable.

        Every field here is `X | None` because `None` is how "not sent" is spelled, but that is
        NOT the same as the caller sending `null`, and `model_fields_set` cannot tell them apart
        once they reach `changes()`. `user-management` paid for this lesson: `PATCH
        {"email": null}` answered `200` and wrote the string `"none"` into the login identity.
        Here the equivalent would be `{"name": null}` on a NOT NULL column, reaching the database
        as an unmapped `500`.
        """
        sent_nulls = {
            field
            for field in self.model_fields_set
            if field not in NULLABLE_FIELDS and getattr(self, field) is None
        }
        if sent_nulls:
            raise ValueError(
                f"{', '.join(sorted(sent_nulls))} cannot be null; only "
                f"{', '.join(sorted(NULLABLE_FIELDS))} can be cleared"
            )
        return self

    def changes(self) -> dict[str, Any]:
        """Only the fields the caller actually sent, and only those the use case may write.

        The allowlist is imported from `domain/`, not restated here: two copies of one rule is
        how they drift, and this one is load-bearing — `current_operational_state` being absent
        from it is what makes a route around `PropertyStateMachine` impossible rather than merely
        unimplemented.

        `wifi_password` is passed through even though it is NOT in the allowlist: it is not a
        plain column write, and the use case routes it to `set_wifi_password`, which encrypts.
        """
        allowed = PATCHABLE_PROPERTY_FIELDS | {"wifi_password"}
        return {
            field: getattr(self, field)
            for field in self.model_fields_set
            if field in allowed
        }


class PropertyResponse(BaseModel):
    """One property. Structurally without the wifi password, in any form (R5.2).

    Fields are enumerated and built by `from_domain`, never dumped with `from_attributes`: the
    entity gains fields owned by other modules over time and a dump would publish each new one
    automatically. That is the same reason `reservations` and `users` enumerate theirs.
    """

    id: uuid.UUID
    name: str
    internal_code: str
    pms_external_id: str | None
    pms_provider: PMSProvider | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    country: str
    timezone: str
    max_guests: int
    bedrooms: int
    bathrooms: int
    current_operational_state: PropertyOperationalState
    default_check_in_time: time
    default_check_out_time: time
    wifi_name: str | None
    has_wifi_password: bool
    access_notes: str | None
    cleaning_notes: str | None
    emergency_notes: str | None
    status: PropertyStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, property: Property) -> "PropertyResponse":
        return cls(
            id=property.id,
            name=property.name,
            internal_code=property.internal_code,
            pms_external_id=property.pms_external_id,
            pms_provider=property.pms_provider,
            address_line1=property.address_line1,
            address_line2=property.address_line2,
            city=property.city,
            province=property.province,
            postal_code=property.postal_code,
            country=property.country,
            timezone=property.timezone,
            max_guests=property.max_guests,
            bedrooms=property.bedrooms,
            bathrooms=property.bathrooms,
            current_operational_state=property.current_operational_state,
            default_check_in_time=property.default_check_in_time,
            default_check_out_time=property.default_check_out_time,
            wifi_name=property.wifi_name,
            has_wifi_password=property.has_wifi_password,
            access_notes=property.access_notes,
            cleaning_notes=property.cleaning_notes,
            emergency_notes=property.emergency_notes,
            status=property.status,
            created_at=property.created_at,
            updated_at=property.updated_at,
        )


class PropertyListItemResponse(BaseModel):
    """One property **in a listing**: `PropertyResponse` minus the three free-text notes.

    Why a second model instead of one with an optional field: this is the mechanism half of
    `tech-incident-context` D5, and rule 11 of `steering/security.md` requires the chosen form to
    be *implemented*, not only documented. `GET /api/v1/properties` returned the access
    instructions of **every** flat of the tenant in one response, which is the only bulk surface
    those columns had — and a field a caller could ask for would not be an exclusion.

    **On the rule this borrows from, stated precisely because the loose version is tempting.**
    Rule 4 says "número de documento jamás en listados", and it says it about `document_number`
    and nothing else — these three columns are not named there, and rule 4 does not reach them on
    its own. What is borrowed is the *shape* of that remedy: keep the bulk surface from carrying
    the value at all, rather than masking it. Rule 11 is what applies that shape here, through
    excepción 6, which is the row that owns this decision. Citing rule 4 as if it governed these
    columns directly would be the kind of almost-true sentence rule 11 says of itself is worse
    than no census at all.

    **All three notes, not just `access_notes`.** Only `access_notes` earns a census row (D12
    says why: the other two do not carry a rule-3 value by purpose), but the exclusion is one
    schema and the same cost, and a listing that hides one note and shows two is a form nobody
    will be able to explain in six months. Approved in the design gate on 2026-08-19 (OQ3).

    What stays: `GET /api/v1/properties/{id}` still carries all three, and the guest portal still
    returns `access_notes` verbatim as `arrival_notes`. Leaving the listing is not leaving the
    system — it is leaving the one place where the whole portfolio arrived at once.

    Enumerated and built by `from_domain` like `PropertyResponse`, never dumped with
    `from_attributes`: a dump would re-acquire every field the entity gains later, which is the
    failure this class exists to prevent.
    """

    id: uuid.UUID
    name: str
    internal_code: str
    pms_external_id: str | None
    pms_provider: PMSProvider | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    country: str
    timezone: str
    max_guests: int
    bedrooms: int
    bathrooms: int
    current_operational_state: PropertyOperationalState
    default_check_in_time: time
    default_check_out_time: time
    wifi_name: str | None
    has_wifi_password: bool
    status: PropertyStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, property: Property) -> "PropertyListItemResponse":
        return cls(
            id=property.id,
            name=property.name,
            internal_code=property.internal_code,
            pms_external_id=property.pms_external_id,
            pms_provider=property.pms_provider,
            address_line1=property.address_line1,
            address_line2=property.address_line2,
            city=property.city,
            province=property.province,
            postal_code=property.postal_code,
            country=property.country,
            timezone=property.timezone,
            max_guests=property.max_guests,
            bedrooms=property.bedrooms,
            bathrooms=property.bathrooms,
            current_operational_state=property.current_operational_state,
            default_check_in_time=property.default_check_in_time,
            default_check_out_time=property.default_check_out_time,
            wifi_name=property.wifi_name,
            has_wifi_password=property.has_wifi_password,
            status=property.status,
            created_at=property.created_at,
            updated_at=property.updated_at,
        )


class PropertyStateResponse(BaseModel):
    """The light state endpoint of PRD §23:1942 (`dashboard-api` R3.1).

    Exactly the two values R3.1 names, and no more: the client that polls this to refresh an
    indicator does not want the property again. `current_operational_state` is the canonical
    literal, never translated (R5.5); `last_transition_at` is ISO-8601 UTC and is `null` for
    a property that has never moved — creation is not a transition, so there is no instant,
    as opposed to one we failed to find.
    """

    current_operational_state: PropertyOperationalState
    last_transition_at: datetime | None

    @classmethod
    def from_domain(cls, state: PropertyState) -> "PropertyStateResponse":
        return cls(
            current_operational_state=state.current_operational_state,
            last_transition_at=state.last_transition_at,
        )


class PropertyPageResponse(BaseModel):
    """The pagination envelope of PRD §23.

    `data` carries `PropertyListItemResponse` and not `PropertyResponse`: the three free-text
    notes leave the listing (`tech-incident-context` D5). It is an incompatible change to this
    contract, and the cost was measured before taking it — no component of the frontend reads any
    of the three; every appearance in `frontend/` is inside the generated
    `lib/api/generated/openapi.d.ts`.
    """

    data: list[PropertyListItemResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(
        cls, properties: tuple[Property, ...], *, total: int, page: int, per_page: int
    ) -> "PropertyPageResponse":
        return cls(
            data=[PropertyListItemResponse.from_domain(item) for item in properties],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page if per_page else 0,
        )


class BlockedTransitionListQuery(BaseModel):
    """Query parameters of `GET /api/v1/blocked-transitions` (R3.3, R4.4 of
    `blocked-transition-response-ids`).

    The two pagination fields are bound to a Pydantic model (not raw `Query(...)` ints) so the
    model can carry `extra="forbid"`: an unknown query key — most importantly `tenant_id` — is
    rejected with `422` rather than silently dropped by FastAPI's default param parsing. The
    endpoint has no body, so the body half of R4.4 is structurally unreachable; this guard covers
    the query-string half. See `BlockedTransitionResponse` for the response-side counterpart and
    `test_action_id_isolation.py::test_tenant_id_in_query_string_is_rejected_with_422` for the
    assertion that the rejection actually fires.
    """

    model_config = ConfigDict(extra="forbid")

    page: Annotated[int, Field(ge=1, le=MAX_PAGE)] = 1
    per_page: Annotated[int, Field(ge=1, le=MAX_PER_PAGE)] = 20


class BlockedTransitionResponse(BaseModel):
    """One transition the calendar required and the flat's state refused (R2.2).

    `trigger` and `blocking_state` travel as their **canonical literals, without prose**: the same
    treatment `dashboard-api` gives `operational_state` ("carries no colour: the colour mapping
    belongs to the client"). Translating them here would open a catalogue of strings for a
    consumer that does not exist yet — this change is `[BE]` and ships the API, not the screen.

    `due_since` answers "since when", which is the number an operator actually wants: for REDES11,
    the 19th of August and not the day somebody happened to look.
    """

    property_id: uuid.UUID
    property_code: str
    reservation_id: uuid.UUID
    trigger: str
    blocking_state: str
    due_since: datetime
    # Action ids (R2.1, R2.2 of `blocked-transition-response-ids`): the resource a button on the
    # dashboard would call a mutation against. Optional because the lookup is "open task/incident
    # on the property" and the absence is a real answer, not a missing value — see R2.3 and R2.4.
    # Never accept these from request input; they are populated server-side from
    # `cleaning_tasks`/`incidents` rows tenant-scoped to the verified token (R3).
    cleaning_task_id: uuid.UUID | None = None
    incident_id: uuid.UUID | None = None

    @classmethod
    def from_row(cls, row: BlockedTransitionRow) -> "BlockedTransitionResponse":
        return cls(
            property_id=row.mismatch.property_id,
            property_code=row.property_code,
            reservation_id=row.mismatch.reservation_id,
            trigger=row.mismatch.trigger.value,
            blocking_state=row.mismatch.blocking_state.value,
            due_since=row.mismatch.due_since,
            # Action ids populated by `ActionIdResolver` in `ListBlockedTransitionsUseCase`
            # (R2 of `blocked-transition-response-ids`). The row carries them as `None`
            # until the resolver fills them in; a `None` here serialises to JSON `null`
            # and is what the dashboard's mutation buttons render as "no resource to call".
            cleaning_task_id=row.cleaning_task_id,
            incident_id=row.incident_id,
        )


class BlockedTransitionPageResponse(BaseModel):
    """The pagination envelope of PRD §23, over the stalls rather than over the flats.

    `total` is how many stalls the tenant has, not how many properties were examined — see
    `ListBlockedTransitionsUseCase`, which pages the result precisely so a stalled flat cannot
    hide on page 3 of the source.
    """

    data: list[BlockedTransitionResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(
        cls, rows: tuple[BlockedTransitionRow, ...], *, total: int, page: int, per_page: int
    ) -> "BlockedTransitionPageResponse":
        return cls(
            data=[BlockedTransitionResponse.from_row(row) for row in rows],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page if per_page else 0,
        )
