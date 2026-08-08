"""Request/response DTOs for the access endpoints (PRD §23, R2, R3).

Two rules inherited from `app/reservations/api/schemas.py`, and one of this module's own:

* **No request schema has a `tenant_id`** — the effective tenant comes only from the verified
  token, so one sent in a body is rejected by `extra="forbid"`.
* **Response fields are enumerated, never dumped from the entity.**
* **`AccessRecordResponse` has no field for a plaintext code, and `RegisterCodeRequest` is
  the only place the plaintext exists at all** (design D9). The request carries it in, the
  entity masks it, and nothing on the way out can carry it back — a `from_attributes` dump
  would be one added column away from publishing it, which is why there is none.
"""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.access.domain.entities import AccessRecord
from app.access.domain.enums import AccessCreatedMode, AccessProvider, AccessRecordStatus

MAX_PER_PAGE = 100
# `page` needs a ceiling too: the value becomes a SQL OFFSET and a 20-digit page number
# overflows int8 into a driver error instead of a 422. Same bound as `reservations`.
MAX_PAGE = 100_000
MAX_CODE = 100
MAX_NOTES = 2000


class RegisterCodeRequest(BaseModel):
    """The one place a plaintext access code enters the system (R2.2).

    It goes no further than `AccessRecord.register_manual_code`, which masks it. No column,
    no response field and no log line can hold it — see design D9.
    """

    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=MAX_CODE)]
    notes: Annotated[str | None, Field(max_length=MAX_NOTES)] = None


class MarkExternalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: Annotated[str | None, Field(max_length=MAX_NOTES)] = None


class AccessRecordResponse(BaseModel):
    id: uuid.UUID
    property_id: uuid.UUID
    reservation_id: uuid.UUID | None
    provider: AccessProvider
    status: AccessRecordStatus
    created_mode: AccessCreatedMode
    #: `****XX` and nothing else. Rule 4 of `steering/security.md`.
    code_masked: str | None
    external_id: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, record: AccessRecord) -> "AccessRecordResponse":
        return cls(
            id=record.id,
            property_id=record.property_id,
            reservation_id=record.reservation_id,
            provider=record.provider,
            status=record.status,
            created_mode=record.created_mode,
            code_masked=record.code_masked,
            external_id=record.external_id,
            valid_from=record.valid_from,
            valid_to=record.valid_to,
            notes=record.notes,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class AccessRecordPageResponse(BaseModel):
    data: list[AccessRecordResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(cls, items, total: int, page: int, per_page: int) -> "AccessRecordPageResponse":
        return cls(
            data=[AccessRecordResponse.from_domain(item) for item in items],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page if per_page else 0,
        )
