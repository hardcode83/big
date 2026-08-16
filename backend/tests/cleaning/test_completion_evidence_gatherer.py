"""R4 — `CompletionEvidenceGatherer`, against fakes of its four ports.

No database and no `httpx`: what is under test is the ASSEMBLY of the evidence, which is a
property of the gatherer and of no adapter. The close itself stays covered end to end by
`test_tasks_api.py`; this is the half that got cheap when the four reads moved out of an
eleven-collaborator use case.

The fakes record the arguments they are called with, because R4.5 is about the scoping and a
fake that only returns a value cannot show that `tenant_id` travelled.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.cleaning.application.evidence import CompletionEvidenceGatherer
from app.cleaning.domain.entities import (
    CleaningChecklistCompletion,
    CleaningChecklistTemplate,
    CleaningTask,
)
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import ChecklistTemplateNotFoundError
from app.cleaning.domain.value_objects import parse_template_content

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
CLEANER = uuid.uuid4()


# --- fakes -----------------------------------------------------------------------------


class FakeTemplateRepository:
    def __init__(self, template: CleaningChecklistTemplate | None) -> None:
        self._template = template
        self.calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def get(self, tenant_id, template_id):
        self.calls.append((tenant_id, template_id))
        return self._template


class FakeCompletionRepository:
    def __init__(self, completions=()) -> None:
        self._completions = list(completions)
        self.calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def list_for_task(self, tenant_id, task_id):
        self.calls.append((tenant_id, task_id))
        return self._completions


class FakePhotoRepository:
    def __init__(self, uploaded=frozenset()) -> None:
        self._uploaded = frozenset(uploaded)
        self.calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def uploaded_photo_types(self, tenant_id, task_id):
        self.calls.append((tenant_id, task_id))
        return self._uploaded


class FakeIncidentQuery:
    def __init__(self, *, blocked: bool = False) -> None:
        self._blocked = blocked
        self.calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def has_unresolved_critical(self, tenant_id, property_id):
        self.calls.append((tenant_id, property_id))
        return self._blocked


# --- builders --------------------------------------------------------------------------


def _template(*, items=None, required_photos=None) -> CleaningChecklistTemplate:
    return CleaningChecklistTemplate(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Estándar",
        items=items
        if items is not None
        else [
            {"item_id": "kitchen", "label": "Cocina", "required": True},
            {"item_id": "balcony", "label": "Terraza", "required": False},
        ],
        required_photos=required_photos
        if required_photos is not None
        else [{"photo_type": "after", "label": "Después", "required": True}],
        created_at=NOW,
        updated_at=NOW,
    )


def _task(template_id: uuid.UUID) -> CleaningTask:
    return CleaningTask(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        property_id=uuid.uuid4(),
        checklist_template_id=template_id,
        created_at=NOW,
        updated_at=NOW,
        status=CleaningTaskStatus.IN_PROGRESS,
        assigned_cleaner_id=CLEANER,
    )


def _completion(task_id: uuid.UUID, item_id: str, *, completed: bool):
    return CleaningChecklistCompletion(
        id=uuid.uuid4(),
        cleaning_task_id=task_id,
        item_id=item_id,
        completed=completed,
        completed_at=NOW if completed else None,
        completed_by=CLEANER if completed else None,
    )


# --- the happy path ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_happy_path_assembles_the_five_fields():
    """R4.2 — the assembly the close hands to `CleaningTask.complete()`, in isolation."""
    template = _template()
    task = _task(template.id)
    gatherer = CompletionEvidenceGatherer(
        templates=FakeTemplateRepository(template),
        completions=FakeCompletionRepository(
            [
                _completion(task.id, "kitchen", completed=True),
                _completion(task.id, "balcony", completed=False),
            ]
        ),
        photos=FakePhotoRepository({"after"}),
        incidents=FakeIncidentQuery(blocked=False),
    )

    evidence = await gatherer.gather(tenant_id=TENANT, task=task)

    assert evidence.required_item_ids == frozenset({"kitchen"})
    # Only what was actually ticked: `balcony` was reported and left undone.
    assert evidence.completed_item_ids == frozenset({"kitchen"})
    assert evidence.required_photo_types == frozenset({"after"})
    assert evidence.uploaded_photo_types == frozenset({"after"})
    assert evidence.has_unresolved_critical_incident is False


# --- required, not merely declared -------------------------------------------------------


@pytest.mark.asyncio
async def test_an_optional_photo_type_is_not_a_required_one():
    """R4.3 — the difference between `required_photo_types()` and `photo_types()`.

    Pinned by behaviour rather than by the comment that has been guarding it: reading the
    other accessor would make the optional "before" shot mandatory and turn every close
    without it into a 409 nobody asked for.
    """
    template = _template(
        required_photos=[
            {"photo_type": "after", "label": "Después", "required": True},
            {"photo_type": "before", "label": "Antes", "required": False},
        ]
    )
    task = _task(template.id)
    gatherer = CompletionEvidenceGatherer(
        templates=FakeTemplateRepository(template),
        completions=FakeCompletionRepository(),
        photos=FakePhotoRepository(),
        incidents=FakeIncidentQuery(),
    )

    evidence = await gatherer.gather(tenant_id=TENANT, task=task)

    assert evidence.required_photo_types == frozenset({"after"})
    # The type IS declared — the gatherer read the accessor that filters, not the one that
    # lists — so the two answers genuinely disagree and the assertion above is not vacuous.
    spec = parse_template_content(template.items, template.required_photos)
    assert "before" in spec.photo_types()


# --- the refusal --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_missing_template_is_the_same_error_as_before():
    """R4.4, R1.5 — same exception and same message, so `api/errors.py` still answers 404.

    404 `NOT_FOUND`, not 409: the mapping is `errors.py:45` and `test_errors.py:76` pins it.
    R1.5 was itself worded as 409 until the section-1 panel read the table — worth stating
    here, because this docstring is the local restatement of the requirement.
    """
    task = _task(uuid.uuid4())
    gatherer = CompletionEvidenceGatherer(
        templates=FakeTemplateRepository(None),
        completions=FakeCompletionRepository(),
        photos=FakePhotoRepository(),
        incidents=FakeIncidentQuery(),
    )

    with pytest.raises(ChecklistTemplateNotFoundError) as raised:
        await gatherer.gather(tenant_id=TENANT, task=task)

    assert str(raised.value) == "The task's checklist template no longer exists"


# --- the scoping ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_port_is_asked_within_the_tenant_and_for_the_right_subject():
    """R4.5 — the four reads carry the tenant, and each one asks by its own identifier.

    Incidents is the one that is easy to get wrong: it is asked by `property_id`, not by the
    task, because a critical incident blocks the property rather than the cleaning.
    """
    template = _template()
    task = _task(template.id)
    templates = FakeTemplateRepository(template)
    completions = FakeCompletionRepository()
    photos = FakePhotoRepository()
    incidents = FakeIncidentQuery(blocked=True)
    gatherer = CompletionEvidenceGatherer(
        templates=templates, completions=completions, photos=photos, incidents=incidents
    )

    evidence = await gatherer.gather(tenant_id=TENANT, task=task)

    assert templates.calls == [(TENANT, task.checklist_template_id)]
    assert completions.calls == [(TENANT, task.id)]
    assert photos.calls == [(TENANT, task.id)]
    assert incidents.calls == [(TENANT, task.property_id)]
    assert task.property_id != task.id
    # The answer travels back rather than being defaulted — the field's default is `False`.
    assert evidence.has_unresolved_critical_incident is True
