"""Request/response DTOs for the cleaning endpoints (PRD §23, R1, R7).

Two rules this module exists to enforce, both inherited from
`app/reservations/api/schemas.py`:

* **No request schema has a `tenant_id`** — the effective tenant comes only from the
  verified token (R7.1), so one sent in a body is rejected by `extra="forbid"` and never
  reaches a use case. Nor an `assigned_cleaner_id` on the listing filters: the row-level
  restriction of R7.2 is derived from the role inside the use case, never accepted from the
  client (design D7).
* **Response fields are enumerated, never dumped from the entity.** `CleaningTask` carries
  `notes`, which design D13 keeps out of this change's surface entirely — a
  `from_attributes` dump would publish it the day someone writes to it.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.cleaning.application.use_cases import UploadedCleaningPhoto
from app.cleaning.domain.entities import CleaningChecklistTemplate, CleaningTask
from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus
from app.cleaning.domain.read_models import CleaningTaskContext
from app.cleaning.domain.value_objects import (
    MAX_ITEMS,
    MAX_KEY_LENGTH,
    MAX_LABEL_LENGTH,
    MAX_REQUIRED_PHOTOS,
)

MAX_PER_PAGE = 100
# `page` needs a ceiling too, not just `per_page`: the value becomes a SQL OFFSET and a
# 20-digit page number overflows int8, producing an unhandled driver error instead of a 422
# in the PRD §23 envelope. Same bound and same reason as `reservations`.
MAX_PAGE = 100_000
MAX_NAME = 200


class ChecklistItemPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: Annotated[str, Field(min_length=1, max_length=100)]
    label: Annotated[str, Field(min_length=1, max_length=MAX_LABEL_LENGTH)]
    required: bool = False


class RequiredPhotoPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_type: Annotated[str, Field(min_length=1, max_length=100)]
    label: Annotated[str, Field(min_length=1, max_length=MAX_LABEL_LENGTH)]
    required: bool = False


class CreateChecklistTemplateRequest(BaseModel):
    """The shape check. The **content** rules stay in the domain.

    Pydantic bounds the list sizes so an oversized body is refused before anything parses
    it, but the charset of `item_id`, its uniqueness and the `String(100)` ceiling are
    `parse_template_content`'s (R1.2) — those must hold for every path into a template, not
    only for HTTP.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
    items: Annotated[list[ChecklistItemPayload], Field(min_length=1, max_length=MAX_ITEMS)]
    required_photos: Annotated[
        list[RequiredPhotoPayload], Field(max_length=MAX_REQUIRED_PHOTOS)
    ] = []
    property_id: uuid.UUID | None = None


class ChecklistTemplateResponse(BaseModel):
    id: uuid.UUID
    name: str
    property_id: uuid.UUID | None
    active: bool
    items: list[dict[str, Any]]
    required_photos: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, template: CleaningChecklistTemplate) -> "ChecklistTemplateResponse":
        return cls(
            id=template.id,
            name=template.name,
            property_id=template.property_id,
            active=template.active,
            items=template.items,
            required_photos=template.required_photos,
            created_at=template.created_at,
            updated_at=template.updated_at,
        )


class ChecklistTemplatePageResponse(BaseModel):
    """The envelope of PRD §23."""

    data: list[ChecklistTemplateResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(cls, items, total: int, page: int, per_page: int):
        return cls(
            data=[ChecklistTemplateResponse.from_domain(item) for item in items],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page if per_page else 0,
        )


# --- cleaning tasks ---------------------------------------------------------------


class CreateCleaningTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: uuid.UUID
    reservation_id: uuid.UUID | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None


class AssignCleaningTaskRequest(BaseModel):
    """`PATCH /cleaning-tasks/{id}` — assignment is the only mutation it accepts.

    Not a general-purpose patch: `status` moves only through the lifecycle endpoints (so
    `PropertyStateMachine` is never bypassed), and `notes` is out of this change's writable
    surface entirely (design D13).
    """

    model_config = ConfigDict(extra="forbid")

    assigned_cleaner_id: uuid.UUID


class ValidateCleaningTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_status: CleaningValidationStatus


class CleaningTaskResponse(BaseModel):
    """Enumerated, never dumped from the entity — `notes` must not leak in (design D13)."""

    id: uuid.UUID
    property_id: uuid.UUID
    reservation_id: uuid.UUID | None
    checklist_template_id: uuid.UUID
    assigned_cleaner_id: uuid.UUID | None
    status: CleaningTaskStatus
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    accepted_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    validation_status: CleaningValidationStatus
    validated_by_user_id: uuid.UUID | None
    validated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, task: CleaningTask) -> "CleaningTaskResponse":
        return cls(
            id=task.id,
            property_id=task.property_id,
            reservation_id=task.reservation_id,
            checklist_template_id=task.checklist_template_id,
            assigned_cleaner_id=task.assigned_cleaner_id,
            status=task.status,
            scheduled_start=task.scheduled_start,
            scheduled_end=task.scheduled_end,
            accepted_at=task.accepted_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            validation_status=task.validation_status,
            validated_by_user_id=task.validated_by_user_id,
            validated_at=task.validated_at,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class CleaningTaskContextResponse(BaseModel):
    """What `GET /cleaning-tasks/{task_id}/context` returns — exactly `CleaningTaskContext` (D3).

    A field-for-field mirror on purpose, the `StayInfoResponse` construction
    (`app/guests/api/portal_schemas.py`). The projection is where R1.4 and R2.5 are enforced
    structurally, so this model earning its own opinion about which fields to include would
    reintroduce the very decision the read model exists to remove — and would make the router the
    owner of the denylist, which design D3 rejects by name.

    **`from_attributes` here reads a frozen dataclass of eleven fields, never an entity.** That is
    what makes it safe where a dump of `Property` would not be: `access_notes`, `cleaning_notes`
    and `emergency_notes` are fields of that entity and are not fields of the projection.

    No `exclude_none`, here or anywhere in `backend/app` — which is what satisfies R1.3: a `NULL`
    address travels as `null` **with its key**, rather than the key vanishing. That is inherited
    pydantic behaviour rather than something this model states, so it carries its own test against
    the serialised body (`tests/cleaning/test_task_context_api.py`) instead of being assumed.
    """

    model_config = ConfigDict(from_attributes=True)

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

    @classmethod
    def from_domain(cls, context: CleaningTaskContext) -> "CleaningTaskContextResponse":
        return cls.model_validate(context)


class CleaningTaskPageResponse(BaseModel):
    data: list[CleaningTaskResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(cls, items, total: int, page: int, per_page: int):
        return cls(
            data=[CleaningTaskResponse.from_domain(item) for item in items],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page if per_page else 0,
        )


class ChecklistItemStateResponse(BaseModel):
    item_id: str
    label: str
    required: bool
    completed: bool
    completed_at: datetime | None
    completed_by: uuid.UUID | None

    @classmethod
    def from_view(cls, view) -> "ChecklistItemStateResponse":
        return cls(
            item_id=view.item_id,
            label=view.label,
            required=view.required,
            completed=view.completed,
            completed_at=view.completed_at,
            completed_by=view.completed_by,
        )


class ChecklistResponse(BaseModel):
    data: list[ChecklistItemStateResponse]

    @classmethod
    def build(cls, views) -> "ChecklistResponse":
        return cls(data=[ChecklistItemStateResponse.from_view(view) for view in views])


# --- cleaning photos --------------------------------------------------------------

# `cleaning_photos.photo_type` is `String(100)` and the template validator applies the same
# ceiling (`MAX_KEY_LENGTH`), so the two agree: a longer value is a 422 from the schema here
# instead of a `StringDataRightTruncationError` from the driver.
MAX_PHOTO_TYPE_LENGTH = MAX_KEY_LENGTH


class CleaningPhotoResponse(BaseModel):
    """One uploaded photo. **An allowlist of fields, never a dump of the entity** (R3.2).

    `CleaningPhoto` carries `storage_key` — it has to, the signer needs it — so any
    `model_validate`, `from_attributes` or `asdict` over it publishes the internal storage path
    the moment somebody reaches for the convenient shape. Enumerating the fields is what makes
    "the key never appears as a **field** of a response" a property of this class rather than of
    everyone who ever touches it. `ai_validation_result` is out for a different reason: nothing
    writes it yet (proposal §Out of scope), and a field that is always `null` is a contract
    promise nobody made.

    `url` is the signed URL of design D7, minted per response with a 3600 s expiry. It is what
    a client uses instead of a path, and it is not stored anywhere.

    **And it is where the one accepted exception lives**, so the sentence above says "field" and
    not "response": for an `S3` tenant this URL is minted by the object store and carries the
    bucket and the full key inside its own value, because that is what makes a presigned URL
    presigned. Accepted, with its reasoning and its two rejected alternatives, in
    `docs/adr/0008-object-storage-provider-dev.md`. For `LOCAL` the URL carries only the photo's
    UUID, and the prohibition stays absolute everywhere else — body, headers, and every other
    field of this class.
    """

    id: uuid.UUID
    cleaning_task_id: uuid.UUID
    photo_type: str
    uploaded_by: uuid.UUID
    created_at: datetime
    url: str

    @classmethod
    def from_upload(cls, uploaded: UploadedCleaningPhoto) -> "CleaningPhotoResponse":
        return cls(
            id=uploaded.photo.id,
            cleaning_task_id=uploaded.photo.cleaning_task_id,
            photo_type=uploaded.photo.photo_type,
            uploaded_by=uploaded.photo.uploaded_by,
            created_at=uploaded.photo.created_at,
            url=uploaded.url,
        )


class CleaningPhotoListResponse(BaseModel):
    """The photos of one task (R3.1), each already carrying its signed URL.

    Wrapped in `data` rather than returned as a bare array, the shape `ChecklistResponse`
    already uses: a top-level JSON array cannot grow a field later without breaking every
    generated client, and this list has an obvious future one (`total`, if a task ever
    accumulates enough photos to page).

    **The element type is `CleaningPhotoResponse`, whose fields are an allowlist**, which is
    where R3.2 is actually enforced — see its docstring. Building this from the entities with
    `model_validate` would publish `storage_key` for every photo at once, so the only way in is
    through `from_upload`.
    """

    data: list[CleaningPhotoResponse]

    @classmethod
    def build(
        cls, uploaded: "Sequence[UploadedCleaningPhoto]"
    ) -> "CleaningPhotoListResponse":
        return cls(data=[CleaningPhotoResponse.from_upload(item) for item in uploaded])
