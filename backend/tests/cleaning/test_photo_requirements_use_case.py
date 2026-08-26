"""R1-R4 — `GetPhotoRequirementsUseCase` against fakes of the three ports it holds.

No database and no disk, per `steering/backend-architecture.md` §"Cómo se testea cada capa".

What only this level can pin is the **order of the two reads**. Over HTTP a task that is not
this caller's and a task whose photos happen to be absent are indistinguishable from the body,
because `uploaded_photo_types` answers an empty set for a task outside the tenant — its declared
safe direction. The difference is R1.5: the foreign task must be a `404` byte-identical to an
unknown id, never a `200` whose every `uploaded` is `false`. The photo fake below records what
it was asked, so "the task was resolved first" is checked and not assumed.

The serialised-body half — the closed field set, the absence of template leakage, the RBAC
matrix — is `test_photo_requirements_api.py`'s, against a real response.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.auth.domain.enums import UserRole
from app.cleaning.application.use_cases import (
    CleaningActor,
    GetPhotoRequirementsUseCase,
)
from app.cleaning.domain.entities import CleaningChecklistTemplate, CleaningTask
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import (
    ChecklistTemplateNotFoundError,
    CleaningTaskNotFoundError,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
CLEANER = uuid.uuid4()
OTHER_CLEANER = uuid.uuid4()
MANAGER = uuid.uuid4()

ITEMS = [{"item_id": "kitchen", "label": "Cocina", "required": True}]
# Deliberately **not** alphabetical, and deliberately mixing `required`: alphabetical would make
# R1.3 pass under `sorted()` too, and an all-required list could not tell `required_photos` from
# `required_photo_types()` (R2.2).
PHOTOS = [
    {"photo_type": "kitchen", "label": "Cocina", "required": True},
    {"photo_type": "before", "label": "Antes de empezar", "required": False},
    {"photo_type": "aftermath", "label": "Al terminar", "required": True},
]


class FakeTaskRepository:
    def __init__(self, task: CleaningTask) -> None:
        self._task = task

    async def get(self, tenant_id, task_id):
        if tenant_id != self._task.tenant_id or task_id != self._task.id:
            return None
        return self._task


class FakeTemplateRepository:
    def __init__(self, template: CleaningChecklistTemplate | None) -> None:
        self._template = template

    async def get(self, tenant_id, template_id):
        if self._template is None:
            return None
        if tenant_id != self._template.tenant_id or template_id != self._template.id:
            return None
        return self._template


class FakePhotoRepository:
    """Records the (tenant, task) it was asked about, so the ordering is checkable."""

    def __init__(self, uploaded: set[str] | None = None) -> None:
        self._uploaded = frozenset(uploaded or set())
        self.queried: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def uploaded_photo_types(self, tenant_id, task_id):
        self.queried.append((tenant_id, task_id))
        return self._uploaded


def _template(*, required_photos=None) -> CleaningChecklistTemplate:
    return CleaningChecklistTemplate(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Estándar",
        items=ITEMS,
        required_photos=PHOTOS if required_photos is None else required_photos,
        created_at=NOW,
        updated_at=NOW,
    )


def _task(template: CleaningChecklistTemplate, *, status=None) -> CleaningTask:
    return CleaningTask(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        property_id=uuid.uuid4(),
        checklist_template_id=template.id,
        created_at=NOW,
        updated_at=NOW,
        status=status or CleaningTaskStatus.ASSIGNED,
        assigned_cleaner_id=CLEANER,
    )


def _use_case(task, template, photos) -> GetPhotoRequirementsUseCase:
    return GetPhotoRequirementsUseCase(
        tasks=FakeTaskRepository(task),
        templates=FakeTemplateRepository(template),
        photos=photos,
    )


def _cleaner() -> CleaningActor:
    return CleaningActor(user_id=CLEANER, role=UserRole.CLEANER)


def _manager() -> CleaningActor:
    return CleaningActor(user_id=MANAGER, role=UserRole.PROPERTY_MANAGER)


async def test_one_entry_per_declared_type_with_its_photo_type_and_label() -> None:
    """R1.1."""
    template = _template()
    task = _task(template)

    views = await _use_case(task, template, FakePhotoRepository()).execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner()
    )

    assert [(view.photo_type, view.label) for view in views] == [
        ("kitchen", "Cocina"),
        ("before", "Antes de empezar"),
        ("aftermath", "Al terminar"),
    ]


async def test_a_template_declaring_no_photo_is_an_empty_list_and_never_a_not_found() -> None:
    """R1.2 — "esta tarea no pide fotos" is an answer, not an error."""
    template = _template(required_photos=[])
    task = _task(template)

    views = await _use_case(task, template, FakePhotoRepository()).execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner()
    )

    assert views == []


async def test_the_order_is_the_template_s_own_and_not_sorted() -> None:
    """R1.3 — the order the author wrote is the order the work is done in.

    `PHOTOS` is not alphabetical on purpose: an implementation that went through
    `sorted(spec.photo_types())` would produce `aftermath, before, kitchen` and pass any test
    whose fixture happened to be sorted already.
    """
    template = _template()
    task = _task(template)

    views = await _use_case(task, template, FakePhotoRepository()).execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner()
    )

    types = [view.photo_type for view in views]
    assert types == ["kitchen", "before", "aftermath"]
    assert types != sorted(types)


@pytest.mark.parametrize("status", list(CleaningTaskStatus))
async def test_the_answer_does_not_depend_on_the_task_s_status(status) -> None:
    """R1.4 — including before `IN_PROGRESS`, which is when the cleaner needs it most."""
    template = _template()
    task = _task(template, status=status)

    views = await _use_case(task, template, FakePhotoRepository()).execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner()
    )

    assert [view.photo_type for view in views] == ["kitchen", "before", "aftermath"]


async def test_an_unknown_task_is_a_not_found() -> None:
    """R1.5, first of the three causes."""
    template = _template()
    task = _task(template)

    with pytest.raises(CleaningTaskNotFoundError):
        await _use_case(task, template, FakePhotoRepository()).execute(
            tenant_id=TENANT, task_id=uuid.uuid4(), actor=_cleaner()
        )


async def test_another_tenants_task_is_the_same_not_found() -> None:
    """R1.5, second cause — and the photo repository is never reached.

    The assertion on `queried` is the one this level exists for: `uploaded_photo_types` answers
    an empty set outside the tenant, so an implementation that read it first would have a `200`
    in hand with every `uploaded` false, and only the ordering stops it.
    """
    template = _template()
    task = _task(template)
    photos = FakePhotoRepository({"kitchen"})

    with pytest.raises(CleaningTaskNotFoundError):
        await _use_case(task, template, photos).execute(
            tenant_id=OTHER_TENANT, task_id=task.id, actor=_cleaner()
        )

    assert photos.queried == []


async def test_another_cleaners_task_is_the_same_not_found() -> None:
    """R1.5, third cause — from `_load_task`, with no exception of its own."""
    template = _template()
    task = _task(template)
    photos = FakePhotoRepository({"kitchen"})
    actor = CleaningActor(user_id=OTHER_CLEANER, role=UserRole.CLEANER)

    with pytest.raises(CleaningTaskNotFoundError):
        await _use_case(task, template, photos).execute(
            tenant_id=TENANT, task_id=task.id, actor=actor
        )

    assert photos.queried == []


async def test_the_three_causes_raise_the_same_message() -> None:
    """R1.5 — indistinguishable, which is a property of the message and not only of the type."""
    template = _template()
    task = _task(template)
    use_case = _use_case(task, template, FakePhotoRepository())

    messages = set()
    for tenant_id, task_id, actor in (
        (TENANT, uuid.uuid4(), _cleaner()),
        (OTHER_TENANT, task.id, _cleaner()),
        (TENANT, task.id, CleaningActor(user_id=OTHER_CLEANER, role=UserRole.CLEANER)),
    ):
        with pytest.raises(CleaningTaskNotFoundError) as raised:
            await use_case.execute(tenant_id=tenant_id, task_id=task_id, actor=actor)
        messages.add(str(raised.value))

    assert len(messages) == 1


async def test_a_deleted_template_is_a_template_not_found() -> None:
    """R1.6 — the same failure the close already answers for the same cause."""
    template = _template()
    task = _task(template)

    with pytest.raises(ChecklistTemplateNotFoundError):
        await _use_case(task, None, FakePhotoRepository()).execute(
            tenant_id=TENANT, task_id=task.id, actor=_cleaner()
        )


async def test_an_optional_type_is_in_the_collection() -> None:
    """R2.2 — the upload admits it, so the enumeration has to name it.

    This is the behavioural half of "the source is `required_photos` and never
    `required_photo_types()`"; the structural half is the AST guard in
    `test_completion_clause_contract.py`.
    """
    template = _template()
    task = _task(template)

    views = await _use_case(task, template, FakePhotoRepository()).execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner()
    )

    by_type = {view.photo_type: view.required for view in views}
    assert by_type == {"kitchen": True, "before": False, "aftermath": True}


async def test_uploaded_is_true_only_for_the_types_already_there() -> None:
    """R3.1 — a fact reported, scoped to this tenant and this task."""
    template = _template()
    task = _task(template)
    photos = FakePhotoRepository({"before"})

    views = await _use_case(task, template, photos).execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner()
    )

    assert {view.photo_type: view.uploaded for view in views} == {
        "kitchen": False,
        "before": True,
        "aftermath": False,
    }
    assert photos.queried == [(TENANT, task.id)]


async def test_an_uploaded_type_the_template_no_longer_declares_does_not_appear() -> None:
    """R1.1 again, from the other side: driven by the template, not by the photos table.

    A stale `photo_type` — the template was edited after the photo was taken — must not grow a
    row of its own, exactly as `/checklist` refuses to show a completion for an item the
    template dropped.
    """
    template = _template()
    task = _task(template)
    photos = FakePhotoRepository({"kitchen", "balcony"})

    views = await _use_case(task, template, photos).execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner()
    )

    assert [view.photo_type for view in views] == ["kitchen", "before", "aftermath"]


async def test_a_manager_is_not_restricted_to_a_cleaners_rows() -> None:
    """R4.3 — the restriction comes off the persisted role and from nowhere else.

    The task is assigned to `CLEANER`; a `PROPERTY_MANAGER` reaches it because
    `CleaningActor.restrict_to_cleaner_id` is `None` for their role. There is no parameter on
    `execute` that could widen or narrow this — the signature is the proof, and this is its
    behaviour.
    """
    template = _template()
    task = _task(template)

    views = await _use_case(task, template, FakePhotoRepository()).execute(
        tenant_id=TENANT, task_id=task.id, actor=_manager()
    )

    assert len(views) == 3


async def test_execute_takes_nothing_that_could_widen_the_scope() -> None:
    """R4.3, structurally: three keyword parameters and not a fourth.

    `restrict_to_cleaner_id` is derived inside `_load_task` from `actor.role`. A
    `cleaner_id=`/`assigned_to=` parameter would let a caller name someone else's rows, and it
    would arrive as a query string the moment the route grew it.
    """
    import inspect

    parameters = list(inspect.signature(GetPhotoRequirementsUseCase.execute).parameters)

    assert parameters == ["self", "tenant_id", "task_id", "actor"], (
        "the use case gained a parameter: R4.3 keeps the row-level scope derived from the "
        f"persisted role, never from the request. Found {parameters}"
    )
