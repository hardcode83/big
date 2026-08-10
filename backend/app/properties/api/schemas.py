"""Request/response DTOs of the property endpoints (PRD §23, R1, R2, R3, R5).

Three rules this module exists to enforce:

* **No request schema has a `tenant_id`** — the effective tenant comes only from the verified
  token (R2.2), so one sent in a body is rejected by `extra="forbid"` and never reaches a use
  case.
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
    """The pagination envelope of PRD §23."""

    data: list[PropertyResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(
        cls, properties: tuple[Property, ...], *, total: int, page: int, per_page: int
    ) -> "PropertyPageResponse":
        return cls(
            data=[PropertyResponse.from_domain(item) for item in properties],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page if per_page else 0,
        )
