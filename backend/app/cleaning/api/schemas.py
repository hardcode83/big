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

from app.auth.domain.enums import UserRole
from app.cleaning.application.use_cases import CleaningTaskListView, UploadedCleaningPhoto
from app.cleaning.domain.entities import (
    MAX_CLEANING_TASK_MESSAGE_LENGTH,
    CleaningChecklistTemplate,
    CleaningTask,
    CleaningTaskMessage,
)
from app.cleaning.domain.enums import (
    CleaningAssignmentBlocker,
    CleaningTaskStatus,
    CleaningValidationStatus,
)
from app.cleaning.domain.repositories import CleaningTaskMessagePage
from app.cleaning.domain.ports import (
    IncidentReport,
    IncidentReportedAcknowledgement,
)
from app.cleaning.domain.read_models import CleaningTaskContext
from app.cleaning.domain.value_objects import (
    MAX_ITEMS,
    MAX_KEY_LENGTH,
    MAX_LABEL_LENGTH,
    MAX_REQUIRED_PHOTOS,
)
from app.core.storable_text import MultiLineText, SingleLineText
from app.maintenance.domain.entities import (
    MAX_INCIDENT_DESCRIPTION,
    MAX_INCIDENT_TITLE,
)
from app.maintenance.domain.enums import IncidentStatus

#: A cancellation reason is a sentence, not a document. Bounded like every other free-text field
#: here so a request body cannot be used as storage (`cleaning-stall-blocks-next-stay` R3.1).
MAX_CANCEL_REASON = 500

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


class CancelCleaningTaskRequest(BaseModel):
    """`cleaning-stall-blocks-next-stay` R3.1.

    `reason` is required and non-blank even though `PropertyStateMachine` does not demand one for
    `CLEANING_CANCELLED` (it is not in its `manual` set): retiring the work of another person is
    exactly what has to be explainable six months later. It is recorded on
    `property_state_transitions.reason` and deliberately **not** in `audit_logs.changes`, which
    admits only real, non-sensitive columns of the entity.
    """

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(min_length=1, max_length=MAX_CANCEL_REASON)]


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


# A model's docstring is **published** as its schema `description`, so the one below says what a
# consumer needs and the rest of the reasoning stays in this comment:
#
# * A second model rather than an optional field on `CleaningTaskResponse`, the way
#   `PropertyListItemResponse` exists next to the property detail and for the same reason of
#   shape (`cleaning-assign-preconditions` D5). The field on the shared model would oblige the
#   eight endpoints that return it — `POST`, `GET /{id}`, `PATCH`, `accept`, `reject`, `start`,
#   `complete`, `validate` — to read the flat's state to answer a question none of them was
#   asked.
# * Enumerated and built by hand like its sibling, **never** `from_attributes`: `notes` is a
#   field of the entity and must not leak into any response (design D13 of `cleaning`).
# * Not inherited from `CleaningTaskResponse` either. The duplication is the point: inheritance
#   would make every future field of the detail model appear in the listing silently, and "the
#   listing carries exactly these fields" is the property this file keeps.
class CleaningTaskListItemResponse(BaseModel):
    """One row of the cleaning-task listing: a task plus whether it can be assigned now."""

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
    #: Why this row cannot be assigned right now, or `null` if it can (R3.1).
    #:
    #: A courtesy for the screen and **not** an authorisation: it is computed when the page is
    #: read, so it can be stale by the time anyone clicks. The backend refuses again on the
    #: mutation and that refusal is the authority (R3.3). `null` therefore means "nothing known
    #: to be blocking", which is also what an unresolved flat yields.
    assignment_blocked_by: CleaningAssignmentBlocker | None

    @classmethod
    def from_domain(cls, view: CleaningTaskListView) -> "CleaningTaskListItemResponse":
        task = view.task
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
            assignment_blocked_by=view.blocker,
        )


class CleaningTaskPageResponse(BaseModel):
    data: list[CleaningTaskListItemResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(cls, items, total: int, page: int, per_page: int):
        return cls(
            data=[CleaningTaskListItemResponse.from_domain(item) for item in items],
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


class PhotoRequirementStateResponse(BaseModel):
    """One photo category the task's template declares (`cleaner-photo-requirements` R2.1).

    **Four fields enumerated by hand, and no `from_attributes`** — the rule this module opens
    with. The view it is built from carries only these four, but enumerating them is what makes
    R4.4 ("ni el `id` de la plantilla, ni su `name`, ni su `property_id`, ni su `active`, ni sus
    `items` en crudo") a property of this class rather than of whoever next edits the view.

    **`required` is not what the collection means.** Belonging to the collection says *the
    upload admits this type*; `required: true` says *the close demands it*. The column these
    come from is named `required_photos` and holds entries that may perfectly well be optional
    — the domain says so of itself in `RequiredPhotoSpec`'s docstring — so the two facts are
    published under two names and the ambiguity of the column name stops at the schema.

    `uploaded` reports what is already there and adjudicates nothing: whether the task may be
    closed stays inside `CleaningTask.complete()`, which is the only place any clause of
    PRD §11 is applied.
    """

    photo_type: str
    label: str
    required: bool
    uploaded: bool

    @classmethod
    def from_view(cls, view) -> "PhotoRequirementStateResponse":
        return cls(
            photo_type=view.photo_type,
            label=view.label,
            required=view.required,
            uploaded=view.uploaded,
        )


class PhotoRequirementsResponse(BaseModel):
    """The photo categories of one task, in the order the template declares them.

    A single `data` key, the shape `ChecklistResponse` above and `CleaningPhotoListResponse`
    below already use: a top-level JSON array cannot grow a field later without breaking every
    generated client.

    **The class names deliberately do not start with `CleaningPhoto`.** That prefix already
    collides in the published contract — `backend/openapi.json` carries
    `app__cleaning__api__schemas__CleaningPhotoResponse` and
    `app__dashboard__api__schemas__CleaningPhotoResponse`, mangled by module — and those mangled
    names are what a frontend consumer writes by hand. A third collision would mangle the two
    that survive today as well (design D3).
    """

    data: list[PhotoRequirementStateResponse]

    @classmethod
    def build(cls, views) -> "PhotoRequirementsResponse":
        return cls(data=[PhotoRequirementStateResponse.from_view(view) for view in views])


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


class ReportTaskIncidentRequest(BaseModel):
    """What `POST /cleaning-tasks/{task_id}/incidents` accepts: a title and a description.

    **Exactly two fields, and `extra="forbid"` is what makes that a contract** (R1.3). A body
    carrying `property_id`, `reservation_id`, `tenant_id`, `source`, `category`, `severity`,
    `status`, `assigned_technician_id` or any cost field is rejected rather than ignored: those
    are derived or sealed by the system, and silently dropping one would leave a caller believing
    it had been accepted. `test_task_incident_api.py` pins the set so that adding a third field is
    a deliberate act rather than a drift.

    **The bounds are imported, never re-derived** (D7). `MAX_INCIDENT_TITLE` and
    `MAX_INCIDENT_DESCRIPTION` live in `app/maintenance/domain/entities.py`, the module that owns
    the **bound** — the column's own DDL is next door in that module's
    `infrastructure/models.py`. The guest portal's request schema binds the same two constants; a
    local `300` here would be a copy nobody keeps in step with either.

    **`storable_text` is not decoration**: without it a `title` carrying `U+0000` or an unpaired
    surrogate reaches asyncpg and surfaces as an undeclared `500`, which is the failure the
    section-7 panel of `guest-portal-api` measured twice on these two columns. `SingleLineText`
    for the title (no control characters at all — it is rendered into lists and logs) and
    `MultiLineText` for the description (paragraphs and tabs are how a person describes a
    problem).

    `str_strip_whitespace=True` with `min_length=1` is what makes a whitespace-only report a
    `422`, and it means the maxima count characters *after* stripping.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: Annotated[
        SingleLineText, Field(min_length=1, max_length=MAX_INCIDENT_TITLE)
    ]
    description: Annotated[
        MultiLineText, Field(min_length=1, max_length=MAX_INCIDENT_DESCRIPTION)
    ]

    def to_report(self) -> IncidentReport:
        """Request → domain, **here and not in the router** (D9).

        This is load-bearing for the rule-11 census guard, not tidiness: the guard in
        `tests/maintenance/test_free_text_sink_contract.py` reports any gated module that names
        `title` or `description` in a writing position. Because the mapping lives in this
        schema, `tasks_router.py` never does — which is a property of the design rather than
        luck, and the reason the router needs no allowlist entry.
        """
        return IncidentReport(title=self.title, description=self.description)


class TaskIncidentReportedResponse(BaseModel):
    """The acknowledgement, and **only** the acknowledgement (R4.4, D8).

    Three fields: the id of the incident just created, its status and when. A mirror of the guest
    portal's `IncidentReportedResponse`, and for the same reason — the cleaner does not read,
    list, classify or resolve incidents (proposal §Out of scope), so this is the whole of what
    this surface may ever say about one.

    It carries no `category`, no `severity` and no `ai_*`: those are `maintenance`'s to fill in
    and returning their initial values would promise a shape that changes underneath the caller.
    It does not echo the `description` back either — there is nothing to learn from it and it is
    a rule-11 sink, so the round trip would be one more place the value travels to.
    """

    id: uuid.UUID
    status: IncidentStatus
    created_at: datetime

    @classmethod
    def from_acknowledgement(
        cls, acknowledgement: IncidentReportedAcknowledgement
    ) -> "TaskIncidentReportedResponse":
        return cls(
            id=acknowledgement.id,
            status=acknowledgement.status,
            created_at=acknowledgement.created_at,
        )


# --- cleaning task messages (`staff-messaging`) -----------------------------------


class SendCleaningTaskMessageRequest(BaseModel):
    """`POST /cleaning-tasks/{task_id}/messages` (R1.1, R5.1, R5.2).

    The exact shape of `CompleteIncidentRequest.materials` (design D5): `storable_text` guards
    against a value asyncpg cannot store, `Field(min_length=1, max_length=...)` rejects an
    empty or oversized body as a `422` before anything reaches the use case, and
    `str_strip_whitespace=True` means the maximum counts characters *after* stripping — so a
    whitespace-only message is refused rather than persisted.

    **The bound is imported, never re-derived**: `MAX_CLEANING_TASK_MESSAGE_LENGTH` lives in
    `app/cleaning/domain/entities.py`, the module that owns the column — its DDL is next door
    in that module's `infrastructure/models.py`.

    `MultiLineText` rather than `SingleLineText`: a staff message can span more than one line,
    the same choice `ReportTaskIncidentRequest.description` makes.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: Annotated[
        MultiLineText, Field(min_length=1, max_length=MAX_CLEANING_TASK_MESSAGE_LENGTH)
    ]


class CleaningTaskMessageResponse(BaseModel):
    """One message of a task's staff thread. **An allowlist, never a dump of the entity**
    (the rule this module opens with) — even though `CleaningTaskMessage` has no field this
    change needs to exclude, `from_domain` is the only way in, the `CleaningPhotoResponse`
    discipline and not an accident.
    """

    id: uuid.UUID
    author_id: uuid.UUID
    author_role: UserRole
    content: str
    created_at: datetime

    @classmethod
    def from_domain(cls, message: CleaningTaskMessage) -> "CleaningTaskMessageResponse":
        return cls(
            id=message.id,
            author_id=message.author_id,
            author_role=message.author_role,
            content=message.content,
            created_at=message.created_at,
        )


class CleaningTaskMessagePageResponse(BaseModel):
    """The envelope of PRD §23, the `CleaningTaskPageResponse` pattern."""

    data: list[CleaningTaskMessageResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(
        cls, page: CleaningTaskMessagePage, *, page_number: int, per_page: int
    ) -> "CleaningTaskMessagePageResponse":
        return cls(
            data=[CleaningTaskMessageResponse.from_domain(item) for item in page.items],
            total=page.total,
            page=page_number,
            per_page=per_page,
            total_pages=(page.total + per_page - 1) // per_page if per_page else 0,
        )
